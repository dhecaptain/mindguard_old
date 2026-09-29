"""Consent-scoped analysis for in-person visitors without user accounts."""

import json
import asyncio
import ipaddress
import os
import re
import secrets
import socket
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.auth import require_auth
from backend.database import consume_rate_limit, get_db, write_audit
from backend.services.crypto import decrypt_pii, encrypt_pii, hash_token
from backend.services.predictor import InferenceUnavailableError, predict_batch
from backend.utils import calibrate_risk_score, clean_text

router = APIRouter(prefix="/api/v1/guest-analysis", tags=["guest-analysis"])
SUPPORTED = {"reddit", "bluesky", "mastodon"}
RETENTION_DAYS = int(os.getenv("GUEST_ANALYSIS_RETENTION_DAYS", "90"))
CONSENT_LINK_DAYS = 7


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_counsellor(user: dict) -> None:
    if user.get("role_type") not in {"counsellor", "admin"} or str(user.get("status") or "").lower() not in {"approved", "active"}:
        raise HTTPException(403, "Active counsellor or global administrator access required")


class GuestCaseCreate(BaseModel):
    platforms: dict[str, str] = Field(min_length=1, max_length=6)


class GuestConsent(BaseModel):
    token: str = Field(min_length=32, max_length=200)
    accepted: bool


class GuestAttestation(BaseModel):
    confirmed: bool


class GuestReferral(BaseModel):
    note: str = Field(min_length=2, max_length=2000)


class GuestCaseNote(BaseModel):
    private_note: str = Field(min_length=1, max_length=10000)
    visitor_update: str | None = Field(default=None, max_length=3000)


def _owned_case(conn, case_id: str, user: dict):
    query = "SELECT * FROM guest_cases WHERE id = ? AND deleted_at IS NULL"
    params: tuple = (case_id,)
    if user.get("role_type") != "admin":
        query += " AND counsellor_id = ?"
        params = (case_id, user["id"])
    row = conn.execute(query, params).fetchone()
    if not row:
        raise HTTPException(404, "Guest case not found")
    return row


@router.post("/cases", status_code=201)
async def create_guest_case(data: GuestCaseCreate, request: Request, user: dict = Depends(require_auth)):
    _require_counsellor(user)
    cleaned: dict[str, str] = {}
    for platform, handle in data.platforms.items():
        key = platform.strip().lower()
        value = handle.strip()
        if key not in SUPPORTED:
            raise HTTPException(400, f"{platform} is not available for privacy-scoped guest retrieval")
        if not value or len(value) > 300:
            raise HTTPException(400, f"Enter a valid {key} handle")
        cleaned[key] = value
    if not consume_rate_limit(f"guest-case:{user['id']}", 20, 3600):
        raise HTTPException(429, "Too many guest cases. Please try again later.")
    case_id = str(uuid.uuid4())
    token = secrets.token_urlsafe(32)
    case_code = f"GST-{secrets.token_hex(3).upper()}"
    now = _now()
    expires = (datetime.now(timezone.utc) + timedelta(days=RETENTION_DAYS)).isoformat()
    consent_expires = (datetime.now(timezone.utc) + timedelta(days=CONSENT_LINK_DAYS)).isoformat()
    conn = get_db()
    conn.execute(
        "INSERT INTO guest_cases (id, case_code, counsellor_id, institution_id, status, consent_token_hash, consent_expires_at, expires_at, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (case_id, case_code, user["id"], user.get("institution_id"), "pending_consent", hash_token(token), consent_expires, expires, now, now),
    )
    for platform, handle in cleaned.items():
        conn.execute(
            "INSERT INTO guest_platform_authorizations (id, case_id, platform, handle_encrypted, ownership_status, created_at) VALUES (?,?,?,?,?,?)",
            (str(uuid.uuid4()), case_id, platform, encrypt_pii(handle), "visitor_authorized_unverified", now),
        )
    conn.commit()
    conn.close()
    write_audit(user["id"], user["role_type"], "GUEST_CASE_CREATED", "guest_case", case_id, payload={"platforms": sorted(cleaned), "retention_days": RETENTION_DAYS}, ip=request.client.host if request.client else None)
    base = os.getenv("APP_BASE_URL", "https://app.mindguardai.me").rstrip("/")
    return {"id": case_id, "case_code": case_code, "status": "pending_consent", "expires_at": expires, "consent_expires_at": consent_expires, "consent_url": f"{base}/guest-consent?token={token}"}


