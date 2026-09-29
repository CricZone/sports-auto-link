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

# প্রতি রানে সর্বোচ্চ ৫টি নতুন ম্যাচ অ্যাড হবে
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
    now_dt = datetime.now(BD_TZ)
    if not date_str:
        return now_dt.astimezone(timezone.utc), now_dt

    try:
        date_str = str(date_str).strip()
        time_str = str(time_str).strip() if time_str else "00:00:00"

        parts = [int(p) for p in re.findall(r'\d+', date_str)]
        if len(parts) >= 3:
            if parts[0] > 1000:
                year, month, day = parts[0], parts[1], parts[2]
            else:
                day, month, year = parts[0], parts[1], parts[2]
        else:
            return now_dt.astimezone(timezone.utc), now_dt

        t_parts = [int(p) for p in re.findall(r'\d+', time_str)]
        hh = t_parts[0] if len(t_parts) > 0 else 0
        mm = t_parts[1] if len(t_parts) > 1 else 0
        ss = t_parts[2] if len(t_parts) > 2 else 0

        match_utc_dt = datetime(year, month, day, hh, mm, ss, tzinfo=timezone.utc)
        match_bd_dt = match_utc_dt.astimezone(BD_TZ)
        return match_utc_dt, match_bd_dt
    except Exception:
        return now_dt.astimezone(timezone.utc), now_dt

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

def add_new_events_step(live_feed, my_events):
    now_bd = datetime.now(BD_TZ)
    now_utc = datetime.now(timezone.utc)
    start_of_today_bd = now_bd.replace(hour=0, minute=0, second=0, microsecond=0)

    added_count = 0

    for feed_match in live_feed:
        if added_count >= MAX_ADD_PER_RUN:
            break

        if not isinstance(feed_match, dict):
            continue

        raw_status = str(feed_match.get("matchStatus") or feed_match.get("status") or "").lower()
        if raw_status in ["live_ended", "finished", "ended"]:
            continue

        date_val = feed_match.get("date")
        time_val = feed_match.get("time")
        match_utc_dt, match_bd_dt = parse_feed_time_to_bd(date_val, time_val)

        if match_bd_dt < start_of_today_bd:
            continue

        duration_min = 135
        if feed_match.get("end_time") and time_val:
            try:
                s_parts = [int(p) for p in re.findall(r'\d+', time_val)]
                e_parts = [int(p) for p in re.findall(r'\d+', feed_match["end_time"])]
                s_m = s_parts[0] * 60 + s_parts[1]
                e_m = e_parts[0] * 60 + e_parts[1]
                if e_m < s_m:
                    e_m += 24 * 60
                if e_m - s_m > 0:
                    duration_min = e_m - s_m
            except Exception:
                pass

        match_end_utc = match_utc_dt + timedelta(minutes=duration_min)
        if match_end_utc < now_utc:
            continue

        t_a_raw = feed_match.get("teamAName") or feed_match.get("teamA") or feed_match.get("team1") or ""
        t_b_raw = feed_match.get("teamBName") or feed_match.get("teamB") or feed_match.get("team2") or ""
        f_title = feed_match.get("eventName") or feed_match.get("name") or f"{t_a_raw} vs {t_b_raw}"

        clean_fa = clean_name(t_a_raw)
        clean_fb = clean_name(t_b_raw)
        clean_ftitle = clean_name(f_title)

        if not clean_fa and not clean_ftitle:
            continue

        already_exists = False
        for item_db in my_events:
            ev_data = item_db
            if "event" in item_db and isinstance(item_db["event"], str):
                try:
                    ev_data = json.loads(item_db["event"])
                except Exception:
                    pass

            db_a = clean_name(ev_data.get("teamAName") or item_db.get("teamAName") or ev_data.get("team1"))
            db_b = clean_name(ev_data.get("teamBName") or item_db.get("teamBName") or ev_data.get("team2"))
            db_title = clean_name(ev_data.get("eventName") or ev_data.get("tournament") or ev_data.get("title"))

            if clean_fa and clean_fb and db_a and db_b:
                if (clean_fa == db_a and clean_fb == db_b) or (clean_fa == db_b and clean_fb == db_a):
                    already_exists = True
                    break

            if clean_ftitle and db_title and clean_ftitle == db_title:
                if clean_fa and (clean_fa == db_a or clean_fa == db_b):
                    already_exists = True
                    break
                if not clean_fb:
                    already_exists = True
                    break

        if already_exists:
            continue

        links = feed_match.get("streaming_links") or feed_match.get("links") or []
        formatted_links = format_links_data(links)

        logo1 = fix_image_url(feed_match.get("teamAFlag") or feed_match.get("team1_logo"))
        logo2 = fix_image_url(feed_match.get("teamBFlag") or feed_match.get("team2_logo"))
        t_logo = fix_image_url(feed_match.get("eventLogo") or feed_match.get("tournament_logo"))
        category = feed_match.get("category") or "Football"

        unique_slug = f"links/{int(time.time() * 1000)}_{added_count}"
        end_dt = match_bd_dt + timedelta(minutes=duration_min)

        new_event_dict = {
            "visible": True,
            "isHot": False,
            "priority": 0,
            "category": category,
            "eventName": f_title,
            "eventLogo": t_logo,
            "teamAName": t_a_raw,
            "teamBName": t_b_raw,
            "teamAFlag": logo1,
            "teamBFlag": logo2,
            "date": match_bd_dt.strftime("%d/%m/%Y"),
            "time": match_bd_dt.strftime("%H:%M:%S"),
            "notiThumb": "",
            "countryCodes": "",
            "whitelistCountryCodes": "",
            "messages": "{}",
            "end_date": end_dt.strftime("%d/%m/%Y"),
            "end_time": end_dt.strftime("%H:%M:%S"),
            "links": unique_slug
        }

        links_json_str = json.dumps(formatted_links)

        insert_payload = {
            "event": json.dumps(new_event_dict),
            "links": links_json_str,
            "linksData": links_json_str,
            "linksPath": unique_slug,
            "requestData": generate_security_token()
        }

        try:
            in_res = requests.post(BASE_URL + "admin/add_event", json=insert_payload, headers=get_headers(), timeout=12)
            if in_res.status_code in [200, 201]:
                added_count += 1
                print(f"[Added Event {added_count}/{MAX_ADD_PER_RUN}] {t_a_raw} vs {t_b_raw} | Links: {len(formatted_links)}")
                # Git Commit সম্পূর্ণ হওয়ার জন্য ২.৫ সেকেন্ড বিরতি
                time.sleep(2.5)
            else:
                time.sleep(1)
        except Exception as e:
            print(f"Error adding {t_a_raw}:", e)

    return added_count

