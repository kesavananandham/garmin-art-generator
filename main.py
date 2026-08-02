import base64
import io
import os
import random
import tarfile
import textwrap
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

# External Dynamic Endpoints
DYNAMIC_NATURE_URL = "https://loremflickr.com/1080/1920/nature,landscape/all"
# External Dynamic Quote Endpoints (Free, No Auth Required)
EXTERNAL_QUOTE_URLS = [
    "https://type.fit/api/quotes",
    "https://api.quotable.io/quotes/random?tags=sports|competition|motivational",
]

# Robust backup pool if all external APIs are unreachable
FALLBACK_QUOTES = [
    "“The miracle isn't that I finished. The miracle is that I had the courage to start.”",
    "“Pain is inevitable. Suffering is optional.”",
    "“Run when you can, walk if you have to, crawl if you must; just never give up.”",
    "“It never gets easier, you just get better.”",
    "“Clear your mind of can’t.”",
    "“Your body will argue that there is no justifiable reason to continue. Your job is to prove it wrong.”",
]


async def fetch_external_quote() -> str:
    """Fetches dynamic sports/running quotes from external APIs with clean filtering."""
    sports_keywords = [
        "run", "runner", "running", "stride", "pace", "finish", "race",
        "athlete", "sport", "discipline", "grit", "mile", "km", "courage",
        "push", "strong", "win", "strive", "effort", "mind", "body", "train"
    ]

    async with httpx.AsyncClient(follow_redirects=True) as client:
        # Try Primary API (TypeFit)
        try:
            resp = await client.get(EXTERNAL_QUOTE_URLS[0], timeout=4.0)
            if resp.status_code == 200:
                quotes_data = resp.json()
                # Filter for running/sports relevant quotes
                matching_quotes = []
                for item in quotes_data:
                    q_text = item.get("text", "")
                    if any(kw in q_text.lower() for kw in sports_keywords):
                        # Clean up formatting/author suffixes
                        clean_text = q_text.replace(", type.fit", "").strip()
                        matching_quotes.append(clean_text)

                if matching_quotes:
                    selected = random.choice(matching_quotes)
                    return f"“{selected.strip('“ ”')}”"
        except Exception as err:
            print(f"⚠️ Primary quote API failed ({err}). Trying secondary endpoint...")

        # Try Secondary API (Quotable)
        try:
            resp = await client.get(EXTERNAL_QUOTE_URLS[1], timeout=4.0)
            if resp.status_code == 200:
                data = resp.json()
                quote_item = data[0] if isinstance(data, list) and len(data) > 0 else data
                q_text = quote_item.get("content", "")
                if q_text:
                    return f"“{q_text.strip('“ ”')}”"
        except Exception as err:
            print(f"⚠️ Secondary quote API failed ({err}).")

    # Fallback to local running pool if network/APIs are down
    print("ℹ️ External APIs unreachable or rate-limited. Using backup quote.")
    return random.choice(FALLBACK_QUOTES)


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
        raise ValueError("GARMIN_EMAIL or GARMIN_PASSWORD not set in environment.")

    client = Garmin(email, password, is_cn=False)

    if not os.path.exists(TOKEN_DIR) or not os.listdir(TOKEN_DIR):
        restore_tokens_from_env()

    try:
        print("🔐 Attempting to log in using cached session tokens...")
        client.login(TOKEN_DIR)
        print("✅ Logged in successfully with cached tokens.")
    except Exception as e:
        print(f"⚠️ Token login failed ({e}). Attempting full credential login...")
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
    total_sec = int(seconds)
    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    secs = total_sec % 60

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def safe_get_zone_seconds(z: dict) -> float:
    if not isinstance(z, dict):
        return 0.0
    for key in ["secsInZone", "durationInZoneSecs", "secs", "timeInZone", "zoneTime"]:
        if key in z and z[key] is not None:
            try:
                return float(z[key])
            except (ValueError, TypeError):
                pass
    return 0.0