@router.get("/consent")
async def guest_consent_details(token: str, request: Request):
    if not consume_rate_limit(
        f"guest-consent-preview:{request.client.host if request.client else 'unknown'}", 30, 3600
    ):
        raise HTTPException(429, "Too many consent link checks. Please try again later.")
    conn = get_db()
    row = conn.execute(
        "SELECT id,case_code,status,consent_expires_at,expires_at FROM guest_cases "
        "WHERE consent_token_hash=? AND deleted_at IS NULL",
        (hash_token(token),),
    ).fetchone()
    if (
        not row
        or row["status"] != "pending_consent"
        or row["consent_expires_at"] <= _now()
        or row["expires_at"] <= _now()
    ):
        conn.close()
        raise HTTPException(400, "This guest consent link is invalid or expired")
    accounts = conn.execute(
        "SELECT platform,handle_encrypted,ownership_status FROM guest_platform_authorizations WHERE case_id=? ORDER BY platform",
        (row["id"],),
    ).fetchall()
    conn.close()
    return {
        "case_code": row["case_code"],
        "consent_expires_at": row["consent_expires_at"],
        "retention_expires_at": row["expires_at"],
        "accounts": [
            {
                "platform": account["platform"],
                "handle": decrypt_pii(account["handle_encrypted"]),
                "ownership_status": account["ownership_status"],
            }
            for account in accounts
        ],
    }


@router.post("/consent")
async def accept_guest_consent(data: GuestConsent, request: Request):
    supplied_hash = hash_token(data.token)
    conn = get_db()
    row = conn.execute("SELECT * FROM guest_cases WHERE consent_token_hash = ? AND deleted_at IS NULL", (supplied_hash,)).fetchone()
    if not row or row["expires_at"] <= _now() or row["consent_expires_at"] <= _now() or row["status"] != "pending_consent":
        conn.close()
        raise HTTPException(400, "This guest consent link is invalid or expired")
    now = _now()
    if data.accepted:
        changed = conn.execute("UPDATE guest_cases SET status='consented', consent_method='visitor_link', consented_at=?, consent_token_hash=?, consent_expires_at=?, updated_at=? WHERE id=? AND status='pending_consent' AND consent_token_hash=?", (now, hash_token(secrets.token_urlsafe(32)), now, now, row["id"], supplied_hash)).rowcount
        status = "consented"
        event = "GUEST_CONSENT_ACCEPTED"
    else:
        changed = conn.execute("UPDATE guest_cases SET status='declined', consent_method='visitor_declined', consent_token_hash=?, consent_expires_at=?, updated_at=? WHERE id=? AND status='pending_consent' AND consent_token_hash=?", (hash_token(secrets.token_urlsafe(32)), now, now, row["id"], supplied_hash)).rowcount
        if changed:
            conn.execute("DELETE FROM guest_platform_authorizations WHERE case_id=?", (row["id"],))
        status = "declined"
        event = "GUEST_CONSENT_DECLINED"
    if changed != 1:
        conn.rollback()
        conn.close()
        raise HTTPException(409, "A decision has already been recorded for this consent link")
    conn.commit()
    conn.close()
    write_audit(None, "guest", event, "guest_case", row["id"], ip=request.client.host if request.client else None)
    return {"ok": True, "case_code": row["case_code"], "status": status}


@router.post("/cases/{case_id}/attest")
async def attest_guest_consent(case_id: str, data: GuestAttestation, request: Request, user: dict = Depends(require_auth)):
    _require_counsellor(user)
    if not data.confirmed:
        raise HTTPException(400, "Confirm that the visitor gave informed consent in person")
    conn = get_db()
    row = _owned_case(conn, case_id, user)
    if row["status"] != "pending_consent":
        conn.close()
        raise HTTPException(409, "This case is no longer awaiting consent")
    now = _now()
    conn.execute("UPDATE guest_cases SET status='consented', consent_method='counsellor_attestation', consented_at=?, consent_token_hash=?, consent_expires_at=?, updated_at=? WHERE id=? AND status='pending_consent'", (now, hash_token(secrets.token_urlsafe(32)), now, now, case_id))
    conn.commit()
    conn.close()
    write_audit(user["id"], user["role_type"], "GUEST_CONSENT_ATTESTED", "guest_case", case_id, payload={"ownership_verified": False}, ip=request.client.host if request.client else None)
    return {"ok": True, "warning": "Counsellor attestation records authorization but does not prove account ownership."}


