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


def voice_tool_definitions(user: dict) -> list[dict]:
    """Return only the MindGuard actions supported for this authenticated role."""
    tools = [
        _tool("get_my_current_support", "Look up the authenticated user's own current support relationship and active requests."),
        _tool("get_my_upcoming_appointments", "Look up the authenticated user's own upcoming appointments."),
        _tool("navigate", "Open one approved MindGuard page. Never provide a URL.", {
            "target": {"type": "string", "enum": list(NAVIGATION_TARGETS)},
        }, ["target"]),
        _tool("prepare_for_appointment", "Start private preparation prompts for one appointment returned by get_my_upcoming_appointments. Do not save or share preparation notes.", {
            "appointment_id": {"type": "string"},
        }, ["appointment_id"]),
        _tool("propose_private_summary", "Prepare a concise, non-diagnostic note of the user's expressed concerns and decisions. This only stages a private note; wait for explicit confirmation before saving.", {
            "summary": {"type": "string", "description": "Concise draft distinguishing user statements from assistant suggestions. Do not diagnose."},
        }, ["summary"]),
    ]
    if user.get("role_type") == "workplace_employee":
        tools.extend([
            _tool("get_my_available_providers", "List providers currently eligible for this employee's workplace."),
            _tool("propose_workplace_checkin", "Stage a private workplace check-in using the existing three 1-to-5 answers. Ask for explicit ratings; never infer scores from conversation. This action always requires confirmation.", {
                "mood": {"type": "integer", "minimum": 1, "maximum": 5},
                "stress": {"type": "integer", "minimum": 1, "maximum": 5},
                "support_access": {"type": "integer", "minimum": 1, "maximum": 5},
            }, ["mood", "stress", "support_access"]),
            _tool("propose_summary_share", "Stage sharing an already-saved private note with one of the employee's own active workplace support cases. This always requires separate confirmation.", {
                "case_id": {"type": "string"},
            }, ["case_id"]),
        ])
    if user.get("role_type") == "student":
        tools.append(_tool("propose_human_support", "Stage a short request to the user's already-assigned counsellor. It includes no transcript or private note and always requires confirmation."))
    elif user.get("role_type") == "workplace_employee":
        tools.append(_tool("propose_human_support", "After the user chooses one returned eligible provider, start the MindGuard support request flow. The server will separately ask permission to share the latest check-in and then ask for final confirmation. Do not claim a request was sent.", {
            "provider_id": {"type": "string"},
        }, ["provider_id"]))
    return tools


def _tool(name: str, description: str, properties: dict | None = None, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties or {},
            "required": required or [],
            "additionalProperties": False,
        },
    }
