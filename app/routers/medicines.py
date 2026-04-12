"""
MediMind AI — Medicines CRUD router
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import List
from uuid import UUID

# IST = UTC+5:30
IST = timezone(timedelta(hours=5, minutes=30))

from fastapi import APIRouter, Depends, HTTPException, Header

from app.config import get_supabase_admin
from app.models.schemas import MedicineCreate, MedicineOut, MedicineUpdate, SuccessResponse
from app.services.scheduler import generate_tomorrows_doses

router = APIRouter(prefix="/medicines", tags=["Medicines"])


def _get_user(x_user_id: str = Header(..., description="Supabase user UUID")) -> str:
    return x_user_id


# ─────────────────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[dict])
async def list_medicines(user_id: str = Depends(_get_user)):
    db = get_supabase_admin()
    result = (
        db.table("medicines")
        .select("*")
        .eq("user_id", user_id)
        .eq("is_active", True)
        .order("created_at")
        .execute()
    )
    return result.data or []


@router.post("/", response_model=dict, status_code=201)
async def add_medicine(body: MedicineCreate, user_id: str = Depends(_get_user)):
    db = get_supabase_admin()
    payload = body.model_dump()
    payload["user_id"] = user_id
    # Convert date to string
    if payload.get("start_date"):
        payload["start_date"] = str(payload["start_date"])
    if payload.get("end_date"):
        payload["end_date"] = str(payload["end_date"])

    result = db.table("medicines").insert(payload).execute()
    if not result.data:
        raise HTTPException(500, "Failed to create medicine")

    med = result.data[0]

    # Pre-generate today's dose log rows (use IST date since user enters IST times)
    today_ist = datetime.now(IST).date().isoformat()
    dose_rows = []
    for t in body.dose_times:
        dose_rows.append({
            "user_id":      user_id,
            "medicine_id":  med["id"],
            "scheduled_at": f"{today_ist}T{t}:00+05:30",
            "status":       "pending",
        })
    if dose_rows:
        db.table("dose_logs").insert(dose_rows).execute()

    return med


@router.get("/{medicine_id}", response_model=dict)
async def get_medicine(medicine_id: UUID, user_id: str = Depends(_get_user)):
    db = get_supabase_admin()
    result = (
        db.table("medicines")
        .select("*")
        .eq("id", str(medicine_id))
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(404, "Medicine not found")
    return result.data


@router.patch("/{medicine_id}", response_model=dict)
async def update_medicine(
    medicine_id: UUID,
    body: MedicineUpdate,
    user_id: str = Depends(_get_user),
):
    db = get_supabase_admin()
    payload = {k: v for k, v in body.model_dump().items() if v is not None}
    if not payload:
        raise HTTPException(400, "No fields to update")

    result = (
        db.table("medicines")
        .update(payload)
        .eq("id", str(medicine_id))
        .eq("user_id", user_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(404, "Medicine not found")

    med = result.data[0]

    # If schedule changed, sync today's pending doses
    if "dose_times" in payload or "frequency" in payload:
        today_ist = datetime.now(IST).date().isoformat()
        
        # 1. Fetch existing non-pending dose times for today to avoid duplicates
        existing_logs = db.table("dose_logs").select("scheduled_at").eq("medicine_id", med["id"]).neq("status", "pending").gte("scheduled_at", f"{today_ist}T00:00:00+05:30").execute()
        done_times = {datetime.fromisoformat(row["scheduled_at"]).strftime("%H:%M") for row in existing_logs.data}

        # 2. Clear all existing PENDING doses for today
        db.table("dose_logs").delete().eq("medicine_id", med["id"]).eq("status", "pending").gte("scheduled_at", f"{today_ist}T00:00:00+05:30").execute()

        # 3. Re-create pending doses from the new schedule (skipping already-taken times)
        new_doses = []
        for t in med.get("dose_times", []):
            if t not in done_times:
                new_doses.append({
                    "user_id":      user_id,
                    "medicine_id":  med["id"],
                    "scheduled_at": f"{today_ist}T{t}:00+05:30",
                    "status":       "pending",
                })
        if new_doses:
            db.table("dose_logs").insert(new_doses).execute()

    return med


@router.delete("/{medicine_id}", response_model=SuccessResponse)
async def delete_medicine(medicine_id: UUID, user_id: str = Depends(_get_user)):
    """Delete a medicine and ALL related data (doses, reminders, AI decisions).
    
    The DB schema uses ON DELETE CASCADE on all child FKs,
    so deleting dose_logs cascades to reminder_events,
    and deleting the medicine cascades to dose_logs + ai_decisions.
    We explicitly delete dose_logs first as a safety measure.
    """
    db = get_supabase_admin()
    mid = str(medicine_id)

    # Explicitly delete all dose_logs for this medicine 
    # (this cascades to reminder_events via FK)
    db.table("dose_logs").delete().eq("medicine_id", mid).execute()

    # Explicitly delete ai_decisions for this medicine
    db.table("ai_decisions").delete().eq("medicine_id", mid).execute()

    # Now delete the medicine itself
    db.table("medicines").delete().eq("id", mid).eq("user_id", user_id).execute()

    return SuccessResponse(message="Medicine and all related data deleted")

