import base64
from datetime import datetime
import json
import re
import requests

BASE_URL = "https://dlsports.proapp.workers.dev/"
FEED_SOURCE = "https://s1.noobon.top/axsx/streamx.php"

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
    """MainWindow ক্লাসের লজিক অনুযায়ী from: app দিয়ে ম্যাচ ডেটা আনা"""
    token = generate_security_token()
    payload = {
        "from": "app",
        "requestData": token
    }
    try:
        res = requests.post(BASE_URL + "admin/select", json=payload, headers=get_headers(), timeout=15)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, dict):
                # events অ্যারে বা মূল তালিকা খুঁজে বের করা
                return data.get("events") or data.get("live_events") or data.get("data") or []
            elif isinstance(data, list):
                return data
    except Exception as e:
        print("Error fetching saved events:", e)
    return []

def format_links_data(raw_links):
    """প্লেয়ার যে ফরম্যাটে linksData রিসিভ করে"""
    formatted = []
    if not raw_links:
        return formatted

    if isinstance(raw_links, list):
        for idx, item in enumerate(raw_links):
            if isinstance(item, dict):
                name = item.get("name") or item.get("title") or f"Server {idx + 1}"
                url = item.get("url") or item.get("link") or item.get("stream_url") or ""
                ua = item.get("user_agent") or item.get("headers", {}).get("User-Agent") or "Mozilla/5.0"
                headers_dict = item.get("headers") or {"User-Agent": ua}
            else:
                name = f"Live Stream {idx + 1}"
                url = str(item)
                headers_dict = {"User-Agent": "Mozilla/5.0"}

            if url and str(url).startswith("http"):
                formatted.append({
                    "name": name,
                    "url": url,
                    "stream_url": url,
                    "headers": headers_dict,
                    "user_agent": "Mozilla/5.0",
                    "type": "m3u8" if ".m3u8" in str(url).lower() else "stream"
                })
    return formatted

def sync_manual_events():
    my_events = get_my_saved_events()
    print(f"Total Manually Added Events Found: {len(my_events)}")

    if not my_events:
        print("কোনো ইভেন্ট পাওয়া যায়নি। প্যানেলে ম্যাচ তৈরি করা আছে কি না যাচাই করুন।")
        return

    try:
        res = requests.get(FEED_SOURCE, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        if res.status_code != 200:
            print("Feed fetch failed:", res.status_code)
            return

        raw_data = res.json()
        live_feed = raw_data if isinstance(raw_data, list) else raw_data.get("matches", raw_data.get("events", []))
    except Exception as e:
        print("Feed load error:", e)
        return

    for event in my_events:
        event_name = str(event.get("eventName") or event.get("title") or event.get("name") or "").strip().lower()
        team_a = str(event.get("teamAName") or event.get("team1") or "").strip().lower()
        team_b = str(event.get("teamBName") or event.get("team2") or "").strip().lower()
        event_id = event.get("id")
        links_path = str(event.get("linksPath") or event.get("links") or "")

        if not event_id:
            continue

        for item in live_feed:
            feed_name = str(item.get("title") or item.get("name") or "").strip().lower()
            raw_links = item.get("links", [])

            # দলের নাম অথবা টাইটেল দিয়ে মিল যাচাই
            is_matched = False
            if feed_name and event_name and (feed_name in event_name or event_name in feed_name):
                is_matched = True
            elif team_a and team_a in feed_name:
                is_matched = True

            if is_matched and raw_links:
                formatted_links = format_links_data(raw_links)
                if not formatted_links:
                    continue

                links_data_str = json.dumps(formatted_links)

                # b0 ক্লাসের মেথড X এর স্ট্রাকচার
                payload = {
                    "id": str(event_id),
                    "event": json.dumps(event) if isinstance(event, dict) else str(event),
                    "linksPath": links_path,
                    "linksData": links_data_str,
                    "requestData": generate_security_token()
                }

                up_res = requests.post(
                    BASE_URL + "admin/update_event",
                    json=payload,
                    headers=get_headers(),
                    timeout=15
                )

                print(f"Updated Event [{event_name}] | Status: {up_res.status_code} | Links: {len(formatted_links)}")
                break

if __name__ == "__main__":
    sync_manual_events()
