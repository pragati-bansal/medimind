import os
import io
from PIL import Image, ImageDraw, ImageFont
import sys

# Add current directory to path so we can import app modules
sys.path.append(os.getcwd())

from app.services.ocr_service import extract_text_from_image, parse_prescription_text

def test_ocr():
    # 1. Create a dummy prescription image
    img = Image.new('RGB', (800, 400), color=(255, 255, 255))
    d = ImageDraw.Draw(img)
    
    # Try to use a real font if available, fallback to default
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 40)
    except:
        font = ImageFont.load_default()

    # Test multiline case where frequency is on separate line
    text = "Rx\nMetformin 500 mg\nTake 1-0-1\nWith food\n\nLisinopril 10 mg\nOnce Daily\nMorning"
    d.text((50, 50), text, fill=(0, 0, 0), font=font)
    
    print("--- Testing Real OCR Engine ---")
    raw_text = extract_text_from_image(img)
    print(f"Raw Text Extracted:\n{raw_text}")
    print("-" * 30)
    
    if raw_text == "__DEMO_MODE__":
        print("FAIL: Still in Demo Mode. Local Tesseract not working.")
        return

    medicines, confidence = parse_prescription_text(raw_text)
    print(f"Medicines Found ({len(medicines)}):")
    for m in medicines:
        print(f" - {m.name}: {m.dosage} ({m.frequency}) conf: {m.confidence}")
    print(f"Overall Confidence: {confidence}")

if __name__ == "__main__":
    test_ocr()
