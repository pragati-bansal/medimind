"""
MediMind AI — AI Decision Engine router
"""
from __future__ import annotations
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException
from app.config import get_supabase_admin
from app.models.schemas import MissedDoseRequest, AIDecisionOut
from app.services.ai_engine import decide_missed_dose, save_ai_decision

router = APIRouter(prefix="/ai", tags=["AI Engine"])


def _get_user(x_user_id: str = Header(...)) -> str:
    return x_user_id


@router.post("/decide", response_model=AIDecisionOut)
async def get_ai_decision(body: MissedDoseRequest, user_id: str = Depends(_get_user)):
    """
    Given a missed dose + how long ago it was due, return an AI recommendation.
    """
    db = get_supabase_admin()

    # Fetch medicine details
    med_result = (
        db.table("medicines")
        .select("name, frequency")
        .eq("id", str(body.medicine_id))
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    if not med_result.data:
        raise HTTPException(404, "Medicine not found")

    med = med_result.data
    decision = decide_missed_dose(
        medicine_name=med["name"],
        delay_minutes=body.delay_minutes,
        frequency=med.get("frequency", "twice_daily"),
    )

    # Persist decision
    await save_ai_decision(
        user_id=user_id,
        medicine_id=str(body.medicine_id),
        delay_minutes=body.delay_minutes,
        decision=decision,
        dose_log_id=str(body.dose_log_id) if body.dose_log_id else None,
    )

    return decision


@router.get("/insights/{user_id}")
async def get_ai_insights(user_id: str, x_user_id: str = Header(...)):
    """Return AI-generated weekly insights based on dose history."""
    if x_user_id != user_id:
        raise HTTPException(403, "Forbidden")

    db = get_supabase_admin()
    from datetime import datetime, timezone, timedelta
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

    logs = db.table("dose_logs").select("status, scheduled_at, medicines(name)").eq("user_id", user_id).gte("scheduled_at", since).execute().data or []

    # Build simple insights
    total = len(logs)
    taken = sum(1 for l in logs if l["status"] == "taken")
    missed = sum(1 for l in logs if l["status"] == "missed")
    rate = round((taken / total * 100) if total else 0, 1)

    insights = []
    if rate >= 90:
        insights.append({"type": "success", "title": "Excellent adherence!", "body": f"You took {rate}% of doses on time this week. Outstanding!"})
    elif rate >= 75:
        insights.append({"type": "info", "title": f"{rate}% adherence this week", "body": "Good consistency. A few more on-time doses and you'll hit 90%."})
    else:
        insights.append({"type": "warning", "title": f"Only {rate}% adherence", "body": f"You missed {missed} doses this week. Try setting louder reminders."})

    # Morning vs evening analysis
    morning_logs = [l for l in logs if "T0" in l.get("scheduled_at","") or "T07" in l.get("scheduled_at","") or "T08" in l.get("scheduled_at","")]
    evening_logs = [l for l in logs if "T2" in l.get("scheduled_at","") or "T19" in l.get("scheduled_at","") or "T20" in l.get("scheduled_at","")]

    if morning_logs and evening_logs:
        m_rate = sum(1 for l in morning_logs if l["status"]=="taken") / len(morning_logs) * 100
        e_rate = sum(1 for l in evening_logs if l["status"]=="taken") / len(evening_logs) * 100
        if m_rate > e_rate + 15:
            insights.append({"type": "warning", "title": "Evening doses often missed", "body": f"Morning: {m_rate:.0f}% vs Evening: {e_rate:.0f}%. Set an evening reminder."})

    return {"insights": insights, "adherence_rate": rate, "period_days": 7}
