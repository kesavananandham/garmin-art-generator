import io
import os
import dotenv
from garminconnect import Garmin
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

dotenv.load_dotenv()


def create_fancy_garmin_card(input_photo_path, output_path="fancy_output.png"):
    # --- 1. Fetch Garmin Data ---
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

    print(f"📊 Stats: {distance_km} KM | {pace_str} /KM | {avg_hr} BPM")

    # --- 2. Load Base Photo ---
    base_img = Image.open(input_photo_path).convert("RGBA")
    w, h = base_img.size

    # --- 3. Create Glassmorphism Layer (Frosted Glass Effect) ---
    # Create an overlay layer for the floating card at the bottom
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Card dimensions: 85% width, positioned near the bottom
    card_w = int(w * 0.9)
    card_h = int(h * 0.18)
    card_x = (w - card_w) // 2
    card_y = h - card_h - int(h * 0.04)

    # Draw rounded rectangle box with semi-transparent dark glass fill (160/255 alpha)
    corner_radius = int(card_h * 0.2)
    draw.rounded_rectangle(
        [(card_x, card_y), (card_x + card_w, card_y + card_h)],
        radius=corner_radius,
        fill=(15, 23, 42, 180),  # Deep Slate / Navy translucent
        outline=(255, 255, 255, 60),  # Subtle glossy border glow
        width=2,
    )

    # Composite glass overlay onto original image
    combined = Image.alpha_composite(base_img, overlay)
    draw_final = ImageDraw.Draw(combined)

    # --- 4. Render Styled Metrics & Typography ---
    # Draw primary Distance callout (Large bold text)
    # Note: Using default font; if custom TTF (e.g. Montserrat/Impact) is available, load via ImageFont.truetype()
    try:
        # Optional: Use system font if available
        font_large = ImageFont.truetype("Helvetica", size=int(card_h * 0.35))
        font_small = ImageFont.truetype("Helvetica", size=int(card_h * 0.15))
        font_label = ImageFont.truetype("Helvetica", size=int(card_h * 0.12))
    except Exception:
        font_large = font_small = font_label = ImageFont.load_default()

    # Column 1: Distance
    col1_x = card_x + int(card_w * 0.08)
    col1_y = card_y + int(card_h * 0.2)
    draw_final.text(
        (col1_x, col1_y), distance_km, fill=(255, 255, 255), font=font_large
    )
    draw_final.text(
        (col1_x, col1_y + int(card_h * 0.45)),
        "KILOMETERS",
        fill=(0, 230, 153),
        font=font_label,
    )  # Vibrant Electric Mint accent

    # Column 2: Pace
    col2_x = card_x + int(card_w * 0.42)
    draw_final.text(
        (col2_x, col1_y), pace_str, fill=(255, 255, 255), font=font_large
    )
    draw_final.text(
        (col2_x, col1_y + int(card_h * 0.45)),
        "AVG PACE (/KM)",
        fill=(255, 180, 0),
        font=font_label,
    )  # Neon Amber accent

    # Column 3: Heart Rate
    col3_x = card_x + int(card_w * 0.72)
    draw_final.text(
        (col3_x, col1_y), avg_hr, fill=(255, 255, 255), font=font_large
    )
    draw_final.text(
        (col3_x, col1_y + int(card_h * 0.45)),
        "AVG HR (BPM)",
        fill=(255, 70, 70),
        font=font_label,
    )  # Crimson Red accent

    # --- 5. Save Finished Artwork ---
    combined.convert("RGB").save(output_path, "PNG")
    print(f"🎉 Styled card generated successfully: {output_path}")


if __name__ == "__main__":
    if os.path.exists("selfie.jpeg"):
        create_fancy_garmin_card("selfie.jpeg")
    elif os.path.exists("selfie.png"):
        create_fancy_garmin_card("selfie.png")