def load_scalable_font(font_names: list[str], size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for font_name in font_names:
        try:
            return ImageFont.truetype(font_name, size=size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def render_zone2_garmin_style_template(
        base_img: Image.Image,
        current: dict,
        last: dict | None,
        hr_zones: list,
        quote_text: str,
        user_avatar: Image.Image | None = None,
) -> Image.Image:
    target_w, target_h = 1080, 1920

    # 1. Canvas
    bg = ImageOps.fit(base_img, (target_w, target_h), Image.Resampling.LANCZOS)
    gradient_overlay = create_vertical_gradient(
        target_w, target_h, top_color=(0, 0, 0, 110), bottom_color=(5, 7, 10, 170)
    )
    canvas = Image.alpha_composite(bg.convert("RGBA"), gradient_overlay)

    overlay = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    def draw_text_with_shadow(position, text, font, fill_color, shadow_color=(0, 0, 0, 240), offset=(2, 2),
                              anchor=None):
        x, y = position
        draw.text((x + offset[0], y + offset[1]), str(text), font=font, fill=shadow_color, anchor=anchor)
        draw.text((x, y), str(text), font=font, fill=fill_color, anchor=anchor)

    font_candidates = ["DejaVuSans-Bold.ttf", "DejaVuSans.ttf", "Arial.ttf", "FreeSans.ttf", "Helvetica"]

    font_title = load_scalable_font(font_candidates, size=48)
    font_huge = load_scalable_font(font_candidates, size=86)
    font_large_val = load_scalable_font(font_candidates, size=64)
    font_med = load_scalable_font(font_candidates, size=38)
    font_small = load_scalable_font(font_candidates, size=30)
    font_quote = load_scalable_font(["DejaVuSans-Oblique.ttf", "DejaVuSans.ttf", "FreeSans.ttf"], size=36)

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

    card_bg = (12, 16, 22, 225)
    card_border = (255, 255, 255, 120)

    text_primary = (255, 255, 255, 255)
    text_secondary = (210, 225, 245, 255)

    # TOP CARD
    draw.rounded_rectangle([(40, 60), (target_w - 40, 380)], radius=24, fill=card_bg, outline=card_border, width=2)
    draw_text_with_shadow((80, 90), activity_name, font_title, text_secondary)

    avatar_size = 130
    avatar_x, avatar_y = 80, 180

    if user_avatar is not None:
        avatar_crop = ImageOps.fit(user_avatar, (avatar_size, avatar_size), Image.Resampling.LANCZOS)
        mask = Image.new("L", (avatar_size, avatar_size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, avatar_size, avatar_size), fill=255)

        overlay.paste(avatar_crop, (avatar_x, avatar_y), mask)
        draw.ellipse([(avatar_x, avatar_y), (avatar_x + avatar_size, avatar_y + avatar_size)],
                     outline=(255, 255, 255, 220), width=3)

    draw_text_with_shadow((240, 175), distance_km, font_huge, text_primary)
    draw_text_with_shadow((240, 280), f"{dur_str} • {pace_str}", font_med, text_secondary)

    # MID CARD
    draw.rounded_rectangle([(40, 410), (target_w - 40, 680)], radius=24, fill=card_bg, outline=card_border, width=2)
    draw_text_with_shadow((80, 450), f"{avg_hr} bpm", font_large_val, text_primary)
    draw_text_with_shadow((80, 540), "Average", font_med, text_secondary)

    draw_text_with_shadow((560, 450), f"{max_hr} bpm", font_large_val, text_primary)
    draw_text_with_shadow((560, 540), "Maximum", font_med, text_secondary)

    # BOTTOM CARD (HR ZONES & EXTERNAL DYNAMIC QUOTE)
    draw.rounded_rectangle([(40, 710), (target_w - 40, 1860)], radius=24, fill=card_bg, outline=card_border, width=2)

    parsed_zones = hr_zones if isinstance(hr_zones, list) and len(hr_zones) > 0 else [
        {"zoneNumber": 1, "secsInZone": 718, "zoneLowBoundary": 121, "zoneHighBoundary": 134},
        {"zoneNumber": 2, "secsInZone": 2729, "zoneLowBoundary": 135, "zoneHighBoundary": 149},
        {"zoneNumber": 3, "secsInZone": 186, "zoneLowBoundary": 150, "zoneHighBoundary": 163},
        {"zoneNumber": 4, "secsInZone": 0, "zoneLowBoundary": 164, "zoneHighBoundary": 178},
        {"zoneNumber": 5, "secsInZone": 0, "zoneLowBoundary": 178, "zoneHighBoundary": 0},
    ]

    total_secs = sum(safe_get_zone_seconds(z) for z in parsed_zones) or 1.0
    zone_names = {1: "Warm Up", 2: "Easy", 3: "Aerobic", 4: "Threshold", 5: "Maximum"}
    zone_colors = {1: (240, 245, 250, 240), 2: (41, 121, 255, 240), 3: (56, 142, 60, 240), 4: (245, 124, 0, 240),
                   5: (211, 47, 47, 240)}
    zone_map = {z.get("zoneNumber", idx + 1) if isinstance(z, dict) else idx + 1: z for idx, z in
                enumerate(parsed_zones)}

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

        bar_y, bar_w = curr_y + 55, target_w - 160
        draw.rounded_rectangle([(80, bar_y), (80 + bar_w, bar_y + 24)], radius=12, fill=(255, 255, 255, 50))
        fill_w = int(bar_w * (secs / total_secs))
        if fill_w > 0:
            draw.rounded_rectangle([(80, bar_y), (80 + max(fill_w, 18), bar_y + 24)], radius=12,
                                   fill=zone_colors.get(z_num, (255, 255, 255, 240)))

        curr_y += 185

    # RENDER EXTERNALLY FETCHED QUOTE
    quote_wrapped = textwrap.fill(quote_text, width=52)
    draw_text_with_shadow(
        position=(target_w // 2, 1710),
        text=quote_wrapped,
        font=font_quote,
        fill_color=(245, 180, 80, 230),  # Soft warm gold accent
        shadow_color=(0, 0, 0, 255),
        anchor="ma",
    )

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
        file: UploadFile | None = File(None, description="Optional profile image"),
        template: TemplateType = Query(default=TemplateType.glassmorphism, description="Card layout template"),
):
    global garmin_client

    if garmin_client is None:
        try:
            garmin_client = get_garmin_client()
        except Exception:
            raise HTTPException(status_code=503, detail="Garmin service unavailable. Try again later.")

    # Fetch Garmin Activities
    try:
        activities = garmin_client.get_activities(0, 2)
    except Exception as e:
        print(f"🔄 Session expired, re-authenticating... ({e})")
        garmin_client = get_garmin_client()
        activities = garmin_client.get_activities(0, 2)

    current_run = activities[0]
    last_run = activities[1] if len(activities) > 1 else None

    # Fetch HR Zones
    hr_zones_data = []
    if template == TemplateType.zone2:
        try:
            hr_zones_data = garmin_client.get_activity_hr_in_time_zones(current_run["activityId"])
        except Exception as err:
            print(f"⚠️ Could not fetch HR zones: {err}")

    # Process Avatar Photo
    uploaded_avatar = None
    if file is not None:
        photo_bytes = await file.read()
        raw_avatar = Image.open(io.BytesIO(photo_bytes))
        uploaded_avatar = ImageOps.exif_transpose(raw_avatar).convert("RGBA")

    # Fetch Dynamic Background & Dynamic Quote asynchronously
    async with httpx.AsyncClient(follow_redirects=True) as client:
        try:
            bg_resp = await client.get(DYNAMIC_NATURE_URL, timeout=10.0)
            raw_bg = Image.open(io.BytesIO(bg_resp.content)) if bg_resp.status_code == 200 else Image.new("RGB",
                                                                                                          (1080, 1920),
                                                                                                          color=(15, 23,
                                                                                                                 42))
        except Exception:
            raw_bg = Image.new("RGB", (1080, 1920), color=(15, 23, 42))

    dynamic_quote = await fetch_external_quote()

    base_bg = ImageOps.exif_transpose(raw_bg).convert("RGBA")
    enhanced_bg = ImageEnhance.Color(base_bg).enhance(1.25)
    enhanced_bg = ImageEnhance.Contrast(enhanced_bg).enhance(1.15)
    enhanced_bg = ImageEnhance.Sharpness(enhanced_bg).enhance(1.2)

    if template == TemplateType.zone2:
        final_img = render_zone2_garmin_style_template(
            enhanced_bg,
            current_run,
            last_run,
            hr_zones_data,
            quote_text=dynamic_quote,
            user_avatar=uploaded_avatar,
        )
    else:
        w, h = enhanced_bg.size
        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        card_w, card_h = int(w * 0.9), int(h * 0.16)
        card_x, card_y = (w - card_w) // 2, h - card_h - int(h * 0.04)

        draw.rounded_rectangle([(card_x, card_y), (card_x + card_w, card_y + card_h)], radius=int(card_h * 0.22),
                               fill=(15, 23, 42, 185), outline=(255, 255, 255, 90), width=2)
        final_img = Image.alpha_composite(enhanced_bg, overlay)

    out_buffer = io.BytesIO()
    final_img.convert("RGB").save(out_buffer, format="PNG")
    return Response(content=out_buffer.getvalue(), media_type="image/png")