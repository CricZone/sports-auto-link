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

def complete_database_repair():
    events = get_my_saved_events()
    total = len(events)
    print(f"--- Starting Complete Repair for {total} Events ---")

    now_bd = datetime.now(BD_TZ)
    default_date = now_bd.strftime("%Y-%m-%d")
    default_time = now_bd.strftime("%Y-%m-%d %H:%M:%S")

    success_count = 0
    failed_ids = []

    for idx, item in enumerate(events):
        ev_id = str(item.get("id"))
        
        # ১. ইভেন্ট ডাটা এক্সট্রাক্ট করা
        ev_data = {}
        if "event" in item and isinstance(item["event"], str):
            try:
                ev_data = json.loads(item["event"])
            except Exception:
                ev_data = {}
        elif isinstance(item.get("event"), dict):
            ev_data = item.get("event")

        # ২. links অ্যারে নিশ্চিত করা
        links_val = ev_data.get("links")
        if isinstance(links_val, list):
            formatted_links = links_val
        else:
            formatted_links = []

        # ৩. কোনো ফিল্ড যেন null না থাকে (Crash Protection)
        team_a = str(ev_data.get("teamAName") or item.get("teamAName") or "Team A").strip()
        team_b = str(ev_data.get("teamBName") or item.get("teamBName") or "Team B").strip()
        
        tournament = str(ev_data.get("eventName") or ev_data.get("match_title") or ev_data.get("tournament") or "International Friendly Games").strip()
        category = str(ev_data.get("category") or "Football").strip()
        
        # টাইম ভ্যালিডেশন (স্প্লিট ক্র্যাশ এড়াতে পূর্ণাঙ্গ ফরম্যাট)
        time_raw = str(ev_data.get("time") or "").strip()
        if len(time_raw) < 10:
            time_val = default_time
        else:
            time_val = time_raw

        date_val = str(ev_data.get("date") or default_date).strip()

        # শতভাগ নিরাপদ ইভেন্ট অবজেক্ট
        repaired_event = {
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
            "date": date_val,
            "time": time_val,
            "status": "Not Started",
            "links": formatted_links,
            "notiThumb": "",
            "countryCodes": "",
            "whitelistCountryCodes": "",
            "messages": "{}"
        }

        # order_index সুরক্ষিত রাখা
        raw_order = item.get("order_index")
        if raw_order is not None and str(raw_order).lstrip('-').isdigit():
            order_idx = int(raw_order)
        else:
            order_idx = idx + 10

        payload = {
            "from": "events",
            "id": ev_id,
            "event": json.dumps(repaired_event),
            "links": f"links/{ev_id}",
            "linksPath": f"links/{ev_id}",
            "linksData": json.dumps(formatted_links),
            "order_index": order_idx,
            "requestData": generate_security_token()
        }

        # ৪. আপডেট ও রিট্রাই মেকানিজম
        updated = False
        for attempt in range(2):
            try:
                res = requests.post(BASE_URL + "admin/update_event", json=payload, headers=get_headers(), timeout=12)
                if res.status_code == 200:
                    updated = True
                    success_count += 1
                    print(f"[{success_count}/{total}] Fixed ID {ev_id} | {team_a} vs {team_b}")
                    break
                else:
                    time.sleep(2)
            except Exception:
                time.sleep(2)

        if not updated:
            failed_ids.append(ev_id)
            print(f"[FAILED] Could not update ID {ev_id}")

        time.sleep(2)

    print(f"\nRepair Finished! Successfully fixed: {success_count}/{total}")
    if failed_ids:
        print(f"Failed IDs: {failed_ids}")

if __name__ == "__main__":
    complete_database_repair()
