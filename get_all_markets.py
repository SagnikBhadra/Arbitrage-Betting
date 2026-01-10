import time
import requests
from requests.exceptions import ConnectionError, Timeout, HTTPError

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2/markets"
PAGE_LIMIT = 500  # Lower page size can reduce server load
MAX_RETRIES = 5
INITIAL_BACKOFF = 1  # seconds

def fetch_all_market_tickers():
    ticker_map = {}
    cursor = None
    counter = 0

    while True:
        params = {"limit": PAGE_LIMIT,
                 "status": "open",}
        if cursor:
            params["cursor"] = cursor

        retries = 0
        backoff = INITIAL_BACKOFF

        while retries < MAX_RETRIES:
            print("Iteration Start")
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
                # If the server returns a 4xx/5xx, stop trying this page
                print(f"HTTP error: {e}. Aborting.")
                return ticker_map

        else:
            # Retries exhausted
            print("Max retries exceeded. Stopping.")
            return ticker_map

        # Process markets
        markets = data.get("markets", [])
        for m in markets:
            ticker = m.get("ticker")
            if ticker and ticker.startswith("KXNBAGAME") and ticker not in ticker_map:
                ticker_map[ticker] = ticker.split("-")[-1] + "_" + ticker.split("-")[1][:7] + "_WIN"
                counter += 1

        # Continue pagination
        cursor = data.get("cursor")
        if not cursor:
            break

    return ticker_map


if __name__ == "__main__":
    tickers = fetch_all_market_tickers()
    print("{")
    for t, i in tickers.items():
        print(f'  "{t}": {i},')
    print("}")
    print(f"\nTotal fetched: {len(tickers)}")
