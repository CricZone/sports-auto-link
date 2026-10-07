import base64
from datetime import datetime
import json
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

def delete_single_event(event_id):
    str_id = str(event_id)
    int_id = int(str_id) if str_id.isdigit() else str_id

    del_payload = {
        "from": "events",
        "table": "events",
        "id": int_id,
        "eventId": str_id,
        "requestData": generate_security_token()
    }

    headers = get_headers()
    endpoints = ["admin/delete", "admin/delete_event"]

    for ep in endpoints:
        try:
            r = requests.post(BASE_URL + ep, json=del_payload, headers=headers, timeout=10)
            if r.status_code in [200, 201]:
                return True, r.text[:80]
        except Exception:
            pass
    return False, "Failed"

def main():
    print("Fetching all matches from database...")
    events = get_all_events()
    total_events = len(events)
    print(f"Total Matches Found in Database: {total_events}")

    if total_events == 0:
        print("Database is already empty. No matches to delete.")
        return

    deleted_count = 0
    failed_count = 0

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

        t_a = ev_data.get("teamAName") or item.get("teamAName") or ev_data.get("team1") or "Match"
        t_b = ev_data.get("teamBName") or item.get("teamBName") or ev_data.get("team2") or ""

        ok, resp_txt = delete_single_event(event_id)
        if ok:
            deleted_count += 1
            print(f"[{idx}/{total_events} Deleted] ID: {event_id} | {t_a} vs {t_b} | Resp: {resp_txt}")
        else:
            failed_count += 1
            print(f"[{idx}/{total_events} FAILED] ID: {event_id}")

        time.sleep(0.08)

    print("\n==========================================")
    print(f"Deletion Completed! Total Deleted: {deleted_count} | Failed: {failed_count}")
    print("==========================================")

if __name__ == "__main__":
    main()
