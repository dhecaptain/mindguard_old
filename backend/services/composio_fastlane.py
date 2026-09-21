import logging
import os
import subprocess
import json
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def _decrypt_demo_field(v):
    if isinstance(v, str) and v.startswith("gcm1:"):
        try:
            from backend.services.crypto import decrypt_pii

            return decrypt_pii(v)
        except Exception:
            return v
    return v


def _hash_email(email: str) -> str:
    try:
        from backend.services.crypto import hash_email

        return hash_email(email)
    except Exception:
        return email.strip().lower() if email else ""


def _score_demo(work_email: str, org_type: str) -> str:
    w = (work_email or "").lower()
    if w.endswith(".edu") or ".ac.uk" in w or "university" in (org_type or "").lower():
        return "HIGH_PRIORITY"
    return "STANDARD"


def _run_composio(script_abs: str, payload: dict):
    if not os.getenv("COMPOSIO_API_KEY"):
        logger.info("composio fastlane skipped: COMPOSIO_API_KEY not set")
        return
    sheet_id = os.getenv("GOOGLE_SHEETS_CRM_ID", "").strip()
    slack_demo = os.getenv("SLACK_CHANNEL_DEMO", "#demo-requests")
    slack_triage = os.getenv("SLACK_CHANNEL_TRIAGE", "#triage")
    # Use `composio run` with injected execute(); payload passed via env JSON
    tmp = Path(tempfile.gettempdir()) / f"composio_payload_{os.getpid()}.json"
    try:
        tmp.write_text(json.dumps(payload))
        env = {
            **os.environ,
            "COMPOSIO_PAYLOAD_FILE": str(tmp),
            "GOOGLE_SHEETS_CRM_ID": sheet_id,
            "SLACK_CHANNEL_DEMO": slack_demo,
            "SLACK_CHANNEL_TRIAGE": slack_triage,
        }
        subprocess.run(
            ["composio", "run", script_abs], env=env, timeout=25, capture_output=True
        )
    except Exception as e:
        logger.warning("composio run failed: %s", e)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def trigger_demo_fastlane(demo: dict):
    work_email = _decrypt_demo_field(demo.get("work_email") or "")
    name = _decrypt_demo_field(demo.get("full_name") or "")
    org = _decrypt_demo_field(demo.get("organisation") or "")
    payload = {
        "kind": "demo",
        "name": name,
        "work_email": work_email,
        "work_email_hash": _hash_email(work_email),
        "institution": org,
        "org_type": demo.get("organisation_type") or "",
        "score": _score_demo(work_email, demo.get("organisation_type") or ""),
        "demo_id": demo.get("id"),
    }
    script = str(
        Path(__file__).resolve().parent.parent.parent
        / "marketing"
        / "scripts"
        / "composio_fastlane.mjs"
    )
    # Also direct fallback via python composio CLI if script prefers env payload
    _run_composio(script, payload)
    # Best-effort direct python-side execute via composio CLI inline
    try:
        _direct_demo(payload)
    except Exception as e:
        logger.debug("direct demo composio skipped: %s", e)


def _direct_demo(p: dict):
    if not os.getenv("COMPOSIO_API_KEY") or not os.getenv("GOOGLE_SHEETS_CRM_ID"):
        return
    sheet = os.getenv("GOOGLE_SHEETS_CRM_ID").strip()
    demo_chan = os.getenv("SLACK_CHANNEL_DEMO", "#demo-requests")

    # These use `composio execute` synchronously; failures are logged not raised.
    # NOTE: Gmail sending has been removed. All application email must go through
    # the central Resend email service (backend/services/email_sender.py).
    def _exec(slug, data):
        try:
            subprocess.run(
                ["composio", "execute", slug, "-d", json.dumps(data)],
                timeout=20,
                capture_output=True,
            )
        except Exception as e:
            logger.warning("composio execute %s failed: %s", slug, e)

    _exec(
        "GOOGLESHEETS_SPREADSHEETS_VALUES_APPEND",
        {
            "spreadsheetId": sheet,
            "range": "Sheet1!A:E",
            "valueInputOption": "USER_ENTERED",
            "values": [
                [
                    p["name"],
                    p["work_email_hash"],
                    p["institution"],
                    p["score"],
                    p.get("demo_id", ""),
                ]
            ],
        },
    )
    _exec(
        "SLACK_SEND_MESSAGE",
        {
            "channel": demo_chan,
            "text": f"🚀 Demo: {p['name']} {p['institution']} {p['score']} hash:{p['work_email_hash']}",
        },
    )


def trigger_triage_fastlane(
    *, student_id: str, rolling_score: float, platform: str, actor: dict
):
    from backend.services.risk_policy import ALERT_THRESHOLD, assess_risk

    if rolling_score < ALERT_THRESHOLD:
        return
    if not os.getenv("COMPOSIO_API_KEY"):
        return
    from backend.services.crypto import hash_email as _he

    # student_id is user.id; hash for Slack PII boundary
    sid_hash = _he(student_id) if "@" in student_id else student_id[:12]
    triage_chan = os.getenv("SLACK_CHANNEL_TRIAGE", "#triage")
    payload = {
        "kind": "triage",
        "student_id_hash": sid_hash,
        "risk_tier": assess_risk(rolling_score).tier.upper(),
        "prob": rolling_score,
        "institution_id": actor.get("institution_id") or actor.get("id"),
        "platform": platform,
    }

    def _exec(slug, data):
        try:
            subprocess.run(
                ["composio", "execute", slug, "-d", json.dumps(data)],
                timeout=20,
                capture_output=True,
            )
        except Exception as e:
            logger.warning("composio triage execute %s failed: %s", slug, e)

    _exec(
        "SLACK_SEND_MESSAGE",
        {
            "channel": triage_chan,
            "text": f"⚠️ Triage {payload['risk_tier']} prob {rolling_score:.2f} hash {sid_hash} <https://app.mindguardai.me/dashboard|Dashboard>",
        },
    )
    try:
        jk = os.getenv("JIRA_PROJECT_KEY", "TRIAGE")
        if jk:
            _exec(
                "JIRA_CREATE_ISSUE",
                {
                    "project_key": jk,
                    "summary": f"[Triage] {payload['risk_tier']} {sid_hash[:8]}",
                    "description": f"hash={sid_hash} tier={payload['risk_tier']} prob={rolling_score} inst={payload['institution_id']} dashboard=https://app.mindguardai.me/dashboard",
                    "issue_type": "Task",
                },
            )
    except Exception:
        pass
