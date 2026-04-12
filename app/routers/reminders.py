"""
MediMind AI — Reminders router
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Header
from app.config import get_supabase_admin

router = APIRouter(prefix="/reminders", tags=["Reminders"])

def _get_user(x_user_id: str = Header(...)) -> str:
    return x_user_id


@router.get("/active")
async def get_active_reminders(user_id: str = Depends(_get_user)):
    """Get all unacknowledged reminders for the user."""
    db = get_supabase_admin()
    result = (
        db.table("reminder_events")
        .select("*, medicines(name, dosage), dose_logs(scheduled_at, status)")
        .eq("user_id", user_id)
        .eq("acknowledged", False)
        .order("triggered_at", desc=True)
        .execute()
    )
    return result.data or []


@router.post("/{reminder_id}/ack")
async def acknowledge_reminder(reminder_id: str, user_id: str = Depends(_get_user)):
    from datetime import datetime, timezone
    db = get_supabase_admin()
    db.table("reminder_events").update({
        "acknowledged": True,
        "ack_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", reminder_id).eq("user_id", user_id).execute()
    return {"success": True, "message": "Reminder acknowledged"}
