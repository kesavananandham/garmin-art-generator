import io
import os
import dotenv
from garminconnect import Garmin
from PIL import Image, ImageDraw, ImageFont
import google.generativeai as genai

dotenv.load_dotenv()

# Configure Gemini
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))


def generate_garmin_card(input_photo_path, style_preset="glassmorphism"):
    # --- 1. Fetch Garmin Metrics ---
    print("🔄 Fetching latest Garmin stats...")
    garmin = Garmin(os.getenv("GARMIN_EMAIL"), os.getenv("GARMIN_PASSWORD"))
    garmin.login()

    latest = garmin.get_activities(0, 1)[0]
    distance_km = round(latest.get("distance", 0) / 1000, 2)
    avg_hr = latest.get("averageHR", "N/A")

    avg_speed = latest.get("averageSpeed", 0)
    pace_str = "N/A"
    if avg_speed > 0:
        sec = 1000 / avg_speed
        pace_str = f"{int(sec // 60)}:{int(sec % 60):02d}"

    stats_str = (
        f"DIST: {distance_km} KM   |   PACE: {pace_str} /KM   |   HR: {avg_hr} BPM"
    )
    print(f"📊 Stats to embed: {stats_str}")

    # --- 2. Load Input Photo ---
    print("🎨 Processing image...")
    input_img = Image.open(input_photo_path).convert("RGBA")
    w, h = input_img.size

    # --- 3. Overlay Glassmorphism Stats Banner (PIL) ---
    draw = ImageDraw.Draw(input_img)

    # Draw semi-transparent dark banner at bottom
    banner_height = int(h * 0.12)
    rect_coords = [(0, h - banner_height), (w, h)]
    draw.rectangle(rect_coords, fill=(0, 0, 0, 190))

    # Add Stats Text
    font = ImageFont.load_default()
    text_position = (30, h - (banner_height // 2) - 10)
    draw.text(text_position, stats_str, fill=(255, 255, 255))

    output_filename = "garmin_card_result.png"
    input_img.save(output_filename)
    print(f"🎉 SUCCESS! Final image saved as: {output_filename}")


if __name__ == "__main__":
    if os.path.exists("selfie.jpeg"):
        generate_garmin_card("selfie.jpeg")
    elif os.path.exists("selfie.png"):
        generate_garmin_card("selfie.png")
    else:
        print("⚠️ Please place a 'selfie.jpeg' or 'selfie.png' in your project folder!")