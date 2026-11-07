import base64
from datetime import datetime
import json
import time
import requests

BASE_URL = "https://dlsports.proapp.workers.dev/"


def generate_security_token():
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    b64 = base64.b64encode(now_str.encode("utf-8")).decode("utf-8")
    rev1 = b64[::-1]
    hex_str = "".join(f"{b:02x}" for b in rev1.encode("utf-8"))
    return hex_str[::-1]


def get_headers():
    return {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "okhttp/4.9.2",
    }


def delete_all_events():
    payload = {"from": "events", "requestData": generate_security_token()}
    try:
        res = requests.post(
            BASE_URL + "admin/select",
            json=payload,
            headers=get_headers(),
            timeout=20,
        )
        if res.status_code != 200:
            print(f"ইভেন্ট ফেচ করা যায়নি: HTTP {res.status_code}")
            return
        data = res.json()
        events = (
            data
            if isinstance(data, list)
            else (data.get("events") or data.get("data") or [])
        )
    except Exception as e:
        print(f"সার্ভার এরর: {e}")
        return

    total = len(events)
    if total == 0:
        print("কোনো ইভেন্ট পাওয়া যায়নি। প্যানেল ইতিমধ্যে খালি।")
        return

    print(f"মোট {total} টি ইভেন্ট পাওয়া গেছে।")
    print(
        "স্বয়ংক্রিয়ভাবে সব ইভেন্ট মুছে ফেলা শুরু হচ্ছে...\n" + "-" * 40
    )
    deleted = 0

    for idx, item in enumerate(events, 1):
        event_id = item.get("id")
        if not event_id:
            continue

        ev_data = item
        if "event" in item and isinstance(item["event"], str):
            try:
                ev_data = json.loads(item["event"])
            except Exception:
                pass

        t_a = ev_data.get("teamAName") or item.get("teamAName") or ""
        t_b = ev_data.get("teamBName") or item.get("teamBName") or ""
        name = (
            f"{t_a} vs {t_b}".strip()
            or ev_data.get("eventName")
            or f"ID: {event_id}"
        )

        del_payload = {
            "id": int(event_id) if str(event_id).isdigit() else str(event_id),
            "requestData": generate_security_token(),
        }

        try:
            del_res = requests.post(
                BASE_URL + "admin/delete_event",
                json=del_payload,
                headers=get_headers(),
                timeout=12,
            )
            if del_res.status_code in [200, 201]:
                deleted += 1
                print(f"[{idx}/{total}] ডিলিট হয়েছে: {name} (ID: {event_id})")
            else:
                print(
                    f"[{idx}/{total}] ব্যর্থ! ID: {event_id} | HTTP {del_res.status_code}"
                )
        except Exception as e:
            print(f"[{idx}/{total}] এরর (ID: {event_id}): {e}")

        # Worker রেট লিমিট এড়াতে বিরতি
        time.sleep(0.4)

    print("-" * 40)
    print(f"সম্পন্ন: মোট {deleted}/{total} টি ইভেন্ট মুছে ফেলা হয়েছে।")


if __name__ == "__main__":
    delete_all_events()
