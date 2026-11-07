import os
import time
import base64
import json
import re
import requests
from datetime import datetime, timezone, timedelta

BASE_URL = "https://dlsports.proapp.workers.dev/"
FEED_SOURCE = os.getenv("SECRET_FEED_SOURCE", "")

# ================= TIMEZONE SETTINGS =================
# Feed-এর সময় কোন timezone-এ আসে (UTC offset, ঘণ্টায়). Feed UTC হলে 0.
FEED_TZ_OFFSET = float(os.getenv("FEED_TZ_OFFSET", "0"))

# Panel/App-এ কোন timezone-এ সময় save হবে.
#   6 = বাংলাদেশ সময় সরাসরি save (অ্যাপ যদি raw সময় দেখায়)
#   0 = UTC save (অ্যাপ যদি নিজে UTC ধরে ফোনের সময়ে convert করে)
STORE_TZ_OFFSET = float(os.getenv("STORE_TZ_OFFSET", "6"))

# Security token কোন timezone-এ বানাবে (server যেটা আশা করে). Server যেখানেই চলুক, একই থাকবে.
TOKEN_TZ_OFFSET = float(os.getenv("TOKEN_TZ_OFFSET", "6"))
# =====================================================

FEED_TZ = timezone(timedelta(hours=FEED_TZ_OFFSET))
STORE_TZ = timezone(timedelta(hours=STORE_TZ_OFFSET))
TOKEN_TZ = timezone(timedelta(hours=TOKEN_TZ_OFFSET))
BD_TZ = timezone(timedelta(hours=6))  # শুধু log দেখানোর জন্য

MAX_ADD_PER_RUN = 5
KEEP_FINISHED_LIMIT = 50
LOOP_INTERVAL_SECONDS = 300
SAME_MATCH_WINDOW = timedelta(hours=24)  # একই টিম জোড়া + এই সময়ের মধ্যে = একই ম্যাচ
ENDED_STATUSES = ["live_ended", "finished", "ended"]
DEFAULT_LOGO = "https://i.postimg.cc/0Qs5rKL8/app-logo.png"

# event_id -> links hash (panel থেকে links ফেরত না এলে অপ্রয়োজনীয় update ঠেকাতে)
LINKS_CACHE = {}


# ---------------------------------------------------------------- helpers
def generate_security_token():
    now_str = datetime.now(TOKEN_TZ).strftime("%Y-%m-%d %H:%M:%S")
    b64 = base64.b64encode(now_str.encode("utf-8")).decode("utf-8")
    rev1 = b64[::-1]
    hex_str = "".join(f"{b:02x}" for b in rev1.encode("utf-8"))
    return hex_str[::-1]


def get_headers():
    return {"Content-Type": "application/json; charset=utf-8", "User-Agent": "okhttp/4.9.2"}


def clean_name(val):
    """'united', 'city' মুছে না, তাই Man United আর Man City আলাদা থাকে."""
    if not val:
        return ""
    w = str(val).lower()
    w = re.sub(r"\b(fc|cf|sc|vs|v)\b", "", w)
    return re.sub(r"[^a-z0-9]", "", w).strip()


def fix_image_url(url):
    if not url or not isinstance(url, str):
        return DEFAULT_LOGO
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        return DEFAULT_LOGO
    if url.startswith("http://"):
        url = "https://" + url[7:]
    return url.replace("api.sofascore.com", "img.sofascore.com")


def has_word(text, words):
    """Whole-word match: 'raw' 'draw'-এ মিলবে না, 'test' 'latest'-এ মিলবে না."""
    for w in words:
        if re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", text):
            return True
    return False


