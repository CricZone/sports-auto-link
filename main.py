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

# আপকামিং ম্যাচ প্রতি রানে ধাপে ধাপে অ্যাড হওয়ার সীমা
MAX_UPCOMING_ADD_PER_RUN = 6

# Finished ট্যাবে সবসময় সাম্প্রতিক ১২টি সমাপ্ত ম্যাচ থাকবে
KEEP_FINISHED_LIMIT = 12

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

def is_feed_match_ended(feed_match):
    if not feed_match or not isinstance(feed_match, dict):
        return False
    status_values = [
        feed_match.get("matchStatus"),
        feed_match.get("match_status"),
        feed_match.get("status"),
        feed_match.get("state"),
        feed_match.get("matchStatusLabel"),
        feed_match.get("statusLabel")
    ]
    for st in status_values:
        if st is not None:
            s_clean = str(st).lower().strip()
            if s_clean in ["finished", "finish", "ended", "end", "completed", "complete", "closed", "cancelled", "canceled", "live_ended"]:
                return True
    return False

# ফিডের টাইম সঠিকভাবে UTC-তে রূপান্তর
def parse_feed_utc_dt(date_str, time_str):
    now_utc = datetime.now(timezone.utc)
    if not date_str:
        return now_utc

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
            return now_utc

        t_parts = [int(p) for p in re.findall(r'\d+', time_str)]
        hh = t_parts[0] if len(t_parts) > 0 else 0
        mm = t_parts[1] if len(t_parts) > 1 else 0
        ss = t_parts[2] if len(t_parts) > 2 else 0

        lower_t = time_str.lower()
        if "pm" in lower_t and hh < 12:
            hh += 12
        elif "am" in lower_t and hh == 12:
            hh = 0

        # Feed এর সময় থেকে UTC হিসাব
        dt_local = datetime(year, month, day, hh, mm, ss, tzinfo=timezone.utc)
        return dt_local
    except Exception:
        return now_utc

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

# ১. ডুপ্লিকেট ম্যাচ পরিষ্কার করা
def remove_duplicate_events_step(my_events):
    seen = {}
    deleted_dup = 0

    for item_db in my_events:
        event_id = item_db.get("id")
        if not event_id:
            continue

        ev_data = item_db
        if "event" in item_db and isinstance(item_db["event"], str):
            try:
                ev_data = json.loads(item_db["event"])
            except Exception:
                pass

        t_a = clean_name(ev_data.get("teamAName") or item_db.get("teamAName") or ev_data.get("team1"))
        t_b = clean_name(ev_data.get("teamBName") or item_db.get("teamBName") or ev_data.get("team2"))
        title = clean_name(ev_data.get("eventName") or item_db.get("eventName") or ev_data.get("tournament"))

        if t_a and t_b:
            match_key = tuple(sorted([t_a, t_b]))
        elif title:
            match_key = (title,)
        else:
            continue

        if match_key in seen:
            del_payload = {
                "id": int(event_id) if str(event_id).isdigit() else str(event_id),
                "requestData": generate_security_token()
            }
            try:
                del_res = requests.post(BASE_URL + "admin/delete_event", json=del_payload, headers=get_headers(), timeout=12)
                if del_res.status_code in [200, 201]:
                    deleted_dup += 1
                    print(f"[Duplicate Removed] ID: {event_id} | {t_a} vs {t_b}")
                    time.sleep(0.5)
            except Exception as e:
                print(f"Error removing duplicate {event_id}:", e)
        else:
            seen[match_key] = event_id

    return deleted_dup