def sync_streaming_links_step(live_feed, my_events):
    indexed_feed = []
    for f in live_feed:
        t_a = clean_name(f.get("teamAName") or f.get("teamA") or "")
        t_b = clean_name(f.get("teamBName") or f.get("teamB") or "")
        links = f.get("streaming_links") or f.get("links") or []

        if links:
            indexed_feed.append({
                "teamA": t_a,
                "teamB": t_b,
                "raw_teamA": f.get("teamAName") or f.get("teamA"),
                "raw_teamB": f.get("teamBName") or f.get("teamB"),
                "streaming_links": links
            })

    updated_count = 0

    for item_db in my_events:
        event_id = item_db.get("id")

        ev_data = item_db
        if "event" in item_db and isinstance(item_db["event"], str):
            try:
                ev_data = json.loads(item_db["event"])
            except Exception:
                pass

        my_a = clean_name(ev_data.get("teamAName") or item_db.get("teamAName"))
        my_b = clean_name(ev_data.get("teamBName") or item_db.get("teamBName"))

        if not my_a or my_a in ["teama", "livematch"]:
            continue

        matched_match = None
        for inf in indexed_feed:
            both_match = (my_a == inf["teamA"] and my_b == inf["teamB"]) or (my_a == inf["teamB"] and my_b == inf["teamA"])
            single_strong_a = len(my_a) >= 5 and (my_a == inf["teamA"] or my_a == inf["teamB"])
            single_strong_b = len(my_b) >= 5 and (my_b == inf["teamA"] or my_b == inf["teamB"])

            if both_match or (single_strong_a and single_strong_b) or (single_strong_a and not inf["teamB"]):
                matched_match = inf
                break

        if not matched_match:
            continue

        formatted_links = format_links_data(matched_match["streaming_links"])
        if not formatted_links:
            continue

        links_path = str(item_db.get("linksPath") or ev_data.get("linksPath") or ev_data.get("links") or f"links/{event_id}")
        event_str = item_db["event"] if ("event" in item_db and isinstance(item_db["event"], str)) else json.dumps(ev_data)

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
                print(f"[Links Updated] ID: {event_id} | {ev_data.get('teamAName')} vs {ev_data.get('teamBName')} | Links: {len(formatted_links)}")
                updated_count += 1
        except Exception as e:
            print(f"Error updating ID {event_id}:", e)

    return updated_count

def main():
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

    # ১. নতুন ম্যাচ ৫টি অ্যাড করা
    added = add_new_events_step(live_feed, my_events)

    # ২. ডাটাবেস রিফ্রেশ
    if added > 0:
        time.sleep(2)
        my_events = get_my_saved_events()

    # ৩. সব ম্যাচের লিংক সিঙ্ক
    updated = sync_streaming_links_step(live_feed, my_events)

    print("\n==========================================")
    print(f"Finished! Added: {added} | Links Updated: {updated}")
    print("==========================================")

if __name__ == "__main__":
    main()
