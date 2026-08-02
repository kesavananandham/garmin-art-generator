import base64
import io
import os
import tarfile
from contextlib import asynccontextmanager
from enum import Enum

import dotenv
import httpx
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from garminconnect import Garmin
from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

dotenv.load_dotenv()

# Global Garmin client instance
garmin_client = None
TOKEN_DIR = "/tmp/garmin_tokens"

# Dynamic Nature Background Endpoint
DYNAMIC_NATURE_URL = "https://loremflickr.com/1080/1920/nature,landscape/all"


class TemplateType(str, Enum):
    glassmorphism = "glassmorphism"
    minimal_left = "minimal_left"
    zone2 = "zone2"


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


def create_vertical_gradient(
    width: int,
    height: int,
    top_color: tuple[int, int, int, int],
    bottom_color: tuple[int, int, int, int],
) -> Image.Image:
    """Generates a vertical gradient overlay."""
    base = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(base)
    for y in range(height):
        t = y / float(height)
        r = int(top_color[0] + (bottom_color[0] - top_color[0]) * t)
        g = int(top_color[1] + (bottom_color[1] - top_color[1]) * t)
        b = int(top_color[2] + (bottom_color[2] - top_color[2]) * t)
        a = int(top_color[3] + (bottom_color[3] - top_color[3]) * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b, a))
    return base


def format_seconds_to_mmss(seconds: float | int) -> str:
    """Formats total seconds into MM:SS or HH:MM:SS string."""
    total_sec = int(seconds)
    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    secs = total_sec % 60

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def safe_get_zone_seconds(z: dict) -> float:
    """Helper function to extract zone time from various Garmin API structures."""
    if not isinstance(z, dict):
        return 0.0
    for key in [
        "secsInZone",
        "durationInZoneSecs",
        "secs",
        "timeInZone",
        "zoneTime",
    ]:
        if key in z and z[key] is not None:
            try:
                return float(z[key])
            except (ValueError, TypeError):
                pass
    return 0.0


