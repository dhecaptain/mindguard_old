"""Shared, non-diagnostic risk policy for analysis and care workflows."""

from dataclasses import dataclass


MODERATE_THRESHOLD = 0.35
ALERT_THRESHOLD = 0.55
CRISIS_REVIEW_THRESHOLD = 0.75


@dataclass(frozen=True)
class RiskAssessment:
    tier: str
    alert_eligible: bool
    crisis_escalation_eligible: bool


def assess_risk(
    score: float, alert_threshold: float = ALERT_THRESHOLD
) -> RiskAssessment:
    score = float(score)
    if score < MODERATE_THRESHOLD:
        tier = "low"
    elif score < ALERT_THRESHOLD:
        tier = "moderate"
    elif score < CRISIS_REVIEW_THRESHOLD:
        tier = "high"
    else:
        tier = "critical"
    return RiskAssessment(
        tier=tier,
        alert_eligible=score >= alert_threshold,
        crisis_escalation_eligible=score >= CRISIS_REVIEW_THRESHOLD,
    )


def risk_label(score: float) -> tuple[str, str, str]:
    labels = {
        "low": ("Low Risk", "#22c55e"),
        "moderate": ("Moderate Risk", "#f59e0b"),
        "high": ("High Risk", "#f97316"),
        "critical": ("Critical Risk", "#ef4444"),
    }
    tier = assess_risk(score).tier
    label, color = labels[tier]
    return label, color, tier
