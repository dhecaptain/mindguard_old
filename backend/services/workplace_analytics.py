"""Privacy layer for company-facing workplace insights.

All employer analytics flow through this module. Only fixed, whole-company,
completed-month aggregates leave the service; respondent identities are used
transiently to deduplicate contributors and are never serialized.
"""

import json
import os
from collections import defaultdict
from datetime import date, datetime, timezone

from backend.services.crypto import decrypt_pii
from backend.services.workplace_commercial import can_use as commercial_can_use

METRICS = ("mood", "stress", "support_access")
METRIC_LABELS = {
    "mood": "Mood",
    "stress": "Stress manageability",
    "support_access": "Perceived access to support",
}
AVAILABLE = "AVAILABLE"
INSUFFICIENT = "INSUFFICIENT_DATA"
NO_DATA = "NO_DATA"
NOT_ENTITLED = "NOT_ENTITLED"
INACTIVE = "WORKPLACE_INACTIVE"


def minimum_cohort() -> int:
    """Allow stricter deployment thresholds, never weaken the 10-person floor."""
    try:
        configured = int(os.getenv("WORKPLACE_ANALYTICS_MIN_COHORT", "10"))
    except (TypeError, ValueError):
        configured = 10
    return min(1000, max(10, configured))


def _completed_months(now: datetime | None = None, count: int = 6) -> list[str]:
    current = (now or datetime.now(timezone.utc)).date().replace(day=1)
    months = []
    for offset in range(count, 0, -1):
        month_index = current.year * 12 + current.month - 1 - offset
        year, month = divmod(month_index, 12)
        months.append(date(year, month + 1, 1).strftime("%Y-%m"))
    return months


def _period_result(people: dict[str, dict[str, list[int]]], threshold: int) -> dict:
    if not people:
        return {"state": NO_DATA}
    if len(people) < threshold:
        return {"state": INSUFFICIENT}
    averages: dict[str, float] = {}
    for metric in METRICS:
        participants = [values[metric] for values in people.values() if values[metric]]
        if len(participants) < threshold:
            return {"state": INSUFFICIENT}
        # Weight workers equally, regardless of how often they checked in.
        averages[metric] = round(sum(sum(values) / len(values) for values in participants) / len(participants), 1)
    return {
        "state": AVAILABLE,
        "contributors": f"{threshold}+",
        "checkins": f"{threshold}+",
        "averages": averages,
        "wellbeing_indicator": round(sum(averages.values()) / len(METRICS), 1),
    }


def _recommendations(period: dict) -> list[dict[str, str]]:
    if period.get("state") != AVAILABLE:
        return []
    values = period["averages"]
    suggestions = []
    if values["stress"] <= 2.8:
        suggestions.append({"title": "Review workload practices", "detail": "Consider reviewing workload distribution and working-hours expectations across the organization."})
    if values["support_access"] <= 2.8:
        suggestions.append({"title": "Reinforce support options", "detail": "Consider making existing wellbeing and independent support options easier for everyone to find."})
    if values["mood"] <= 2.8:
        suggestions.append({"title": "Strengthen organization-wide wellbeing", "detail": "Consider broad manager wellbeing training and organization-wide opportunities for staff support."})
    if not suggestions:
        suggestions.append({"title": "Continue supportive practices", "detail": "Continue communicating available support and reinforcing organization-wide wellbeing practices."})
    return suggestions


def _unavailable(state: str, threshold: int) -> dict:
    messages = {
        NOT_ENTITLED: "Workplace Insights are not included in the current company plan.",
        INACTIVE: "Workplace Insights are unavailable while this workplace is inactive.",
        NO_DATA: "Insights will appear after eligible participants contribute in a completed reporting period.",
        INSUFFICIENT: "Insights will become available once enough employees have contributed to protect participant privacy.",
    }
    return {
        "state": state,
        "minimum_cohort": threshold,
        "privacy_message": messages.get(state, "Workplace Insights are currently unavailable."),
        "period": None,
        "overview": None,
        "themes": [],
        "risk_distribution": {"state": "UNAVAILABLE", "message": "The current check-in model does not define a reviewed organizational risk classification."},
        "trends": [],
        "comparison": {"state": state},
        "recommendations": [],
    }


