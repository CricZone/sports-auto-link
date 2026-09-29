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

def emergency_crash_fix():
    events = get_my_saved_events()
    print(f"Total Events Found: {len(events)}")
    fixed_count = 0

    for idx, item in enumerate(events):
        ev_id = str(item.get("id"))
        
        # ইভেন্ট ডাটা পার্স করা
        ev_data = {}
        if "event" in item and isinstance(item["event"], str):
            try:
                ev_data = json.loads(item["event"])
            except Exception:
                ev_data = {}
        elif isinstance(item.get("event"), dict):
            ev_data = item.get("event")

        # ১. links কে নিশ্চিতভাবে JSONArray (তালিকা) বানানো
        curr_links = ev_data.get("links")
        if isinstance(curr_links, list):
            formatted_links = curr_links
        else:
            # যদি স্ট্রিং হয়ে থাকে, তবে খালি তালিকা বা ডিফল্ট সার্ভার স্ট্রাকচার দেওয়া
            formatted_links = []

        # ২. event অবজেক্ট ঠিক করা
        ev_data["links"] = formatted_links
        ev_data["visible"] = True
        ev_data["status"] = ev_data.get("status") or "Not Started"
        
        # ৩. order_index নিশ্চিত করা
        order = item.get("order_index")
        if order is None or not str(order).lstrip('-').isdigit():
            order = idx + 10
        else:
            order = int(order)

        payload = {
            "from": "events",
            "id": ev_id,
            "event": json.dumps(ev_data),
            "links": f"links/{ev_id}",
            "linksPath": f"links/{ev_id}",
            "linksData": json.dumps(formatted_links),
            "order_index": order,
            "requestData": generate_security_token()
        }

        try:
            res = requests.post(BASE_URL + "admin/update_event", json=payload, headers=get_headers(), timeout=12)
            if res.status_code == 200:
                fixed_count += 1
                print(f"[{fixed_count}/{len(events)}] Fixed ID {ev_id} | Links Array Restored")
            # ফাইলের SHA রেস-কন্ডিশন এড়াতে ২ সেকেন্ড বিরতি
            time.sleep(2)
        except Exception as e:
            print(f"Error on ID {ev_id}:", e)

    print(f"\nSuccessfully repaired {fixed_count} events. Apps will now open properly.")

if __name__ == "__main__":
    emergency_crash_fix()
