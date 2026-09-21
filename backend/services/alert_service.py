"""
Alert generation and disposition.

Thresholds:
  - Default risk threshold: 0.55 (institution-tunable)
  - Confidence floor: 0.70 (posts below don't trigger alerts)
  - Short-text penalty: < 20 tokens → score × 0.8
  - Cooldown: 12 h after alert fires; second alert only if score jumps >= 0.15
  - Rolling risk: time-decayed weighted average (recent posts weigh more)
"""

import math
from datetime import datetime, timezone

from backend.services.risk_policy import ALERT_THRESHOLD


def compute_rolling_risk(posts: list, window_days: int = 14) -> float:
    """
    Time-decayed weighted average of post risk scores.
    Posts from today weigh 1.0; posts from window_days ago weigh ~0.1.

    Each post dict must have:
      - risk_score: float
      - date: ISO-8601 string (may include trailing 'Z')
      - text: str  (used for short-text penalty)
    """
    if not posts:
        return 0.0

    now = datetime.now(timezone.utc)
    total_weight = 0.0
    weighted_sum = 0.0

    for post in posts:
        score = float(post.get("risk_score", 0.0))

        try:
            raw_date = (post.get("date") or "").replace("Z", "+00:00")
            post_date = datetime.fromisoformat(raw_date)
            days_ago = max(0.0, (now - post_date).total_seconds() / 86400)
        except (ValueError, AttributeError):
            days_ago = float(window_days)

        # Exponential decay: weight = e^(-3 * days_ago / window_days)
        weight = math.exp(-3.0 * days_ago / window_days)

        # Short-text penalty: fewer than 20 tokens → 80 % of score
        n_tokens = len((post.get("text") or "").split())
        if n_tokens < 20:
            score *= 0.8

        weighted_sum += weight * score
        total_weight += weight

    return weighted_sum / total_weight if total_weight > 0 else 0.0


def should_alert(
    rolling_score: float,
    threshold: float = ALERT_THRESHOLD,
    confidence: float = 1.0,
    confidence_floor: float = 0.70,
) -> bool:
    """Return True when rolling score meets the threshold and confidence is sufficient."""
    return rolling_score >= threshold and confidence >= confidence_floor


def try_create_alert(
    student_id: str,
    counsellor_id: str,
    rolling_score: float,
    platform: str,
    threshold: float = ALERT_THRESHOLD,
) -> dict | None:
    """
    Create an alert when:
      - rolling_score >= threshold
      - No open alert with cooldown_until in the future, OR
        score jumped >= 0.15 above the existing open alert's risk_score.

    Returns the new alert dict, or None if suppressed.
    """
    from backend.database import create_alert, get_open_alert_for_student

    if rolling_score < threshold:
        return None

    now = datetime.now(timezone.utc).isoformat()
    existing = get_open_alert_for_student(student_id)

    if existing:
        cooldown = existing.get("cooldown_until") or ""
        if cooldown and now < cooldown:
            # Still in cooldown — only fire if score jumped >= 0.15
            jump = rolling_score - float(existing.get("risk_score", 0.0))
            if jump < 0.15:
                return None

    return create_alert(student_id, counsellor_id, rolling_score, threshold, platform)
