import os
import dotenv
from garminconnect import Garmin

# Load environment variables from .env
dotenv.load_dotenv()

email = os.getenv("GARMIN_EMAIL")
password = os.getenv("GARMIN_PASSWORD")


def fetch_latest_activity():
    print("🔄 Authenticating with Garmin Connect...")
    garmin = Garmin(email, password)
    garmin.login()
    print("✅ Authenticated successfully!")

    # Fetch 1 most recent activity
    activities = garmin.get_activities(0, 1)

    if not activities:
        print("⚠️ No activities found in your Garmin account.")
        return

    latest = activities[0]

    # Extract Key Metrics
    activity_type = latest.get("activityType", {}).get(
        "typeKey", "unspecified"
    )
    distance_m = latest.get("distance", 0)
    distance_km = round(distance_m / 1000, 2)
    duration_s = latest.get("duration", 0)
    duration_min = round(duration_s / 60, 1)

    avg_hr = latest.get("averageHR", "N/A")
    max_hr = latest.get("maxHR", "N/A")
    avg_speed = latest.get("averageSpeed", 0)  # meters per second

    # Calculate Pace (min/km) from m/s
    pace_str = "N/A"
    if avg_speed > 0:
        sec_per_km = 1000 / avg_speed
        pace_min = int(sec_per_km // 60)
        pace_sec = int(sec_per_km % 60)
        pace_str = f"{pace_min}:{pace_sec:02d}"

    print("\n--- 📊 LATEST ACTIVITY STATS ---")
    print(f"Activity Type: {activity_type}")
    print(f"Distance:      {distance_km} km")
    print(f"Duration:      {duration_min} mins")
    print(f"Average Pace:  {pace_str} /km")
    print(f"Heart Rate:    Avg {avg_hr} bpm | Max {max_hr} bpm")
    print("--------------------------------\n")


if __name__ == "__main__":
    fetch_latest_activity()