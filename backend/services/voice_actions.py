"""Allowlisted Voice action metadata and safe result vocabulary.

The realtime model has no direct application tools. Authenticated UI requests
enter through the Voice API and are checked again before execution.
"""

from typing import Final

READ_ONLY: Final = "READ_ONLY"
CONFIRM_REQUIRED: Final = "CONFIRM_REQUIRED"
SHARE_REQUIRED: Final = "SHARE_REQUIRED"

ACTION_SENSITIVITY: Final = {
    "get_my_current_support": READ_ONLY,
    "get_my_upcoming_appointments": READ_ONLY,
    "get_my_available_providers": READ_ONLY,
    "navigate": READ_ONLY,
    "prepare_for_appointment": READ_ONLY,
    "propose_workplace_checkin": CONFIRM_REQUIRED,
    "propose_human_support": CONFIRM_REQUIRED,
    "propose_private_summary": CONFIRM_REQUIRED,
    "propose_summary_share": SHARE_REQUIRED,
}

ACTION_RESULTS: Final = {
    "SUCCESS",
    "NOT_FOUND",
    "NOT_ALLOWED",
    "CONFIRMATION_REQUIRED",
    "CONSENT_REQUIRED",
    "WORKPLACE_UNAVAILABLE",
    "PROVIDER_UNAVAILABLE",
    "FAILED",
}

NAVIGATION_TARGETS: Final = {
    "appointments": "appointments",
    "support": "communications",
    "checkins": "feedback",
    "workplace_space": "workplace",
}
