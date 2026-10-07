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

# Bangladesh Timezone (UTC+6)
BD_TZ = timezone(timedelta(hours=6))

# Maximum new matches to add per cycle
MAX_ADD_PER_RUN = 5

# Maximum finished matches to retain (older ones get auto-deleted)
KEEP_FINISHED_LIMIT = 50

# Continuous loop interval in seconds (5 minutes)
LOOP_INTERVAL_SECONDS = 300

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

# Sports Duration Engine (GeeSports Match-Keeping Standards)
def get_exact_sport_duration_minutes(match_dict):
    cat = str(match_dict.get("category") or "").lower()
    tour = str(match_dict.get("tournament") or match_dict.get("eventName") or "").lower()
    t1 = str(match_dict.get("teamAName") or match_dict.get("team1") or "").lower()
    t2 = str(match_dict.get("teamBName") or match_dict.get("team2") or "").lower()
    title = str(match_dict.get("title") or match_dict.get("name") or "").lower()
    combined = f"{cat} {tour} {title} {t1} {t2}"

    is_final = "final" in combined and "semi" not in combined and "quarter" not in combined
    is_semi = "semi" in combined
    is_quarter = "quarter" in combined
    is_knockout = is_semi or is_quarter or any(k in combined for k in ["round of 16", "round of 8", "round of 32", "r16", "r32", "playoff", "play-off", "knockout"])

    # 1. Full-Day Tournament Streams (EVENTO)
    if any(k in combined for k in ["evento", "sports live", "tv channel"]):
        if "tennis" in combined: return 960
        if "cycling" in combined: return 480
        if "golf" in combined: return 720
        if "tabel tennis" in combined or "table tennis" in combined: return 480
        if "judo" in combined or "wrestling" in combined: return 480
        return 960

    # 2. Tennis
    if "tennis" in combined:
        if is_final or any(k in combined for k in ["grand slam", "wimbledon", "us open", "french open", "australian open"]):
            return 330
        return 240

    # 3. Cricket
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

    # 4. Football / Soccer
    if "football" in combined or "soccer" in combined or "football" in cat:
        if is_final: return 210
        if is_knockout: return 195
        return 180

    # 5. American Football (NFL / NCAA / CFL)
    if any(k in combined for k in ["nfl", "american football", "cfl", "ncaa"]):
        return 400 if is_final else 360

    # 6. Basketball (NBA / FIBA)
    if any(k in combined for k in ["nba", "basketball", "fiba", "euroleague"]):
        return 210 if (is_final or is_knockout) else 180

    # 7. Baseball (MLB)
    if any(k in combined for k in ["baseball", "mlb", "npb", "kbo"]):
        return 220

    # 8. Combat Sports & Wrestling
    if any(k in combined for k in ["wwe", "raw", "smackdown", "nxt", "aew", "tna", "wrestling"]):
        if "raw" in combined: return 200
        if any(k in combined for k in ["ple", "wrestlemania", "royal rumble", "summer slam"]): return 260
        return 150
    if any(k in combined for k in ["ufc", "mma", "one fight", "bellator"]): return 240
    if "boxing" in combined: return 210

    # 9. Motorsports
    if "formula 1" in combined or "f1" in combined: return 140
    if "motogp" in combined or "sbk" in combined: return 70
    if "nascar" in combined: return 240
    if "wrc" in combined or "rally" in combined: return 360

    # 10. Others
    if "horse racing" in combined or "horse" in combined: return 600
    if "racing" in combined: return 480
    if "snooker" in combined: return 270
    if "darts" in combined or "pdc" in combined: return 140
    if "hockey" in combined or "nhl" in combined: return 180
    if "kabaddi" in combined: return 70

    return 180

def parse_feed_time_to_bd(date_str, time_str):
    now_dt = datetime.now(BD_TZ)
    if not date_str:
        return datetime.now(timezone.utc), now_dt

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
            return datetime.now(timezone.utc), now_dt

        t_parts = [int(p) for p in re.findall(r'\d+', time_str)]
        hh = t_parts[0] if len(t_parts) > 0 else 0
        mm = t_parts[1] if len(t_parts) > 1 else 0
        ss = t_parts[2] if len(t_parts) > 2 else 0

        match_utc_dt = datetime(year, month, day, hh, mm, ss, tzinfo=timezone.utc)
        match_bd_dt = match_utc_dt.astimezone(BD_TZ)
        return match_utc_dt, match_bd_dt
    except Exception:
        return datetime.now(timezone.utc), now_dt

