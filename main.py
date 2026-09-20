import base64
from datetime import datetime
import json
import requests

# ব্যাকএন্ড ও সোর্স লিঙ্ক
BASE_URL = "https://dlsports.proapp.workers.dev/"
FEED_SOURCE = "https://s1.noobon.top/axsx/streamx.php"

def generate_security_token():
    """অ্যাডমিন অ্যাপের সিকিউরিটি টোকেন জেনারেটর (Base64 -> Rev -> Hex -> Rev)"""
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

def get_my_events():
    """আপনার সার্ভারে পূর্বে অ্যাড করা ম্যাচগুলোর লিস্ট আনা"""
    payload = {"requestData": generate_security_token()}
    try:
        res = requests.post(BASE_URL + "admin/select", json=payload, headers=get_headers(), timeout=15)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, dict):
                return data.get("events", [])
            elif isinstance(data, list):
                return data
    except Exception as e:
        print("Error fetching your events:", e)
    return []

def get_live_stream_feed():
    """সোর্স ফিড থেকে চলমান ম্যাচের লাইভ স্ট্রিম লিঙ্ক সংগ্রহ করা"""
    try:
        res = requests.get(FEED_SOURCE, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        if res.status_code == 200:
            data = res.json()
            return data if isinstance(data, list) else data.get("matches", [])
    except Exception as e:
        print("Error fetching feed:", e)
    return []

def sync_links():
    my_events = get_my_events()
    if not my_events:
        print("আপনার প্যানেলে বর্তমানে কোনো ইভেন্ট অ্যাড করা নেই।")
        return

    live_feed = get_live_stream_feed()
    if not live_feed:
        print("সোর্স ফিড থেকে কোনো ডেটা পাওয়া যায়নি।")
        return

    print(f"Total Saved Events: {len(my_events)}, Feed Items: {len(live_feed)}")

    # আপনার প্রতিটা ম্যাচ চেক করা
    for event in my_events:
        event_name = str(event.get("title", "") or event.get("name", "")).strip().lower()
        event_id = event.get("id")

        if not event_name or not event_id:
            continue

        # ফিডের ম্যাচের নামের সাথে মিলিয়ে দেখা
        for item in live_feed:
            feed_name = str(item.get("title", "") or item.get("name", "")).strip().lower()
            links = item.get("links", [])

            # নাম আংশিক মিললে এবং লিংকের সন্ধান পেলে
            if (feed_name in event_name or event_name in feed_name) and links:
                print(f"Found active stream for [{event_name}]! Updating links...")

                update_payload = {
                    "id": event_id,
                    "links": links,
                    "requestData": generate_security_token()
                }

                up_res = requests.post(
                    BASE_URL + "admin/update_event",
                    json=update_payload,
                    headers=get_headers(),
                    timeout=15
                )

                print(f"Result for [{event_name}]: {up_res.status_code}")
                break

if __name__ == "__main__":
    sync_links()