# ২. এপিআই নির্ভর ফিনিশড এবং ১২ ঘণ্টার পুরোনো ম্যাচ হ্যান্ডলিং
def manage_finished_events_step(my_events, live_feed):
    finished_list = []
    now_utc = datetime.now(timezone.utc)
    
    live_feed_keys = set()
    ended_feed_keys = set()

    for f in live_feed:
        if not isinstance(f, dict):
            continue
        t_a = clean_name(f.get("teamAName") or f.get("teamA") or f.get("team1"))
        t_b = clean_name(f.get("teamBName") or f.get("teamB") or f.get("team2"))
        title = clean_name(f.get("eventName") or f.get("name") or f.get("title"))
        
        m_key = None
        if t_a and t_b:
            m_key = tuple(sorted([t_a, t_b]))
        elif title:
            m_key = (title,)

        if m_key:
            if is_feed_match_ended(f):
                ended_feed_keys.add(m_key)
            else:
                live_feed_keys.add(m_key)

    for item_db in my_events:
        event_id = item_db.get("id")
        if not event_id:
            continue

        ev_data = item_db
        if "event" in item_db and isinstance(item_db["event"], str):
            try:
                ev_data = json.loads(item_db["event"])
            except Exception:
                pass

        db_a = clean_name(ev_data.get("teamAName") or item_db.get("teamAName") or ev_data.get("team1"))
        db_b = clean_name(ev_data.get("teamBName") or item_db.get("teamBName") or ev_data.get("team2"))
        db_title = clean_name(ev_data.get("eventName") or item_db.get("eventName") or ev_data.get("tournament"))

        m_key = None
        if db_a and db_b:
            m_key = tuple(sorted([db_a, db_b]))
        elif db_title:
            m_key = (db_title,)

        match_dt = parse_feed_utc_dt(ev_data.get("date"), ev_data.get("time"))
        is_over_12_hours = (now_utc - match_dt) > timedelta(hours=12)

        is_finished = False
        if is_over_12_hours:
            is_finished = True
        elif m_key and m_key in ended_feed_keys:
            is_finished = True
        elif m_key and (m_key not in live_feed_keys):
            is_finished = True

        if is_finished:
            finished_list.append({
                "id": event_id,
                "created_at": ev_data.get("created_at") or 0,
                "t_a": ev_data.get("teamAName") or item_db.get("teamAName") or "Event",
                "t_b": ev_data.get("teamBName") or item_db.get("teamBName") or ""
            })

    # সাম্প্রতিক ১২টি রেখে অতিরিক্ত পুরোনো সমাপ্ত ম্যাচ মুছে ফেলা
    to_delete = finished_list[KEEP_FINISHED_LIMIT:]
    deleted_count = 0

    for item in to_delete:
        del_payload = {
            "id": int(item["id"]) if str(item["id"]).isdigit() else str(item["id"]),
            "requestData": generate_security_token()
        }
        try:
            del_res = requests.post(BASE_URL + "admin/delete_event", json=del_payload, headers=get_headers(), timeout=12)
            if del_res.status_code in [200, 201]:
                deleted_count += 1
                print(f"[Finished Removed] ID: {item['id']} | {item['t_a']} vs {item['t_b']}")
                time.sleep(0.5)
        except Exception as e:
            print(f"Error deleting event {item['id']}:", e)

    return deleted_count

def format_links_data(streaming_links):
    formatted = []
    if not streaming_links or not isinstance(streaming_links, list):
        return formatted

    dlsports_counter = 1

    for idx, item in enumerate(streaming_links):
        if not isinstance(item, dict):
            continue

        original_name = str(item.get("name") or f"Server {idx + 1}").strip()
        url = str(item.get("link") or item.get("url") or "").strip()
        
        name_upper = original_name.upper().replace(" ", "")
        
        if any(x in name_upper for x in ["LOWQUALITY", "USEVPN", "LINK", "STREAMTV+HD"]):
            if dlsports_counter == 1:
                name = "DLSPORTS"
            else:
                name = f"DLSPORTS {dlsports_counter}"
            dlsports_counter += 1
        else:
            name = original_name

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

