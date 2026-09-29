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

def delete_corrupt_event(ev_id):
    """ফিক্স না হলে নষ্ট ইভেন্টটি ডাটাবেস থেকে মুছে ফেলা"""
    payload = {
        "from": "events",
        "id": str(ev_id),
        "requestData": generate_security_token()
    }
    for endpoint in ["admin/delete_event", "admin/delete"]:
        try:
            del_res = requests.post(BASE_URL + endpoint, json=payload, headers=get_headers(), timeout=10)
            if del_res.status_code == 200:
                print(f"[DELETED] Successfully removed broken event ID: {ev_id}")
                return True
        except Exception:
            pass
    return False

def targeted_repair():
    events = get_my_saved_events()
    total = len(events)
    print(f"Total events found in database: {total}")

    now_bd = datetime.now(BD_TZ)
    default_date = now_bd.strftime("%Y-%m-%d")
    default_time = now_bd.strftime("%Y-%m-%d %H:%M:%S")

    # অ্যাপ ক্র্যাশ প্রতিরোধে শতভাগ বাধ্যতামূলক ফিল্ড চেক
    corrupted_items = []
    for item in events:
        ev_id = str(item.get("id"))
        ev_data = None

        if "event" in item and isinstance(item["event"], str):
            try:
                ev_data = json.loads(item["event"])
            except Exception:
                ev_data = None
        elif isinstance(item.get("event"), dict):
            ev_data = item.get("event")

        # যে ম্যাচগুলোতে কোনো ফিল্ড null বা খালি আছে
        if not ev_data or not isinstance(ev_data, dict):
            corrupted_items.append((ev_id, item, {}))
        else:
            time_val = ev_data.get("time")
            date_val = ev_data.get("date")
            cat_val = ev_data.get("category")
            title_val = ev_data.get("match_title") or ev_data.get("eventName")
            links_val = ev_data.get("links")

            if not time_val or not date_val or not cat_val or not title_val or not isinstance(links_val, list):
                corrupted_items.append((ev_id, item, ev_data))

    print(f"\nIdentified {len(corrupted_items)} corrupted/risky events that can crash the app.\n")

    if not corrupted_items:
        print("No corrupted events found. All events have valid non-null fields.")
        return

    fixed_count = 0
    deleted_count = 0

    for ev_id, item, ev_data in corrupted_items:
        team_a = str(ev_data.get("teamAName") or item.get("teamAName") or "Team A").strip()
        team_b = str(ev_data.get("teamBName") or item.get("teamBName") or "Team B").strip()
        
        # .split() ক্র্যাশ রোধে category এবং tournament ফরম্যাট
        category_name = "Football || International Friendly Games"
        tournament_name = str(ev_data.get("eventName") or ev_data.get("match_title") or "International Friendly Games").strip()

        clean_event = {
            "visible": True,
            "isHot": False,
            "priority": -1,
            "category": category_name,
            "eventName": tournament_name,
            "match_title": tournament_name,
            "matchTitle": tournament_name,
            "eventLogo": str(ev_data.get("eventLogo") or ""),
            "teamAName": team_a,
            "teamBName": team_b,
            "teamAFlag": str(ev_data.get("teamAFlag") or ""),
            "teamBFlag": str(ev_data.get("teamBFlag") or ""),
            "date": default_date,
            "time": default_time,
            "status": "Not Started",
            "links": [],
            "notiThumb": "",
            "countryCodes": "",
            "whitelistCountryCodes": "",
            "messages": "{}"
        }

        raw_order = item.get("order_index")
        order_idx = int(raw_order) if (raw_order is not None and str(raw_order).lstrip('-').isdigit()) else 10

        payload = {
            "from": "events",
            "id": ev_id,
            "event": json.dumps(clean_event),
            "links": f"links/{ev_id}",
            "linksPath": f"links/{ev_id}",
            "linksData": "[]",
            "order_index": order_idx,
            "requestData": generate_security_token()
        }

        # নিরাপদ বিরতি সহ আপডেট চেষ্টা
        updated = False
        try:
            res = requests.post(BASE_URL + "admin/update_event", json=payload, headers=get_headers(), timeout=12)
            if res.status_code == 200:
                updated = True
                fixed_count += 1
                print(f"[REPAIRED] ID: {ev_id} | {team_a} vs {team_b}")
            else:
                print(f"[UPDATE FAILED] ID: {ev_id} | Status: {res.status_code} | Msg: {res.text[:80]}")
        except Exception as e:
            print(f"[ERROR] ID {ev_id}: {e}")

        # আপডেট না নিলে ডাটাবেস থেকে ডিলিট করে ক্লিন করা
        if not updated:
            if delete_corrupt_event(ev_id):
                deleted_count += 1

        time.sleep(3.5)

    print(f"\n--- Finish: Repaired: {fixed_count}, Deleted: {deleted_count} ---")

if __name__ == "__main__":
    targeted_repair()
