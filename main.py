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

MAX_UPCOMING_ADD_PER_RUN = 6
KEEP_FINISHED_LIMIT = 50

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

        return datetime(year, month, day, hh, mm, ss, tzinfo=timezone.utc)
    except Exception:
        return now_utc

def get_exact_sport_duration_minutes(match):
    cat = str(match.get("category") or "").lower()
    tour = str(match.get("tournament") or match.get("eventName") or match.get("name") or "").lower()
    t1 = str(match.get("team1") or match.get("teamAName") or match.get("team1_name") or "").lower()
    t2 = str(match.get("team2") or match.get("teamBName") or match.get("team2_name") or "").lower()
    combined = f"{cat} {tour} {t1} {t2}"

    is_final = "final" in combined and "semi" not in combined and "quarter" not in combined
    is_semi = "semi" in combined
    is_quarter = "quarter" in combined
    is_knockout = is_semi or is_quarter or any(k in combined for k in ["round of 16", "round of 8", "round of 32", "r16", "r32", "playoff", "play-off", "knockout"])

    if any(k in combined for k in ["evento", "sports live", "tv channel"]):
        if "tennis" in combined: return 960
        if "cycling" in combined: return 480
        if "golf" in combined: return 720
        if "table tennis" in combined or "tabel tennis" in combined: return 480
        if "judo" in combined or "wrestling" in combined: return 480
        return 960

    if "tennis" in combined:
        if is_final or any(k in combined for k in ["grand slam", "wimbledon", "us open", "french open", "australian open"]):
            return 330
        return 240

    if "cricket" in combined or "cricket" in cat:
        if any(k in combined for k in ["test", "ranji", "sheffield", "county", "4-day", "four day"]):
            return 540
        if any(k in combined for k in ["odi", "one day", "50 over", "world cup", "trophy", "u19"]):
            return 540 if is_final else 510
        if "ipl" in combined or "indian premier" in combined:
            return 260 if is_final else 240
        if any(k in combined for k in ["t20", "bpl", "psl", "bbl", "big bash", "cpl", "sa20", "mlc", "ilt20", "legends", "road safety", "wcl", "super smash"]):
            return 260 if is_final else 230
        if "hundred" in combined: return 160
        if "t15" in combined: return 140
        if "t10" in combined or "ten10" in combined or "abu dhabi" in combined: return 100
        if "t5" in combined or "sixes" in combined: return 60
        return 230

    if "football" in combined or "soccer" in combined or "football" in cat:
        if is_final: return 210
        if is_knockout: return 195
        return 180

    if any(k in combined for k in ["nfl", "american football", "cfl", "ncaa"]):
        return 400 if is_final else 360

    if any(k in combined for k in ["nba", "basketball", "fiba", "euroleague"]):
        return 210 if (is_final or is_knockout) else 180

    if any(k in combined for k in ["baseball", "mlb", "npb", "kbo"]):
        return 220

    if any(k in combined for k in ["wwe", "raw", "smackdown", "nxt", "aew", "tna", "wrestling"]):
        if "raw" in combined: return 200
        if any(k in combined for k in ["ple", "wrestlemania", "royal rumble", "summer slam"]): return 260
        return 150
    if any(k in combined for k in ["ufc", "mma", "one fight", "bellator"]):
        return 240
    if "boxing" in combined: return 210

    if "formula 1" in combined or "f1" in combined: return 140
    if "motogp" in combined or "sbk" in combined: return 70
    if "nascar" in combined: return 240
    if "wrc" in combined or "rally" in combined: return 360

    if "horse racing" in combined or "horse" in combined: return 600
    if "racing" in combined: return 480
    if "snooker" in combined: return 270
    if "darts" in combined or "pdc" in combined: return 140
    if "hockey" in combined or "nhl" in combined: return 180
    if "kabaddi" in combined: return 70

    return 160

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

def delete_single_event_from_db(event_id):
    str_id = str(event_id)
    int_id = int(str_id) if str_id.isdigit() else str_id

    del_payload = {
        "from": "events",
        "table": "events",
        "id": int_id,
        "eventId": str_id,
        "requestData": generate_security_token()
    }

    headers = get_headers()
    endpoints = ["admin/delete", "admin/delete_event"]

    for ep in endpoints:
        try:
            r = requests.post(BASE_URL + ep, json=del_payload, headers=headers, timeout=10)
            if r.status_code in [200, 201]:
                return True, r.text[:80]
        except Exception:
            pass
    return False, "Failed"

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
            ok, resp_txt = delete_single_event_from_db(event_id)
            if ok:
                deleted_dup += 1
                print(f"[Duplicate Removed] ID: {event_id} | {t_a} vs {t_b} | Resp: {resp_txt}")
                time.sleep(0.1)
        else:
            seen[match_key] = event_id

    return deleted_dup