def get_workplace_insights(conn, company_id: str, *, now: datetime | None = None,
                           actor_id: str | None = None, record_access: bool = True) -> dict:
    """Return one fixed-window, company-isolated, cohort-protected report DTO."""
    threshold = minimum_cohort()
    company = conn.execute("SELECT type,status FROM institutions WHERE id=?", (company_id,)).fetchone()
    if not company or str(company["type"]).lower() != "company" or str(company["status"] or "").upper() != "ACTIVE":
        result = _unavailable(INACTIVE, threshold)
    elif not commercial_can_use(conn, company_id, "aggregate_analytics"):
        result = _unavailable(NOT_ENTITLED, threshold)
    else:
        months = _completed_months(now)
        end_month = (now or datetime.now(timezone.utc)).date().replace(day=1).isoformat()
        start_month = date.fromisoformat(f"{months[0]}-01").isoformat()
        # The eligible cohort is active, explicitly opted-in workplace members
        # with an active account and at least one valid numeric answer in-month.
        rows = conn.execute(
            "SELECT substr(c.created_at,1,7) AS period,c.user_id,c.answers_json "
            "FROM workplace_checkins c "
            "JOIN workplace_memberships m ON m.company_id=c.company_id AND m.user_id=c.user_id "
            "JOIN users u ON u.id=m.user_id "
            "WHERE c.company_id=? AND c.created_at>=? AND c.created_at<? "
            "AND m.status='active' AND m.withdrawn_at IS NULL AND m.consented_at IS NOT NULL "
            "AND u.role_type='workplace_employee' AND lower(u.status) IN ('approved','active') "
            "ORDER BY c.created_at",
            (company_id, start_month, end_month),
        ).fetchall()
        by_month: dict[str, dict[str, dict[str, list[int]]]] = defaultdict(dict)
        for row in rows:
            try:
                answers = json.loads(decrypt_pii(row["answers_json"]))
            except (ValueError, TypeError, RuntimeError):
                continue
            month_people = by_month[row["period"]]
            person = month_people.setdefault(row["user_id"], {metric: [] for metric in METRICS})
            for metric in METRICS:
                value = answers.get(metric)
                if type(value) is int and 1 <= value <= 5:
                    person[metric].append(value)
        periods = {month: _period_result(by_month.get(month, {}), threshold) for month in months}
        latest, previous = months[-1], months[-2]
        current_data = periods[latest]
        if current_data["state"] in {NO_DATA, INSUFFICIENT}:
            result = _unavailable(current_data["state"], threshold)
            result["period"] = latest
            result["trends"] = [{"period": month, **periods[month]} for month in months]
        else:
            previous_data = periods[previous]
            delta = None
            direction = "unavailable"
            if previous_data["state"] == AVAILABLE:
                delta = round(current_data["wellbeing_indicator"] - previous_data["wellbeing_indicator"], 1)
                direction = "improving" if delta > 0.1 else "declining" if delta < -0.1 else "stable"
            themes = [
                {"key": metric, "label": METRIC_LABELS[metric], "average": current_data["averages"][metric], "scale": "1–5; higher is more positive"}
                for metric in METRICS
            ]
            comparison = {"state": AVAILABLE, "current_period": latest, "previous_period": previous, "changes": None}
            if previous_data["state"] == AVAILABLE:
                comparison["changes"] = {
                    metric: round(current_data["averages"][metric] - previous_data["averages"][metric], 1)
                    for metric in METRICS
                }
            else:
                comparison["state"] = previous_data["state"]
                comparison["current_period"] = latest
                comparison["previous_period"] = previous
            result = {
                "state": AVAILABLE,
                "minimum_cohort": threshold,
                "privacy_message": "All figures represent the whole workplace and meet the minimum distinct-participant threshold. No individual records are included.",
                "period": latest,
                "overview": {
                    "wellbeing_indicator": current_data["wellbeing_indicator"],
                    "scale": "1–5; higher is more positive",
                    "contributors": current_data["contributors"],
                    "checkins": current_data["checkins"],
                    "trend_direction": direction,
                    "change_from_previous_period": delta,
                },
                "themes": themes,
                "risk_distribution": {"state": "UNAVAILABLE", "message": "The current check-in model does not define a reviewed organizational risk classification."},
                "trends": [{"period": month, **periods[month]} for month in months],
                "comparison": comparison,
                "recommendations": _recommendations(current_data),
            }
    if record_access:
        conn.execute(
            "INSERT INTO workplace_audit_events (id,company_id,actor_user_id,event_type,occurred_at) VALUES (?,?,?,'WORKPLACE_INSIGHTS_VIEWED',?)",
            (__import__("uuid").uuid4().hex, company_id, actor_id, (now or datetime.now(timezone.utc)).isoformat()),
        )
    return result