def parse_saved_bd_dt(date_str, time_str):
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
        if "am" in lower_t and hh == 12:
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
                    time.sleep(1.0)
            except Exception as e:
                print(f"Error removing duplicate {event_id}:", e)
        else:
            seen[match_key] = event_id

    return deleted_dup

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

        end_time_str = ev_data.get("end_time") or item_db.get("end_time")
        end_date_str = ev_data.get("end_date") or item_db.get("end_date")

        if end_date_str and end_time_str:
            end_dt = parse_saved_bd_dt(end_date_str, end_time_str)
            if not end_dt:
                end_dt = match_dt + timedelta(minutes=get_exact_sport_duration_minutes(ev_data))
        else:
            end_dt = match_dt + timedelta(minutes=get_exact_sport_duration_minutes(ev_data))

        if end_dt < now_bd:
            finished_list.append({
                "id": event_id,
                "end_dt": end_dt,
                "t_a": ev_data.get("teamAName") or item_db.get("teamAName") or "Event",
                "t_b": ev_data.get("teamBName") or item_db.get("teamBName") or ""
            })

    finished_list.sort(key=lambda x: x["end_dt"], reverse=True)

    # Retain the latest 50 finished matches and delete older ones
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
                time.sleep(1.0)
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

        date_val = feed_match.get("date")
        time_val = feed_match.get("time")
        match_utc_dt, match_bd_dt = parse_feed_time_to_bd(date_val, time_val)

        if match_bd_dt < start_of_today_bd:
            continue

        raw_status = str(feed_match.get("matchStatus") or feed_match.get("status") or "").lower()
        if match_utc_dt <= now_utc and raw_status in ["live_ended", "finished", "ended"]:
            continue

        # Dynamic End Time calculation matching GeeSports engine
        feed_end_utc, feed_end_bd = parse_feed_time_to_bd(feed_match.get("end_date"), feed_match.get("end_time"))
        if feed_end_utc and feed_end_utc > match_utc_dt:
            end_dt = feed_end_bd
            match_end_utc = feed_end_utc
        else:
            duration_min = get_exact_sport_duration_minutes(feed_match)
            end_dt = match_bd_dt + timedelta(minutes=duration_min)
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
                    print(f"[Added Event {added_count}/{MAX_ADD_PER_RUN}] {t_a_raw} vs {t_b_raw} | Links: {len(formatted_links)}")
                    my_events.append(new_event_dict)
                    success = True
                    time.sleep(2.0)
                    break
                else:
                    time.sleep(1.5)
            except Exception:
                time.sleep(1.5)

        if not success:
            print(f"[Skipped/Failed] {t_a_raw} vs {t_b_raw}")

    return added_count

def sync_streaming_links_step(live_feed, my_events):
    now_bd = datetime.now(BD_TZ)
    indexed_feed = []

    for f in live_feed:
        t_a = clean_name(f.get("teamAName") or f.get("teamA") or "")
        t_b = clean_name(f.get("teamBName") or f.get("teamB") or "")
        links = f.get("streaming_links") or f.get("links") or []
        raw_status = str(f.get("matchStatus") or f.get("status") or "").lower()

        indexed_feed.append({
            "teamA": t_a,
            "teamB": t_b,
            "raw_teamA": f.get("teamAName") or f.get("teamA"),
            "raw_teamB": f.get("teamBName") or f.get("teamB"),
            "streaming_links": links,
            "status": raw_status,
            "raw_feed": f
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

        f_obj = matched_match["raw_feed"]
        match_utc, correct_bd_dt = parse_feed_time_to_bd(f_obj.get("date"), f_obj.get("time"))
        correct_time_str = correct_bd_dt.strftime("%I:%M:%S %p")
        correct_date_str = correct_bd_dt.strftime("%d/%m/%Y")

        ev_data["time"] = correct_time_str
        ev_data["date"] = correct_date_str

        # Instant Finish Sync: If GeeSports feed marks match as live_ended, set end time to past
        if matched_match["status"] in ["live_ended", "finished", "ended"]:
            past_dt = now_bd - timedelta(minutes=5)
            ev_data["end_date"] = past_dt.strftime("%d/%m/%Y")
            ev_data["end_time"] = past_dt.strftime("%I:%M:%S %p")
        else:
            feed_end_utc, feed_end_bd = parse_feed_time_to_bd(f_obj.get("end_date"), f_obj.get("end_time"))
            if feed_end_utc and feed_end_utc > match_utc:
                ev_data["end_date"] = feed_end_bd.strftime("%d/%m/%Y")
                ev_data["end_time"] = feed_end_bd.strftime("%I:%M:%S %p")
            else:
                duration_min = get_exact_sport_duration_minutes(ev_data)
                end_dt = correct_bd_dt + timedelta(minutes=duration_min)
                ev_data["end_date"] = end_dt.strftime("%d/%m/%Y")
                ev_data["end_time"] = end_dt.strftime("%I:%M:%S %p")

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
                print(f"[Updated] ID: {event_id} | {ev_data.get('teamAName')} vs {ev_data.get('teamBName')} | Status: {matched_match['status']}")
                updated_count += 1
        except Exception as e:
            print(f"Error updating ID {event_id}:", e)

    return updated_count

def run_single_sync_cycle():
    if not FEED_SOURCE:
        print("Error: SECRET_FEED_SOURCE environment variable is not configured.")
        return

    my_events = get_my_saved_events()
    print(f"\n[Cycle Started: {datetime.now(BD_TZ).strftime('%Y-%m-%d %I:%M:%S %p')}]")
    print(f"Total Events currently in Panel: {len(my_events)}")

    # 1. Deduplicate
    dup_removed = remove_duplicate_events_step(my_events)
    if dup_removed > 0:
        time.sleep(2)
        my_events = get_my_saved_events()

    # 2. Keep 50 finished and delete older ones
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

    # 3. Add max 5 new events per run
    added = add_new_events_step(live_feed, my_events)

    if added > 0:
        time.sleep(2)
        my_events = get_my_saved_events()

    # 4. Sync streaming links and status
    updated = sync_streaming_links_step(live_feed, my_events)

    print("==========================================")
    print(f"Cycle Done | Dup Removed: {dup_removed} | Expired Deleted: {deleted} | Added: {added} | Synced: {updated}")
    print("==========================================")

def main():
    # If run in GitHub Actions (single execution mode)
    if os.getenv("GITHUB_ACTIONS") == "true" or os.getenv("SINGLE_RUN") == "true":
        run_single_sync_cycle()
        return

    # Continuous 5-minute loop for Termux / VPS / Local Server
    print("Starting Continuous Auto-Sync Engine (Interval: 5 minutes)...")
    while True:
        try:
            run_single_sync_cycle()
        except Exception as e:
            print("Cycle Error:", e)

        print(f"Sleeping for {LOOP_INTERVAL_SECONDS} seconds...")
        time.sleep(LOOP_INTERVAL_SECONDS)

if __name__ == "__main__":
    main()
