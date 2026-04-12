"""
MediMind AI — OCR / Prescription router
"""
from __future__ import annotations
import io
from fastapi import APIRouter, Depends, Header, UploadFile, File, HTTPException
from PIL import Image
from app.config import get_supabase_admin
from app.services.ocr_service import extract_text_from_image, parse_prescription_text

router = APIRouter(prefix="/prescriptions", tags=["OCR / Prescriptions"])


def _get_user(x_user_id: str = Header(...)) -> str:
    return x_user_id


@router.post("/scan")
async def scan_prescription(
    file: UploadFile = File(...),
    user_id: str = Depends(_get_user),
):
    """Upload a prescription image → OCR → extract medicines."""
    if not file.content_type.startswith("image/"):
        raise HTTPException(400, "Only image files are supported")

    contents = await file.read()
    image = Image.open(io.BytesIO(contents))

    raw_text = extract_text_from_image(image)
    medicines, confidence = parse_prescription_text(raw_text)

    db = get_supabase_admin()
    result = db.table("prescriptions").insert({
        "user_id":     user_id,
        "raw_text":    raw_text,
        "parsed_data": [m.model_dump() for m in medicines],
        "status":      "processed" if medicines else "failed",
    }).execute()

    prescription_id = result.data[0]["id"] if result.data else None

    return {
        "prescription_id":    prescription_id,
        "raw_text":           raw_text[:500] + "..." if len(raw_text) > 500 else raw_text,
        "medicines":          [m.model_dump() for m in medicines],
        "overall_confidence": confidence,
        "demo_mode":          raw_text == "__DEMO_MODE__",
    }


@router.get("/")
async def list_prescriptions(user_id: str = Depends(_get_user)):
    db = get_supabase_admin()
    result = db.table("prescriptions").select("id, status, created_at, parsed_data").eq("user_id", user_id).order("created_at", desc=True).limit(20).execute()
    return result.data or []
