import os
import sys
import base64
from datetime import datetime, timezone, timedelta
import json
import re
import time
import requests

BASE_URL = "https://dlsports.proapp.workers.dev/"
FEED_SOURCE = os.getenv("SECRET_FEED_SOURCE", "")
MAX_ADD_PER_RUN = 5

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

def clean_name(val):
    if not val:
        return ""
    w = str(val).lower()
    w = re.sub(r'\b(fc|cf|sc|united|city|club|women|vs|v)\b', '', w)
    return re.sub(r'[^a-z0-9]', '', w).strip()

def parse_match_time(raw_val):
    if not raw_val:
        return None
    try:
        now_bd = datetime.now(BD_TZ)
        val_str = str(raw_val).strip()

        if "t" in val_str.lower():
            clean_iso = val_str.replace("Z", "+00:00").replace("z", "+00:00")
            dt = datetime.fromisoformat(clean_iso)
            return dt.astimezone(BD_TZ)

        if val_str.isdigit() or (val_str.replace('.', '', 1).isdigit() and len(val_str) >= 10):
            ts = float(val_str)
            if ts > 1e11:
                ts /= 1000
            return datetime.fromtimestamp(ts, tz=BD_TZ)

        formats = [
            "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %I:%M %p", "%Y-%m-%d %H:%M",
            "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %I:%M %p", "%d-%m-%Y %H:%M",
            "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %I:%M %p", "%d/%m/%Y %H:%M",
            "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(val_str, fmt)
                return dt.replace(tzinfo=BD_TZ)
            except ValueError:
                pass

        time_formats = ["%I:%M %p", "%H:%M", "%I:%M%p"]
        for t_fmt in time_formats:
            try:
                t_dt = datetime.strptime(val_str, t_fmt)
                return now_bd.replace(hour=t_dt.hour, minute=t_dt.minute, second=0, microsecond=0)
            except ValueError:
                pass
    except Exception:
        pass
    return None

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

def repair_and_sync():
    my_events = get_my_saved_events()
    print(f"Total Events in Panel to verify: {len(my_events)}")

    now_bd = datetime.now(BD_TZ)
    repair_count = 0

    # ====================================================
    # ১. ক্র্যাশ হওয়া ইভেন্টগুলো রিপেয়ার করা (Fix Crash)
    # ====================================================
    for idx, item in enumerate(my_events):
        ev_id = str(item.get("id"))
        ev_data = {}
        if "event" in item and isinstance(item["event"], str):
            try:
                ev_data = json.loads(item["event"])
            except Exception:
                pass
        elif isinstance(item.get("event"), dict):
            ev_data = item.get("event")

        # সঠিক order_index নির্ধারণ (যা ডিলিট হয়ে অ্যাপ ক্র্যাশ করাচ্ছিল)
        raw_order = item.get("order_index")
        if raw_order is not None and str(raw_order).lstrip('-').isdigit():
            order_index = int(raw_order)
        else:
            order_index = idx + 10

        # টাইম ফিল্ড ফিক্স
        time_val = str(ev_data.get("time") or "")
        date_val = str(ev_data.get("date") or now_bd.strftime("%Y-%m-%d"))

        # যদি time ফিল্ডে সম্পূর্ণ ফরম্যাট না থাকে, তবে পূর্ণাঙ্গ ফরম্যাটে রূপান্তর
        if len(time_val) < 15:
            dt = parse_match_time(time_val) or now_bd
            time_full = dt.strftime("%Y-%m-%d %H:%M:%S")
        else:
            time_full = time_val

        # অ্যাপের মূল ফিল্ডগুলো ঠিক করা
        team_a = ev_data.get("teamAName") or "Team A"
        team_b = ev_data.get("teamBName") or "Team B"
        tournament = ev_data.get("match_title") or ev_data.get("eventName") or ev_data.get("tournament") or "Live Event"
        category = ev_data.get("category") or "Football"

        # Smali কোড অনুযায়ী event অবজেক্ট
        repaired_event = {
            "teamAName": team_a,
            "teamBName": team_b,
            "teamAFlag": ev_data.get("teamAFlag") or "",
            "teamBFlag": ev_data.get("teamBFlag") or "",
            "match_title": tournament,
            "eventName": tournament,
            "category": category,
            "time": time_full,
            "date": date_val,
            "status": "Not Started",
            "visible": True,
            "isHot": False,
            "priority": -1,
            "links": f"links/{ev_id}"
        }

        # linksData উদ্ধার
        links_data = ev_data.get("linksData") or item.get("linksData") or []
        if isinstance(links_data, str):
            try:
                links_data = json.loads(links_data)
            except Exception:
                links_data = []

        payload = {
            "from": "events",
            "id": ev_id,
            "event": json.dumps(repaired_event),
            "links": f"links/{ev_id}",
            "linksPath": f"links/{ev_id}",
            "linksData": json.dumps(links_data) if isinstance(links_data, list) else str(links_data),
            "order_index": order_index,
            "requestData": generate_security_token()
        }

        try:
            up_res = requests.post(BASE_URL + "admin/update_event", json=payload, headers=get_headers(), timeout=10)
            if up_res.status_code == 200:
                repair_count += 1
        except Exception as e:
            pass

    print(f"Repaired and restored {repair_count} events in panel. Crashes resolved.")

if __name__ == "__main__":
    repair_and_sync()