# ৩. লাইভ ম্যাচ প্রাধান্য দিয়ে ও আপকামিং ম্যাচ সঠিকভাবে যোগ করা
def add_events_step(live_feed, my_events):
    now_utc = datetime.now(timezone.utc)

    live_candidates = []
    upcoming_candidates = []

    for feed_match in live_feed:
        if not isinstance(feed_match, dict):
            continue

        # এপিআইতে সমাপ্ত ম্যাচ বাদ দেওয়া
        if is_feed_match_ended(feed_match):
            continue

        date_val = feed_match.get("date")
        time_val = feed_match.get("time")
        match_utc_dt = parse_feed_utc_dt(date_val, time_val)

        # ১২ ঘণ্টার বেশি পুরোনো ম্যাচ বাদ
        if (now_utc - match_utc_dt) > timedelta(hours=12):
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
                try: ev_data = json.loads(item_db["event"])
                except Exception: pass

            db_a = clean_name(ev_data.get("teamAName") or item_db.get("teamAName") or ev_data.get("team1"))
            db_b = clean_name(ev_data.get("teamBName") or item_db.get("teamBName") or ev_data.get("team2"))

            if clean_fa and clean_fb and db_a and db_b:
                if (clean_fa == db_a and clean_fb == db_b) or (clean_fa == db_b and clean_fb == db_a):
                    already_exists = True
                    break
            elif not clean_fb and not db_b:
                db_title = clean_name(ev_data.get("eventName") or ev_data.get("tournament") or ev_data.get("title"))
                if clean_ftitle and db_title and clean_ftitle == db_title:
                    already_exists = True
                    break

        if already_exists:
            continue

        item_tuple = (feed_match, match_utc_dt, t_a_raw, t_b_raw, f_title)

        # ম্যাচ শুরু হয়ে থাকলে বা ৩০ মিনিট আগের হলে লাইভ উইন্ডোতে ফেলা
        if match_utc_dt <= (now_utc + timedelta(minutes=30)):
            live_candidates.append(item_tuple)
        else:
            upcoming_candidates.append(item_tuple)

    upcoming_candidates.sort(key=lambda x: x[1])

    to_add_list = []
    to_add_list.extend(live_candidates)  
    to_add_list.extend(upcoming_candidates[:MAX_UPCOMING_ADD_PER_RUN])  

    added_count = 0

    for feed_match, match_utc_dt, t_a_raw, t_b_raw, f_title in to_add_list:
        links = feed_match.get("streaming_links") or feed_match.get("links") or []
        formatted_links = format_links_data(links)

        logo1 = fix_image_url(feed_match.get("teamAFlag") or feed_match.get("team1_logo"))
        logo2 = fix_image_url(feed_match.get("teamBFlag") or feed_match.get("team2_logo"))
        t_logo = fix_image_url(feed_match.get("eventLogo") or feed_match.get("tournament_logo"))
        category = feed_match.get("category") or "Football"

        unique_slug = f"links/{int(time.time() * 1000)}_{added_count}"

        utc_time_str = match_utc_dt.strftime("%H:%M:%S")
        utc_date_str = match_utc_dt.strftime("%d/%m/%Y")
        
        match_end_utc = match_utc_dt + timedelta(hours=3)
        utc_end_time_str = match_end_utc.strftime("%H:%M:%S")
        utc_end_date_str = match_end_utc.strftime("%d/%m/%Y")

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
            "date": utc_date_str,
            "time": utc_time_str,
            "notiThumb": "",
            "countryCodes": "",
            "whitelistCountryCodes": "",
            "messages": "{}",
            "end_date": utc_end_date_str,
            "end_time": utc_end_time_str,
            "links": unique_slug,
            "created_at": int(time.time() * 1000)
        }

        links_json_str = json.dumps(formatted_links)

        insert_payload = {
            "event": json.dumps(new_event_dict),
            "links": links_json_str,
            "linksData": links_json_str,
            "linksPath": unique_slug,
            "requestData": generate_security_token()
        }

        for attempt in range(3):
            try:
                insert_payload["requestData"] = generate_security_token()
                in_res = requests.post(BASE_URL + "admin/add_event", json=insert_payload, headers=get_headers(), timeout=15)
                if in_res.status_code in [200, 201]:
                    added_count += 1
                    lbl = "🔴 LIVE" if match_utc_dt <= now_utc else "UPCOMING"
                    print(f"[{lbl} Added {added_count}] {t_a_raw} vs {t_b_raw} | UTC Time: {utc_date_str} {utc_time_str}")
                    my_events.append(new_event_dict)
                    time.sleep(1.0)
                    break
                else:
                    time.sleep(1.0)
            except Exception:
                time.sleep(1.0)

    return added_count

