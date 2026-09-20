import json
import requests

FEED_SOURCE = "https://s1.noobon.top/axsx/streamx.php"

def check_feed_keys():
    try:
        res = requests.get(FEED_SOURCE, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        data = res.json()
        print("=== FEED STRUCTURE (FIRST ITEM) ===")
        if isinstance(data, list) and len(data) > 0:
            print(json.dumps(data[0], indent=2))
        elif isinstance(data, dict):
            # ডিকশনারি হলে ভেতরের প্রথম আইটেম
            first_key = list(data.keys())[0]
            print(f"Key: {first_key}")
            sample = data[first_key]
            if isinstance(sample, list) and len(sample) > 0:
                print(json.dumps(sample[0], indent=2))
            else:
                print(json.dumps(sample, indent=2))
    except Exception as e:
        print("Error reading feed:", e)

if __name__ == "__main__":
    check_feed_keys()
