from collections import defaultdict
import json
import time
import asyncio
import aiohttp
import requests
from datetime import datetime, timedelta, timezone
from requests.exceptions import ConnectionError, Timeout, HTTPError

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2/events"
PAGE_LIMIT = 200
MAX_RETRIES = 5
INITIAL_BACKOFF = 1  # seconds
MAX_CONCURRENT_REQUESTS = 3  # Reduced to avoid rate limiting
REQUEST_DELAY = 0.5  # Delay between batches of requests
MIN_CLOSE_TS = 2 # Set to 0 for all events
MAX_CLOSE_TS = 5 # Set to 0 for all events


# ----------------------------------------------------------------------
# Kalshi market-type identification
# ----------------------------------------------------------------------
# Per Kalshi docs and live data, sport game events expose a
# `product_metadata.competition_scope` field with values like:
#   - "Moneyline"   (game-level winner)
#   - "Spread"      (point spread vs strike)
#   - "Point Total" (over/under)
#   - "Series Spread", "Series Total Games" (playoff series)
#   - other niche scopes per league (e.g. "Total Maps" for esports)
#
# As a backup we also detect by series_ticker pattern, since most
# Kalshi sport series follow the convention of suffixing the series
# with SPREAD / TOTAL (e.g. KXNBASPREAD, KXMLBTOTAL, KXNHLSERIESSPREAD,
# KXCS2TOTALMAPS, KXNBASERIESGAMES).

SPREAD_SCOPES = {"Spread", "Series Spread", "1H Spread", "2H Spread"}
TOTAL_SCOPES = {
    "Point Total", "Total", "Team Total",
    "Series Total Games", "Total Maps",
    "1H Point Total", "2H Point Total",
}


def _series_ticker_matches(series_ticker, suffixes):
    """True if series_ticker ends with any of the given uppercase suffixes."""
    if not series_ticker:
        return False
    st = series_ticker.upper()
    return any(st.endswith(suffix) for suffix in suffixes)


def is_spread_event(event):
    """Return True if the (brief) event represents a Kalshi spread market."""
    scope = (event.get("product_metadata") or {}).get("competition_scope", "")
    if scope in SPREAD_SCOPES:
        return True
    return _series_ticker_matches(event.get("series_ticker"), ("SPREAD",))


def is_total_event(event):
    """Return True if the (brief) event represents a Kalshi total market."""
    scope = (event.get("product_metadata") or {}).get("competition_scope", "")
    if scope in TOTAL_SCOPES:
        return True
    return _series_ticker_matches(
        event.get("series_ticker"),
        ("TOTAL", "TOTALMAPS", "TEAMTOTAL", "SERIESGAMES"),
    )


def get_min_max_close_time():
    now = datetime.now(timezone.utc)
    min_close_ts = int((now + timedelta(days=MIN_CLOSE_TS)).timestamp())
    max_close_ts = int((now + timedelta(days=MAX_CLOSE_TS)).timestamp())
    return min_close_ts, max_close_ts


def fetch_all_events(status="open"):
    """Fetch all events from Kalshi API with pagination support."""
    all_events = []
    cursor = None

    while True:
        params = {"limit": PAGE_LIMIT, "status": status}
        if cursor:
            params["cursor"] = cursor
        if MIN_CLOSE_TS != 0 or MAX_CLOSE_TS != 0:
            min_close_ts, max_close_ts = get_min_max_close_time()
            params["min_close_ts"] = min_close_ts
            params["max_close_ts"] = max_close_ts

        retries = 0
        backoff = INITIAL_BACKOFF

        while retries < MAX_RETRIES:
            print(f"Fetching events... (cursor: {cursor})")
            try:
                response = requests.get(BASE_URL, params=params, timeout=10)
                response.raise_for_status()
                data = response.json()
                break
            except (ConnectionError, Timeout) as e:
                retries += 1
                print(f"Request failed: {e}. Retrying in {backoff}s ({retries}/{MAX_RETRIES})")
                time.sleep(backoff)
                backoff *= 2
            except HTTPError as e:
                print(f"HTTP error: {e}. Aborting.")
                return all_events
        else:
            print("Max retries exceeded. Stopping.")
            return all_events

        events = data.get("events", [])
        all_events.extend(events)
        print(f"Fetched {len(events)} events. Total: {len(all_events)}")

        cursor = data.get("cursor")
        if not cursor:
            break

    return all_events


async def fetch_event_details_async(session, event_ticker, semaphore, counter, total):
    """Fetch detailed data for a specific event asynchronously."""
    url = f"https://api.elections.kalshi.com/trade-api/v2/events/{event_ticker}"

    async with semaphore:
        retries = 0
        backoff = INITIAL_BACKOFF

        while retries < MAX_RETRIES:
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status == 200:
                        result = await response.json()
                        counter["done"] += 1
                        print(f"[{counter['done']}/{total}] Fetched: {event_ticker}")
                        await asyncio.sleep(REQUEST_DELAY)
                        return result
                    elif response.status == 429:
                        retry_after = int(response.headers.get("Retry-After", backoff))
                        print(f"[{counter['done']}/{total}] Rate limited for {event_ticker}. Waiting {retry_after}s...")
                        await asyncio.sleep(retry_after)
                        retries += 1
                        backoff *= 2
                    else:
                        counter["done"] += 1
                        print(f"[{counter['done']}/{total}] HTTP {response.status} for {event_ticker}. Skipping.")
                        return None
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                retries += 1
                print(f"[{counter['done']}/{total}] Request failed for {event_ticker}: {e}. Retrying in {backoff}s ({retries}/{MAX_RETRIES})")
                await asyncio.sleep(backoff)
                backoff *= 2

        counter["done"] += 1
        print(f"[{counter['done']}/{total}] Max retries exceeded for {event_ticker}. Skipping.")
        return None


