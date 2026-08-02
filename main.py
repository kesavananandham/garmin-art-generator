
import base64
import io
import os
from contextlib import asynccontextmanager
import dotenv
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import Response
from garminconnect import Garmin
from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps
import tarfile

dotenv.load_dotenv()

# Global Garmin client instance
garmin_client = None
# TOKEN_DIR = os.path.expanduser("~/.garmin_tokens")

TOKEN_DIR = "/tmp/garmin_tokens"


def restore_tokens_from_env():
    """Extracts Base64-encoded session tokens from GARMIN_TOKENS_BASE64 into TOKEN_DIR."""
    b64_str = os.getenv("GARMIN_TOKENS_BASE64")
    if not b64_str:
        return False

    try:
        compressed_data = base64.b64decode(b64_str)
        buffer = io.BytesIO(compressed_data)
        os.makedirs(TOKEN_DIR, exist_ok=True)

        with tarfile.open(fileobj=buffer, mode="r:gz") as tar:
            for member in tar.getmembers():
                if member.isfile():
                    filename = os.path.basename(member.name)
                    dest_path = os.path.join(TOKEN_DIR, filename)
                    with (
                        tar.extractfile(member) as source,
                        open(dest_path, "wb") as target,
                    ):
                        target.write(source.read())

        print(f"📦 Successfully restored Garmin session tokens to {TOKEN_DIR}")
        return True
    except Exception as e:
        print(f"⚠️ Failed to restore tokens from env: {e}")
        return False

def get_garmin_client():
    """Initializes Garmin connection using cached tokens if available."""
    email = os.getenv("GARMIN_EMAIL")
    password = os.getenv("GARMIN_PASSWORD")

    if not email or not password:
        raise ValueError(
            "GARMIN_EMAIL or GARMIN_PASSWORD not set in environment."
        )

    client = Garmin(email, password, is_cn=False)

    # Automatically unpack tokens from env if the token directory is missing/empty
    if not os.path.exists(TOKEN_DIR) or not os.listdir(TOKEN_DIR):
        restore_tokens_from_env()

    try:
        print("🔐 Attempting to log in using cached session tokens...")
        client.login(TOKEN_DIR)
        print("✅ Logged in successfully with cached tokens.")
    except Exception as e:
        print(
            f"⚠️ Token login failed ({e}). Attempting full credential login..."
        )
        try:
            client.login()
            os.makedirs(TOKEN_DIR, exist_ok=True)
            client.garth.dump(TOKEN_DIR)
            print(f"✅ Full login successful. Session saved to {TOKEN_DIR}")
        except Exception as login_err:
            print(f"❌ Garmin Login Error: {login_err}")
            raise login_err

    return client


@asynccontextmanager
async def lifespan(app: FastAPI):
    global garmin_client
    try:
        garmin_client = get_garmin_client()
    except Exception as e:
        print(f"🚨 Initial Garmin login failed on startup: {e}")
    yield


app = FastAPI(title="Garmin Card Generator API", lifespan=lifespan)


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "garmin_connected": garmin_client is not None,
    }


@app.post("/generate")
async def generate_card(file: UploadFile):
    global garmin_client

    # Ensure client is connected; retry login if it was down
    if garmin_client is None:
        try:
            garmin_client = get_garmin_client()
        except Exception:
            raise HTTPException(
                status_code=503,
                detail="Garmin service unavailable (Cloudflare/Auth error). Try again later.",
            )

    # 1. Fetch Garmin Data using existing session
    try:
        latest = garmin_client.get_activities(0, 1)[0]
    except Exception as e:
        print(f"🔄 Session expired, re-authenticating... ({e})")
        garmin_client = get_garmin_client()
        latest = garmin_client.get_activities(0, 1)[0]

    distance_km = f"{round(latest.get('distance', 0) / 1000, 2)}"
    avg_hr = (
        f"{int(latest.get('averageHR', 0))}" if latest.get("averageHR") else "--"
    )

    avg_speed = latest.get("averageSpeed", 0)
    pace_str = "--"
    if avg_speed > 0:
        sec = 1000 / avg_speed
        pace_str = f"{int(sec // 60)}:{int(sec % 60):02d}"

    # 2. Read Incoming Photo & Automatically Fix Orientation
    photo_bytes = await file.read()
    raw_img = Image.open(io.BytesIO(photo_bytes))
    base_img = ImageOps.exif_transpose(raw_img).convert("RGBA")
    w, h = base_img.size

    # 3. Photo Color Enhancement & Grading
    converter = ImageEnhance.Color(base_img)
    enhanced = converter.enhance(1.25)

    contrast = ImageEnhance.Contrast(enhanced)
    enhanced = contrast.enhance(1.15)

    sharpness = ImageEnhance.Sharpness(enhanced)
    enhanced = sharpness.enhance(1.2)

    # 4. Glassmorphism HUD Overlay
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    card_w = int(w * 0.9)
    card_h = int(h * 0.16)
    card_x = (w - card_w) // 2
    card_y = h - card_h - int(h * 0.04)

    corner_radius = int(card_h * 0.22)

    draw.rounded_rectangle(
        [(card_x, card_y), (card_x + card_w, card_y + card_h)],
        radius=corner_radius,
        fill=(15, 23, 42, 185),
        outline=(255, 255, 255, 90),
        width=2,
    )

    combined = Image.alpha_composite(enhanced, overlay)
    draw_final = ImageDraw.Draw(combined)

    # 5. Render Metrics
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

    # 6. Output Image Bytes back to Client
    out_buffer = io.BytesIO()
    combined.convert("RGB").save(out_buffer, format="PNG")

    return Response(content=out_buffer.getvalue(), media_type="image/png")