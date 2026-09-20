import base64
from datetime import datetime
import json
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
        "User-Agent": "okhttp/4.9.2"
    }

def print_raw_server_data():
    payload = {
        "from": "app",
        "requestData": generate_security_token()
    }
    res = requests.post(BASE_URL + "admin/select", json=payload, headers=get_headers(), timeout=15)
    print("=== RAW SERVER RESPONSE ===")
    print(res.text)

if __name__ == "__main__":
    print_raw_server_data()
