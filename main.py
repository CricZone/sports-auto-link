import base64
from datetime import datetime
import json
import re
import requests

BASE_URL = "https://dlsports.proapp.workers.dev/"
FEED_SOURCE = "https://s1.noobon.top/axsx/streamx.php"

def generate_security_token():
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    b64 = base64.b64encode(now_str.encode("utf-8")).decode("utf-8")
    rev1 = b64[::-1]
    hex_str = "".join(f"{b:02x}" for b in rev1.encode("utf-8"))
    return hex_str[::-1]

def get_headers():
    return {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "okhttp/4.9.2"
    }

def clean_filename(name):
    return re.sub(r'[^a-zA-Z0-9_-]', '_', name.strip().lower())

def sync_all_events():
    print("Fetching feed from source...")
    try:
        res = requests.get(FEED_SOURCE, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        if res.status_code != 200:
            print(f"Feed error: {res.status_code}")
            return

        raw_data = res.json()
        matches = raw_data if isinstance(raw_data, list) else raw_data.get("matches", raw_data.get("events", []))

        if not matches:
            print("No matches found.")
            return

        now = datetime.now()
        cur_date = now.strftime("%Y-%m-%d")
        cur_time = now.strftime("%I:%M %p")

        for m in matches:
            event_name = m.get("title") or m.get("name") or "Live Match"
            team_a = m.get("team1") or m.get("teamA") or "Team A"
            team_b = m.get("team2") or m.get("teamB") or "Team B"
            
            # যদি সরাসরি টিম না থাকে টাইটেল থেকে আলাদা করা
            if " vs " in event_name.lower() and (team_a == "Team A" or not team_a):
                parts = re.split(r'\s+vs\s+', event_name, flags=re.IGNORECASE)
                if len(parts) >= 2:
                    team_a, team_b = parts[0].strip(), parts[1].strip()

            logo_a = m.get("team1_logo") or m.get("logo1") or "https://dlsports.top/default.png"
            logo_b = m.get("team2_logo") or m.get("logo2") or "https://dlsports.top/default.png"
            event_logo = m.get("logo") or logo_a

            links = m.get("links", [])
            links_str = json.dumps(links) if isinstance(links, list) else str(links)
            links_path = f"{clean_filename(event_name)}_{clean_filename(team_a)}_{clean_filename(team_b)}"

            # ক্লাসের কোড অনুযায়ী "event" অবজেক্ট প্রস্তুত
            event_dict = {
                "visible": True,
                "isHot": True,
                "priority": 1,
                "category": m.get("category", "Live Sports"),
                "eventName": event_name,
                "eventLogo": event_logo,
                "teamAName": team_a,
                "teamBName": team_b,
                "teamAFlag": logo_a,
                "teamBFlag": logo_b,
                "date": m.get("date", cur_date),
                "time": m.get("time", cur_time),
                "notiThumb": "",
                "countryCodes": "",
                "whitelistCountryCodes": "",
                "messages": "{}",
                "links": links_path
            }

            # ক্লাসের কোড অনুযায়ী মূল পে-লোড প্রস্তুত
            payload = {
                "event": json.dumps(event_dict),
                "links": links_str,
                "linksPath": links_path,
                "requestData": generate_security_token()
            }

            endpoint = BASE_URL + "admin/add_event"
            post_res = requests.post(endpoint, json=payload, headers=get_headers(), timeout=15)
            print(f"[{event_name}] Status: {post_res.status_code}, Response: {post_res.text}")

    except Exception as e:
        print("Sync failed:", str(e))

if __name__ == "__main__":
    sync_all_events()
