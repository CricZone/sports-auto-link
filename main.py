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

def clean_word(word):
    """টিমের সাধারণ শব্দ বাদ দিয়ে মূল নাম বের করা"""
    w = str(word).lower()
    w = re.sub(r'\b(fc|cf|sc|united|city|club|women)\b', '', w)
    return re.sub(r'[^a-zA-Z0-9]', '', w).strip()

def get_my_saved_events():
    token = generate_security_token()
    payload = {
        "from": "events",
        "requestData": token
    }
    try:
        res = requests.post(BASE_URL + "admin/select", json=payload, headers=get_headers(), timeout=15)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                return data.get("events") or data.get("data") or []
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
    print(f"Total Manually Added Events in Panel: {len(my_events)}")

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

    print(f"Total Matches in Online Feed: {len(live_feed)}")

    for item_db in my_events:
        event_id = item_db.get("id")
        links_path = str(item_db.get("linksPath") or item_db.get("links") or "")
        
        ev_data = item_db
        if "event" in item_db and isinstance(item_db["event"], str):
            try:
                ev_data = json.loads(item_db["event"])
            except:
                pass

        event_name = str(ev_data.get("eventName") or item_db.get("eventName") or "").strip()
        team_a = str(ev_data.get("teamAName") or item_db.get("teamAName") or "").strip()
        team_b = str(ev_data.get("teamBName") or item_db.get("teamBName") or "").strip()

        core_a = clean_word(team_a)
        core_b = clean_word(team_b)

        matched_feed = None
        for f in live_feed:
            f_title = str(f.get("title") or f.get("name") or "").lower()
            
            # ফিডে দুই দলের নাম অথবা অন্তত মূল দলের নাম থাকলে ম্যাচ ধরবে
            cond_a = core_a and len(core_a) >= 3 and core_a in f_title
            cond_b = core_b and len(core_b) >= 3 and core_b in f_title
            
            if (cond_a and cond_b) or cond_a or cond_b:
                matched_feed = f
                break

        if not matched_feed:
            continue

        raw_links = matched_feed.get("links", [])
        if not raw_links:
            continue

        formatted_links = format_links_data(raw_links)
        if not formatted_links:
            continue

        print(f"-> MATCHED: [{team_a} vs {team_b}] with Feed: [{matched_feed.get('title')}]")
        links_data_str = json.dumps(formatted_links)

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

        print(f"Update Result Status: {up_res.status_code} | Links Added: {len(formatted_links)}")

if __name__ == "__main__":
    sync_manual_events()
