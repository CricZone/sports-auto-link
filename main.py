import os
import sys
import base64
from datetime import datetime, timezone, timedelta
import json
import time
import requests

BASE_URL = "https://dlsports.proapp.workers.dev/"
BD_TZ = timezone(timedelta(hours=6))

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

def get_my_saved_events():
    token = generate_security_token()
    payload = {"from": "events", "requestData": token}
    try:
        res = requests.post(BASE_URL + "admin/select", json=payload, headers=get_headers(), timeout=20)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                return data.get("events") or data.get("data") or []
    except Exception as e:
        print("Error fetching saved events:", e)
    return []

def exact_fix_split_crash():
    events = get_my_saved_events()
    total = len(events)
    print(f"Total events found in database: {total}")

    now_bd = datetime.now(BD_TZ)
    default_date = now_bd.strftime("%d/%m/%Y")
    default_time = now_bd.strftime("%I:%M %p").lower()

    fixed_count = 0

    for idx, item in enumerate(events):
        ev_id = str(item.get("id"))
        
        # ইভেন্ট ডাটা রিড করা
        ev_data = {}
        if "event" in item and isinstance(item["event"], str):
            try:
                ev_data = json.loads(item["event"])
            except Exception:
                ev_data = {}
        elif isinstance(item.get("event"), dict):
            ev_data = item.get("event")

        # আসল স্মালি কোড অনুযায়ী links পাথ স্ট্রিং (Lf7/g; line 656)
        links_path_str = f"links/{ev_id}"

        team_a = str(ev_data.get("teamAName") or item.get("teamAName") or "Team A").strip()
        team_b = str(ev_data.get("teamBName") or item.get("teamBName") or "Team B").strip()
        tournament = str(ev_data.get("eventName") or ev_data.get("match_title") or "Live Match").strip()
        category = str(ev_data.get("category") or "Football").strip()

        # .split() ক্র্যাশ প্রতিরোধে নিশ্চিত স্ট্রিং ভ্যালু
        clean_event = {
            "visible": True,
            "isHot": False,
            "priority": -1,
            "category": category,
            "eventName": tournament,
            "match_title": tournament,
            "matchTitle": tournament,
            "eventLogo": str(ev_data.get("eventLogo") or ""),
            "teamAName": team_a,
            "teamBName": team_b,
            "teamAFlag": str(ev_data.get("teamAFlag") or ""),
            "teamBFlag": str(ev_data.get("teamBFlag") or ""),
            "date": str(ev_data.get("date") or default_date),
            "time": str(ev_data.get("time") or default_time),
            "status": "Not Started",
            # ক্র্যাশ ফিক্স: এটি নিশ্চিতভাবে স্ট্রিং হতে হবে, অ্যারে নয়
            "links": links_path_str,
            "notiThumb": "",
            "countryCodes": "",
            "whitelistCountryCodes": "",
            "messages": "{}"
        }

        # order_index অক্ষুণ্ণ রাখা
        raw_order = item.get("order_index")
        order_idx = int(raw_order) if (raw_order is not None and str(raw_order).lstrip('-').isdigit()) else (idx + 10)

        payload = {
            "from": "events",
            "id": ev_id,
            "event": json.dumps(clean_event),
            "links": links_path_str,
            "linksPath": links_path_str,
            "linksData": "[]",
            "order_index": order_idx,
            "requestData": generate_security_token()
        }

        try:
            res = requests.post(BASE_URL + "admin/update_event", json=payload, headers=get_headers(), timeout=12)
            if res.status_code == 200:
                fixed_count += 1
                print(f"[{fixed_count}/{total}] Fixed ID: {ev_id} | Set links to string '{links_path_str}'")
            time.sleep(2)
        except Exception as e:
            print(f"Error on ID {ev_id}:", e)

    print(f"\nAll {fixed_count} events restored with valid string paths. Apps will open now!")

if __name__ == "__main__":
    exact_fix_split_crash()