def parse_dt(date_str, time_str, tz):
    """Date+time string -> aware datetime (tz-এ). ব্যর্থ হলে None (এখনকার সময় নয়!)."""
    if not date_str:
        return None
    try:
        date_str = str(date_str).strip()
        time_str = str(time_str).strip() if time_str else "00:00:00"
        parts = [int(p) for p in re.findall(r"\d+", date_str)]
        if len(parts) < 3:
            return None
        if parts[0] > 1000:
            y, m, d = parts[0], parts[1], parts[2]
        else:
            d, m, y = parts[0], parts[1], parts[2]
        tp = [int(p) for p in re.findall(r"\d+", time_str)]
        hh = tp[0] if len(tp) > 0 else 0
        mm = tp[1] if len(tp) > 1 else 0
        ss = tp[2] if len(tp) > 2 else 0
        low = time_str.lower()
        if "pm" in low and hh < 12:
            hh += 12
        if "am" in low and hh == 12:
            hh = 0
        return datetime(y, m, d, hh, mm, ss, tzinfo=tz)
    except Exception:
        return None


def parse_feed_dt(date_str, time_str):
    dt = parse_dt(date_str, time_str, FEED_TZ)
    return dt.astimezone(timezone.utc) if dt else None


def parse_saved_dt(date_str, time_str):
    dt = parse_dt(date_str, time_str, STORE_TZ)
    return dt.astimezone(timezone.utc) if dt else None


def fmt_store(dt_utc):
    d = dt_utc.astimezone(STORE_TZ)
    return d.strftime("%d/%m/%Y"), d.strftime("%I:%M:%S %p")


def bd_str(dt_utc):
    return dt_utc.astimezone(BD_TZ).strftime("%Y-%m-%d %I:%M:%S %p")


def unpack_event(item_db):
    ev = item_db
    if isinstance(item_db.get("event"), str):
        try:
            ev = json.loads(item_db["event"])
        except Exception:
            ev = item_db
    return ev


def post_json(endpoint, payload, timeout=15):
    payload["requestData"] = generate_security_token()
    return requests.post(BASE_URL + endpoint, json=payload, headers=get_headers(), timeout=timeout)


# ---------------------------------------------------------------- duration
def get_exact_sport_duration_minutes(m):
    cat = str(m.get("category") or "").lower()
    tour = str(m.get("tournament") or m.get("eventName") or "").lower()
    t1 = str(m.get("teamAName") or m.get("teamA") or m.get("team1") or "").lower()
    t2 = str(m.get("teamBName") or m.get("teamB") or m.get("team2") or "").lower()
    title = str(m.get("title") or m.get("name") or "").lower()
    c = f"{cat} {tour} {title} {t1} {t2}"

    is_semi = has_word(c, ["semi", "semifinal", "semi-final", "semifinals"])
    is_quarter = has_word(c, ["quarter", "quarterfinal", "quarter-final", "quarterfinals"])
    is_final = has_word(c, ["final", "finals"]) and not is_semi and not is_quarter
    is_ko = is_semi or is_quarter or has_word(
        c, ["round of 16", "round of 8", "round of 32", "r16", "r32", "playoff", "play-off", "knockout"])

    # 1. Full-day streams
    if has_word(c, ["evento", "sports live", "tv channel"]):
        if has_word(c, ["cycling"]): return 480
        if has_word(c, ["golf"]): return 720
        if has_word(c, ["table tennis", "tabel tennis", "judo", "wrestling"]): return 480
        return 960

    # 2. Tennis (table tennis আলাদা)
    if has_word(c, ["table tennis", "tabel tennis"]): return 180
    if has_word(c, ["tennis"]):
        if is_final or has_word(c, ["grand slam", "wimbledon", "us open", "french open", "australian open"]):
            return 330
        return 240

    # 3. Cricket (T20 আগে, তারপর ODI)
    if has_word(c, ["cricket"]) or "cricket" in cat:
        if has_word(c, ["test", "ranji", "sheffield", "county", "4-day", "four day"]): return 540
        if has_word(c, ["ipl", "indian premier"]): return 260 if is_final else 240
        if has_word(c, ["t20", "t20i", "bpl", "psl", "bbl", "big bash", "cpl", "sa20", "mlc", "ilt20",
                        "legends", "road safety", "wcl", "super smash"]):
            return 260 if is_final else 230
        if has_word(c, ["the hundred", "hundred"]): return 160
        if has_word(c, ["t15"]): return 140
        if has_word(c, ["t10", "ten10", "abu dhabi"]): return 100
        if has_word(c, ["t5", "sixes"]): return 60
        if has_word(c, ["odi", "one day", "50 over", "world cup", "trophy", "u19"]):
            return 540 if is_final else 510
        return 230

    # 4. American Football (সাধারণ football-এর আগে)
    if has_word(c, ["nfl", "american football", "cfl", "ncaa"]):
        return 400 if is_final else 360

    # 5. Football / Soccer
    if has_word(c, ["football", "soccer"]) or "football" in cat or "soccer" in cat:
        if is_final: return 210
        if is_ko: return 195
        return 180

    # 6. Basketball
    if has_word(c, ["nba", "basketball", "fiba", "euroleague"]):
        return 210 if (is_final or is_ko) else 180

    # 7. Baseball
    if has_word(c, ["baseball", "mlb", "npb", "kbo"]): return 220

    # 8. Combat
    if has_word(c, ["wwe", "raw", "smackdown", "nxt", "aew", "tna", "wrestling"]):
        if has_word(c, ["raw"]): return 200
        if has_word(c, ["ple", "wrestlemania", "royal rumble", "summer slam", "summerslam"]): return 260
        return 150
    if has_word(c, ["ufc", "mma", "one fight", "bellator"]): return 240
    if has_word(c, ["boxing"]): return 210

    # 9. Motorsports
    if has_word(c, ["formula 1", "f1"]): return 140
    if has_word(c, ["motogp", "sbk"]): return 70
    if has_word(c, ["nascar"]): return 240
    if has_word(c, ["wrc", "rally"]): return 360

    # 10. Others
    if has_word(c, ["horse racing", "horse"]): return 600
    if has_word(c, ["racing"]): return 480
    if has_word(c, ["snooker"]): return 270
    if has_word(c, ["darts", "pdc"]): return 140
    if has_word(c, ["hockey", "nhl"]): return 180
    if has_word(c, ["kabaddi"]): return 70
    return 180


