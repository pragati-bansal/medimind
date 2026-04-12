"""
MediMind AI — AI Decision Engine
Determines what a patient should do when a dose is missed.
"""
from __future__ import annotations
from typing import Optional
from uuid import UUID

from app.config import get_supabase_admin
from app.models.schemas import AIDecisionOut


# ─────────────────────────────────────────────────────────────────────────────
# Drug safety profiles  (simplified — extend with a real drug DB in production)
# ─────────────────────────────────────────────────────────────────────────────

DRUG_PROFILES = {
    # drug keyword → {half_life_h, safe_window_mins, can_double, critical}
    "metformin":     {"half_life_h": 6,  "safe_window_mins": 120, "can_double": False, "critical": False},
    "lisinopril":    {"half_life_h": 12, "safe_window_mins": 240, "can_double": False, "critical": True},
    "atorvastatin":  {"half_life_h": 14, "safe_window_mins": 480, "can_double": False, "critical": False},
    "aspirin":       {"half_life_h": 6,  "safe_window_mins": 180, "can_double": False, "critical": False},
    "metoprolol":    {"half_life_h": 5,  "safe_window_mins": 90,  "can_double": False, "critical": True},
    "amlodipine":    {"half_life_h": 35, "safe_window_mins": 720, "can_double": False, "critical": True},
    "pantoprazole":  {"half_life_h": 2,  "safe_window_mins": 60,  "can_double": False, "critical": False},
    "warfarin":      {"half_life_h": 40, "safe_window_mins": 360, "can_double": False, "critical": True},
    "insulin":       {"half_life_h": 1,  "safe_window_mins": 30,  "can_double": False, "critical": True},
    "default":       {"half_life_h": 8,  "safe_window_mins": 120, "can_double": False, "critical": False},
}


def _get_drug_profile(medicine_name: str) -> dict:
    name_lower = medicine_name.lower()
    for key, profile in DRUG_PROFILES.items():
        if key in name_lower:
            return profile
    return DRUG_PROFILES["default"]


# ─────────────────────────────────────────────────────────────────────────────
# Core decision logic
# ─────────────────────────────────────────────────────────────────────────────

def decide_missed_dose(
    medicine_name: str,
    delay_minutes: int,
    frequency: str = "once_daily",
    next_dose_minutes: Optional[int] = None,
) -> AIDecisionOut:
    """
    Rule-based + heuristic AI engine.
    Returns recommendation: take_now | delay | skip
    """
    profile = _get_drug_profile(medicine_name)
    safe_window = profile["safe_window_mins"]
    critical = profile["critical"]
    can_double = profile["can_double"]

    # Determine next dose gap
    freq_gap_map = {
        "once_daily": 1440,
        "twice_daily": 720,
        "thrice_daily": 480,
        "four_times_daily": 360,
        "weekly": 10080,
    }
    dose_gap = freq_gap_map.get(frequency, 720)
    if next_dose_minutes is None:
        next_dose_minutes = dose_gap

    # ── Decision tree ────────────────────────────────────────────────────────

    # Case 1: Very recent miss (within safe window) → take now
    if delay_minutes <= safe_window and delay_minutes <= (dose_gap * 0.33):
        confidence = round(0.95 - (delay_minutes / safe_window) * 0.2, 2)
        return AIDecisionOut(
            recommendation="take_now",
            reasoning=(
                f"You are {delay_minutes} minutes late, still within the safe window "
                f"for {medicine_name} ({safe_window} min). Take the dose now."
            ),
            confidence=min(confidence, 0.95),
            safety_note="Take with food if required. Continue normal schedule after."
        )

    # Case 2: Missed more than half the dose interval → skip
    if delay_minutes >= dose_gap * 0.5:
        safety_note = (
            "⚠️ Do NOT take a double dose." if not can_double
            else "You may continue with the next scheduled dose."
        )
        confidence = round(0.85 + (delay_minutes / dose_gap) * 0.1, 2)
        return AIDecisionOut(
            recommendation="skip",
            reasoning=(
                f"You are {delay_minutes} minutes late — more than half the dosing interval "
                f"for {medicine_name}. Skipping and resuming normal schedule is safest."
            ),
            confidence=min(confidence, 0.95),
            safety_note=safety_note
        )

    # Case 3: Critical medication — always lean toward caution
    if critical and delay_minutes > safe_window:
        return AIDecisionOut(
            recommendation="skip",
            reasoning=(
                f"{medicine_name} is a critical medication with narrow therapeutic windows. "
                f"Since {delay_minutes} minutes have passed beyond the safe window, "
                "skipping and contacting your doctor is recommended."
            ),
            confidence=0.88,
            safety_note="⚠️ Consult your doctor if you frequently miss this medication."
        )

    # Case 4: Moderate delay — delay to next scheduled slot
    return AIDecisionOut(
        recommendation="delay",
        reasoning=(
            f"The delay of {delay_minutes} minutes is moderate. "
            f"Taking {medicine_name} with your next meal or scheduled time is recommended "
            "to maintain consistent blood levels."
        ),
        confidence=0.80,
        safety_note="Adjust your next dose to the original scheduled time, not earlier."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Save decision to Supabase
# ─────────────────────────────────────────────────────────────────────────────

async def save_ai_decision(
    user_id: str,
    medicine_id: str,
    delay_minutes: int,
    decision: AIDecisionOut,
    dose_log_id: Optional[str] = None,
) -> str:
    db = get_supabase_admin()
    payload = {
        "user_id": user_id,
        "medicine_id": medicine_id,
        "delay_minutes": delay_minutes,
        "recommendation": decision.recommendation,
        "reasoning": decision.reasoning,
        "confidence": float(decision.confidence),
    }
    if dose_log_id:
        payload["dose_log_id"] = dose_log_id

    result = db.table("ai_decisions").insert(payload).execute()
    return result.data[0]["id"] if result.data else ""
