import io
import os
import urllib.parse
import dotenv
from garminconnect import Garmin
from PIL import Image, ImageDraw, ImageFont
import requests

dotenv.load_dotenv()


def generate_full_ai_garmin_card(
    input_photo_path,
    style_prompt="cyberpunk runner finish line with glowing neon lights, cinematic lighting, 8k wallpaper",
    output_path="ai_garmin_card.png",
):
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

    # --- 2. Generate Free AI Art Background ---
    print("🎨 Requesting AI Background Generation (Free)...")
    encoded_prompt = urllib.parse.quote(style_prompt)
    ai_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true"

    response = requests.get(ai_url)
    if response.status_code == 200:
        bg_img = Image.open(io.BytesIO(response.content)).convert("RGBA")
    else:
        print("⚠️ AI generation failed, falling back to uploaded selfie.")
        bg_img = Image.open(input_photo_path).convert("RGBA")

    w, h = bg_img.size

    # --- 3. Composite Glassmorphism HUD Overlay ---
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    card_w = int(w * 0.9)
    card_h = int(h * 0.18)
    card_x = (w - card_w) // 2
    card_y = h - card_h - int(h * 0.05)

    corner_radius = int(card_h * 0.2)
    draw.rounded_rectangle(
        [(card_x, card_y), (card_x + card_w, card_y + card_h)],
        radius=corner_radius,
        fill=(15, 23, 42, 195),
        outline=(255, 255, 255, 80),
        width=2,
    )

    combined = Image.alpha_composite(bg_img, overlay)
    draw_final = ImageDraw.Draw(combined)

    # --- 4. Render Typography & Stats ---
    try:
        font_large = ImageFont.truetype("Helvetica", size=int(card_h * 0.35))
        font_label = ImageFont.truetype("Helvetica", size=int(card_h * 0.12))
    except Exception:
        font_large = font_label = ImageFont.load_default()

    # Metrics Layout
    col1_x = card_x + int(card_w * 0.08)
    col1_y = card_y + int(card_h * 0.2)

    # Distance
    draw_final.text(
        (col1_x, col1_y), distance_km, fill=(255, 255, 255), font=font_large
    )
    draw_final.text(
        (col1_x, col1_y + int(card_h * 0.45)),
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
        (col2_x, col1_y + int(card_h * 0.45)),
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
        (col3_x, col1_y + int(card_h * 0.45)),
        "AVG HR (BPM)",
        fill=(255, 70, 70),
        font=font_label,
    )

    combined.convert("RGB").save(output_path, "PNG")
    print(f"🎉 Final card generated successfully: {output_path}")


if __name__ == "__main__":
    generate_full_ai_garmin_card("selfie.jpeg")