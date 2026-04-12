import os
import re
import logging
from typing import List, Optional, Tuple

from PIL import Image, ImageEnhance
import pytesseract

from app.models.schemas import ParsedMedicine

logger = logging.getLogger("medimind.ocr")

def preprocess_image(image: Image.Image) -> Image.Image:
    """Prepare image for Tesseract by upscaling and boosting contrast."""
    # 1. Grayscale
    gray = image.convert("L")
    
    # 2. Upscale (2.5x) for better character definition
    w, h = gray.size
    gray = gray.resize((int(w*2.5), int(h*2.5)), Image.Resampling.LANCZOS)
    
    # 3. Boost Contrast & Sharpness
    gray = ImageEnhance.Contrast(gray).enhance(1.8)
    gray = ImageEnhance.Sharpness(gray).enhance(2.0)
    
    # We no longer apply a hardcoded threshold here.
    # Tesseract's own adaptive thresholding is better for real-world photos.
    return gray

# ─────────────────────────────────────────────────────────────────────────────
# Common medicine keywords / dosage patterns
# ─────────────────────────────────────────────────────────────────────────────

DOSAGE_PATTERN = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(mg|mcg|g|ml|iu|units?|%)\b",
    re.IGNORECASE
)

FREQUENCY_KEYWORDS = {
    "once daily": "once_daily",
    "od":         "once_daily",
    "twice daily": "twice_daily",
    "bd":         "twice_daily",
    "bid":        "twice_daily",
    "thrice daily": "thrice_daily",
    "tds":        "thrice_daily",
    "tid":        "thrice_daily",
    "four times":  "four_times_daily",
    "qid":        "four_times_daily",
    "weekly":     "weekly",
    "sos":        "as_needed",
    "as needed":  "as_needed",
    # Mappings for common shorthands
    r"\bb\.d\.\b": "twice_daily",
    r"\bo\.d\.\b": "once_daily",
    r"\bt\.i\.d\.\b": "thrice_daily",
}

TIME_KEYWORDS = {
    r"\bmorning\b":          "07:00",
    r"\bbreakfast\b":        "08:00",
    r"\blunch\b":            "13:00",
    r"\bafternoon\b":        "14:00",
    r"\bevening\b":          "18:00",
    r"\bdinner\b":           "20:00",
    r"\bnight\b":            "21:00",
    r"\bbedtime\b":          "22:00",
    r"\b(\d{1,2}):(\d{2})\b": None,   # Literal HH:MM times
}

MEDICINE_LINE_PATTERN = re.compile(
    r"^(?P<name>[A-Za-z][A-Za-z0-9\s\-]+?)\s+"
    r"(?P<dosage>\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml|iu|units?|%))\s*"
    r"(?P<rest>.*)$",
    re.IGNORECASE | re.MULTILINE
)


# ─────────────────────────────────────────────────────────────────────────────
# Local Tesseract Configuration
# ─────────────────────────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOCAL_TESS_BIN = os.path.join(BASE_DIR, "bin", "tesseract", "tesseract")
LOCAL_TESSDATA = os.path.join(BASE_DIR, "bin", "tesseract", "tessdata")

if os.path.exists(LOCAL_TESS_BIN):
    pytesseract.pytesseract.tesseract_cmd = LOCAL_TESS_BIN
    os.environ['TESSDATA_PREFIX'] = LOCAL_TESSDATA
    logger.info(f"Using local Tesseract binary: {LOCAL_TESS_BIN}")


def is_tesseract_available() -> bool:
    """Check if tesseract binary is runnable."""
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception as e:
        logger.debug(f"Tesseract check failed: {e}")
        return False


def extract_text_from_image(image: Image.Image) -> str:
    """Run Tesseract OCR on a PIL Image and return raw text."""
    # Try local or system tesseract
    if not is_tesseract_available():
        logger.warning("Tesseract not found anywhere. Entering OCR Demo Mode.")
        return "__DEMO_MODE__"

    try:
        # Preprocess for better OCR
        processed = preprocess_image(image)
        
        # Ensure we point to our local tessdata if it exists
        # PSM 3 = Fully automatic page segmentation, but no OSD.
        # OEM 3 = Default, based on what is available.
        config = f'--tessdata-dir "{LOCAL_TESSDATA}" --oem 3 --psm 3' if os.path.exists(LOCAL_TESSDATA) else "--oem 3 --psm 3"
        text = pytesseract.image_to_string(processed, config=config)
        return text.strip()
    except Exception as e:
        logger.error(f"OCR failed: {e}")
        return "__DEMO_MODE__"


# ─────────────────────────────────────────────────────────────────────────────
# Text → structured medicine list
# ─────────────────────────────────────────────────────────────────────────────

def parse_frequency(text: str) -> Optional[str]:
    text_lower = text.lower()
    for keyword, freq in FREQUENCY_KEYWORDS.items():
        if keyword in text_lower:
            return freq
    
    # Check for shorthand like 1-0-1, 1-1-1, etc.
    if re.search(r'\b1\s*-\s*0\s*-\s*1\b', text_lower): return "twice_daily"
    if re.search(r'\b1\s*-\s*1\s*-\s*1\b', text_lower): return "thrice_daily"
    if re.search(r'\b1\s*-\s*0\s*-\s*0\b', text_lower): return "once_daily"
    if re.search(r'\b0\s*-\s*0\s*-\s*1\b', text_lower): return "once_daily"
    
    return None


