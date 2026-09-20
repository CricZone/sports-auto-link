import base64
from datetime import datetime
import json
import requests

BASE_URL = "https://dlsports.proapp.workers.dev/"
FEED_SOURCE = "https://s1.noobon.top/axsx/streamx.php"

def generate_security_token():
    """অ্যাপের সিকিউরিটি টোকেন জেনারেটর (Base64 -> Rev -> Hex -> Rev)"""
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

def fetch_and_push_all_matches():
    print("Fetching live matches from source feed...")
    try:
        res = requests.get(FEED_SOURCE, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        if res.status_code != 200:
            print(f"Failed to fetch feed, status code: {res.status_code}")
            return

        raw_data = res.json()
        matches_list = raw_data if isinstance(raw_data, list) else raw_data.get("matches", raw_data.get("events", []))

        if not matches_list:
            print("No matches found in feed.")
            return

        print(f"Total {len(matches_list)} matches found from feed. Processing...")

        # সার্ভারে পাঠানোর জন্য ইভেন্ট ফরম্যাট তৈরি
        formatted_events = []
        for m in matches_list:
            # ম্যাচের সব ডাটা এবং লিংক হুবহু নেওয়া
            event_obj = {
                "title": m.get("title") or m.get("name") or f"{m.get('team1', '')} vs {m.get('team2', '')}".strip(),
                "time": m.get("time", ""),
                "date": m.get("date", ""),
                "category": m.get("category", "Cricket"),
                "status": m.get("matchStatus") or m.get("status", "LIVE"),
                "team1_logo": m.get("team1_logo") or m.get("logo1", ""),
                "team2_logo": m.get("team2_logo") or m.get("logo2", ""),
                "links": m.get("links", [])
            }
            # ফিডে আইডি থাকলে তা সংরক্ষণ
            if "id" in m:
                event_obj["id"] = m["id"]

            formatted_events.append(event_obj)

        # সার্ভারের add_events এন্ডপয়েন্টে পাঠানো
        payload = {
            "events": formatted_events,
            "requestData": generate_security_token()
        }

        target_url = BASE_URL + "admin/add_events"
        post_res = requests.post(target_url, json=payload, headers=get_headers(), timeout=25)

        print(f"Push Completed! Server Status Code: {post_res.status_code}")
        print("Server Response:", post_res.text)

    except Exception as e:
        print("Error during sync:", str(e))

if __name__ == "__main__":
    fetch_and_push_all_matches()
