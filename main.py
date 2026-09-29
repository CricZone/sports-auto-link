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

# প্রতি রানে নতুন ম্যাচ অ্যাড সীমা
MAX_ADD_PER_RUN = 15

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

# ফিডের আন্তর্জাতিক UTC সময়কে বাংলাদেশ সময়ে (+৬ ঘণ্টা) রূপান্তর
def parse_feed_time_to_bd(date_str, time_str):
    now_bd = datetime.now(BD_TZ)
    if not date_str:
        return datetime.now(timezone.utc), now_bd

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
            return datetime.now(timezone.utc), now_bd

        t_parts = [int(p) for p in re.findall(r'\d+', time_str)]
        hh = t_parts[0] if len(t_parts) > 0 else 0
        mm = t_parts[1] if len(t_parts) > 1 else 0
        ss = t_parts[2] if len(t_parts) > 2 else 0

        # ফিডের সময় UTC সময় হিসেবে পার্স
        match_utc_dt = datetime(year, month, day, hh, mm, ss, tzinfo=timezone.utc)
        # বাংলাদেশ সময়ে (+৬ ঘণ্টা) রূপান্তর
        match_bd_dt = match_utc_dt.astimezone(BD_TZ)
        return match_utc_dt, match_bd_dt
    except Exception:
        return datetime.now(timezone.utc), now_bd

# ডাটাবেসে সেভ থাকা বাংলাদেশ সময় রিড করার ফাংশন
def parse_saved_bd_dt(date_str, time_str):
    if not date_str:
        return None
    try:
        date_str = str(date_str).strip()
        time_str = str(time_str).strip() if time_str else "00:00:00"

        parts = [int(p) for p in re.findall(r'\d+', date_str)]
        if len(parts) >= 3:
            if parts[0] > 1000:
                y, m, d = parts[0], parts[1], parts[2]
            else:
                d, m, y = parts[0], parts[1], parts[2]
        else:
            return None

        t_parts = [int(p) for p in re.findall(r'\d+', time_str)]
        hh = t_parts[0] if len(t_parts) > 0 else 0
        mm = t_parts[1] if len(t_parts) > 1 else 0
        ss = t_parts[2] if len(t_parts) > 2 else 0

        lower_t = time_str.lower()
        if "pm" in lower_t and hh < 12:
            hh += 12
        elif "am" in lower_t and hh == 12:
            hh = 0

        return datetime(y, m, d, hh, mm, ss, tzinfo=BD_TZ)
    except Exception:
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
        title = clean_name(ev_data.get("eventName") or ev_data.get("tournament") or ev_data.get("title"))

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
                    time.sleep(1.5)
            except Exception as e:
                print(f"Error removing duplicate {event_id}:", e)
        else:
            seen[match_key] = event_id

    return deleted_dup

# Finished ট্যাবে সবসময় সাম্প্রতিক ১০-১২টি ম্যাচ সংরক্ষিত রাখা
def delete_expired_events_step(my_events):
    now_bd = datetime.now(BD_TZ)
    finished_list = []

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

        date_str = ev_data.get("date") or item_db.get("date")
        time_str = ev_data.get("time") or item_db.get("time")
        if not date_str:
            continue

        match_dt = parse_saved_bd_dt(date_str, time_str)
        if not match_dt:
            continue

        duration_min = 135
        end_time_str = ev_data.get("end_time") or item_db.get("end_time")
        end_date_str = ev_data.get("end_date") or item_db.get("end_date")

        if end_date_str and end_time_str:
            end_dt = parse_saved_bd_dt(end_date_str, end_time_str) or (match_dt + timedelta(minutes=duration_min))
        else:
            end_dt = match_dt + timedelta(minutes=duration_min)

        if end_dt < now_bd:
            finished_list.append({
                "id": event_id,
                "end_dt": end_dt,
                "t_a": ev_data.get("teamAName") or item_db.get("teamAName") or "Event",
                "t_b": ev_data.get("teamBName") or item_db.get("teamBName") or ""
            })

    finished_list.sort(key=lambda x: x["end_dt"], reverse=True)
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
                print(f"[Auto Deleted Old Finished] ID: {item['id']} | {item['t_a']} vs {item['t_b']}")
                time.sleep(1.5)
        except Exception as e:
            print(f"Error deleting event {item['id']}:", e)

    return deleted_count

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

