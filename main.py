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

def get_all_saved_events():
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
        print(f"[Error] Failed to fetch events: {e}")
    return []

def delete_single_event(event_id, title=""):
    token = generate_security_token()
    payload = {
        "id": int(event_id) if str(event_id).isdigit() else str(event_id),
        "requestData": token
    }
    try:
        res = requests.post(BASE_URL + "admin/delete_event", json=payload, headers=get_headers(), timeout=12)
        if res.status_code in [200, 201]:
            print(f"[Deleted] ID: {event_id} | {title}")
            return True
        else:
            print(f"[Failed] ID: {event_id} (Status Code: {res.status_code})")
    except Exception as e:
        print(f"[Error] ID: {event_id} - {e}")
    return False

def main():
    print("Fetching all events from panel...")
    events = get_all_saved_events()
    total_events = len(events)
    
    if total_events == 0:
        print("No events found in the panel! Everything is already clean.")
        return

    print(f"Total events found: {total_events}")
    confirm = input(f"Are you sure you want to delete ALL {total_events} events? (yes/no): ").strip().lower()
    
    if confirm != "yes":
        print("Deletion cancelled by user.")
        return

    print("\nStarting full cleanup...")
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

        t_a = ev_data.get("teamAName") or item.get("teamAName") or ev_data.get("team1") or "Event"
        t_b = ev_data.get("teamBName") or item.get("teamBName") or ev_data.get("team2") or ""
        title = f"{t_a} vs {t_b}".strip() if t_b else t_a

        if delete_single_event(event_id, title):
            deleted_count += 1

        # Small delay to prevent API rate limiting
        time.sleep(0.8)

    print("\n==========================================")
    print(f"Cleanup Completed! Successfully deleted: {deleted_count}/{total_events}")
    print("==========================================")

if __name__ == "__main__":
    main()
