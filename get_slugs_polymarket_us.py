import json
import time
import base64
from collections import defaultdict
import requests
from typing import Dict, List
from cryptography.hazmat.primitives.asymmetric import ed25519

# ================================
# CONFIG
# ================================

BASE_URL = "https://gateway.polymarket.us"
EVENTS_FILE = "statics/all_polymarket_us_events.json"
EVENT_MARKET_MAPPING_FILE = "statics/polymarket_us_event_to_market_mapping.json"

PAGE_LIMIT = 200
MAX_RETRIES = 5
INITIAL_BACKOFF = 1


# ================================
# AUTH
# ================================

with open("polymarket.key", "r") as f:
    private_key_base64 = f.read().strip()

api_key_id = "8f004f3b-4858-4401-a979-ca189946cde1"

private_key = ed25519.Ed25519PrivateKey.from_private_bytes(
    base64.b64decode(private_key_base64)[:32]
)


def sign_request(method: str, path: str):
    timestamp = str(int(time.time() * 1000))
    message = f"{timestamp}{method}{path}"
    signature = base64.b64encode(private_key.sign(message.encode())).decode()

    return {
        "X-PM-Access-Key": api_key_id,
        "X-PM-Timestamp": timestamp,
        "X-PM-Signature": signature,
        "Content-Type": "application/json",
    }


# ================================
# FETCH ALL EVENTS
# ================================

def fetch_all_events() -> List[dict]:
    """
    Fetch all Polymarket US events with pagination + retry logic
    """
    all_events = []
    cursor = None

    while True:
        path = "/v1/events"
        params = {
            "limit": PAGE_LIMIT,
            "active": True,
            "closed": False,
            "archived": False,
        }

        if cursor:
            params["cursor"] = cursor

        retries = 0
        backoff = INITIAL_BACKOFF

        while retries < MAX_RETRIES:
            try:
                print(f"Fetching events... (cursor={cursor})")

                response = requests.get(
                    f"{BASE_URL}{path}",
                    headers=sign_request("GET", path),
                    params=params,
                    timeout=10,
                )

                response.raise_for_status()
                data = response.json()
                break

            except requests.exceptions.RequestException as e:
                retries += 1
                print(f"Error: {e} — retrying in {backoff}s ({retries}/{MAX_RETRIES})")
                time.sleep(backoff)
                backoff *= 2
        else:
            print("Max retries reached. Stopping.")
            return all_events

        events = data.get("events", [])
        all_events.extend(events)

        print(f"Fetched {len(events)} events. Total: {len(all_events)}")

        cursor = data.get("cursor")
        if not cursor:
            break

    return all_events


# ================================
# SAVE EVENTS
# ================================

def save_all_events():
    events = fetch_all_events()

    with open(EVENTS_FILE, "w") as f:
        json.dump(events, f, indent=4)

    print(f"\nSaved {len(events)} events to {EVENTS_FILE}")


# ================================
# BUILD EVENT -> MARKET MAPPING
# ================================

def build_event_to_market_mapping():
    """
    category -> series -> event -> metadata
    """
    mapping = defaultdict(lambda: defaultdict(dict))

    with open(EVENTS_FILE, "r") as f:
        events = json.load(f)

    for event in events:
        category = event.get("category", {})
        series = event.get("seriesSlug", {})
        event_slug = event.get("slug")
        
        
        title = event.get("title", "").lower()
        subtitle = event.get("subtitle", "").lower()

        if not event_slug:
            continue

        market_slugs = []

        for market in event.get("markets", []):
            slug = market.get("slug")
            if slug:
                market_slugs.append(slug)

        if market_slugs:
            mapping[category][series][event_slug] = {
                "title": title,
                "subtitle": subtitle,
                "market_slugs": market_slugs
            }

    with open(EVENT_MARKET_MAPPING_FILE, "w") as f:
        json.dump(mapping, f, indent=4)

    print(f"Saved mapping to {EVENT_MARKET_MAPPING_FILE}")


# ================================
# MAIN
# ================================

if __name__ == "__main__":
    start = time.time()

    print("\n==============================")
    print("Fetching all Polymarket US events")
    print("==============================\n")

    save_all_events()

    print("\n==============================")
    print("Building event -> market mapping")
    print("==============================\n")

    build_event_to_market_mapping()

    print(f"\nDone in {time.time() - start:.2f} seconds")