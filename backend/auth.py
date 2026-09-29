import logging
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Header, HTTPException, Request

from backend.config import JWT_SECRET

logger = logging.getLogger(__name__)

SECRET_KEY = JWT_SECRET
if not SECRET_KEY:
    raise RuntimeError(
        "JWT_SECRET environment variable is required. "
        'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(32))"'
    )

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

# In-memory cache of revoked tokens (keyed by jti). The source of truth is the
# persistent ``revoked_tokens`` table (database.revoke_token) so revocation
# survives restarts and is shared across processes; this set only avoids a DB
# hit for tokens already seen as revoked in this process.
_token_blacklist: set[str] = set()


def blacklist_token(jti: str, expires_at: str | None = None) -> None:
    if not jti:
        return
    _token_blacklist.add(jti)
    try:
        from backend.database import revoke_token

        revoke_token(jti, expires_at=expires_at)
    except Exception as e:
        logger.error("Failed to persist revoked token %s: %s", jti, e)


def _is_token_revoked(jti: str) -> bool:
    if jti in _token_blacklist:
        return True
    try:
        from backend.database import is_token_revoked

        revoked = is_token_revoked(jti)
    except Exception as e:
        logger.error("Failed to check revoked token %s: %s", jti, e)
        return True  # fail closed on DB errors
    if revoked:
        _token_blacklist.add(jti)
    return revoked


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash or not isinstance(password_hash, str):
        return False
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: str, role_type: str) -> str:
    payload = {
        "sub": user_id,
        "role": role_type,
        "jti": str(uuid.uuid4()),
        "exp": datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            options={"require": ["exp", "iat", "sub"]},
            issuer=None,
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")


async def require_auth(
    request: Request, authorization: str | None = Header(None)
) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Invalid authorization header")
    token = authorization[7:]
    payload = decode_token(token)
    if "sub" not in payload:
        raise HTTPException(401, "Invalid token payload")
    jti = payload.get("jti", "")
    if jti and _is_token_revoked(jti):
        raise HTTPException(401, "Token has been revoked")
    try:
        from backend.database import get_user_by_id

        user = get_user_by_id(payload["sub"])
    except Exception as e:
        logger.error("Database error in require_auth: %s", e)
        raise HTTPException(503, "Service temporarily unavailable")
    if not user:
        raise HTTPException(401, "User not found")
    if str(user.get("status") or "").lower() == "revoked":
        raise HTTPException(401, "Account has been revoked")
    if user.get("role_type") in {
        "company_admin",
        "workplace_employee",
        "workplace_provider",
    }:
        path = request.url.path
        allowed = path.startswith("/api/v1/workplace/") or path.startswith("/api/v1/voice/") or path in {
            "/api/auth/me",
            "/api/auth/terms",
            "/api/auth/change-password",
            "/api/auth/logout",
            "/api/institution/staff/profile",
        }
        if not allowed:
            raise HTTPException(
                403,
                "This workplace account cannot access school, social-analysis, or general community services",
            )
    user["_token_jti"] = jti
    user["_token_exp"] = payload.get("exp")
    return user


async def optional_auth(
    request: Request, authorization: str | None = Header(None)
) -> dict | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        return await require_auth(request, authorization)
    except HTTPException:
        return None
