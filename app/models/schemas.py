"""
MediMind AI — Pydantic models / schemas
"""
from __future__ import annotations
from datetime import date, datetime
from typing import List, Optional
from pydantic import BaseModel, Field, validator
from uuid import UUID


# ─────────────────────────────────────────
# Medicine
# ─────────────────────────────────────────

class MedicineCreate(BaseModel):
    name: str
    generic_name: Optional[str] = None
    dosage: str
    form: str = "tablet"
    frequency: str                          # once_daily | twice_daily | thrice_daily | weekly | custom
    dose_times: List[str]                   # ["08:00", "13:00"]
    with_food: bool = True
    condition: Optional[str] = None
    prescribing_doc: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    refill_reminder: int = 7
    stock_count: int = 30
    notes: Optional[str] = None
    color_tag: str = "mint"

    @validator("dose_times")
    def validate_times(cls, v):
        for t in v:
            try:
                h, m = t.split(":")
                assert 0 <= int(h) <= 23 and 0 <= int(m) <= 59
            except Exception:
                raise ValueError(f"Invalid time format: {t}. Use HH:MM")
        return v


class MedicineUpdate(BaseModel):
    name: Optional[str] = None
    dosage: Optional[str] = None
    frequency: Optional[str] = None
    dose_times: Optional[List[str]] = None
    with_food: Optional[bool] = None
    condition: Optional[str] = None
    end_date: Optional[date] = None
    stock_count: Optional[int] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


class MedicineOut(MedicineCreate):
    id: UUID
    user_id: UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ─────────────────────────────────────────
# Dose Log
# ─────────────────────────────────────────

class DoseLogCreate(BaseModel):
    medicine_id: UUID
    scheduled_at: datetime
    notes: Optional[str] = None


class DoseActionRequest(BaseModel):
    status: str             # taken | skipped | delayed
    notes: Optional[str] = None
    ai_decision: Optional[str] = None   # take_now | delay | skip
    snooze_minutes: Optional[int] = None



class DoseLogOut(BaseModel):
    id: UUID
    user_id: UUID
    medicine_id: UUID
    scheduled_at: datetime
    taken_at: Optional[datetime]
    status: str
    delay_minutes: int
    notes: Optional[str]
    ai_decision: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# ─────────────────────────────────────────
# AI Decision
# ─────────────────────────────────────────

class MissedDoseRequest(BaseModel):
    medicine_id: UUID
    dose_log_id: Optional[UUID] = None
    delay_minutes: int = Field(..., ge=0, description="Minutes since dose was due")


class AIDecisionOut(BaseModel):
    recommendation: str         # take_now | delay | skip
    reasoning: str
    confidence: float
    safety_note: Optional[str] = None


# ─────────────────────────────────────────
# Adherence
# ─────────────────────────────────────────

class AdherenceStats(BaseModel):
    total_doses: int
    taken_doses: int
    missed_doses: int
    skipped_doses: int
    delayed_doses: int
    adherence_rate: float
    consistency_score: float
    risk_level: str             # low | medium | high
    streak_days: int
    behavior_trends: dict


# ─────────────────────────────────────────
# OCR / Prescription
# ─────────────────────────────────────────

class ParsedMedicine(BaseModel):
    name: str
    dosage: Optional[str] = None
    frequency: Optional[str] = None
    instructions: Optional[str] = None
    confidence: float = 0.0


class PrescriptionOut(BaseModel):
    id: UUID
    status: str
    raw_text: Optional[str]
    parsed_medicines: List[ParsedMedicine] = []
    created_at: datetime

    class Config:
        from_attributes = True


# ─────────────────────────────────────────
# Reminder
# ─────────────────────────────────────────

class ReminderOut(BaseModel):
    id: UUID
    medicine_id: UUID
    medicine_name: str
    scheduled_at: datetime
    overdue_minutes: int
    status: str


# ─────────────────────────────────────────
# Generic responses
# ─────────────────────────────────────────

class SuccessResponse(BaseModel):
    success: bool = True
    message: str
    data: Optional[dict] = None
