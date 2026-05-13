import json
import time
import base64
from collections import defaultdict
import requests
from typing import Dict, List, Optional
from cryptography.hazmat.primitives.asymmetric import ed25519

# ================================
# CONFIG
# ================================

BASE_URL = "https://gateway.polymarket.us"
EVENTS_FILE = "statics/all_polymarket_us_events.json"
STATICS_FILE = "statics/statics.json"

# Per-market-type mapping output files
EVENT_MARKET_MAPPING_FILES = {
    "moneyline": "statics/polymarket_us_event_to_market_mapping.json",
    "spread":    "statics/polymarket_us_spread_event_to_market_mapping.json",
    "total":     "statics/polymarket_us_total_event_to_market_mapping.json",
}

# Per-market-type ASSET_ID_MAPPING keys inside statics.json
STATICS_ASSET_ID_KEYS = {
    "moneyline": "Polymarket_US",
    "spread":    "Polymarket_US_Spread",
    "total":     "Polymarket_US_Total",
}

PAGE_LIMIT = 1000
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
    """Fetch all Polymarket US events with pagination + retry logic."""
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
                print(f"Error: {e} - retrying in {backoff}s ({retries}/{MAX_RETRIES})")
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


def save_all_events():
    events = fetch_all_events()
    with open(EVENTS_FILE, "w") as f:
        json.dump(events, f, indent=4)
    print(f"\nSaved {len(events)} events to {EVENTS_FILE}")


# ================================
# MARKET-TYPE NORMALIZATION
# ================================
# Polymarket exposes the discriminator under two related fields. The
# preferred field is `marketType` ("moneyline", "spreads", "totals",
# "futures", ...). For older or partially-populated rows we fall back to
# `sportsMarketTypeV2` ("SPORTS_MARKET_TYPE_MONEYLINE", "..._SPREAD",
# "..._TOTAL", ...). Note Polymarket's marketType uses plurals for
# spread / total (`spreads`, `totals`) and singular for moneyline.

_MARKETTYPE_TO_NORMALIZED = {
    "moneyline": "moneyline",
    "spreads":   "spread",
    "spread":    "spread",
    "totals":    "total",
    "total":     "total",
}

_SPORTSMARKETTYPEV2_TO_NORMALIZED = {
    "SPORTS_MARKET_TYPE_MONEYLINE": "moneyline",
    "SPORTS_MARKET_TYPE_SPREAD":    "spread",
    "SPORTS_MARKET_TYPE_TOTAL":     "total",
}


def get_market_type(market: dict) -> Optional[str]:
    """Return one of "moneyline" / "spread" / "total" (or None) using
    `marketType` first and falling back to `sportsMarketTypeV2`."""
    mt = market.get("marketType")
    if mt in _MARKETTYPE_TO_NORMALIZED:
        return _MARKETTYPE_TO_NORMALIZED[mt]

    smtv2 = market.get("sportsMarketTypeV2")
    if smtv2 in _SPORTSMARKETTYPEV2_TO_NORMALIZED:
        return _SPORTSMARKETTYPEV2_TO_NORMALIZED[smtv2]

    return None


# ================================
# BUILD EVENT -> MARKET MAPPING (per market type)
# ================================

def build_event_to_market_mapping(market_type: str):
    """Build category -> series -> event -> { title, subtitle, market_slugs }
    for the given market type. Also updates statics.json's ASSET_ID_MAPPING
    under the appropriate venue key."""
    if market_type not in EVENT_MARKET_MAPPING_FILES:
        raise ValueError(
            "Unknown market_type " + repr(market_type)
            + "; expected one of " + str(sorted(EVENT_MARKET_MAPPING_FILES))
        )

    out_path = EVENT_MARKET_MAPPING_FILES[market_type]
    statics_key = STATICS_ASSET_ID_KEYS[market_type]

    polymarket_us_statics: Dict[str, str] = {}
    mapping = defaultdict(lambda: defaultdict(dict))

    with open(STATICS_FILE, "r") as f:
        statics = json.load(f)

    with open(EVENTS_FILE, "r") as f:
        events = json.load(f)

    for event in events:
        category = event.get("category", "")
        series = event.get("seriesSlug", "")
        event_slug = event.get("slug")

        title = (event.get("title") or "").lower()
        subtitle = (event.get("subtitle") or "").lower()

        if not event_slug:
            continue

        market_slugs: List[str] = []

        for market in event.get("markets", []):
            if get_market_type(market) != market_type:
                continue
            slug = market.get("slug")
            if slug:
                polymarket_us_statics[slug] = slug
                market_slugs.append(slug)

        if market_slugs:
            mapping[category][series][event_slug] = {
                "title": title,
                "subtitle": subtitle,
                "market_slugs": market_slugs,
            }

    # Update statics
    statics.setdefault("ASSET_ID_MAPPING", {})
    statics["ASSET_ID_MAPPING"][statics_key] = polymarket_us_statics

    with open(STATICS_FILE, "w") as f:
        json.dump(statics, f, indent=4)

    with open(out_path, "w") as f:
        json.dump(mapping, f, indent=4)

    n_events = sum(len(s) for c in mapping.values() for s in c.values())
    print(
        "[" + market_type + "] Saved "
        + str(n_events) + " events with "
        + str(len(polymarket_us_statics)) + " markets to " + out_path
    )


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
    print("Building event -> market mappings")
    print("==============================\n")
    for mt in ("moneyline", "spread", "total"):
        build_event_to_market_mapping(mt)

    print("\nDone in " + str(round(time.time() - start, 2)) + " seconds")