# লাইভ এবং নতুন ম্যাচ অ্যাড করা
def add_new_events_step(live_feed, my_events):
    now_bd = datetime.now(BD_TZ)
    now_utc = datetime.now(timezone.utc)
    added_count = 0

    # লাইভ ও আসন্ন ম্যাচগুলো আগে অ্যাড করার জন্য সর্টিং
    def get_priority_key(m):
        _, m_bd = parse_feed_time_to_bd(m.get("date"), m.get("time"))
        dur = 135
        end_bd = m_bd + timedelta(minutes=dur)
        if m_bd <= now_bd <= end_bd:
            return 0  # বর্তমানে চলমান লাইভ ম্যাচ আগে যাবে
        elif m_bd > now_bd:
            return 1  # আসন্ন ম্যাচ
        return 2

    sorted_feed = sorted(live_feed, key=get_priority_key)

    for feed_match in sorted_feed:
        if added_count >= MAX_ADD_PER_RUN:
            break

        if not isinstance(feed_match, dict):
            continue

        date_val = feed_match.get("date")
        time_val = feed_match.get("time")
        match_utc_dt, match_bd_dt = parse_feed_time_to_bd(date_val, time_val)

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

        match_end_bd = match_bd_dt + timedelta(minutes=duration_min)

        # ১২ ঘণ্টার বেশি পুরোনো খেলা বাদ
        if match_end_bd < now_bd - timedelta(hours=12):
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

        links = feed_match.get("streaming_links") or feed_match.get("links") or []
        formatted_links = format_links_data(links)

        logo1 = fix_image_url(feed_match.get("teamAFlag") or feed_match.get("team1_logo"))
        logo2 = fix_image_url(feed_match.get("teamBFlag") or feed_match.get("team2_logo"))
        t_logo = fix_image_url(feed_match.get("eventLogo") or feed_match.get("tournament_logo"))
        category = feed_match.get("category") or "Football"

        unique_slug = f"links/{int(time.time() * 1000)}_{added_count}"
        end_dt = match_bd_dt + timedelta(minutes=duration_min)

        # ১২ ঘণ্টার AM/PM ফরম্যাট সহ সংরক্ষণ
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
            "time": match_bd_dt.strftime("%I:%M:%S %p"),
            "notiThumb": "",
            "countryCodes": "",
            "whitelistCountryCodes": "",
            "messages": "{}",
            "end_date": end_dt.strftime("%d/%m/%Y"),
            "end_time": end_dt.strftime("%I:%M:%S %p"),
            "links": unique_slug
        }

        links_json_str = json.dumps(formatted_links)

        insert_payload = {
            "event": json.dumps(new_event_dict),
            "date": match_bd_dt.strftime("%d/%m/%Y"),
            "time": match_bd_dt.strftime("%I:%M:%S %p"),
            "links": links_json_str,
            "linksData": links_json_str,
            "linksPath": unique_slug,
            "requestData": generate_security_token()
        }

        success = False
        for attempt in range(3):
            try:
                insert_payload["requestData"] = generate_security_token()
                in_res = requests.post(BASE_URL + "admin/add_event", json=insert_payload, headers=get_headers(), timeout=15)
                if in_res.status_code in [200, 201]:
                    added_count += 1
                    status_lbl = "🔴 LIVE" if match_bd_dt <= now_bd <= end_dt else "UPCOMING"
                    print(f"[{status_lbl} Added {added_count}] {t_a_raw} vs {t_b_raw} | Time: {match_bd_dt.strftime('%d/%m/%Y %I:%M %p')}")
                    my_events.append(new_event_dict)
                    success = True
                    time.sleep(2.5)
                    break
                else:
                    time.sleep(2.0)
            except Exception:
                time.sleep(2.0)

    return added_count