async def _fetch_reddit(handle: str) -> list[dict]:
    username = handle.strip().lstrip("u/").strip("/")
    if not re.fullmatch(r"[A-Za-z0-9_-]{3,20}", username):
        raise ValueError("Invalid Reddit username")
    url = f"https://www.reddit.com/user/{quote(username)}/submitted.json?limit=50&raw_json=1"
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": "MindGuard/2.0 guest-consent-analysis"}) as client:
        response = await client.get(url)
        response.raise_for_status()
        children = response.json().get("data", {}).get("children", [])
    return [{"text": f"{item['data'].get('title','')} {item['data'].get('selftext','')}".strip(), "date": item["data"].get("created_utc"), "url": ""} for item in children]


async def _fetch_bluesky(handle: str) -> list[dict]:
    actor = handle.strip().lstrip("@").lower()
    if not re.fullmatch(r"[a-z0-9.-]{3,253}", actor):
        raise ValueError("Invalid Bluesky handle")
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get("https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed", params={"actor": actor, "limit": 50})
        response.raise_for_status()
        feed = response.json().get("feed", [])
    return [{"text": item.get("post", {}).get("record", {}).get("text", ""), "date": item.get("post", {}).get("record", {}).get("createdAt"), "url": item.get("post", {}).get("uri", "")} for item in feed]


async def _fetch_mastodon(handle: str) -> list[dict]:
    value = handle.strip().lstrip("@").lower()
    if value.count("@") != 1:
        raise ValueError("Use a Mastodon handle like user@instance.social")
    username, host = value.split("@", 1)
    if not re.fullmatch(r"[a-z0-9_.-]{1,64}", username) or not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,63}", host):
        raise ValueError("Invalid Mastodon handle")
    try:
        addresses = await asyncio.to_thread(socket.getaddrinfo, host, 443, 0, socket.SOCK_STREAM)
        resolved = {ipaddress.ip_address(item[4][0]) for item in addresses}
    except (OSError, ValueError) as exc:
        raise ValueError("Mastodon instance could not be safely resolved") from exc
    if not resolved or any(not address.is_global for address in resolved):
        raise ValueError("Private or local Mastodon instances are not supported")
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        lookup = await client.get(f"https://{host}/api/v1/accounts/lookup", params={"acct": username})
        lookup.raise_for_status()
        account_id = lookup.json()["id"]
        statuses = await client.get(f"https://{host}/api/v1/accounts/{account_id}/statuses", params={"limit": 40, "exclude_replies": "true"})
        statuses.raise_for_status()
        payload = statuses.json()
    return [{"text": re.sub(r"<[^>]+>", " ", item.get("content", "")), "date": item.get("created_at"), "url": item.get("url", "")} for item in payload]


@router.post("/cases/{case_id}/run")
async def run_guest_case(case_id: str, request: Request, user: dict = Depends(require_auth)):
    _require_counsellor(user)
    if not consume_rate_limit(f"guest-analysis:{user['id']}", 10, 3600):
        raise HTTPException(429, "Guest analysis limit reached. Please try again later.")
    conn = get_db()
    case = _owned_case(conn, case_id, user)
    if case["status"] != "consented" or not case["consented_at"]:
        conn.close()
        raise HTTPException(403, "A new consent decision is required before another analysis")
    if case["expires_at"] <= _now():
        conn.close()
        raise HTTPException(410, "This guest case has expired")
    accounts = conn.execute("SELECT platform, handle_encrypted, ownership_status FROM guest_platform_authorizations WHERE case_id=?", (case_id,)).fetchall()
    conn.close()
    results = []
    for account in accounts:
        platform = account["platform"]
        try:
            handle = decrypt_pii(account["handle_encrypted"])
            posts = await {"reddit": _fetch_reddit, "bluesky": _fetch_bluesky, "mastodon": _fetch_mastodon}[platform](handle)
            posts = [p for p in posts if clean_text(p.get("text", ""))][:50]
            if not posts:
                raise ValueError("No public text posts were available")
            scores = await predict_batch([clean_text(p["text"]) for p in posts])
            enriched = []
            for post, score in zip(posts, scores):
                item = {**post, **calibrate_risk_score(post["text"], float(score))}
                enriched.append(item)
            overall = sum(float(p["risk_score"]) for p in enriched) / len(enriched)
            results.append({"platform": platform, "status": "complete", "overall": overall, "n_posts": len(enriched), "posts": enriched, "ownership_status": account["ownership_status"], "analysed_at": _now()})
        except (httpx.HTTPError, ValueError, KeyError, InferenceUnavailableError) as exc:
            results.append({"platform": platform, "status": "failed", "message": str(exc) or "Analysis failed", "ownership_status": account["ownership_status"], "analysed_at": _now()})
    now = _now()
    session_id = str(uuid.uuid4())
    conn = get_db()
    conn.execute("INSERT INTO guest_analysis_sessions (id, case_id, counsellor_id, results_encrypted, created_at) VALUES (?,?,?,?,?)", (session_id, case_id, user["id"], encrypt_pii(json.dumps(results)), now))
    conn.execute("UPDATE guest_cases SET status='analysed', updated_at=? WHERE id=?", (now, case_id))
    conn.commit()
    conn.close()
    write_audit(user["id"], user["role_type"], "GUEST_ANALYSIS_RUN", "guest_case", case_id, payload={"platforms": [r["platform"] for r in results], "session_id": session_id}, ip=request.client.host if request.client else None)
    return {"session_id": session_id, "case_code": case["case_code"], "ownership_warning": "Visitor authorization was attested; account ownership was not technically verified.", "results": results}


