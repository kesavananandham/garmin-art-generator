import os
import dotenv
from garminconnect import Garmin
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

dotenv.load_dotenv()


def enhance_garmin_selfie(
    input_photo_path, output_path="enhanced_garmin_card.png"
):
    print("🔄 Fetching Garmin Stats...")
    garmin = Garmin(os.getenv("GARMIN_EMAIL"), os.getenv("GARMIN_PASSWORD"))
    garmin.login()

    latest = garmin.get_activities(0, 1)[0]
    distance_km = f"{round(latest.get('distance', 0) / 1000, 2)}"
    avg_hr = f"{int(latest.get('averageHR', 0))}" if latest.get("averageHR") else "--"

    avg_speed = latest.get("averageSpeed", 0)
    pace_str = "--"
    if avg_speed > 0:
        sec = 1000 / avg_speed
        pace_str = f"{int(sec // 60)}:{int(sec % 60):02d}"

    # --- 1. Load Original Selfie ---
    base_img = Image.open(input_photo_path).convert("RGBA")
    w, h = base_img.size

    # --- 2. Color Grading & Photo Enhancement ---
    # Enhance Saturation (Color Vibrancy)
    converter = ImageEnhance.Color(base_img)
    enhanced = converter.enhance(1.25)

    # Enhance Contrast
    contrast = ImageEnhance.Contrast(enhanced)
    enhanced = contrast.enhance(1.15)

    # Enhance Sharpness
    sharpness = ImageEnhance.Sharpness(enhanced)
    enhanced = sharpness.enhance(1.2)

    # --- 3. Glassmorphism HUD Overlay ---
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    card_w = int(w * 0.9)
    card_h = int(h * 0.16)
    card_x = (w - card_w) // 2
    card_y = h - card_h - int(h * 0.04)

    corner_radius = int(card_h * 0.22)

    # Translucent Glass Box with border glow
    draw.rounded_rectangle(
        [(card_x, card_y), (card_x + card_w, card_y + card_h)],
        radius=corner_radius,
        fill=(15, 23, 42, 185),  # Slate dark glass
        outline=(255, 255, 255, 90),  # Crisp border
        width=2,
    )

    combined = Image.alpha_composite(enhanced, overlay)
    draw_final = ImageDraw.Draw(combined)

    # --- 4. Render Metrics & Typography ---
    try:
        font_large = ImageFont.truetype("Helvetica", size=int(card_h * 0.38))
        font_label = ImageFont.truetype("Helvetica", size=int(card_h * 0.13))
    except Exception:
        font_large = font_label = ImageFont.load_default()

    col1_x = card_x + int(card_w * 0.08)
    col1_y = card_y + int(card_h * 0.18)

    # Distance
    draw_final.text(
        (col1_x, col1_y), distance_km, fill=(255, 255, 255), font=font_large
    )
    draw_final.text(
        (col1_x, col1_y + int(card_h * 0.48)),
        "KILOMETERS",
        fill=(0, 230, 153),
        font=font_label,
    )

    # Pace
    col2_x = card_x + int(card_w * 0.42)
    draw_final.text(
        (col2_x, col1_y), pace_str, fill=(255, 255, 255), font=font_large
    )
    draw_final.text(
        (col2_x, col1_y + int(card_h * 0.48)),
        "AVG PACE (/KM)",
        fill=(255, 180, 0),
        font=font_label,
    )

    # Heart Rate
    col3_x = card_x + int(card_w * 0.72)
    draw_final.text(
        (col3_x, col1_y), avg_hr, fill=(255, 255, 255), font=font_large
    )
    draw_final.text(
        (col3_x, col1_y + int(card_h * 0.48)),
        "AVG HR (BPM)",
        fill=(255, 70, 70),
        font=font_label,
    )

    # --- 5. Save Output ---
    combined.convert("RGB").save(output_path, "PNG")
    print(f"🎉 Enhanced selfie card created: {output_path}")


if __name__ == "__main__":
    if os.path.exists("selfie.jpeg"):
        enhance_garmin_selfie("selfie.jpeg")
    elif os.path.exists("selfie.png"):
        enhance_garmin_selfie("selfie.png")