# ---------------------------------------------------------------- identity
def get_signature(d):
    """ম্যাচ চেনার key: টিম জোড়া (sorted), না থাকলে title."""
    a = clean_name(d.get("teamAName") or d.get("teamA") or d.get("team1"))
    b = clean_name(d.get("teamBName") or d.get("teamB") or d.get("team2"))
    if a and b:
        return ("teams",) + tuple(sorted([a, b]))
    title = clean_name(d.get("eventName") or d.get("name") or d.get("tournament") or d.get("title"))
    if a and not b:
        return ("single", a)
    if title:
        return ("title", title)
    return None


def is_placeholder(d):
    a = clean_name(d.get("teamAName") or d.get("teamA"))
    return a in ["teama", "livematch"]


def same_match(sig1, dt1, sig2, dt2):
    if not sig1 or sig1 != sig2:
        return False
    if dt1 is None or dt2 is None:
        return False
    return abs(dt1 - dt2) <= SAME_MATCH_WINDOW


def saved_start(ev, item_db):
    return parse_saved_dt(ev.get("date") or item_db.get("date"), ev.get("time") or item_db.get("time"))


def saved_end(ev, item_db, start):
    e_date = ev.get("end_date") or item_db.get("end_date")
    e_time = ev.get("end_time") or item_db.get("end_time")
    end = parse_saved_dt(e_date, e_time) if (e_date and e_time) else None
    if end is None and start is not None:
        end = start + timedelta(minutes=get_exact_sport_duration_minutes(ev))
    return end


# ---------------------------------------------------------------- panel API
def get_my_saved_events():
    try:
        res = post_json("admin/select", {"from": "events"}, timeout=20)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get("events") or data.get("data") or []
        else:
            print(f"[Panel Error] admin/select HTTP {res.status_code}: {res.text[:180]}")
    except Exception as e:
        print(f"[Panel Connection Error] admin/select: {e}")
    return []


def delete_event(event_id):
    payload = {"id": int(event_id) if str(event_id).isdigit() else str(event_id)}
    try:
        r = post_json("admin/delete_event", payload, timeout=12)
        return r.status_code in [200, 201]
    except Exception as e:
        print(f"Error deleting {event_id}:", e)
        return False