@router.get("/cases")
async def list_guest_cases(user: dict = Depends(require_auth)):
    _require_counsellor(user)
    conn = get_db()
    if user.get("role_type") == "admin":
        rows = conn.execute("SELECT id, case_code, status, consent_method, consented_at, expires_at, created_at FROM guest_cases WHERE deleted_at IS NULL ORDER BY created_at DESC LIMIT 100").fetchall()
    else:
        rows = conn.execute("SELECT id, case_code, status, consent_method, consented_at, expires_at, created_at FROM guest_cases WHERE counsellor_id=? AND deleted_at IS NULL ORDER BY created_at DESC LIMIT 100", (user["id"],)).fetchall()
    conn.close()
    return [dict(row) for row in rows]


@router.get("/cases/{case_id}")
async def get_guest_case(case_id: str, user: dict = Depends(require_auth)):
    _require_counsellor(user)
    conn = get_db()
    case = _owned_case(conn, case_id, user)
    sessions = conn.execute("SELECT id, results_encrypted, created_at FROM guest_analysis_sessions WHERE case_id=? ORDER BY created_at DESC", (case_id,)).fetchall()
    notes = conn.execute("SELECT note_type,private_note_encrypted,visitor_update_encrypted,created_at FROM guest_case_notes WHERE case_id=? ORDER BY created_at DESC", (case_id,)).fetchall()
    conn.close()
    return {"case": {k: case[k] for k in ("id", "case_code", "status", "consent_method", "consented_at", "expires_at", "created_at")}, "sessions": [{"id": row["id"], "created_at": row["created_at"], "results": json.loads(decrypt_pii(row["results_encrypted"]))} for row in sessions], "notes": [{"type": n["note_type"], "private_note": decrypt_pii(n["private_note_encrypted"]), "visitor_update": decrypt_pii(n["visitor_update_encrypted"]) if n["visitor_update_encrypted"] else None, "created_at": n["created_at"]} for n in notes]}


@router.post("/cases/{case_id}/renew-consent")
async def renew_guest_consent(case_id: str, user: dict = Depends(require_auth)):
    _require_counsellor(user)
    conn = get_db()
    case = _owned_case(conn, case_id, user)
    if case["status"] in {"closed", "declined", "deleted", "expired_deleted"} or case["expires_at"] <= _now():
        conn.close()
        raise HTTPException(409, "This guest case cannot be renewed; create a new case instead")
    token = secrets.token_urlsafe(32)
    now = _now()
    consent_expires = (datetime.now(timezone.utc) + timedelta(days=CONSENT_LINK_DAYS)).isoformat()
    conn.execute("UPDATE guest_cases SET status='pending_consent',consent_method=NULL,consented_at=NULL,consent_token_hash=?,consent_expires_at=?,updated_at=? WHERE id=?", (hash_token(token), consent_expires, now, case_id))
    conn.commit(); conn.close()
    base = os.getenv("APP_BASE_URL", "https://app.mindguardai.me").rstrip("/")
    return {"consent_url": f"{base}/guest-consent?token={token}", "consent_expires_at": consent_expires, "expires_at": case["expires_at"]}


