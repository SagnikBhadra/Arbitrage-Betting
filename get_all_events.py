import json
import time
import asyncio
import aiohttp
import requests
from requests.exceptions import ConnectionError, Timeout, HTTPError

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2/events"
PAGE_LIMIT = 200
MAX_RETRIES = 5
INITIAL_BACKOFF = 1  # seconds
MAX_CONCURRENT_REQUESTS = 3  # Reduced to avoid rate limiting
REQUEST_DELAY = 0.5  # Delay between batches of requests


def fetch_all_events(status="open"):
    """Fetch all events from Kalshi API with pagination support.
    
    Args:
        status: Filter by event status ('open', 'closed', etc.)
    
    Returns:
        List of event dictionaries
    """
    all_events = []
    cursor = None

    while True:
        params = {
            "limit": PAGE_LIMIT,
            "status": status,
        }
        if cursor:
            params["cursor"] = cursor

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
                print(f"Request failed: {e}. Retrying in {backoff}s… ({retries}/{MAX_RETRIES})")
                time.sleep(backoff)
                backoff *= 2
            except HTTPError as e:
                print(f"HTTP error: {e}. Aborting.")
                return all_events
        else:
            print("Max retries exceeded. Stopping.")
            return all_events

        # Process events
        events = data.get("events", [])
        all_events.extend(events)
        print(f"Fetched {len(events)} events. Total: {len(all_events)}")

        # Continue pagination
        cursor = data.get("cursor")
        if not cursor:
            break

    return all_events


async def fetch_event_details_async(session, event_ticker, semaphore, counter, total):
    """Fetch detailed data for a specific event asynchronously.
    
    Args:
        session: aiohttp ClientSession
        event_ticker: The event ticker to fetch details for
        semaphore: Semaphore to limit concurrent requests
        counter: Shared counter dict for progress tracking
        total: Total number of events to fetch
    
    Returns:
        Event details dictionary or None if failed
    """
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
                print(f"[{counter['done']}/{total}] Request failed for {event_ticker}: {e}. Retrying in {backoff}s… ({retries}/{MAX_RETRIES})")
                await asyncio.sleep(backoff)
                backoff *= 2
        
        counter["done"] += 1
        print(f"[{counter['done']}/{total}] Max retries exceeded for {event_ticker}. Skipping.")
        return None


async def fetch_all_mutually_exclusive_details_async(mutually_exclusive_events):
    """Fetch detailed data for all mutually exclusive events concurrently.
    
    Args:
        mutually_exclusive_events: List of mutually exclusive event dictionaries
    
    Returns:
        List of detailed event data
    """
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    event_tickers = [e.get("event_ticker") for e in mutually_exclusive_events if e.get("event_ticker")]
    total = len(event_tickers)
    counter = {"done": 0}  # Shared mutable counter
    
    print(f"Fetching details for {total} events...")
    
    async with aiohttp.ClientSession() as session:
        tasks = [
            fetch_event_details_async(session, ticker, semaphore, counter, total)
            for ticker in event_tickers
        ]
        results = await asyncio.gather(*tasks)
    
    # Filter out None results
    detailed_events = [r for r in results if r is not None]
    return detailed_events


def fetch_all_mutually_exclusive_details(mutually_exclusive_events):
    """Wrapper to run async fetch synchronously.
    
    Args:
        mutually_exclusive_events: List of mutually exclusive event dictionaries
    
    Returns:
        List of detailed event data
    """
    return asyncio.run(fetch_all_mutually_exclusive_details_async(mutually_exclusive_events))


def process_event_data(events):
    """Separate events by mutually_exclusive flag.
    
    Args:
        events: List of event dictionaries from Kalshi API
    
    Returns:
        Tuple of (mutually_exclusive_events, non_mutually_exclusive_events)
    """
    mutually_exclusive = []
    non_mutually_exclusive = []
    
    for event in events:
        if event.get("mutually_exclusive", False):
            mutually_exclusive.append(event)
        else:
            non_mutually_exclusive.append(event)
    
    return mutually_exclusive, non_mutually_exclusive


if __name__ == "__main__":
    start_time = time.time()
    
    events = fetch_all_events(status="open")
    
    print(f"\n{'='*50}")
    print(f"Total events fetched: {len(events)}")
    print(f"{'='*50}\n")
    
    # Process and separate events
    mutually_exclusive, non_mutually_exclusive = process_event_data(events)
    
    print(f"Mutually exclusive events: {len(mutually_exclusive)}")
    print(f"Non-mutually exclusive events: {len(non_mutually_exclusive)}")
    
    # Fetch detailed data for mutually exclusive events (concurrent)
    print(f"\n{'='*50}")
    print("Fetching detailed data for mutually exclusive events...")
    print(f"{'='*50}\n")
    
    detailed_mutually_exclusive = fetch_all_mutually_exclusive_details(mutually_exclusive)
    
    print(f"\nSuccessfully fetched details for {len(detailed_mutually_exclusive)} events")
    
    # Filter events with exactly 2 markets
    two_market_events = []
    for event_data in detailed_mutually_exclusive:
        markets = event_data.get("markets", [])
        if len(markets) == 2:
            two_market_events.append(event_data)
    
    print(f"\n{'='*50}")
    print(f"Events with exactly 2 markets: {len(two_market_events)}")
    print(f"{'='*50}\n")
    
    for event_data in two_market_events:
        event = event_data.get("event", {})
        event_ticker = event.get("event_ticker", "N/A")
        title = event.get("title", "N/A")
        markets = event_data.get("markets", [])
        
        print(f"{event_ticker}: {title}")
        for market in markets:
            ticker = market.get("ticker", "N/A")
            subtitle = market.get("subtitle", "N/A")
            yes_bid = market.get("yes_bid", "N/A")
            yes_ask = market.get("yes_ask", "N/A")
            print(f"  - {ticker}: {subtitle} (Bid: {yes_bid}, Ask: {yes_ask})")
        print()
    
    # Save all events
    output_path = "statics/events.json"
    with open(output_path, "w") as f:
        json.dump(events, f, indent=4)
    print(f"Saved all events to {output_path}")
    
    # Save mutually exclusive events (detailed)
    me_detailed_output_path = "statics/mutually_exclusive_events_detailed.json"
    with open(me_detailed_output_path, "w") as f:
        json.dump(detailed_mutually_exclusive, f, indent=4)
    print(f"Saved detailed mutually exclusive events to {me_detailed_output_path}")
    
    # Save two-market events
    two_market_output_path = "statics/two_market_events.json"
    with open(two_market_output_path, "w") as f:
        json.dump(two_market_events, f, indent=4)
    print(f"Saved two-market events to {two_market_output_path}")
    
    elapsed = time.time() - start_time
    print(f"\n{'='*50}")
    print(f"Total time: {elapsed:.2f} seconds")
    print(f"{'='*50}")