# ---------------------------------------------------------------- steps
def remove_duplicate_events_step(my_events):
    kept = []  # (sig, start_dt, id)
    deleted = 0
    for item_db in my_events:
        event_id = item_db.get("id")
        if not event_id:
            continue
        ev = unpack_event(item_db)
        sig = get_signature(ev) or get_signature(item_db)
        start = saved_start(ev, item_db)
        if not sig or start is None:
            continue

        dup = any(same_match(sig, start, k_sig, k_dt) for k_sig, k_dt, _ in kept)
        if dup:
            if delete_event(event_id):
                deleted += 1
                print(f"[Duplicate Removed] ID: {event_id} | {sig[1:]} | {bd_str(start)}")
                time.sleep(0.8)
        else:
            kept.append((sig, start, event_id))
    return deleted


def delete_expired_events_step(my_events):
    now_utc = datetime.now(timezone.utc)
    finished = []
    for item_db in my_events:
        event_id = item_db.get("id")
        if not event_id:
            continue
        ev = unpack_event(item_db)
        start = saved_start(ev, item_db)
        if start is None:
            continue
        end = saved_end(ev, item_db, start)
        if end and end < now_utc:
            finished.append({
                "id": event_id, "end": end,
                "t_a": ev.get("teamAName") or item_db.get("teamAName") or "Event",
                "t_b": ev.get("teamBName") or item_db.get("teamBName") or "",
            })

    finished.sort(key=lambda x: x["end"], reverse=True)
    deleted = 0
    for item in finished[KEEP_FINISHED_LIMIT:]:
        if delete_event(item["id"]):
            deleted += 1
            LINKS_CACHE.pop(str(item["id"]), None)
            print(f"[Auto Deleted Old Finished] ID: {item['id']} | {item['t_a']} vs {item['t_b']}")
            time.sleep(0.8)
    return deleted


def format_links_data(streaming_links):
    formatted = []
    if not streaming_links or not isinstance(streaming_links, list):
        return formatted

    n = 0
    for item in streaming_links:
        if not isinstance(item, dict):
            continue
        raw_name = str(item.get("name") or "").strip()
        url = str(item.get("link") or item.get("url") or "").strip()

        ua = "Mozilla/5.0"
        m = re.split(r"\|user-agent=", url, maxsplit=1, flags=re.I)
        if len(m) == 2:
            url, ua = m[0].strip(), m[1].strip()

        if not url.startswith("http"):
            continue

        api_key = str(item.get("api") or item.get("drmKey") or item.get("key") or item.get("license") or "").strip()
        token_api = str(item.get("tokenApi") or "").strip()
        is_mpd = ".mpd" in url.lower()
        n += 1

        up = raw_name.upper()
        if re.search(r"\b(4K|UHD)\b", up):
            display = f"DLSPORTS 4K {n}"
        elif re.search(r"\b(HD|FHD|1080P?)\b", up):
            display = f"DLSPORTS HD {n}"
        else:
            display = f"DLSPORTS {n}"

        formatted.append({
            "name": display, "link": url, "url": url, "stream_url": url,
            "headers": {"User-Agent": ua}, "user_agent": ua,
            "type": "mpd" if is_mpd else "m3u8",
            "api": api_key, "tokenApi": token_api, "key": api_key, "drmKey": api_key,
        })
    return formatted


def feed_get(f, *keys):
    for k in keys:
        v = f.get(k)
        if v:
            return v
    return ""


def feed_times(f):
    """(start_utc, end_utc) — feed-এ end না থাকলে sport duration দিয়ে হিসাব."""
    start = parse_feed_dt(f.get("date"), f.get("time"))
    if start is None:
        return None, None
    end = parse_feed_dt(f.get("end_date"), f.get("end_time"))
    if end is None or end <= start:
        end = start + timedelta(minutes=get_exact_sport_duration_minutes(f))
    return start, end


def feed_status(f):
    return str(f.get("matchStatus") or f.get("status") or "").lower()