@router.post("/cases/{case_id}/notes", status_code=201)
async def create_guest_case_note(case_id: str, data: GuestCaseNote, request: Request, user: dict = Depends(require_auth)):
    _require_counsellor(user)
    conn = get_db()
    case = _owned_case(conn, case_id, user)
    if case["status"] in {"closed", "declined", "deleted", "expired_deleted"} or case["expires_at"] <= _now():
        conn.close()
        raise HTTPException(409, "This guest case is closed or expired")
    now = _now()
    conn.execute("INSERT INTO guest_case_notes (id,case_id,counsellor_id,note_type,private_note_encrypted,visitor_update_encrypted,created_at) VALUES (?,?,?,?,?,?,?)", (str(uuid.uuid4()), case_id, user["id"], "care_note", encrypt_pii(data.private_note.strip()), encrypt_pii(data.visitor_update.strip()) if data.visitor_update and data.visitor_update.strip() else None, now))
    conn.commit(); conn.close()
    write_audit(user["id"], user["role_type"], "GUEST_CASE_NOTE_CREATED", "guest_case", case_id, payload={"visitor_update_shared": bool(data.visitor_update and data.visitor_update.strip())}, ip=request.client.host if request.client else None)
    return {"ok": True, "created_at": now}


@router.post("/cases/{case_id}/referrals", status_code=201)
async def record_guest_referral(case_id: str, data: GuestReferral, request: Request, user: dict = Depends(require_auth)):
    _require_counsellor(user)
    conn = get_db()
    case = _owned_case(conn, case_id, user)
    if case["status"] in {"closed", "declined", "deleted", "expired_deleted"}:
        conn.close()
        raise HTTPException(409, "This guest case is closed")
    now = _now()
    conn.execute("INSERT INTO guest_case_notes (id,case_id,counsellor_id,note_type,private_note_encrypted,created_at) VALUES (?,?,?,?,?,?)", (str(uuid.uuid4()), case_id, user["id"], "referral", encrypt_pii(data.note.strip()), now))
    conn.commit(); conn.close()
    write_audit(user["id"], user["role_type"], "GUEST_REFERRAL_RECORDED", "guest_case", case_id, payload={"referral_note_recorded": True}, ip=request.client.host if request.client else None)
    return {"ok": True, "created_at": now}


@router.post("/cases/{case_id}/close")
async def close_guest_case(case_id: str, request: Request, user: dict = Depends(require_auth)):
    _require_counsellor(user)
    conn = get_db()
    case = _owned_case(conn, case_id, user)
    now = _now()
    if case["status"] == "pending_consent":
        conn.execute("DELETE FROM guest_platform_authorizations WHERE case_id=?", (case_id,))
    conn.execute("UPDATE guest_cases SET status='closed', closed_at=?, updated_at=? WHERE id=?", (now, now, case_id))
    conn.commit(); conn.close()
    write_audit(user["id"], user["role_type"], "GUEST_CASE_CLOSED", "guest_case", case_id, ip=request.client.host if request.client else None)
    return {"ok": True}


@router.delete("/cases/{case_id}")
async def delete_guest_case(case_id: str, request: Request, user: dict = Depends(require_auth)):
    _require_counsellor(user)
    conn = get_db()
    _owned_case(conn, case_id, user)
    conn.execute("DELETE FROM guest_analysis_sessions WHERE case_id=?", (case_id,))
    conn.execute("DELETE FROM guest_platform_authorizations WHERE case_id=?", (case_id,))
    conn.execute("DELETE FROM guest_case_notes WHERE case_id=?", (case_id,))
    now = _now()
    conn.execute("UPDATE guest_cases SET status='deleted', consent_token_hash=?, deleted_at=?, updated_at=? WHERE id=?", (hash_token(secrets.token_urlsafe(32)), now, now, case_id))
    conn.commit(); conn.close()
    write_audit(user["id"], user["role_type"], "GUEST_CASE_DELETED", "guest_case", case_id, payload={"sensitive_data_removed": True}, ip=request.client.host if request.client else None)
    return {"ok": True, "recoverable": False}


def purge_expired_guest_cases() -> int:
    now = _now()
    conn = get_db()
    rows = conn.execute(
        "SELECT id FROM guest_cases WHERE deleted_at IS NULL AND "
        "(expires_at<=? OR (status='pending_consent' AND consent_expires_at<=?))",
        (now, now),
    ).fetchall()
    for row in rows:
        conn.execute("DELETE FROM guest_analysis_sessions WHERE case_id=?", (row["id"],))
        conn.execute("DELETE FROM guest_platform_authorizations WHERE case_id=?", (row["id"],))
        conn.execute("DELETE FROM guest_case_notes WHERE case_id=?", (row["id"],))
        conn.execute("UPDATE guest_cases SET status='expired_deleted', consent_token_hash=?, deleted_at=?, updated_at=? WHERE id=?", (hash_token(secrets.token_urlsafe(32)), now, now, row["id"]))
    conn.commit(); conn.close()
    return len(rows)
