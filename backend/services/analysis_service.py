"""Analysis orchestration service (Delivery Brief §7, §9.3).

Defines the boundary between HTTP concerns (routes in ``backend/main.py``) and
the inference/consent logic:

* ``predict_one`` / ``predict_batch`` (``backend.services.predictor``) are the
  low-level model port.
* This module owns the *product* rules that wrap inference for a student:
  consent enforcement, risk computation, alert/notification side-effects, and
  audit. Routes stay thin and simply translate the result (or exception) to an
  HTTP response.

Boundary rules (enforced here, not scattered across routes):

* **Consented student analysis** — analysing a specific student's content
  (``run_consented_student_analysis``) requires an ACCEPTED, non-expired
  consent on record when ``ENFORCE_CONSENT_ANALYSIS`` is on.
* **Self-serve analysis** (``/api/analysis/text|image``) is the student running
  the model on their own input; no institutional consent is required.
* **Analysis-staff handle analysis** (``/api/platforms/*``) targets arbitrary
  public handles supplied by staff; no student consent applies.
"""

import logging

from fastapi import HTTPException

from backend.database import (
    create_notification,
    get_user_by_id,
    get_institution_by_id,
    update_rolling_risk,
    write_audit,
)
from backend.services.alert_service import compute_rolling_risk, try_create_alert
from backend.services.consent_gate import require_consent_for_analysis
from backend.services.risk_policy import ALERT_THRESHOLD, assess_risk

logger = logging.getLogger(__name__)

# Consolidated failure message for every inference outage. Kept as a constant
# so routes, docs and tests agree on the contract.
INFERENCE_UNAVAILABLE_MESSAGE = (
    "Analysis service temporarily unavailable. Please try again in a moment."
)


def inference_http_error(exc: Exception) -> HTTPException:
    """Map a low-level inference failure to a stable 503 response.

    Logs the underlying cause (with request context, via the structured
    logging filter) but never leaks model internals to clients.
    """
    logger.exception("ML inference error: %s", exc)
    return HTTPException(503, INFERENCE_UNAVAILABLE_MESSAGE)


def run_consented_student_analysis(
    *,
    student_id: str,
    posts: list,
    platform: str,
    actor: dict,
    ip: str | None,
) -> dict:
    """Compute rolling risk for a student's posts, consent-gated.

    Raises ``HTTPException(403)`` when consent is enforced and the student has
    no active (accepted, non-expired) consent on record — this is the single
    enforcement point for consented student analysis.
    """
    require_consent_for_analysis(student_id)

    if not isinstance(posts, list) or not posts:
        raise HTTPException(400, "posts must be a non-empty list")
    for i, post in enumerate(posts):
        if not isinstance(post, dict):
            raise HTTPException(400, f"posts[{i}] must be an object")
        if "risk_score" not in post:
            raise HTTPException(400, f"posts[{i}] missing required field 'risk_score'")

    platform = (platform or "unknown").strip().lower()
    rolling_score = compute_rolling_risk(posts, window_days=14)
    n_posts = len(posts)

    risk_record = update_rolling_risk(
        student_id=student_id,
        score=rolling_score,
        top_platform=platform,
        n_posts=n_posts,
    )

    write_audit(
        actor["id"],
        actor["role_type"],
        "ROLLING_RISK_COMPUTED",
        "student",
        student_id,
        payload={"platform": platform, "score": rolling_score, "n_posts": n_posts},
        ip=ip,
    )

    student = get_user_by_id(student_id)
    student_name = student["name"] if student else student_id

    institution = (
        get_institution_by_id(actor.get("institution_id"))
        if actor.get("institution_id")
        else None
    )
    configured_threshold = institution.get("alert_threshold") if institution else None
    try:
        alert_threshold = (
            float(configured_threshold) if configured_threshold is not None else None
        )
    except (TypeError, ValueError):
        alert_threshold = None
    alert_threshold = alert_threshold or ALERT_THRESHOLD
    assessment = assess_risk(rolling_score, alert_threshold=alert_threshold)
    alert = None
    if assessment.alert_eligible:
        try:
            alert = try_create_alert(
                student_id=student_id,
                counsellor_id=actor["id"],
                rolling_score=rolling_score,
                platform=platform,
                threshold=alert_threshold,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("try_create_alert error student=%s: %s", student_id, exc)

        if alert:
            try:
                create_notification(
                    actor["id"],
                    "Risk Alert Triggered",
                    f"Student {student_name} has a rolling risk score of {rolling_score:.2f} on {platform}.",
                    "alert",
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.error(
                    "alert notification failed student=%s: %s", student_id, exc
                )
            write_audit(
                actor["id"],
                actor["role_type"],
                "ALERT_CREATED",
                "alert",
                alert["id"],
                payload={"student_id": student_id, "score": rolling_score},
                ip=ip,
            )

            def _composio_triage_fastlane():
                try:
                    from backend.services.composio_fastlane import (
                        trigger_triage_fastlane,
                    )

                    trigger_triage_fastlane(
                        student_id=student_id,
                        rolling_score=rolling_score,
                        platform=platform,
                        actor=actor,
                    )
                except Exception as e:
                    logger.warning(
                        "composio triage fastlane failed student=%s: %s", student_id, e
                    )

            try:
                import asyncio as _asyncio

                try:
                    _asyncio.get_running_loop().create_task(
                        _asyncio.to_thread(_composio_triage_fastlane)
                    )
                except RuntimeError:
                    _composio_triage_fastlane()
            except Exception:
                pass

    if assessment.crisis_escalation_eligible:
        write_audit(
            actor["id"],
            actor["role_type"],
            "CRISIS_REVIEW_REQUIRED",
            "student",
            student_id,
            payload={"score": rolling_score, "human_review_required": True},
            ip=ip,
        )

    return {
        "student_id": student_id,
        "platform": platform,
        "rolling_score": rolling_score,
        "n_posts": n_posts,
        "risk_record": risk_record,
        "alert_created": alert is not None,
        "alert": alert,
        "risk_tier": assessment.tier,
        "alert_eligible": assessment.alert_eligible,
        "crisis_escalation_eligible": assessment.crisis_escalation_eligible,
        "crisis_review_required": assessment.crisis_escalation_eligible,
    }
