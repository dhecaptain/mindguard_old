"""RBAC permission layer over the existing role model (Delivery Brief §5).

Roles: ``student`` / ``counsellor`` / ``school_admin`` / ``admin`` (plus the
``counselor`` alias). A ``school_admin`` is a counsellor who can additionally
upload/refresh the student roster and drive the bulk consent workflow (Brief
§1.1 "Role tightening — School Admin role added alongside Counsellor and
Student"). Per-user permissions are computed as:

    role defaults ∪ permissions_json

``permissions_json`` on the ``users`` row is an *additive* list of extra
permission grants, e.g. a counsellor promoted to roster duties gets
``["roster.upload", "students.view"]``. It is never used to *remove* a
permission — a role's core permissions always apply.
"""

import json
import logging

from fastapi import HTTPException

logger = logging.getLogger(__name__)


# ── Permission constants ───────────────────────────────────────────────

# Run social-media / text analysis (counsellors, admins).
PERM_ANALYSIS_RUN = "analysis.run"
# Upload / refresh the student roster CSV (school admins).
PERM_ROSTER_UPLOAD = "roster.upload"
# View the student roster.
PERM_STUDENTS_VIEW = "students.view"
# Drive the consent workflow (send, remind, revoke).
PERM_CONSENT_MANAGE = "consent.manage"
# Respond on the consent portal (student/parent side).
PERM_CONSENT_RESPOND = "consent.respond"
# Manage demo requests (internal pipeline).
PERM_DEMO_MANAGE = "demo.manage"
# View the full compliance / audit trail.
PERM_AUDIT_VIEW = "audit.view"

ALL_PERMISSIONS = frozenset(
    {
        PERM_ANALYSIS_RUN,
        PERM_ROSTER_UPLOAD,
        PERM_STUDENTS_VIEW,
        PERM_CONSENT_MANAGE,
        PERM_CONSENT_RESPOND,
        PERM_DEMO_MANAGE,
        PERM_AUDIT_VIEW,
    }
)


# ── Role → permission matrix ───────────────────────────────────────────

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    # Workplace roles use their own endpoint guards in backend.routes.workplace.
    # They intentionally inherit no school/counsellor permission grants.
    "company_admin": frozenset(),
    "workplace_employee": frozenset(),
    "workplace_provider": frozenset(),
    "student": frozenset({PERM_CONSENT_RESPOND}),
    "counsellor": frozenset(
        {
            PERM_ANALYSIS_RUN,
            PERM_STUDENTS_VIEW,
            PERM_CONSENT_MANAGE,
        }
    ),
    # School admin = counsellor duties + roster/bulk-consent workflow (Brief §1.1/§2.5).
    "school_admin": frozenset(
        {
            PERM_ANALYSIS_RUN,
            PERM_STUDENTS_VIEW,
            PERM_CONSENT_MANAGE,
            PERM_ROSTER_UPLOAD,
        }
    ),
    "admin": frozenset(ALL_PERMISSIONS),
}


def normalize_role(role: str | None) -> str:
    """Lowercase and collapse the US-spelling alias to a canonical role."""
    r = str(role or "").strip().lower()
    if r == "counselor":
        return "counsellor"
    return r if r in ROLE_PERMISSIONS else "student"


def role_permissions(role: str | None) -> frozenset[str]:
    return ROLE_PERMISSIONS.get(normalize_role(role), ROLE_PERMISSIONS["student"])


def parse_extra_permissions(permissions_json: str | None) -> set[str]:
    """Parse the additive ``permissions_json`` column (list or dict form)."""
    if not permissions_json:
        return set()
    try:
        raw = json.loads(permissions_json)
    except (ValueError, TypeError):
        logger.warning("permissions_json is not valid JSON: %r", permissions_json)
        return set()
    if isinstance(raw, dict):
        raw = raw.get("permissions", [])
    if not isinstance(raw, list):
        return set()
    extra = {str(p).strip() for p in raw if str(p).strip() in ALL_PERMISSIONS}
    return extra


def user_permissions(user: dict) -> frozenset[str]:
    """Effective permissions for a user row: role defaults ∪ permissions_json."""
    base = set(role_permissions(user.get("role_type")))
    base |= parse_extra_permissions(user.get("permissions_json"))
    return frozenset(base)


def has_permission(user: dict, permission: str) -> bool:
    return permission in user_permissions(user)


_ACTIVE_STATUSES = ("approved", "active")
_BLOCKED_STATUSES = ("pending", "revoked", "suspended", "disabled")


def _ensure_active(user: dict) -> None:
    """Block users whose account is not active from exercising permissions.

    ``pending`` accounts (e.g. a counsellor that registered before staff
    registration was closed) must not be able to view students, run analysis or
    manage consent until an admin approves them. ``revoked``/``suspended``
    accounts are likewise blocked at the permission layer as defense in depth
    on top of the auth check.
    """
    status = str(user.get("status") or "approved").lower()
    if status in _BLOCKED_STATUSES or status not in _ACTIVE_STATUSES:
        raise HTTPException(
            403,
            "Your account has not been approved yet, or has been suspended. "
            "Contact your school administrator if you believe this is in error.",
        )


def require_permission(user: dict, permission: str) -> None:
    _ensure_active(user)
    if not has_permission(user, permission):
        raise HTTPException(
            403,
            f"You need the {permission} permission to perform this action.",
        )


def require_any_permission(user: dict, permissions) -> None:
    _ensure_active(user)
    user_perms = user_permissions(user)
    if not user_perms.intersection(set(permissions)):
        raise HTTPException(403, "You are not authorised to perform this action.")
