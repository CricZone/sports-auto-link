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

def format_links_data(streaming_links):
    """ফিডের streaming_links থেকে linksData তৈরি করা"""
    formatted = []
    if not streaming_links or not isinstance(streaming_links, list):
        return formatted

    for idx, item in enumerate(streaming_links):
        if not isinstance(item, dict):
            continue

        name = item.get("name") or f"Server {idx + 1}"
        url = item.get("link") or item.get("url") or ""

        # যদি URL এর ভেতরেই |user-agent= থাকে তা হ্যান্ডেল করা
        ua = "Mozilla/5.0"
        if "|user-agent=" in url:
            parts = url.split("|user-agent=")
            url = parts[0]
            ua = parts[1]

        if url and str(url).startswith("http"):
            formatted.append({
                "name": name.strip(),
                "url": url.strip(),
                "stream_url": url.strip(),
                "headers": {"User-Agent": ua},
                "user_agent": ua,
                "type": "mpd" if ".mpd" in url.lower() else ("m3u8" if ".m3u8" in url.lower() else "stream")
            })
    return formatted

def sync_manual_events():
    my_events = get_my_saved_events()
    print(f"Total Events in Panel: {len(my_events)}")
    if not my_events:
        return

    try:
        res = requests.get(FEED_SOURCE, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        if res.status_code != 200:
            print("Feed fetch failed:", res.status_code)
            return
        live_feed = res.json()
    except Exception as e:
        print("Feed load error:", e)
        return

    print(f"Total Matches in Feed: {len(live_feed)}")

    # ফিডের ম্যাচগুলো ইনডেক্সিং
    indexed_feed = []
    for f in live_feed:
        t_a = clean_name(f.get("teamAName") or f.get("teamA") or "")
        t_b = clean_name(f.get("teamBName") or f.get("teamB") or "")
        e_n = clean_name(f.get("eventName") or "")
        links = f.get("streaming_links") or f.get("links") or []

        if links:
            indexed_feed.append({
                "teamA": t_a,
                "teamB": t_b,
                "eventName": e_n,
                "raw_teamA": f.get("teamAName") or f.get("teamA"),
                "raw_teamB": f.get("teamBName") or f.get("teamB"),
                "streaming_links": links
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

        my_a = clean_name(ev_data.get("teamAName") or item_db.get("teamAName"))
        my_b = clean_name(ev_data.get("teamBName") or item_db.get("teamBName"))

        # যদি প্যানেলে দলের নাম ডামি থাকে তবে স্কিপ করবে
        if not my_a or my_a in ["teama", "livematch"]:
            continue

        matched_match = None
        for inf in indexed_feed:
            # দুই দলের নামের সাথে মিল যাচাই
            cond_a = my_a and len(my_a) >= 3 and (my_a in inf["teamA"] or inf["teamA"] in my_a)
            cond_b = my_b and len(my_b) >= 3 and (my_b in inf["teamB"] or inf["teamB"] in my_b)

            if cond_a or cond_b:
                matched_match = inf
                break

        if not matched_match:
            continue

        formatted_links = format_links_data(matched_match["streaming_links"])
        if not formatted_links:
            continue

        print(f"\nUPDATING -> ID: {event_id} | Panel: [{ev_data.get('teamAName')} vs {ev_data.get('teamBName')}]")
        print(f"Matched with Feed: [{matched_match['raw_teamA']} vs {matched_match['raw_teamB']}]")

        event_str = item_db["event"] if ("event" in item_db and isinstance(item_db["event"], str)) else json.dumps(ev_data)
        if not links_path:
            links_path = str(ev_data.get("links") or ev_data.get("linksPath") or "")

        # Smali b0.smali এর মেথড X এর পে-লোড
        payload = {
            "id": str(event_id),
            "event": event_str,
            "linksPath": links_path,
            "linksData": json.dumps(formatted_links),
            "requestData": generate_security_token()
        }

        try:
            up_res = requests.post(BASE_URL + "admin/update_event", json=payload, headers=get_headers(), timeout=12)
            print(f"Server Status: {up_res.status_code} | Links Added: {len(formatted_links)}")
            print(f"Server Response: {up_res.text[:100]}")
            if up_res.status_code == 200:
                updated_count += 1
        except Exception as e:
            print("Update failed:", e)

    print(f"\n==========================================")
    print(f"SYNC COMPLETED! Total Matches Updated: {updated_count}")
    print(f"==========================================")

if __name__ == "__main__":
    sync_manual_events()
