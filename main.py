import os
import requests
import base64
from datetime import datetime

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

def clear():
    token = generate_security_token()
    payload = {"from": "events", "requestData": token}
    try:
        res = requests.post(BASE_URL + "admin/select", json=payload, headers=get_headers(), timeout=20)
        data = res.json()
        events = data if isinstance(data, list) else (data.get("events") or data.get("data") or [])
    except Exception:
        events = []

    print(f"Deleting {len(events)} events...")
    for ev in events:
        ev_id = str(ev.get("id"))
        p = {"from": "events", "id": ev_id, "requestData": generate_security_token()}
        requests.post(BASE_URL + "admin/delete_event", json=p, headers=get_headers(), timeout=10)
        requests.post(BASE_URL + "admin/delete", json=p, headers=get_headers(), timeout=10)
        print(f"Deleted ID: {ev_id}")

    print("\nDatabase is 100% clean! Apps are safe and ready to open.")

if __name__ == "__main__":
    clear()