def add_new_events_step(live_feed, my_events):
    now_utc = datetime.now(timezone.utc)
    added = 0

    for f in live_feed:
        if added >= MAX_ADD_PER_RUN:
            break
        if not isinstance(f, dict):
            continue

        start, end = feed_times(f)
        if start is None:
            continue
        if feed_status(f) in ENDED_STATUSES:
            continue
        if end < now_utc:  # শেষ হয়ে গেছে। চলমান (start <= now < end) ম্যাচ add হবে
            continue

        t_a = feed_get(f, "teamAName", "teamA", "team1")
        t_b = feed_get(f, "teamBName", "teamB", "team2")
        title = feed_get(f, "eventName", "name") or f"{t_a} vs {t_b}"

        sig = get_signature(f)
        if not sig:
            continue

        exists = False
        for item_db in my_events:
            ev = unpack_event(item_db)
            db_sig = get_signature(ev) or get_signature(item_db)
            db_start = saved_start(ev, item_db)
            if same_match(sig, start, db_sig, db_start):
                exists = True
                break
        if exists:
            continue

        links = format_links_data(f.get("streaming_links") or f.get("links") or [])

        s_date, s_time = fmt_store(start)
        e_date, e_time = fmt_store(end)
        slug = f"links/{int(time.time() * 1000)}_{added}"

        new_event = {
            "visible": True, "isHot": False, "priority": 0,
            "category": f.get("category") or "Football",
            "eventName": title,
            "eventLogo": fix_image_url(f.get("eventLogo") or f.get("tournament_logo")),
            "teamAName": t_a, "teamBName": t_b,
            "teamAFlag": fix_image_url(f.get("teamAFlag") or f.get("team1_logo")),
            "teamBFlag": fix_image_url(f.get("teamBFlag") or f.get("team2_logo")),
            "date": s_date, "time": s_time,
            "notiThumb": "", "countryCodes": "", "whitelistCountryCodes": "",
            "messages": "{}",
            "end_date": e_date, "end_time": e_time,
            "links": slug,
        }
        links_json = json.dumps(links)
        payload = {
            "event": json.dumps(new_event),
            "links": links_json, "linksData": links_json, "linksPath": slug,
        }

        ok = False
        for attempt in range(3):
            try:
                r = post_json("admin/add_event", payload)
                if r.status_code in [200, 201]:
                    added += 1
                    ok = True
                    my_events.append(new_event)
                    print(f"[Added {added}/{MAX_ADD_PER_RUN}] {t_a} vs {t_b} | BD: {bd_str(start)} | Links: {len(links)}")
                    time.sleep(1.5)
                    break
                print(f"[Add Failed #{attempt + 1}] {t_a} vs {t_b} | HTTP {r.status_code}: {r.text[:140]}")
            except Exception as ex:
                print(f"[Add Exception #{attempt + 1}] {t_a} vs {t_b}: {ex}")
            time.sleep(1.2)
        if not ok:
            print(f"[Skipped/Failed] {t_a} vs {t_b}")

    return added


def find_feed_match(sig, start, feed_index):
    best, best_diff = None, None
    for fsig, fstart, f in feed_index:
        if fsig == sig and fstart is not None:
            diff = abs(fstart - start)
            if diff <= SAME_MATCH_WINDOW and (best is None or diff < best_diff):
                best, best_diff = f, diff
    return best


