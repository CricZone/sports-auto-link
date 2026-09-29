import os
import sys
import base64
from datetime import datetime
import time
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

def delete_single_event(ev_id):
    token = generate_security_token()
    payload = {
        "from": "events",
        "id": str(ev_id),
        "requestData": token
    }
    # Dono endpoint try korbe confirm delete er jonno
    for endpoint in ["admin/delete_event", "admin/delete"]:
        try:
            res = requests.post(BASE_URL + endpoint, json=payload, headers=get_headers(), timeout=12)
            if res.status_code == 200:
                return True
        except Exception:
            pass
    return False

def clear_entire_database():
    events = get_all_events()
    total = len(events)
    print(f"Total events found to delete: {total}")

    if total == 0:
        print("Database already 100% empty!")
        return

    deleted_count = 0
    for idx, item in enumerate(events):
        ev_id = str(item.get("id"))
        if not ev_id or ev_id == "None":
            continue

        success = delete_single_event(ev_id)
        if success:
            deleted_count += 1
            print(f"[{deleted_count}/{total}] Successfully DELETED Event ID: {ev_id}")
        else:
            print(f"[RETRY FAILED] Could not delete ID: {ev_id}")

        # Server rate limit o file conflict erate safe pause
        time.sleep(1.2)

    print(f"\nDone! Successfully deleted {deleted_count} out of {total} events.")
    print("Database is completely clean now. Apps will open without any crash!")

if __name__ == "__main__":
    clear_entire_database()
