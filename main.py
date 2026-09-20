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

def clean_name(val):
    if not val:
        return ""
    w = str(val).lower()
    w = re.sub(r'\b(fc|cf|sc|united|city|club|women|vs|v)\b', '', w)
    return re.sub(r'[^a-z0-9]', '', w).strip()

def get_my_saved_events():
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
        print("Error fetching saved events:", e)
    return []

def format_links_data(raw_links):
    formatted = []
    if not raw_links or not isinstance(raw_links, list):
        return formatted

    for idx, item in enumerate(raw_links):
        if isinstance(item, dict):
            name = item.get("name") or item.get("title") or f"Server {idx + 1}"
            url = item.get("url") or item.get("link") or item.get("stream_url") or ""
            headers_dict = item.get("headers") or {"User-Agent": item.get("user_agent") or "Mozilla/5.0"}
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
    print(f"Total Manually Added Events: {len(my_events)}")
    if not my_events:
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

    print(f"Total Matches in Feed: {len(live_feed)}")

    # ফিডের ম্যাচগুলো দ্রুত মেলাতে ইনডেক্স করা
    valid_feed = []
    for f in live_feed:
        title = str(f.get("title") or f.get("name") or "")
        links = f.get("links", [])
        if title and links:
            valid_feed.append({
                "raw_title": title,
                "clean_title": clean_name(title),
                "links": links
            })

    updated_count = 0

    for item_db in my_events:
        event_id = item_db.get("id")
        links_path = str(item_db.get("linksPath") or item_db.get("links") or "")

        ev_data = item_db
        if "event" in item_db and isinstance(item_db["event"], str):
            try:
                ev_data = json.loads(item_db["event"])
            except:
                pass

        t_a = clean_name(ev_data.get("teamAName") or item_db.get("teamAName"))
        t_b = clean_name(ev_data.get("teamBName") or item_db.get("teamBName"))
        ev_n = clean_name(ev_data.get("eventName") or item_db.get("eventName"))

        matched_item = None
        for vf in valid_feed:
            c_title = vf["clean_title"]
            # দলের নাম অথবা ইভেন্টের নামের মিল চেক
            if (t_a and len(t_a) >= 3 and t_a in c_title) or (t_b and len(t_b) >= 3 and t_b in c_title):
                matched_item = vf
                break
            elif ev_n and len(ev_n) >= 4 and ev_n in c_title:
                matched_item = vf
                break

        if not matched_item:
            continue

        formatted_links = format_links_data(matched_item["links"])
        if not formatted_links:
            continue

        print(f"\nUPDATING -> ID: {event_id} | Matched With: {matched_item['raw_title']}")

        event_str = item_db["event"] if ("event" in item_db and isinstance(item_db["event"], str)) else json.dumps(ev_data)
        if not links_path:
            links_path = str(ev_data.get("links") or ev_data.get("linksPath") or "")

        payload = {
            "id": str(event_id),
            "event": event_str,
            "linksPath": links_path,
            "linksData": json.dumps(formatted_links),
            "requestData": generate_security_token()
        }

        try:
            up_res = requests.post(BASE_URL + "admin/update_event", json=payload, headers=get_headers(), timeout=10)
            print(f"Status: {up_res.status_code} | Server Msg: {up_res.text[:100]} | Links: {len(formatted_links)}")
            if up_res.status_code == 200:
                updated_count += 1
        except Exception as err:
            print("Update error:", err)

    print(f"\nDone! Total Events Updated: {updated_count}")

if __name__ == "__main__":
    sync_manual_events()