async def fetch_event_details_batch_async(events):
    """Fetch detailed data for a list of events concurrently."""
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    event_tickers = [e.get("event_ticker") for e in events if e.get("event_ticker")]
    total = len(event_tickers)
    counter = {"done": 0}

    print(f"Fetching details for {total} events...")

    async with aiohttp.ClientSession() as session:
        tasks = [
            fetch_event_details_async(session, ticker, semaphore, counter, total)
            for ticker in event_tickers
        ]
        results = await asyncio.gather(*tasks)

    return [r for r in results if r is not None]


def fetch_event_details_batch(events):
    """Synchronous wrapper around the async batch fetcher."""
    return asyncio.run(fetch_event_details_batch_async(events))


# Backwards-compatible aliases
fetch_all_mutually_exclusive_details_async = fetch_event_details_batch_async
fetch_all_mutually_exclusive_details = fetch_event_details_batch


def process_event_data(events):
    """Separate events by mutually_exclusive flag."""
    mutually_exclusive = []
    non_mutually_exclusive = []
    for event in events:
        if event.get("mutually_exclusive", False):
            mutually_exclusive.append(event)
        else:
            non_mutually_exclusive.append(event)
    return mutually_exclusive, non_mutually_exclusive


def collect_volume(detailed_events, into=None):
    """Collect 24h volume per market ticker from a list of detailed events."""
    if into is None:
        into = defaultdict(int)
    for event_data in detailed_events:
        for market in event_data.get("markets", []):
            ticker = market.get("ticker")
            if not ticker:
                continue
            into[ticker] = market.get("volume_24h_fp", 0)
    return into


def print_event_summary(detailed_events, label=""):
    """Pretty-print a small summary of detailed events for sanity-checking."""
    if label:
        print(f"\n{'='*50}\n{label}: {len(detailed_events)} events\n{'='*50}")
    for event_data in detailed_events[:10]:
        event = event_data.get("event", {})
        event_ticker = event.get("event_ticker", "N/A")
        title = event.get("title", "N/A")
        markets = event_data.get("markets", [])
        print(f"{event_ticker}: {title} ({len(markets)} markets)")
        for market in markets[:5]:
            ticker = market.get("ticker", "N/A")
            subtitle = market.get("subtitle", "N/A")
            yes_bid = market.get("yes_bid", "N/A")
            yes_ask = market.get("yes_ask", "N/A")
            print(f"  - {ticker}: {subtitle} (Bid: {yes_bid}, Ask: {yes_ask})")
        if len(markets) > 5:
            print(f"  ... and {len(markets) - 5} more markets")


if __name__ == "__main__":
    start_time = time.time()

    events = fetch_all_events(status="open")

    print(f"\n{'='*50}")
    print(f"Total events fetched: {len(events)}")
    print(f"{'='*50}\n")

    # ------------------------------------------------------------------
    # Moneyline (existing flow): mutually_exclusive events with 2 markets
    # ------------------------------------------------------------------
    mutually_exclusive, non_mutually_exclusive = process_event_data(events)
    print(f"Mutually exclusive events: {len(mutually_exclusive)}")
    print(f"Non-mutually exclusive events: {len(non_mutually_exclusive)}")

    print(f"\n{'='*50}\nFetching detailed data for mutually exclusive events...\n{'='*50}\n")
    detailed_mutually_exclusive = fetch_event_details_batch(mutually_exclusive)
    print(f"\nSuccessfully fetched details for {len(detailed_mutually_exclusive)} ME events")

    two_market_events = [
        ed for ed in detailed_mutually_exclusive if len(ed.get("markets", [])) == 2
    ]
    print(f"Events with exactly 2 markets (moneyline): {len(two_market_events)}")

    # ------------------------------------------------------------------
    # Spread / Total (new): identify by competition_scope or series ticker
    # ------------------------------------------------------------------
    spread_events_brief = [e for e in events if is_spread_event(e)]
    total_events_brief = [e for e in events if is_total_event(e)]
    print(f"\nBrief spread events identified: {len(spread_events_brief)}")
    print(f"Brief total events identified:  {len(total_events_brief)}")

    print(f"\n{'='*50}\nFetching detailed data for spread events...\n{'='*50}\n")
    detailed_spread_events = fetch_event_details_batch(spread_events_brief)

    print(f"\n{'='*50}\nFetching detailed data for total events...\n{'='*50}\n")
    detailed_total_events = fetch_event_details_batch(total_events_brief)

    # ------------------------------------------------------------------
    # Volume per market (moneyline + spread + total combined)
    # ------------------------------------------------------------------
    volume_per_market = defaultdict(int)
    collect_volume(two_market_events, into=volume_per_market)
    collect_volume(detailed_spread_events, into=volume_per_market)
    collect_volume(detailed_total_events, into=volume_per_market)

    print_event_summary(two_market_events, label="Moneyline (2-market) events")
    print_event_summary(detailed_spread_events, label="Spread events")
    print_event_summary(detailed_total_events, label="Total events")

    outputs = {
        "statics/events.json": events,
        "statics/mutually_exclusive_events_detailed.json": detailed_mutually_exclusive,
        "statics/two_market_events.json": two_market_events,
        "statics/kalshi_spread_events.json": detailed_spread_events,
        "statics/kalshi_total_events.json": detailed_total_events,
        "statics/kalshi_volume_per_market.json": volume_per_market,
    }
    for path, payload in outputs.items():
        with open(path, "w") as f:
            json.dump(payload, f, indent=4)
        print(f"Saved {path}")

    elapsed = time.time() - start_time
    print(f"\n{'='*50}\nTotal time: {elapsed:.2f} seconds\n{'='*50}")
