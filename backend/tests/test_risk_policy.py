from backend.services.alert_service import compute_rolling_risk, should_alert
from backend.services.risk_policy import assess_risk


def test_risk_tier_boundaries_and_eligibility():
    assert assess_risk(0.34).tier == "low"
    assert assess_risk(0.35).tier == "moderate"
    assert assess_risk(0.54).tier == "moderate"
    assert assess_risk(0.55).tier == "high"
    assert assess_risk(0.74).tier == "high"
    assert assess_risk(0.75).tier == "critical"
    assert not assess_risk(0.50).alert_eligible
    assert assess_risk(0.55).alert_eligible
    assert assess_risk(0.75).crisis_escalation_eligible


def test_alert_threshold_keeps_confidence_and_short_text_rules_separate():
    assert not should_alert(0.55, confidence=0.69)
    assert should_alert(0.55, confidence=0.70)
    assert compute_rolling_risk([{"risk_score": 0.75, "text": "short"}]) < 0.75