def parse_instructions(text: str) -> str:
    """Extract food/timing instructions from a text block."""
    instructions = []
    if re.search(r"\bwith\s+food\b", text, re.I):
        instructions.append("With food")
    if re.search(r"\bempty\s+stomach\b", text, re.I):
        instructions.append("Empty stomach")
    for pattern, time_val in TIME_KEYWORDS.items():
        if re.search(pattern, text, re.I):
            if time_val:
                instructions.append(f"~{time_val}")
            break
    return " · ".join(instructions) if instructions else ""


DEMO_MEDICINES = [
    ParsedMedicine(name="Metformin", dosage="500 mg", frequency="twice_daily", instructions="With food", confidence=0.95),
    ParsedMedicine(name="Lisinopril", dosage="10 mg", frequency="once_daily", instructions="Morning", confidence=0.90),
    ParsedMedicine(name="Atorvastatin", dosage="20 mg", frequency="once_daily", instructions="Bedtime", confidence=0.85),
]


# ─────────────────────────────────────────────────────────────────────────────
# Medical Dictionary & Suffixes
# ─────────────────────────────────────────────────────────────────────────────

MED_SUFFIXES = {'in', 'ol', 'am', 'ide', 'pril', 'pine', 'one', 'tan', 'stat', 'cin', 'zole', 'vir'}
MED_TYPES = {'tab', 'cap', 'syp', 'inj', 'ointment', 'cream', 'gel', 'drop'}

def is_likely_medicine(name: str) -> bool:
    name = name.lower().strip()
    if len(name) < 4: return False
    # Check common suffixes
    if any(name.endswith(s) for s in MED_SUFFIXES): return True
    # Check common types
    if any(t in name for t in MED_TYPES): return True
    return False


def parse_prescription_text(raw_text: str) -> Tuple[List[ParsedMedicine], float]:
    """
    Highly robust contextual parser.
    Searches for medicine anchors and looks at surrounding lines.
    """
    if raw_text == "__DEMO_MODE__":
        return DEMO_MEDICINES, 0.90

    # 1. Broad Text Cleaning
    # Remove obvious noise characters but keep structure
    raw_text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\xff]', '', raw_text)
    raw_text = re.sub(r'\n+', '\n', raw_text)
    raw_text = re.sub(r' +', ' ', raw_text)

    medicines: List[ParsedMedicine] = []
    lines = [l.strip() for l in raw_text.split("\n") if len(l.strip()) > 1]

    for i, line in enumerate(lines):
        # Pass A: Regex Match (High Confidence)
        match = MEDICINE_LINE_PATTERN.match(line)
        if match:
            name = match.group("name").strip().title()
            dosage = match.group("dosage").strip()
            rest = match.group("rest").strip()
            
            freq = parse_frequency(rest)
            if not freq and i + 1 < len(lines):
                freq = parse_frequency(lines[i+1])
            
            instr = parse_instructions(line)
            if i + 1 < len(lines) and not instr:
                instr = parse_instructions(lines[i+1])

            medicines.append(ParsedMedicine(
                name=name, dosage=dosage, frequency=freq, 
                instructions=instr, confidence=0.85 if freq else 0.70
            ))
            continue

        # Pass B: Dosage Anchor (Medium Confidence)
        dosage_match = DOSAGE_PATTERN.search(line)
        if dosage_match:
            dosage = dosage_match.group(0)
            
            # Extract name candidate
            # 1. Search same line before dosage
            # 2. Search line above
            name_cand = line[:dosage_match.start()].strip()
            name_cand = re.sub(r"^[^\w]+", "", name_cand) # Clean prefix noise
            
            if len(name_cand) < 3 and i > 0:
                name_cand = lines[i-1]
            
            if len(name_cand) >= 3:
                freq = parse_frequency(line)
                if not freq and i + 1 < len(lines):
                    freq = parse_frequency(lines[i+1])
                
                medicines.append(ParsedMedicine(
                    name=name_cand.title(),
                    dosage=dosage,
                    frequency=freq,
                    instructions=parse_instructions(line),
                    confidence=0.55 if is_likely_medicine(name_cand) else 0.35
                ))

    # Deduplicate and Clean
    seen = set()
    unique = []
    for m in medicines:
        # Clean medicine name from common trash
        m.name = re.sub(r'^[^\w]+', '', m.name)
        m.name = m.name.split('/')[0].strip() # Take part before slash if any
        key = m.name.lower()
        if key not in seen and len(key) >= 3:
            seen.add(key)
            unique.append(m)

    overall_conf = (
        sum(m.confidence for m in unique) / len(unique) if unique else 0.0
    )
    return unique, round(overall_conf, 2)


# ─────────────────────────────────────────────────────────────────────────────
# Time parser  (convert frequency strings to HH:MM arrays)
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_SCHEDULES = {
    "once_daily":       ["08:00"],
    "twice_daily":      ["08:00", "20:00"],
    "thrice_daily":     ["08:00", "14:00", "20:00"],
    "four_times_daily": ["07:00", "12:00", "17:00", "22:00"],
    "weekly":           ["08:00"],
    "as_needed":        [],
}


def frequency_to_times(frequency: str, instructions: str = "") -> List[str]:
    """Convert frequency code to default time slots, adjusting for meal hints."""
    base = DEFAULT_SCHEDULES.get(frequency, ["08:00"])

    # Adjust morning dose based on instructions
    if "breakfast" in instructions.lower() or "morning" in instructions.lower():
        return [base[0]] + base[1:]
    if "night" in instructions.lower() or "bedtime" in instructions.lower():
        if frequency == "once_daily":
            return ["21:00"]

    return base
