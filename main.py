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
        else:
            print(f"[Fetch Error] Status: {res.status_code} | Text: {res.text[:150]}")
    except Exception as e:
        print(f"[Fetch Exception]: {e}")
    return []

def delete_single_event(event_id, title=""):
    del_payload = {
        "id": int(event_id) if str(event_id).isdigit() else str(event_id),
        "requestData": generate_security_token()
    }
    try:
        del_res = requests.post(BASE_URL + "admin/delete_event", json=del_payload, headers=get_headers(), timeout=12)
        if del_res.status_code in [200, 201]:
            print(f"[Deleted Success] ID: {event_id} | {title}")
            return True
        else:
            print(f"[Delete Failed] ID: {event_id} | HTTP {del_res.status_code}: {del_res.text[:120]}")
    except Exception as e:
        print(f"[Error Deleting ID {event_id}]: {e}")
    return False

def main():
    print("Fetching all events from panel...")
    events = get_all_events()
    total_events = len(events)
    print(f"Total events found: {total_events}")

    if total_events == 0:
        print("Panel-e kono event nei, already empty!")
        return

    deleted_count = 0

    for idx, item in enumerate(events, start=1):
        event_id = item.get("id")
        if not event_id:
            continue

        ev_data = item
        if "event" in item and isinstance(item["event"], str):
            try:
                ev_data = json.loads(item["event"])
            except Exception:
                pass

        t_a = ev_data.get("teamAName") or item.get("teamAName") or ""
        t_b = ev_data.get("teamBName") or item.get("teamBName") or ""
        title = f"{t_a} vs {t_b}".strip()
        if title == "vs" or not title:
            title = ev_data.get("eventName") or ev_data.get("title") or "Unnamed Event"

        print(f"[{idx}/{total_events}] Deleting ID: {event_id} ({title})...")
        if delete_single_event(event_id, title):
            deleted_count += 1
            time.sleep(0.5)  # Rate-limit safety delay

    print("\n==========================================")
    print(f"All Clear Completed! Total Deleted: {deleted_count}/{total_events}")
    print("==========================================")

if __name__ == "__main__":
    main()