def sync_streaming_links_and_reset_utc_time(live_feed, my_events):
    indexed_feed = []

    for f in live_feed:
        if not isinstance(f, dict):
            continue
        t_a = clean_name(f.get("teamAName") or f.get("teamA") or "")
        t_b = clean_name(f.get("teamBName") or f.get("teamB") or "")
        title = clean_name(f.get("eventName") or f.get("name") or "")
        links = f.get("streaming_links") or f.get("links") or []

        indexed_feed.append({
            "teamA": t_a,
            "teamB": t_b,
            "title": title,
            "streaming_links": links,
            "raw_feed": f
        })

    updated_count = 0

    for item_db in my_events:
        event_id = item_db.get("id")
        if not event_id:
            continue

        ev_data = item_db
        if "event" in item_db and isinstance(item_db["event"], str):
            try: ev_data = json.loads(item_db["event"])
            except Exception: pass

        my_a = clean_name(ev_data.get("teamAName") or item_db.get("teamAName"))
        my_b = clean_name(ev_data.get("teamBName") or item_db.get("teamBName"))
        my_title = clean_name(ev_data.get("eventName") or item_db.get("eventName") or ev_data.get("tournament"))

        matched_match = None
        for inf in indexed_feed:
            if my_a and my_b and inf["teamA"] and inf["teamB"]:
                if (my_a == inf["teamA"] and my_b == inf["teamB"]) or (my_a == inf["teamB"] and my_b == inf["teamA"]):
                    matched_match = inf
                    break
            elif my_title and inf["title"] and my_title == inf["title"]:
                matched_match = inf
                break

        if not matched_match:
            continue

        f_obj = matched_match["raw_feed"]
        correct_utc_dt = parse_feed_utc_dt(f_obj.get("date"), f_obj.get("time"))
        end_utc_dt = correct_utc_dt + timedelta(hours=3)

        correct_time_str = correct_utc_dt.strftime("%H:%M:%S")
        correct_date_str = correct_utc_dt.strftime("%d/%m/%Y")
        correct_end_time = end_utc_dt.strftime("%H:%M:%S")
        correct_end_date = end_utc_dt.strftime("%d/%m/%Y")

        ev_data["time"] = correct_time_str
        ev_data["date"] = correct_date_str
        ev_data["end_time"] = correct_end_time
        ev_data["end_date"] = correct_end_date

        formatted_links = format_links_data(matched_match["streaming_links"])
        links_path = str(item_db.get("linksPath") or ev_data.get("linksPath") or ev_data.get("links") or f"links/{event_id}")

        payload = {
            "id": str(event_id),
            "event": json.dumps(ev_data),
            "linksPath": links_path,
            "linksData": json.dumps(formatted_links),
            "requestData": generate_security_token()
        }

        try:
            up_res = requests.post(BASE_URL + "admin/update_event", json=payload, headers=get_headers(), timeout=12)
            if up_res.status_code == 200:
                updated_count += 1
                time.sleep(0.5)
        except Exception as e:
            pass

    return updated_count

def main():
    if not FEED_SOURCE:
        print("Error: SECRET_FEED_SOURCE environment variable is not configured.")
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

    print(f"Total Matches found in Feed API: {len(live_feed)}")

    my_events = get_my_saved_events()
    print(f"Total Events currently in Panel: {len(my_events)}")

    # ১. ডুপ্লিকেট পরিষ্কার
    dup_removed = remove_duplicate_events_step(my_events)
    if dup_removed > 0:
        time.sleep(1.5)
        my_events = get_my_saved_events()

    # ২. এপিআই অনুযায়ী ফিনিশড ও ১২ ঘণ্টার বেশি পুরোনো ম্যাচ ফিল্টার
    deleted = manage_finished_events_step(my_events, live_feed)
    if deleted > 0:
        time.sleep(1.5)
        my_events = get_my_saved_events()

    # ৩. ডেটা ও লিঙ্ক সিঙ্ক
    updated = sync_streaming_links_and_reset_utc_time(live_feed, my_events)
    if updated > 0:
        time.sleep(1.5)
        my_events = get_my_saved_events()

    # ৪. লাইভ ও আপকামিং ম্যাচ যুক্ত করা
    added = add_events_step(live_feed, my_events)

    print("\n==========================================")
    print(f"Finished! Duplicates: {dup_removed} | API End Deleted: {deleted} | Synced: {updated} | Added: {added}")
    print("==========================================")

if __name__ == "__main__":
    main()
