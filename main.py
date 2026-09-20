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
                return data.get("events") or data.get("live_events") or data.get("data") or []
            elif isinstance(data, list):
                return data
    except Exception as e:
        print("Error fetching saved events:", e)
    return []

def format_links_data(raw_links):
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
        print("No events found in DB.")
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

    for item_db in my_events:
        event_id = item_db.get("id")
        links_path = str(item_db.get("linksPath") or item_db.get("links") or "")
        
        # 'event' অবজেক্টটি স্ট্রিং আকারে থাকলে পার্স করা
        ev_data = item_db
        if "event" in item_db and isinstance(item_db["event"], str):
            try:
                ev_data = json.loads(item_db["event"])
            except:
                pass

        event_name = str(ev_data.get("eventName") or ev_data.get("title") or item_db.get("eventName") or "").strip()
        team_a = str(ev_data.get("teamAName") or ev_data.get("team1") or "").strip()
        team_b = str(ev_data.get("teamBName") or ev_data.get("team2") or "").strip()

        print(f"\n--- Checking Saved Event ---")
        print(f"ID: {event_id} | Name: '{event_name}' | TeamA: '{team_a}' | TeamB: '{team_b}'")

        matched_feed = None
        for f in live_feed:
            f_name = str(f.get("title") or f.get("name") or "").strip()
            
            # নামের মিল যাচাই
            cond1 = f_name and event_name and (f_name.lower() in event_name.lower() or event_name.lower() in f_name.lower())
            cond2 = team_a and team_a.lower() in f_name.lower()
            cond3 = team_b and team_b.lower() in f_name.lower()

            if cond1 or cond2 or cond3:
                matched_feed = f
                print(f"-> MATCHED with Feed: '{f_name}'")
                break

        if not matched_feed:
            print(f"-> No match found in feed for this event.")
            continue

        raw_links = matched_feed.get("links", [])
        if not raw_links:
            print("-> Match found, but feed links are empty.")
            continue

        formatted_links = format_links_data(raw_links)
        links_data_str = json.dumps(formatted_links)

        # সার্ভারে আসল স্ট্রাকচারে পাঠানো
        event_str = item_db["event"] if ("event" in item_db and isinstance(item_db["event"], str)) else json.dumps(ev_data)
        if not links_path:
            links_path = str(ev_data.get("links") or ev_data.get("linksPath") or "")

        payload = {
            "id": str(event_id),
            "event": event_str,
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

        print(f"Update Result Status: {up_res.status_code}")
        print(f"Server Response Text: {up_res.text}")

if __name__ == "__main__":
    sync_manual_events()