def manage_finished_events_step(my_events, live_feed):
    now_utc = datetime.now(timezone.utc)
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

        start_utc = parse_feed_utc_dt(ev_data.get("date") or item_db.get("date"), ev_data.get("time") or item_db.get("time"))
        end_date_str = ev_data.get("end_date") or item_db.get("end_date")
        end_time_str = ev_data.get("end_time") or item_db.get("end_time")

        end_utc = parse_feed_utc_dt(end_date_str, end_time_str)
        if not end_date_str or end_utc <= start_utc:
            dur_min = get_exact_sport_duration_minutes(ev_data)
            end_utc = start_utc + timedelta(minutes=dur_min)

        if now_utc >= end_utc:
            finished_list.append({
                "id": event_id,
                "end_utc": end_utc,
                "t_a": ev_data.get("teamAName") or item_db.get("teamAName") or "Event",
                "t_b": ev_data.get("teamBName") or item_db.get("teamBName") or ""
            })

    finished_list.sort(key=lambda x: x["end_utc"], reverse=True)

    to_delete = finished_list[KEEP_FINISHED_LIMIT:]
    deleted_count = 0

    print(f"Total Finished in DB: {len(finished_list)} | Target to Delete: {len(to_delete)}")

    for item in to_delete:
        ok, resp_txt = delete_single_event_from_db(item["id"])
        if ok:
            deleted_count += 1
            print(f"[Deleted Exceeded Finished] ID: {item['id']} | {item['t_a']} vs {item['t_b']} | Resp: {resp_txt}")
            time.sleep(0.1)

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

def add_events_step(live_feed, my_events):
    now_utc = datetime.now(timezone.utc)

    live_candidates = []
    upcoming_candidates = []

    for feed_match in live_feed:
        if not isinstance(feed_match, dict):
            continue

        date_val = feed_match.get("date")
        time_val = feed_match.get("time")
        match_utc_dt = parse_feed_utc_dt(date_val, time_val)

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

        if match_utc_dt <= now_utc:
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

        feed_end_utc = parse_feed_utc_dt(feed_match.get("end_date"), feed_match.get("end_time"))
        fallback_dur = get_exact_sport_duration_minutes(feed_match)

        if feed_end_utc and feed_end_utc > match_utc_dt:
            match_end_utc = feed_end_utc
        else:
            match_end_utc = match_utc_dt + timedelta(minutes=fallback_dur)

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
            "from": "events",
            "table": "events",
            "event": json.dumps(new_event_dict),
            "links": links_json_str,
            "linksData": links_json_str,
            "linksPath": unique_slug,
            "requestData": generate_security_token()
        }

        for attempt in range(2):
            try:
                insert_payload["requestData"] = generate_security_token()
                in_res = requests.post(BASE_URL + "admin/add_event", json=insert_payload, headers=get_headers(), timeout=12)
                if in_res.status_code in [200, 201]:
                    added_count += 1
                    lbl = "LIVE" if match_utc_dt <= now_utc else "UPCOMING"
                    print(f"[{lbl} Added {added_count}] {t_a_raw} vs {t_b_raw} | UTC: {utc_date_str} {utc_time_str}")
                    my_events.append(new_event_dict)
                    time.sleep(0.5)
                    break
                else:
                    time.sleep(0.5)
            except Exception:
                time.sleep(0.5)

    return added_count

def sync_streaming_links_and_reset_utc_time(live_feed, my_events):
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

        feed_end_utc = parse_feed_utc_dt(f_obj.get("end_date"), f_obj.get("end_time"))
        fallback_dur = get_exact_sport_duration_minutes(f_obj)

        if feed_end_utc and feed_end_utc > correct_utc_dt:
            end_utc_dt = feed_end_utc
        else:
            end_utc_dt = correct_utc_dt + timedelta(minutes=fallback_dur)

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
            "from": "events",
            "table": "events",
            "id": str(event_id),
            "event": json.dumps(ev_data),
            "linksPath": links_path,
            "linksData": json.dumps(formatted_links),
            "requestData": generate_security_token()
        }

        try:
            up_res = requests.post(BASE_URL + "admin/update_event", json=payload, headers=get_headers(), timeout=10)
            if up_res.status_code == 200:
                updated_count += 1
                time.sleep(0.1)
        except Exception:
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

    dup_removed = remove_duplicate_events_step(my_events)
    if dup_removed > 0:
        time.sleep(0.5)
        my_events = get_my_saved_events()

    deleted = manage_finished_events_step(my_events, live_feed)
    if deleted > 0:
        time.sleep(0.5)
        my_events = get_my_saved_events()

    updated = sync_streaming_links_and_reset_utc_time(live_feed, my_events)
    if updated > 0:
        time.sleep(0.5)
        my_events = get_my_saved_events()

    added = add_events_step(live_feed, my_events)

    print("\n==========================================")
    print(f"Finished! Duplicates: {dup_removed} | Old Finished Deleted: {deleted} | Synced: {updated} | Added: {added}")
    print("==========================================")

if __name__ == "__main__":
    main()
