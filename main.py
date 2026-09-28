import os
import sys
import base64
from datetime import datetime, timezone, timedelta
import json
import re
import time
import requests

BASE_URL = "https://dlsports.proapp.workers.dev/"
FEED_SOURCE = os.getenv("SECRET_FEED_SOURCE", "")
MAX_ADD_PER_RUN = 5  # প্রতি রানে সর্বোচ্চ ৫টি নতুন ইভেন্ট অ্যাড হবে

# বাংলাদেশ টাইমজোন (UTC+6)
BD_TZ = timezone(timedelta(hours=6))

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

def parse_match_time(raw_val):
    if not raw_val:
        return None
    try:
        now_bd = datetime.now(BD_TZ)
        val_str = str(raw_val).strip()

        if "t" in val_str.lower():
            clean_iso = val_str.replace("Z", "+00:00").replace("z", "+00:00")
            dt = datetime.fromisoformat(clean_iso)
            return dt.astimezone(BD_TZ)

        if val_str.isdigit() or (val_str.replace('.', '', 1).isdigit() and len(val_str) >= 10):
            ts = float(val_str)
            if ts > 1e11:
                ts /= 1000
            return datetime.fromtimestamp(ts, tz=BD_TZ)

        formats = [
            "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %I:%M %p", "%Y-%m-%d %H:%M",
            "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %I:%M %p", "%d-%m-%Y %H:%M",
            "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %I:%M %p", "%d/%m/%Y %H:%M",
            "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(val_str, fmt)
                return dt.replace(tzinfo=BD_TZ)
            except ValueError:
                pass

        time_formats = ["%I:%M %p", "%H:%M", "%I:%M%p"]
        for t_fmt in time_formats:
            try:
                t_dt = datetime.strptime(val_str, t_fmt)
                return now_bd.replace(hour=t_dt.hour, minute=t_dt.minute, second=0, microsecond=0)
            except ValueError:
                pass
    except Exception:
        pass
    return None

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

def sync_manual_events():
    if not FEED_SOURCE:
        print("Error: SECRET_FEED_SOURCE environment variable is not configured.")
        return

    my_events = get_my_saved_events()
    print(f"Total Events in Panel: {len(my_events)}")

    valid_ids = [int(item['id']) for item in my_events if str(item.get('id', '')).isdigit()]
    max_id = max(valid_ids) if valid_ids else 1200

    valid_orders = [int(item['order_index']) for item in my_events if str(item.get('order_index', '')).lstrip('-').isdigit()]
    max_order = max(valid_orders) if valid_orders else 0

    try:
        res = requests.get(FEED_SOURCE, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        if res.status_code != 200:
            print("Feed fetch failed:", res.status_code)
            return
        live_feed = res.json()
        if isinstance(live_feed, dict):
            live_feed = live_feed.get("matches") or live_feed.get("events") or live_feed.get("data") or []
    except Exception as e:
        print("Feed load error:", e)
        return

    print(f"Total Matches in Feed: {len(live_feed)}")

    # বাংলাদেশ সময় অনুযায়ী আজকের শুরু (রাত ১২:০০ AM)
    now_bd = datetime.now(BD_TZ)
    today_start_bd = now_bd.replace(hour=0, minute=0, second=0, microsecond=0)

    existing_teams = []
    for item in my_events:
        ev_data = item
        if "event" in item and isinstance(item["event"], str):
            try:
                ev_data = json.loads(item["event"])
            except Exception:
                pass
        t_a = clean_name(ev_data.get("teamAName") or item.get("teamAName"))
        t_b = clean_name(ev_data.get("teamBName") or item.get("teamBName"))
        if t_a and t_b:
            existing_teams.append((t_a, t_b))

    # ====================================================
    # ১. নতুন ইভেন্ট অটো-অ্যাড (অ্যাপের ফরম্যাট অনুযায়ী)
    # ====================================================
    added_count = 0
    for f in live_feed:
        if added_count >= MAX_ADD_PER_RUN:
            break

        f_raw_a = f.get("teamAName") or f.get("teamA") or f.get("team1") or ""
        f_raw_b = f.get("teamBName") or f.get("teamB") or f.get("team2") or ""
        t_a = clean_name(f_raw_a)
        t_b = clean_name(f_raw_b)

        if not t_a or not t_b:
            continue

        already_exists = any(
            (t_a == ex[0] and t_b == ex[1]) or (t_a == ex[1] and t_b == ex[0])
            for ex in existing_teams
        )
        if already_exists:
            continue

        raw_date = str(f.get("date") or "").strip()
        raw_time = str(f.get("time") or f.get("start_time") or "").strip()
        if raw_date and raw_time and raw_date not in raw_time:
            match_time_raw = f"{raw_date} {raw_time}"
        else:
            match_time_raw = raw_time or raw_date

        match_dt = parse_match_time(match_time_raw)

        # অতীতের ম্যাচ হলে বাদ
        if match_dt and match_dt < today_start_bd:
            continue

        links = f.get("streaming_links") or f.get("links") or []
        formatted_links = format_links_data(links)

        new_event_id = str(max_id + 1 + added_count)
        new_order_index = max_order + 1 + added_count

        # ক্যাটাগরি নির্ধারণ
        raw_cat = str(f.get("category") or f.get("sport") or "").lower()
        if "motor" in raw_cat or "racing" in raw_cat or "f1" in raw_cat:
            category_name = "Motorsports"
        elif "american" in raw_cat or "nfl" in raw_cat:
            category_name = "American football"
        else:
            category_name = "Football"

        tournament_name = f.get("tournament") or f.get("league") or "International Friendly Games"
        
        # অ্যাপের সাথে হুবহু মিল রেখে ডেট-টাইম তৈরি
        date_iso = match_dt.strftime("%Y-%m-%d") if match_dt else now_bd.strftime("%Y-%m-%d")
        time_full = match_dt.strftime("%Y-%m-%d %H:%M:%S") if match_dt else f"{date_iso} 20:00:00"

        # অ্যাপের নমুনা ডাটাবেস অবজেক্ট
        event_body = {
            "teamAName": f_raw_a,
            "teamBName": f_raw_b,
            "teamAFlag": f.get("teamAFlag") or f.get("team1_logo") or f.get("logo1") or "",
            "teamBFlag": f.get("teamBFlag") or f.get("team2_logo") or f.get("logo2") or "",
            "match_title": tournament_name,
            "category": category_name,
            "time": time_full,
            "date": date_iso,
            "status": "Not Started",
            "links": formatted_links
        }

        payload = {
            "from": "events",
            "requestData": generate_security_token(),
            "id": new_event_id,
            "event": json.dumps(event_body),
            "links": f"links/{new_event_id}",
            "order_index": new_order_index,
            "linksPath": f"links/{new_event_id}",
            "linksData": json.dumps(formatted_links)
        }

        try:
            add_res = requests.post(BASE_URL + "admin/add_event", json=payload, headers=get_headers(), timeout=12)
            if add_res.status_code == 200:
                print(f"[Auto-Added Successfully] ID: {new_event_id} | {f_raw_a} vs {f_raw_b}")
                existing_teams.append((t_a, t_b))
                added_count += 1
                time.sleep(3)
            else:
                print(f"[Add Failed] Status: {add_res.status_code} | Msg: {add_res.text[:120]}")
        except Exception as e:
            print(f"Error adding {f_raw_a} vs {f_raw_b}:", e)

    print(f"Total new events added in this run: {added_count}")

    # ====================================================
    # ২. বিদ্যমান ম্যাচগুলোর লাইভ লিংক আপডেট
    # ====================================================
    indexed_feed = []
    for f in live_feed:
        t_a = clean_name(f.get("teamAName") or f.get("teamA") or f.get("team1") or "")
        t_b = clean_name(f.get("teamBName") or f.get("teamB") or f.get("team2") or "")
        links = f.get("streaming_links") or f.get("links") or []

        if links:
            indexed_feed.append({
                "teamA": t_a,
                "teamB": t_b,
                "streaming_links": links
            })

    updated_count = 0
    current_my_events = get_my_saved_events()

    for item_db in current_my_events:
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

            if both_match or (single_strong_a and single_strong_b):
                matched_match = inf
                break

        if not matched_match:
            continue

        formatted_links = format_links_data(matched_match["streaming_links"])
        if not formatted_links:
            continue

        # ইভেন্টের ভেতরে লিংক আপডেট
        if isinstance(ev_data, dict):
            ev_data["links"] = formatted_links
            event_str = json.dumps(ev_data)
        else:
            event_str = item_db.get("event")

        links_path = str(item_db.get("links") or item_db.get("linksPath") or f"links/{event_id}")

        payload = {
            "from": "events",
            "id": str(event_id),
            "event": event_str,
            "links": links_path,
            "linksPath": links_path,
            "linksData": json.dumps(formatted_links),
            "requestData": generate_security_token()
        }

        try:
            up_res = requests.post(BASE_URL + "admin/update_event", json=payload, headers=get_headers(), timeout=12)
            if up_res.status_code == 200:
                print(f"[Updated Links] ID: {event_id} | {ev_data.get('teamAName')} vs {ev_data.get('teamBName')} | Links: {len(formatted_links)}")
                updated_count += 1
        except Exception as e:
            print(f"Error updating ID {event_id}:", e)

    print(f"\nAll operations finished. Total Added: {added_count}, Total Updated: {updated_count}")

if __name__ == "__main__":
    sync_manual_events()
