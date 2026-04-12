"""
MediMind AI — Dose Logs router
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import List, Optional
from uuid import UUID

# IST = UTC+5:30
IST = timezone(timedelta(hours=5, minutes=30))

from fastapi import APIRouter, Depends, HTTPException, Header, Query

from app.config import get_supabase_admin
from app.models.schemas import DoseActionRequest, SuccessResponse

router = APIRouter(prefix="/doses", tags=["Dose Logs"])


def _get_user(x_user_id: str = Header(...)) -> str:
    return x_user_id


@router.get("/today", response_model=List[dict])
async def get_today_doses(user_id: str = Depends(_get_user)):
    """Get all dose logs for today with medicine info joined."""
    db = get_supabase_admin()
    today_ist = datetime.now(IST).date().isoformat()

    result = (
        db.table("dose_logs")
        .select("*, medicines(name, dosage, form, color_tag, with_food, notes)")
        .eq("user_id", user_id)
        .gte("scheduled_at", f"{today_ist}T00:00:00+05:30")
        .lte("scheduled_at", f"{today_ist}T23:59:59+05:30")
        .order("scheduled_at")
        .execute()
    )
    return result.data or []


@router.get("/history", response_model=List[dict])
async def get_dose_history(
    user_id: str = Depends(_get_user),
    days: int = Query(default=7, ge=1, le=90),
    medicine_id: Optional[UUID] = None,
):
    """Get dose history for the last N days."""
    from datetime import timedelta
    db = get_supabase_admin()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    query = (
        db.table("dose_logs")
        .select("*, medicines(name, dosage)")
        .eq("user_id", user_id)
        .gte("scheduled_at", since)
        .order("scheduled_at", desc=True)
    )
    if medicine_id:
        query = query.eq("medicine_id", str(medicine_id))

    result = query.execute()
    return result.data or []


@router.get("/pending", response_model=List[dict])
async def get_pending_doses(user_id: str = Depends(_get_user)):
    """Get all pending (not yet taken) doses for today."""
    db = get_supabase_admin()
    today_ist = datetime.now(IST).date().isoformat()
    now = datetime.now(IST).isoformat()

    result = (
        db.table("dose_logs")
        .select("*, medicines(name, dosage, color_tag, with_food, notes)")
        .eq("user_id", user_id)
        .eq("status", "pending")
        .gte("scheduled_at", f"{today_ist}T00:00:00+05:30")
        .lte("scheduled_at", now)
        .order("scheduled_at")
        .execute()
    )
    return result.data or []


@router.post("/{dose_id}/action", response_model=dict)
async def perform_dose_action(
    dose_id: UUID,
    body: DoseActionRequest,
    user_id: str = Depends(_get_user),
):
    """
    Mark a dose as taken / skipped / delayed.
    Calculates delay_minutes automatically.
    """
    if body.status not in ("taken", "skipped", "delayed"):
        raise HTTPException(400, "status must be: taken | skipped | delayed")

    db = get_supabase_admin()

    # Fetch existing log
    existing = (
        db.table("dose_logs")
        .select("*")
        .eq("id", str(dose_id))
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    if not existing.data:
        raise HTTPException(404, "Dose log not found")

    log = existing.data
    now_utc = datetime.now(timezone.utc)

    if body.snooze_minutes and body.snooze_minutes > 0:
        # SNOOZE: Push scheduled_at forward and keep status as 'pending'
        scheduled = datetime.fromisoformat(log["scheduled_at"].replace("Z", "+00:00"))
        new_scheduled = scheduled + timedelta(minutes=body.snooze_minutes)
        update_payload = {
            "status":        "pending",
            "scheduled_at":  new_scheduled.isoformat(),
            "notes":         f"Snoozed for {body.snooze_minutes}m. " + (body.notes or ""),
        }
    else:
        # STANDARD ACTION: mark as taken/skipped/delayed
        scheduled = datetime.fromisoformat(log["scheduled_at"].replace("Z", "+00:00"))
        delay_mins = max(0, int((now_utc - scheduled).total_seconds() / 60))

        update_payload = {
            "status":        body.status,
            "taken_at":      now_utc.isoformat() if body.status == "taken" else None,
            "delay_minutes": delay_mins,
        }
        if body.notes:
            update_payload["notes"] = body.notes
        if body.ai_decision:
            update_payload["ai_decision"] = body.ai_decision


    result = (
        db.table("dose_logs")
        .update(update_payload)
        .eq("id", str(dose_id))
        .execute()
    )

    # Acknowledge any pending reminder for this dose
    db.table("reminder_events").update({"acknowledged": True, "ack_at": now_utc.isoformat()}).eq("dose_log_id", str(dose_id)).execute()

    return result.data[0] if result.data else {}


@router.get("/overdue", response_model=List[dict])
async def get_overdue_doses(user_id: str = Depends(_get_user)):
    """Get all doses currently overdue (pending + past scheduled time)."""
    db = get_supabase_admin()
    now = datetime.now(IST)
    threshold = (now - timedelta(minutes=5)).isoformat()

    result = (
        db.table("dose_logs")
        .select("*, medicines(name, dosage, color_tag, with_food, notes)")
        .eq("user_id", user_id)
        .eq("status", "pending")
        .lt("scheduled_at", threshold)
        .order("scheduled_at")
        .execute()
    )
    data = result.data or []

    # Enrich with overdue_minutes
    for row in data:
        sched = datetime.fromisoformat(row["scheduled_at"].replace("Z", "+00:00"))
        row["overdue_minutes"] = int((now - sched).total_seconds() / 60)

    return data


@router.delete("/{dose_id}", response_model=SuccessResponse)
async def delete_dose(dose_id: UUID, user_id: str = Depends(_get_user)):
    """Delete a single dose log entry."""
    db = get_supabase_admin()
    db.table("dose_logs").delete().eq("id", str(dose_id)).eq("user_id", user_id).execute()
    return SuccessResponse(message="Dose deleted")


@router.delete("/history/clear", response_model=SuccessResponse)
async def clear_history(user_id: str = Depends(_get_user)):
    """Clear all non-pending dose history (taken/missed/skipped)."""
    db = get_supabase_admin()
    db.table("dose_logs").delete().eq("user_id", user_id).neq("status", "pending").execute()
    return SuccessResponse(message="History cleared")
