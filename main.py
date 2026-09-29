import os
import sys
import time
import base64
from datetime import datetime
import json
import requests

BASE_URL = "https://dlsports.proapp.workers.dev/"

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

def get_all_events():
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
        print("Error fetching events:", e)
    return []

def delete_all():
    print("ডাটাবেস থেকে সব ম্যাচ খোঁজা হচ্ছে...")
    events = get_all_events()
    total = len(events)
    print(f"মোট ম্যাচ পাওয়া গেছে: {total} টি")

    if total == 0:
        print("ডাটাবেসে কোনো ম্যাচ নেই!")
        return

    deleted_count = 0

    for idx, item in enumerate(events, 1):
        event_id = item.get("id")
        if not event_id:
            continue

        ev_data = item
        if "event" in item and isinstance(item["event"], str):
            try:
                ev_data = json.loads(item["event"])
            except Exception:
                pass

        t_a = ev_data.get("teamAName") or item.get("teamAName") or "Event"
        t_b = ev_data.get("teamBName") or item.get("teamBName") or ""

        del_payload = {
            "id": int(event_id) if str(event_id).isdigit() else str(event_id),
            "requestData": generate_security_token()
        }

        try:
            res = requests.post(BASE_URL + "admin/delete_event", json=del_payload, headers=get_headers(), timeout=12)
            if res.status_code in [200, 201]:
                deleted_count += 1
                print(f"[{deleted_count}/{total} ডিলিট সম্পন্ন] ID: {event_id} | {t_a} vs {t_b}")
            else:
                print(f"[ব্যর্থ] ID: {event_id} (Status: {res.status_code})")
        except Exception as e:
            print(f"[ত্রুটি] ID: {event_id} - {e}")

        # সার্ভার যেন ব্লক না করে সেজন্য সামান্য বিরতি
        time.sleep(0.5)

    print("\n==========================================")
    print(f"সম্পূর্ণ সাফ হয়েছে! মোট ডিলিট হয়েছে: {deleted_count} টি ম্যাচ")
    print("==========================================")

if __name__ == "__main__":
    delete_all()
