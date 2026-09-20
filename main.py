import base64
from datetime import datetime
import json
import requests

BASE_URL = "https://dlsports.proapp.workers.dev/"
FEED_SOURCE = "https://s1.noobon.top/axsx/streamx.php"

def generate_security_token():
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    b64 = base64.b64encode(now_str.encode("utf-8")).decode("utf-8")
    rev1 = b64[::-1]
    hex_str = "".join(f"{b:02x}" for b in rev1.encode("utf-8"))
    return hex_str[::-1]

def inspect_names():
    # ১. ফিডের প্রথম ১০টি ম্যাচ টাইটেল
    try:
        res_f = requests.get(FEED_SOURCE, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        f_data = res_f.json()
        print("=== 5 EXAMPLES FROM ONLINE FEED ===")
        for item in f_data[:5]:
            print("Feed Title:", item.get("title") or item.get("name"))
    except Exception as e:
        print("Feed read error:", e)

    # ২. আপনার প্যানেলের শেষ ৫টি ম্যাচের আসল নাম
    payload = {"from": "events", "requestData": generate_security_token()}
    try:
        res_db = requests.post(BASE_URL + "admin/select", json=payload, headers={"Content-Type": "application/json"}, timeout=15)
        events = res_db.json()
        print("\n=== 5 LATEST MATCHES FROM YOUR PANEL ===")
        for ev in events[-5:]:
            e_data = ev
            if "event" in ev and isinstance(ev["event"], str):
                try: e_data = json.loads(ev["event"])
                except: pass
            print(f"ID: {ev.get('id')} | Event: '{e_data.get('eventName')}' | TeamA: '{e_data.get('teamAName')}' | TeamB: '{e_data.get('teamBName')}'")
    except Exception as e:
        print("DB read error:", e)

if __name__ == "__main__":
    inspect_names()
