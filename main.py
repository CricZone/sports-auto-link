import os
import sys
import time
import base64
from datetime import datetime, timezone, timedelta
import json
import re
import requests

BASE_URL = "https://dlsports.proapp.workers.dev/"
FEED_SOURCE = os.getenv("SECRET_FEED_SOURCE", "")

# বাংলাদেশ টাইমজোন (UTC+6)
BD_TZ = timezone(timedelta(hours=6))

# প্রতি ৫ মিনিটে সর্বোচ্চ কয়টি নতুন ম্যাচ অ্যাড হবে
MAX_ADD_PER_RUN = 5

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

def fix_image_url(url):
    if not url or not isinstance(url, str):
        return "https://i.postimg.cc/0Qs5rKL8/app-logo.png"
    url = url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        return "https://i.postimg.cc/0Qs5rKL8/app-logo.png"
    if url.startswith("http://"):
        url = "https://" + url[7:]
    if "api.sofascore.com" in url:
        url = url.replace("api.sofascore.com", "img.sofascore.com")
    return url

def parse_feed_time_to_bd(date_str, time_str):
    if not date_str:
        return None, None, None

    try:
        d_parts = date_str.replace('-', '/').split('/')
        if len(d_parts) != 3:
            return None, None, None
        
        day, month, year = int(d_parts[0]), int(d_parts[1]), int(d_parts[2])

        hh, mm, ss = 0, 0, 0
        if time_str:
            t_parts = time_str.split(':')
            hh = int(t_parts[0]) if len(t_parts) > 0 else 0
            mm = int(t_parts[1]) if len(t_parts) > 1 else 0
            ss = int(t_parts[2]) if len(t_parts) > 2 else 0

        match_utc_dt = datetime(year, month, day, hh, mm, ss, tzinfo=timezone.utc)
        match_bd_dt = match_utc_dt.astimezone(BD_TZ)

        display_time = match_bd_dt.strftime("%I:%M %p %d/%m/%Y")
        return match_utc_dt, match_bd_dt, display_time
    except Exception as e:
        return None, None, None

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
    formatted = []
    if not streaming_links or not isinstance(streaming_links, list):
        return formatted

    for idx, item in enumerate(streaming_links):
        if not isinstance(item, dict):
            continue

        name = str(item.get("name") or f"Server {idx + 1}").strip()
        url = str(item.get("link") or item.get("url") or "").strip()

        ua = "Mozilla/5.0"
        if "|user-agent=" in url:
            parts = url.split("|user-agent=")
            url = parts[0]
            ua = parts[1]

        api_key = str(item.get("api") or item.get("drmKey") or item.get("key") or item.get("license") or "").strip()
        token_api = str(item.get("tokenApi") or "").strip()

        if url.startswith("http"):
            is_mpd = ".mpd" in url.lower()
            formatted.append({
                "name": name,
                "link": url,
                "url": url,
                "stream_url": url,
                "headers": {"User-Agent": ua},
                "user_agent": ua,
                "type": "mpd" if is_mpd else "m3u8",
                "api": api_key,
                "tokenApi": token_api,
                "key": api_key,
                "drmKey": api_key
            })
    return formatted

