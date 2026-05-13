"""Build Kalshi event -> market mappings and update statics.json.

Three market types are processed and each gets its own
ASSET_ID_MAPPING bucket plus its own event-to-market mapping JSON:

    Kalshi          (moneyline)  -> kalshi_event_to_market_mapping.json
    Kalshi_Spread   (spread)     -> kalshi_spread_event_to_market_mapping.json
    Kalshi_Total    (total)      -> kalshi_total_event_to_market_mapping.json

The moneyline path also populates CORRELATED_MARKET_MAPPING with the
two-market pairing used by the existing arbitrage code. Spread and total
events have many strike-bucket markets per event, so we instead store an
intra-event correlation under CORRELATED_SPREAD_MARKET_MAPPING and
CORRELATED_TOTAL_MARKET_MAPPING (each market ticker -> all other tickers
in the same Kalshi event).
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json

MIN_CLOSE_TS = 1   # days from now (set to 0 to disable lower bound)
MAX_CLOSE_TS = 30  # days from now (set to 0 to disable upper bound)

STATICS_PATH = "statics/statics.json"

MARKET_TYPE_CONFIG = {
    "moneyline": {
        "events_path": "statics/two_market_events.json",
        "mapping_path": "statics/kalshi_event_to_market_mapping.json",
        "asset_id_key": "Kalshi",
        "correlated_key": "CORRELATED_MARKET_MAPPING",
        "expected_market_count": 2,
    },
    "spread": {
        "events_path": "statics/kalshi_spread_events.json",
        "mapping_path": "statics/kalshi_spread_event_to_market_mapping.json",
        "asset_id_key": "Kalshi_Spread",
        "correlated_key": "CORRELATED_SPREAD_MARKET_MAPPING",
        "expected_market_count": None,
    },
    "total": {
        "events_path": "statics/kalshi_total_events.json",
        "mapping_path": "statics/kalshi_total_event_to_market_mapping.json",
        "asset_id_key": "Kalshi_Total",
        "correlated_key": "CORRELATED_TOTAL_MARKET_MAPPING",
        "expected_market_count": None,
    },
}


def get_min_max_close_time():
    now = datetime.now(timezone.utc)
    min_close_ts = now + timedelta(days=MIN_CLOSE_TS)
    max_close_ts = now + timedelta(days=MAX_CLOSE_TS)
    return min_close_ts, max_close_ts


def _load_json(path):
    with open(path, "r") as f:
        return json.load(f)


def _save_json(path, payload):
    with open(path, "w") as f:
        json.dump(payload, f, indent=4)


def _normalize_event_envelope(item):
    """The detailed event endpoint returns event/markets envelopes.
    Return (event_dict, markets_list) regardless of input shape."""
    if isinstance(item, dict) and "event" in item and "markets" in item:
        return item["event"], item.get("markets", []) or []
    return item, item.get("markets", []) or []


def update_statics_for_market_type(market_type):
    """Build mapping + asset id table + correlated mapping for one
    Kalshi market type and persist to statics + per-type JSON file."""
    if market_type not in MARKET_TYPE_CONFIG:
        raise ValueError(
            "Unknown market_type " + repr(market_type)
            + "; expected one of " + str(sorted(MARKET_TYPE_CONFIG))
        )

    cfg = MARKET_TYPE_CONFIG[market_type]
    events_path = cfg["events_path"]
    mapping_path = cfg["mapping_path"]
    asset_id_key = cfg["asset_id_key"]
    correlated_key = cfg["correlated_key"]
    expected_count = cfg["expected_market_count"]

    events = _load_json(events_path)
    statics = _load_json(STATICS_PATH)

    asset_id_mapping = {}
    correlated_mapping = {}
    mapping = defaultdict(lambda: defaultdict(dict))

    min_time, max_time = get_min_max_close_time()
    print("[" + market_type + "] Min Close Time: " + str(min_time))
    print("[" + market_type + "] Max Close Time: " + str(max_time))

    skipped_window = 0
    skipped_count = 0

    for item in events:
        event, markets = _normalize_event_envelope(item)

        tickers = []
        in_window_count = 0
        for market in markets:
            ticker = market.get("ticker")
            if not ticker:
                continue
            tickers.append(ticker)

            close_time_str = market.get("close_time")
            if close_time_str:
                try:
                    ct = datetime.fromisoformat(
                        close_time_str.replace("Z", "+00:00")
                    )
                    if (MIN_CLOSE_TS == 0 and MAX_CLOSE_TS == 0) or (
                        min_time <= ct <= max_time
                    ):
                        in_window_count += 1
                except ValueError:
                    in_window_count += 1
            else:
                in_window_count += 1

        if not tickers:
            continue

        if in_window_count == 0:
            skipped_window += 1
            continue

        if expected_count is not None and len(tickers) != expected_count:
            skipped_count += 1
            continue

        for t in tickers:
            asset_id_mapping[t] = t

        for t in tickers:
            correlated_mapping[t] = [other for other in tickers if other != t]

        category = event.get("category", "")
        series = event.get("series_ticker", "")
        event_ticker = event.get("event_ticker", "")
        title = (event.get("title") or "").lower()
        subtitle = (event.get("sub_title") or "").lower()

        if not event_ticker:
            continue

        mapping[category][series][event_ticker] = {
            "title": title,
            "subtitle": subtitle,
            "market_slugs": tickers,
        }

    statics.setdefault("ASSET_ID_MAPPING", {})
    statics["ASSET_ID_MAPPING"][asset_id_key] = asset_id_mapping
    statics[correlated_key] = correlated_mapping

    _save_json(STATICS_PATH, statics)
    _save_json(mapping_path, mapping)

    n_events = sum(len(s) for c in mapping.values() for s in c.values())
    print(
        "[" + market_type + "] Saved " + str(len(asset_id_mapping))
        + " markets across " + str(n_events) + " events to " + mapping_path
    )
    if skipped_window:
        print("[" + market_type + "] Skipped "
              + str(skipped_window) + " events outside close window")
    if skipped_count:
        print("[" + market_type + "] Skipped "
              + str(skipped_count) + " events failing market-count filter")


def update_statics_with_kalshi_events(events_path, statics_path, event_to_market_mapping_path):
    """Legacy entry point preserved for callers that still pass paths
    explicitly. Behaves like the moneyline path of
    update_statics_for_market_type but honors the supplied paths."""
    events = _load_json(events_path)
    statics = _load_json(statics_path)

    asset_id_mapping = {}
    correlated_mapping = {}
    mapping = defaultdict(lambda: defaultdict(dict))

    min_time, max_time = get_min_max_close_time()

    for item in events:
        event, markets = _normalize_event_envelope(item)
        tickers = []
        in_window = 0
        for market in markets:
            ticker = market.get("ticker")
            if not ticker:
                continue
            tickers.append(ticker)
            ct_str = market.get("close_time")
            if ct_str:
                try:
                    ct = datetime.fromisoformat(ct_str.replace("Z", "+00:00"))
                    if min_time <= ct <= max_time:
                        in_window += 1
                except ValueError:
                    in_window += 1
            else:
                in_window += 1

        if len(tickers) == 2 and in_window == 2:
            asset_id_mapping[tickers[0]] = tickers[0]
            asset_id_mapping[tickers[1]] = tickers[1]
            correlated_mapping[tickers[0]] = [tickers[1]]
            correlated_mapping[tickers[1]] = [tickers[0]]

        category = event.get("category", "")
        series = event.get("series_ticker", "")
        event_ticker = event.get("event_ticker", "")
        if not event_ticker:
            continue
        if tickers:
            mapping[category][series][event_ticker] = {
                "title": (event.get("title") or "").lower(),
                "subtitle": (event.get("sub_title") or "").lower(),
                "market_slugs": tickers,
            }

    statics.setdefault("ASSET_ID_MAPPING", {})
    statics["ASSET_ID_MAPPING"]["Kalshi"] = asset_id_mapping
    statics["CORRELATED_MARKET_MAPPING"] = correlated_mapping

    _save_json(statics_path, statics)
    _save_json(event_to_market_mapping_path, mapping)
    print("Saved mapping to " + event_to_market_mapping_path)


if __name__ == "__main__":
    for mt in ("moneyline", "spread", "total"):
        try:
            update_statics_for_market_type(mt)
        except FileNotFoundError as e:
            print("[" + mt + "] Skipping - missing input file: " + str(e))