def load_scalable_font(font_names: list[str], size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Tries loading system TTF fonts; falls back to scalable PIL default font."""
    for font_name in font_names:
        try:
            return ImageFont.truetype(font_name, size=size)
        except OSError:
            continue
    # Pillow >= 10.1.0 supports size in load_default()
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def render_zone2_garmin_style_template(
    base_img: Image.Image,
    current: dict,
    last: dict | None,
    hr_zones: list,
    user_avatar: Image.Image | None = None,
) -> Image.Image:
    target_w, target_h = 1080, 1920

    # 1. Base Canvas
    bg = ImageOps.fit(base_img, (target_w, target_h), Image.Resampling.LANCZOS)

    # Darker gradient overlay to boost overall card contrast
    gradient_overlay = create_vertical_gradient(
        target_w,
        target_h,
        top_color=(0, 0, 0, 110),
        bottom_color=(5, 7, 10, 170),
    )

    canvas = Image.alpha_composite(bg.convert("RGBA"), gradient_overlay)

    # 2. Transparent Overlay Layer
    overlay = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Shadow helper for crisp legibility
    def draw_text_with_shadow(
        position, text, font, fill_color, shadow_color=(0, 0, 0, 240), offset=(2, 2), anchor=None
    ):
        x, y = position
        draw.text((x + offset[0], y + offset[1]), str(text), font=font, fill=shadow_color, anchor=anchor)
        draw.text((x, y), str(text), font=font, fill=fill_color, anchor=anchor)

    # Candidate fonts for cross-platform/Linux server compatibility
    font_candidates = [
        "DejaVuSans-Bold.ttf",
        "DejaVuSans.ttf",
        "Arial.ttf",
        "LiberationSans-Regular.ttf",
        "FreeSans.ttf",
        "Helvetica",
    ]

    # PROPERLY SCALED LARGE FONT SIZES FOR 1080x1920 CANVAS
    font_title = load_scalable_font(font_candidates, size=48)
    font_huge = load_scalable_font(font_candidates, size=86)
    font_large_val = load_scalable_font(font_candidates, size=64)
    font_med = load_scalable_font(font_candidates, size=38)
    font_small = load_scalable_font(font_candidates, size=30)

    # Metrics
    activity_name = current.get("activityName", "Running")
    distance_km = f"{round(current.get('distance', 0) / 1000, 2)} km"
    duration_sec = current.get("duration", 3816)
    dur_str = format_seconds_to_mmss(duration_sec)

    avg_speed = current.get("averageSpeed", 0)
    pace_str = "-- /km"
    if avg_speed > 0:
        sec = 1000 / avg_speed
        pace_str = f"{int(sec // 60)}:{int(sec % 60):02d} /km"

    avg_hr = f"{int(current.get('averageHR', 0))}" if current.get("averageHR") else "--"
    max_hr = f"{int(current.get('maxHR', 0))}" if current.get("maxHR") else "--"

    # Darker high-contrast card background
    card_bg = (12, 16, 22, 225)
    card_border = (255, 255, 255, 120)

    text_primary = (255, 255, 255, 255)
    text_secondary = (210, 225, 245, 255)

    # =============================================================
    # SECTION 1: TOP CARD
    # =============================================================
    draw.rounded_rectangle(
        [(40, 60), (target_w - 40, 380)],
        radius=24,
        fill=card_bg,
        outline=card_border,
        width=2,
    )
    draw_text_with_shadow((80, 90), activity_name, font_title, text_secondary)

    # Persona Avatar Badge
    avatar_size = 130
    avatar_x, avatar_y = 80, 180

    if user_avatar is not None:
        avatar_crop = ImageOps.fit(
            user_avatar, (avatar_size, avatar_size), Image.Resampling.LANCZOS
        )
        mask = Image.new("L", (avatar_size, avatar_size), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse((0, 0, avatar_size, avatar_size), fill=255)

        overlay.paste(avatar_crop, (avatar_x, avatar_y), mask)
        draw.ellipse(
            [(avatar_x, avatar_y), (avatar_x + avatar_size, avatar_y + avatar_size)],
            outline=(255, 255, 255, 220),
            width=3,
        )

    # Re-aligned distance & pace metrics
    draw_text_with_shadow((240, 175), distance_km, font_huge, text_primary)
    draw_text_with_shadow((240, 280), f"{dur_str} • {pace_str}", font_med, text_secondary)

    # =============================================================
    # SECTION 2: MID CARD
    # =============================================================
    draw.rounded_rectangle(
        [(40, 410), (target_w - 40, 680)],
        radius=24,
        fill=card_bg,
        outline=card_border,
        width=2,
    )
    draw_text_with_shadow((80, 450), f"{avg_hr} bpm", font_large_val, text_primary)
    draw_text_with_shadow((80, 540), "Average", font_med, text_secondary)

    draw_text_with_shadow((560, 450), f"{max_hr} bpm", font_large_val, text_primary)
    draw_text_with_shadow((560, 540), "Maximum", font_med, text_secondary)

    # =============================================================
    # SECTION 3: BOTTOM CARD (HR ZONES)
    # =============================================================
    draw.rounded_rectangle(
        [(40, 710), (target_w - 40, 1840)],
        radius=24,
        fill=card_bg,
        outline=card_border,
        width=2,
    )

    parsed_zones = hr_zones if isinstance(hr_zones, list) and len(hr_zones) > 0 else [
        {"zoneNumber": 1, "secsInZone": 718, "zoneLowBoundary": 121, "zoneHighBoundary": 134},
        {"zoneNumber": 2, "secsInZone": 2729, "zoneLowBoundary": 135, "zoneHighBoundary": 149},
        {"zoneNumber": 3, "secsInZone": 186, "zoneLowBoundary": 150, "zoneHighBoundary": 163},
        {"zoneNumber": 4, "secsInZone": 0, "zoneLowBoundary": 164, "zoneHighBoundary": 178},
        {"zoneNumber": 5, "secsInZone": 0, "zoneLowBoundary": 178, "zoneHighBoundary": 0},
    ]

    total_secs = sum(safe_get_zone_seconds(z) for z in parsed_zones) or 1.0

    zone_names = {1: "Warm Up", 2: "Easy", 3: "Aerobic", 4: "Threshold", 5: "Maximum"}
    zone_colors = {
        1: (240, 245, 250, 240),
        2: (41, 121, 255, 240),
        3: (56, 142, 60, 240),
        4: (245, 124, 0, 240),
        5: (211, 47, 47, 240),
    }

    zone_map = {
        z.get("zoneNumber", idx + 1) if isinstance(z, dict) else idx + 1: z
        for idx, z in enumerate(parsed_zones)
    }
    curr_y = 750

    for z_num in range(5, 0, -1):
        z = zone_map.get(z_num, {})
        secs = safe_get_zone_seconds(z)
        pct = int(round((secs / total_secs) * 100)) if total_secs > 0 else 0
        z_time_str = format_seconds_to_mmss(secs)

        low_hr = z.get("zoneLowBoundary", z.get("lowHR", z.get("low", "")))
        high_hr = z.get("zoneHighBoundary", z.get("highHR", z.get("high", "")))
        z_desc = zone_names.get(z_num, "")

        if z_num == 5:
            range_str = f"> {int(low_hr)} bpm • {z_desc}" if low_hr else z_desc
        elif low_hr and high_hr and int(high_hr) > 0:
            range_str = f"{int(low_hr)} - {int(high_hr)} bpm • {z_desc}"
        elif low_hr:
            range_str = f">{int(low_hr)} bpm • {z_desc}"
        else:
            range_str = z_desc

        draw_text_with_shadow((80, curr_y), f"Zone {z_num}", font_med, text_primary)
        draw_text_with_shadow((230, curr_y + 4), range_str, font_small, text_secondary)

        draw_text_with_shadow((target_w - 230, curr_y + 2), z_time_str, font_med, text_primary, anchor="ra")
        draw_text_with_shadow((target_w - 80, curr_y + 2), f"{pct}%", font_med, text_primary, anchor="ra")

        bar_y = curr_y + 55
        bar_w = target_w - 160
        draw.rounded_rectangle(
            [(80, bar_y), (80 + bar_w, bar_y + 24)],
            radius=12,
            fill=(255, 255, 255, 50),
        )

        fill_w = int(bar_w * (secs / total_secs))
        if fill_w > 0:
            draw.rounded_rectangle(
                [(80, bar_y), (80 + max(fill_w, 18), bar_y + 24)],
                radius=12,
                fill=zone_colors.get(z_num, (255, 255, 255, 240)),
            )

        curr_y += 195

    final_img = Image.alpha_composite(canvas, overlay)
    return final_img.convert("RGB")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global garmin_client
    try:
        garmin_client = get_garmin_client()
    except Exception as e:
        print(f"🚨 Initial Garmin login failed on startup: {e}")
    yield


app = FastAPI(title="Garmin Card Generator API", lifespan=lifespan)


@app.api_route("/health", methods=["GET", "HEAD"])
def health_check():
    return {"status": "ok", "garmin_connected": garmin_client is not None}


@app.post("/generate")
async def generate_card(
    file: UploadFile | None = File(
        None, description="Optional custom profile/persona image file"
    ),
    template: TemplateType = Query(
        default=TemplateType.glassmorphism,
        description="Card layout template",
    ),
):
    global garmin_client

    if garmin_client is None:
        try:
            garmin_client = get_garmin_client()
        except Exception:
            raise HTTPException(
                status_code=503,
                detail="Garmin service unavailable. Try again later.",
            )

    # 1. Fetch Garmin Activities
    try:
        activities = garmin_client.get_activities(0, 2)
    except Exception as e:
        print(f"🔄 Session expired, re-authenticating... ({e})")
        garmin_client = get_garmin_client()
        activities = garmin_client.get_activities(0, 2)

    current_run = activities[0]
    last_run = activities[1] if len(activities) > 1 else None

    # Fetch HR Zones via get_activity_hr_in_time_zones
    hr_zones_data = []
    if template == TemplateType.zone2:
        try:
            hr_zones_data = garmin_client.get_activity_hr_in_time_zones(
                current_run["activityId"]
            )
        except Exception as err:
            print(f"⚠️ Could not fetch HR zones: {err}")

    # 2. Process Avatar Photo (User Upload)
    uploaded_avatar = None
    if file is not None:
        photo_bytes = await file.read()
        raw_avatar = Image.open(io.BytesIO(photo_bytes))
        uploaded_avatar = ImageOps.exif_transpose(raw_avatar).convert("RGBA")

    # 3. Fetch Dynamic Landscape Background
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.get(DYNAMIC_NATURE_URL, timeout=10.0)
            if resp.status_code == 200:
                raw_bg = Image.open(io.BytesIO(resp.content))
            else:
                raise Exception(f"HTTP {resp.status_code}")
    except Exception as err:
        print(f"⚠️ Background download failed ({err}), fallback to dark default canvas.")
        raw_bg = Image.new("RGB", (1080, 1920), color=(15, 23, 42))

    base_bg = ImageOps.exif_transpose(raw_bg).convert("RGBA")

    # Background Enhancement
    enhanced_bg = ImageEnhance.Color(base_bg).enhance(1.25)
    enhanced_bg = ImageEnhance.Contrast(enhanced_bg).enhance(1.15)
    enhanced_bg = ImageEnhance.Sharpness(enhanced_bg).enhance(1.2)

    # 4. Template Rendering
    if template == TemplateType.zone2:
        final_img = render_zone2_garmin_style_template(
            enhanced_bg, current_run, last_run, hr_zones_data, user_avatar=uploaded_avatar
        )
    else:
        # Standard Fallback Overlay Rendering
        w, h = enhanced_bg.size
        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        card_w, card_h = int(w * 0.9), int(h * 0.16)
        card_x, card_y = (w - card_w) // 2, h - card_h - int(h * 0.04)

        draw.rounded_rectangle(
            [(card_x, card_y), (card_x + card_w, card_y + card_h)],
            radius=int(card_h * 0.22),
            fill=(15, 23, 42, 185),
            outline=(255, 255, 255, 90),
            width=2,
        )

        final_img = Image.alpha_composite(enhanced_bg, overlay)

    out_buffer = io.BytesIO()
    final_img.convert("RGB").save(out_buffer, format="PNG")
    return Response(content=out_buffer.getvalue(), media_type="image/png")