def sync_and_auto_add_events():
    if not FEED_SOURCE:
        print("Error: SECRET_FEED_SOURCE environment variable is not configured.")
        return

    my_events = get_my_saved_events()
    print(f"Total Events currently in Panel: {len(my_events)}")

    try:
        res = requests.get(FEED_SOURCE, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        if res.status_code != 200:
            print("Feed fetch failed:", res.status_code)
            return
        live_feed = res.json()
    except Exception as e:
        print("Feed load error:", e)
        return

    print(f"Total Matches found in Feed: {len(live_feed)}")

    now_bd = datetime.now(BD_TZ)
    now_utc = datetime.now(timezone.utc)
    start_of_today_bd = now_bd.replace(hour=0, minute=0, second=0, microsecond=0)

    updated_count = 0
    added_count = 0

    for feed_match in live_feed:
        if not isinstance(feed_match, dict):
            continue

        raw_status = str(feed_match.get("matchStatus") or feed_match.get("status") or "").lower()
        if raw_status in ["live_ended", "finished", "ended"]:
            continue

        date_val = feed_match.get("date")
        time_val = feed_match.get("time")
        match_utc_dt, match_bd_dt, display_time = parse_feed_time_to_bd(date_val, time_val)

        if not match_bd_dt:
            continue

        # ১. অতীত ম্যাচ বাদ
        if match_bd_dt < start_of_today_bd:
            continue

        # ২. খেলা শেষ হয়ে গেলে বাদ (ডিলিটের পর যাতে ফিরে না আসে)
        duration_min = 135
        if feed_match.get("end_time") and time_val:
            try:
                s_parts = [int(p) for p in time_val.split(':')]
                e_parts = [int(p) for p in feed_match["end_time"].split(':')]
                s_m = s_parts[0] * 60 + s_parts[1]
                e_m = e_parts[0] * 60 + e_parts[1]
                if e_m < s_m:
                    e_m += 24 * 60
                if e_m - s_m > 0:
                    duration_min = e_m - s_m
            except:
                pass

        match_end_utc = match_utc_dt + timedelta(minutes=duration_min)
        if match_end_utc < now_utc:
            continue

        t_a_raw = feed_match.get("teamAName") or feed_match.get("teamA") or feed_match.get("team1") or "Team 1"
        t_b_raw = feed_match.get("teamBName") or feed_match.get("teamB") or feed_match.get("team2") or "Team 2"
        f_title = feed_match.get("eventName") or feed_match.get("name") or f"{t_a_raw} vs {t_b_raw}"

        clean_fa = clean_name(t_a_raw)
        clean_fb = clean_name(t_b_raw)
        clean_ftitle = clean_name(f_title)

        # ৩. বিদ্যমান ম্যাচ চেক
        matched_db_item = None
        for item_db in my_events:
            ev_data = item_db
            if "event" in item_db and isinstance(item_db["event"], str):
                try:
                    ev_data = json.loads(item_db["event"])
                except:
                    pass

            db_a = clean_name(ev_data.get("teamAName") or item_db.get("teamAName") or ev_data.get("team1"))
            db_b = clean_name(ev_data.get("teamBName") or item_db.get("teamBName") or ev_data.get("team2"))
            db_title = clean_name(ev_data.get("eventName") or ev_data.get("tournament") or ev_data.get("title"))

            both_match = (clean_fa == db_a and clean_fb == db_b) or (clean_fa == db_b and clean_fb == db_a)
            title_match = clean_ftitle and db_title and (clean_ftitle == db_title)

            if both_match or (title_match and (clean_fa in [db_a, db_b])):
                matched_db_item = item_db
                break

        # ৪. ম্যাচ বিদ্যমান থাকলে স্ট্রিমিং লিংক আপডেট
        if matched_db_item:
            links = feed_match.get("streaming_links") or feed_match.get("links") or []
            formatted_links = format_links_data(links)
            if not formatted_links:
                continue

            event_id = matched_db_item.get("id")
            links_path = str(matched_db_item.get("linksPath") or f"links/{event_id}")
            event_str = matched_db_item["event"] if ("event" in matched_db_item and isinstance(matched_db_item["event"], str)) else json.dumps(matched_db_item)

            payload = {
                "id": str(event_id),
                "event": event_str,
                "linksPath": links_path,
                "linksData": json.dumps(formatted_links),
                "requestData": generate_security_token()
            }
            try:
                up_res = requests.post(BASE_URL + "admin/update_event", json=payload, headers=get_headers(), timeout=12)
                if up_res.status_code == 200:
                    print(f"[Updated Links] {t_a_raw} vs {t_b_raw}")
                    updated_count += 1
            except Exception as e:
                print(f"Error updating links for {t_a_raw}:", e)

        # ৫. নতুন ম্যাচ অ্যাড করা (প্রতি সাইকেলে সর্বোচ্চ ৫টি)
        else:
            if added_count >= MAX_ADD_PER_RUN:
                # ৫টি ম্যাচ ইতিমধ্যে অ্যাড হয়ে গেলে এই সাইকেলে আর নতুন ম্যাচ অ্যাড হবে না
                continue

            links = feed_match.get("streaming_links") or feed_match.get("links") or []
            formatted_links = format_links_data(links)

            logo1 = fix_image_url(feed_match.get("teamAFlag") or feed_match.get("team1_logo"))
            logo2 = fix_image_url(feed_match.get("teamBFlag") or feed_match.get("team2_logo"))
            t_logo = fix_image_url(feed_match.get("eventLogo") or feed_match.get("tournament_logo"))
            category = feed_match.get("category") or "Football"

            new_event_dict = {
                "eventName": f_title,
                "title": f_title,
                "tournament": f_title,
                "category": category,
                "categoryLogo": t_logo,
                "eventLogo": t_logo,
                "tournament_logo": t_logo,
                "teamAName": t_a_raw,
                "teamBName": t_b_raw,
                "team1": t_a_raw,
                "team2": t_b_raw,
                "teamAFlag": logo1,
                "teamBFlag": logo2,
                "logo1": logo1,
                "logo2": logo2,
                "time": display_time,
                "date": match_bd_dt.strftime("%d/%m/%Y"),
                "duration": str(duration_min),
                "matchStatus": "upcoming",
                "visible": True
            }

            insert_payload = {
                "from": "events",
                "event": json.dumps(new_event_dict),
                "linksData": json.dumps(formatted_links),
                "requestData": generate_security_token()
            }

            try:
                in_res = requests.post(BASE_URL + "admin/add_event", json=insert_payload, headers=get_headers(), timeout=12)
                if in_res.status_code in [200, 201]:
                    added_count += 1
                    print(f"[{added_count}/{MAX_ADD_PER_RUN} Added] {t_a_raw} vs {t_b_raw} | {display_time}")
                else:
                    print(f"Failed to add {t_a_raw}, status: {in_res.status_code}")
            except Exception as e:
                print(f"Error adding {t_a_raw}:", e)

    print(f"\nCycle Completed -> Added: {added_count} | Links Updated: {updated_count}")

if __name__ == "__main__":
    while True:
        current_time = datetime.now(BD_TZ).strftime("%I:%M:%S %p")
        print(f"\n==========================================")
        print(f"Running Sync at {current_time} (BD Time)")
        print(f"==========================================")
        
        sync_and_auto_add_events()
        
        print("\nSleeping for 5 minutes (300 seconds)...")
        time.sleep(300)
