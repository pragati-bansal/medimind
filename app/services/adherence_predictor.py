"""
MediMind AI — Adherence Predictor
Analyzes historical dose patterns to predict future adherence
and surface behavioral insights without any external ML libraries.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import List, Dict, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

class DoseRecord:
    def __init__(self, scheduled_at: str, status: str, delay_minutes: int = 0):
        self.scheduled_at = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
        self.status = status
        self.delay_minutes = delay_minutes
        self.hour = self.scheduled_at.hour
        self.weekday = self.scheduled_at.weekday()   # 0=Mon, 6=Sun
        self.is_weekend = self.weekday >= 5


# ─────────────────────────────────────────────────────────────────────────────
# Feature extraction
# ─────────────────────────────────────────────────────────────────────────────

def extract_features(records: List[DoseRecord]) -> Dict:
    if not records:
        return {}

    total = len(records)
    taken = [r for r in records if r.status == "taken"]
    missed = [r for r in records if r.status == "missed"]
    delayed = [r for r in records if r.status == "delayed"]

    # Time-of-day buckets
    morning   = [r for r in records if 5  <= r.hour < 12]
    afternoon = [r for r in records if 12 <= r.hour < 18]
    evening   = [r for r in records if 18 <= r.hour < 24]

    def pct(subset, total_):
        return round(len([r for r in subset if r.status == "taken"]) / max(len(subset), 1) * 100, 1)

    # Weekday vs weekend
    weekday_recs = [r for r in records if not r.is_weekend]
    weekend_recs = [r for r in records if r.is_weekend]

    # Day-of-week breakdown
    dow_taken = defaultdict(int)
    dow_total = defaultdict(int)
    for r in records:
        dow_total[r.weekday] += 1
        if r.status == "taken":
            dow_taken[r.weekday] += 1

    dow_rates = {
        ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][d]: round(dow_taken[d]/dow_total[d]*100,1)
        for d in range(7) if dow_total[d] > 0
    }

    # Average delay on delayed/taken doses
    delay_vals = [r.delay_minutes for r in taken + delayed if r.delay_minutes > 0]
    avg_delay = round(sum(delay_vals) / len(delay_vals), 1) if delay_vals else 0

    # Streak (consecutive fully-taken days)
    days_map: dict[str, list] = defaultdict(list)
    for r in records:
        days_map[r.scheduled_at.date().isoformat()].append(r)

    streak = 0
    for day_str in sorted(days_map.keys(), reverse=True):
        day_recs = days_map[day_str]
        if all(r.status == "taken" for r in day_recs):
            streak += 1
        else:
            break

    return {
        "total":             total,
        "taken_count":       len(taken),
        "missed_count":      len(missed),
        "delayed_count":     len(delayed),
        "adherence_rate":    round(len(taken) / total * 100, 2),
        "morning_rate":      pct(morning, total),
        "afternoon_rate":    pct(afternoon, total),
        "evening_rate":      pct(evening, total),
        "weekday_rate":      pct(weekday_recs, total),
        "weekend_rate":      pct(weekend_recs, total),
        "avg_delay_minutes": avg_delay,
        "streak_days":       streak,
        "dow_rates":         dow_rates,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Risk classifier
# ─────────────────────────────────────────────────────────────────────────────

def classify_risk(features: Dict) -> Dict:
    """
    Multi-factor risk scoring (0–100, higher = more risky).
    """
    if not features:
        return {"level": "unknown", "score": 0, "factors": []}

    score = 0
    factors = []

    rate = features.get("adherence_rate", 100)
    if rate < 60:
        score += 40
        factors.append({"factor": "Very low adherence", "weight": "high", "value": f"{rate}%"})
    elif rate < 80:
        score += 20
        factors.append({"factor": "Below target adherence", "weight": "medium", "value": f"{rate}%"})

    weekend_drop = features.get("weekday_rate", 100) - features.get("weekend_rate", 100)
    if weekend_drop > 20:
        score += 15
        factors.append({"factor": "Weekend non-adherence", "weight": "medium", "value": f"-{weekend_drop:.0f}% on weekends"})

    avg_delay = features.get("avg_delay_minutes", 0)
    if avg_delay > 120:
        score += 15
        factors.append({"factor": "Consistently late doses", "weight": "medium", "value": f"Avg {avg_delay} min late"})
    elif avg_delay > 60:
        score += 7

    streak = features.get("streak_days", 0)
    if streak == 0:
        score += 10
        factors.append({"factor": "No current streak", "weight": "low", "value": "0 days"})

    afternoon_rate = features.get("afternoon_rate", 100)
    if afternoon_rate < 60:
        score += 10
        factors.append({"factor": "Afternoon doses often missed", "weight": "low", "value": f"{afternoon_rate}%"})

    score = min(score, 100)
    level = "high" if score >= 50 else ("medium" if score >= 25 else "low")

    return {"level": level, "score": score, "factors": factors}


# ─────────────────────────────────────────────────────────────────────────────
# Prediction (simple weighted trend)
# ─────────────────────────────────────────────────────────────────────────────

def predict_next_week(features: Dict) -> Dict:
    """
    Predict next-week adherence using a simple weighted regression
    on recent trend. No external libraries needed.
    """
    if not features:
        return {"predicted_rate": 0.0, "trend": "unknown", "confidence": 0.0}

    current_rate = features.get("adherence_rate", 0)
    streak = features.get("streak_days", 0)
    avg_delay = features.get("avg_delay_minutes", 0)

    # Positive signals
    boost = 0.0
    if streak >= 7:
        boost += 3.0
    elif streak >= 3:
        boost += 1.5

    # Negative signals
    drag = 0.0
    if avg_delay > 60:
        drag += 2.0
    if features.get("weekend_rate", 100) < features.get("weekday_rate", 100) - 20:
        drag += 1.5

    predicted = round(min(100, max(0, current_rate + boost - drag)), 2)
    delta = predicted - current_rate
    trend = "improving" if delta > 1 else ("declining" if delta < -1 else "stable")

    confidence = 0.85 if features["total"] >= 30 else (0.65 if features["total"] >= 14 else 0.45)

    return {
        "predicted_rate": predicted,
        "current_rate":   current_rate,
        "delta":          round(delta, 2),
        "trend":          trend,
        "confidence":     confidence,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Personalized recommendations
# ─────────────────────────────────────────────────────────────────────────────

def generate_recommendations(features: Dict, risk: Dict) -> List[Dict]:
    recs = []

    # Weekend adherence drop
    if features.get("weekday_rate", 100) - features.get("weekend_rate", 100) > 15:
        recs.append({
            "priority": "high",
            "title":    "Set weekend-specific reminders",
            "body":     "Your weekend adherence is significantly lower. Enable louder or more persistent Saturday/Sunday alerts.",
            "action":   "update_reminder_settings",
        })

    # Afternoon slump
    if features.get("afternoon_rate", 100) < 70:
        recs.append({
            "priority": "medium",
            "title":    "Afternoon doses often missed",
            "body":     "Try linking your afternoon dose to a daily routine — right after lunch or a coffee break.",
            "action":   "add_meal_link",
        })

    # Long delays
    if features.get("avg_delay_minutes", 0) > 90:
        recs.append({
            "priority": "medium",
            "title":    "Reduce average dose delay",
            "body":     f"Your average delay is {features['avg_delay_minutes']} minutes. Move reminder 30 min earlier.",
            "action":   "shift_reminder_earlier",
        })

    # Low streak
    if features.get("streak_days", 0) < 3 and features.get("adherence_rate", 100) > 70:
        recs.append({
            "priority": "low",
            "title":    "Build a consistent streak",
            "body":     "You're close to a solid streak. Taking all doses for 3 more days will unlock a milestone!",
            "action":   "streak_challenge",
        })

    # High performer
    if features.get("adherence_rate", 0) >= 95:
        recs.append({
            "priority": "info",
            "title":    "Excellent adherence — keep it up!",
            "body":     "You're in the top tier of medication adherence. Maintaining this significantly reduces health risks.",
            "action":   None,
        })

    return recs


# ─────────────────────────────────────────────────────────────────────────────
# Main pipeline
# ─────────────────────────────────────────────────────────────────────────────

def run_adherence_pipeline(raw_logs: List[dict]) -> Dict:
    """
    Full pipeline: raw Supabase dose_logs → features → risk → prediction → recs.
    """
    records = [
        DoseRecord(
            scheduled_at=log["scheduled_at"],
            status=log["status"],
            delay_minutes=log.get("delay_minutes", 0) or 0,
        )
        for log in raw_logs
        if log.get("scheduled_at") and log.get("status")
    ]

    features    = extract_features(records)
    risk        = classify_risk(features)
    prediction  = predict_next_week(features)
    recs        = generate_recommendations(features, risk)

    return {
        "features":        features,
        "risk":            risk,
        "prediction":      prediction,
        "recommendations": recs,
    }