# ডাটাবেসে সেভ থাকা সব আগের ম্যাচের সময়কে ফোর্স বাংলাদেশ টাইমে রূপান্তর
def sync_streaming_links_and_force_bd_time(live_feed, my_events):
    indexed_feed = []
    for f in live_feed:
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
            try:
                ev_data = json.loads(item_db["event"])
            except Exception:
                pass

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
        _, correct_bd_dt = parse_feed_time_to_bd(f_obj.get("date"), f_obj.get("time"))
        
        duration_min = 135
        if f_obj.get("end_time") and f_obj.get("time"):
            try:
                s_parts = [int(p) for p in re.findall(r'\d+', f_obj.get("time"))]
                e_parts = [int(p) for p in re.findall(r'\d+', f_obj.get("end_time"))]
                s_m = s_parts[0] * 60 + s_parts[1]
                e_m = e_parts[0] * 60 + e_parts[1]
                if e_m < s_m: e_m += 24 * 60
                if e_m - s_m > 0: duration_min = e_m - s_m
            except Exception:
                pass

        end_bd_dt = correct_bd_dt + timedelta(minutes=duration_min)

        # ১২ ঘণ্টার স্ট্যান্ডার্ড AM/PM স্ট্রিং
        correct_time_str = correct_bd_dt.strftime("%I:%M:%S %p")
        correct_date_str = correct_bd_dt.strftime("%d/%m/%Y")
        correct_end_time = end_bd_dt.strftime("%I:%M:%S %p")
        correct_end_date = end_bd_dt.strftime("%d/%m/%Y")

        ev_data["time"] = correct_time_str
        ev_data["date"] = correct_date_str
        ev_data["end_time"] = correct_end_time
        ev_data["end_date"] = correct_end_date

        formatted_links = format_links_data(matched_match["streaming_links"])
        links_path = str(item_db.get("linksPath") or ev_data.get("linksPath") or ev_data.get("links") or f"links/{event_id}")

        payload = {
            "id": str(event_id),
            "event": json.dumps(ev_data),
            "date": correct_date_str,
            "time": correct_time_str,
            "end_date": correct_end_date,
            "end_time": correct_end_time,
            "linksPath": links_path,
            "linksData": json.dumps(formatted_links),
            "requestData": generate_security_token()
        }

        try:
            up_res = requests.post(BASE_URL + "admin/update_event", json=payload, headers=get_headers(), timeout=12)
            if up_res.status_code == 200:
                print(f"[Time & Links Synced] ID: {event_id} | {ev_data.get('teamAName')} vs {ev_data.get('teamBName')} -> BD Time: {correct_date_str} {correct_time_str}")
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

    # ১. ডুপ্লিকেট ম্যাচ পরিষ্কার
    dup_removed = remove_duplicate_events_step(my_events)
    if dup_removed > 0:
        time.sleep(2)
        my_events = get_my_saved_events()

    # ২. Finished ট্যাবে ১২টি রেখে বাকিগুলো ক্লিন করা
    deleted = delete_expired_events_step(my_events)
    if deleted > 0:
        time.sleep(2)
        my_events = get_my_saved_events()

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

    # ৩. ডাটাবেসে থাকা আগের ম্যাচগুলোর সময় ও লিঙ্ক সিঙ্ক করা (টেনিসসহ সব ম্যাচ ফিক্স হবে)
    updated = sync_streaming_links_and_force_bd_time(live_feed, my_events)
    if updated > 0:
        time.sleep(2)
        my_events = get_my_saved_events()

    # ৪. লাইভ ম্যাচ অগ্রাধিকার দিয়ে নতুন ম্যাচ অ্যাড করা
    added = add_new_events_step(live_feed, my_events)

    print("\n==========================================")
    print(f"Finished! Duplicates: {dup_removed} | Expired Deleted: {deleted} | Synced/Fixed: {updated} | Added: {added}")
    print("==========================================")

if __name__ == "__main__":
    main()