def sync_streaming_links_step(live_feed, my_events):
    now_utc = datetime.now(timezone.utc)

    feed_index = []
    for f in live_feed:
        if not isinstance(f, dict):
            continue
        fsig = get_signature(f)
        fstart = parse_feed_dt(f.get("date"), f.get("time"))
        if fsig and fstart:
            feed_index.append((fsig, fstart, f))

    updated = 0
    for item_db in my_events:
        event_id = item_db.get("id")
        if not event_id:
            continue
        ev = unpack_event(item_db)
        if is_placeholder(ev):
            continue

        sig = get_signature(ev) or get_signature(item_db)
        start = saved_start(ev, item_db)
        if not sig or start is None:
            continue

        f = find_feed_match(sig, start, feed_index)
        if not f:
            continue

        new_ev = dict(ev)
        f_start, f_end = feed_times(f)
        s_date, s_time = fmt_store(f_start)
        new_ev["date"], new_ev["time"] = s_date, s_time

        status = feed_status(f)
        cur_end = saved_end(ev, item_db, start)
        if status in ENDED_STATUSES:
            # আগেই শেষ হয়ে থাকলে আবার বদলাবো না
            if cur_end is None or cur_end > now_utc:
                e_date, e_time = fmt_store(now_utc - timedelta(minutes=5))
                new_ev["end_date"], new_ev["end_time"] = e_date, e_time
        else:
            e_date, e_time = fmt_store(f_end)
            new_ev["end_date"], new_ev["end_time"] = e_date, e_time

        # Links: feed-এ link না থাকলে পুরোনো link overwrite করবো না
        formatted = format_links_data(f.get("streaming_links") or f.get("links") or [])
        links_changed = False
        links_json = None
        if formatted:
            links_json = json.dumps(formatted, sort_keys=True)
            h = hash(links_json)
            if LINKS_CACHE.get(str(event_id)) != h:
                links_changed = True

        event_changed = new_ev != ev
        if not event_changed and not links_changed:
            continue

        links_path = str(item_db.get("linksPath") or ev.get("linksPath") or ev.get("links") or f"links/{event_id}")
        payload = {"id": str(event_id), "event": json.dumps(new_ev), "linksPath": links_path}
        if links_changed:
            payload["linksData"] = json.dumps(formatted)

        try:
            r = post_json("admin/update_event", payload, timeout=12)
            if r.status_code == 200:
                updated += 1
                if links_changed:
                    LINKS_CACHE[str(event_id)] = hash(links_json)
                print(f"[Updated] ID: {event_id} | {ev.get('teamAName')} vs {ev.get('teamBName')} | "
                      f"status: {status or '-'} | event:{event_changed} links:{links_changed}")
                time.sleep(0.5)
            else:
                print(f"[Update Failed] ID: {event_id} | HTTP {r.status_code}: {r.text[:120]}")
        except Exception as e:
            print(f"Error updating ID {event_id}:", e)

    return updated


# ---------------------------------------------------------------- main
def normalize_feed(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ["matches", "events", "data", "result", "results"]:
            if isinstance(data.get(k), list):
                return data[k]
    return []


def run_single_sync_cycle():
    if not FEED_SOURCE:
        print("Error: SECRET_FEED_SOURCE environment variable is not configured.")
        return

    print(f"\n[Cycle Started (BD): {datetime.now(BD_TZ).strftime('%Y-%m-%d %I:%M:%S %p')}]")
    my_events = get_my_saved_events()
    print(f"Total Events in Panel: {len(my_events)}")

    dup_removed = remove_duplicate_events_step(my_events)
    if dup_removed:
        time.sleep(1.5)
        my_events = get_my_saved_events()

    deleted = delete_expired_events_step(my_events)
    if deleted:
        time.sleep(1.5)
        my_events = get_my_saved_events()

    try:
        res = requests.get(FEED_SOURCE, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        if res.status_code != 200:
            print("Feed fetch failed:", res.status_code)
            return
        live_feed = normalize_feed(res.json())
    except Exception as e:
        print("Feed load error:", e)
        return

    print(f"Total Matches in Feed: {len(live_feed)}")

    added = add_new_events_step(live_feed, my_events)
    if added:
        time.sleep(1.5)
        my_events = get_my_saved_events()

    updated = sync_streaming_links_step(live_feed, my_events)

    print("==========================================")
    print(f"Cycle Done | Dup Removed: {dup_removed} | Expired Deleted: {deleted} | Added: {added} | Synced: {updated}")
    print("==========================================")


def main():
    if os.getenv("GITHUB_ACTIONS") == "true" or os.getenv("SINGLE_RUN") == "true":
        run_single_sync_cycle()
        return

    print("Starting Continuous Auto-Sync Engine (5-minute loop)...")
    while True:
        try:
            run_single_sync_cycle()
        except Exception as e:
            print("Cycle Error:", e)
        print(f"Sleeping for {LOOP_INTERVAL_SECONDS} seconds...")
        time.sleep(LOOP_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
