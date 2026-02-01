import json
import time
import requests
from requests.exceptions import ConnectionError, Timeout, HTTPError

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2/markets"
PAGE_LIMIT = 500  # Lower page size can reduce server load
MAX_RETRIES = 5
INITIAL_BACKOFF = 1  # seconds

def fetch_all_market_tickers(series_ticker=""):
    ticker_map = {}
    cursor = None
    counter = 0

    while True:
        params = {
            "limit": PAGE_LIMIT,
            "status": "open",
        }
        # Add series_ticker filter to API request
        if series_ticker:
            params["series_ticker"] = series_ticker
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

        # Process markets - no client-side filtering needed
        markets = data.get("markets", [])
        for m in markets:
            ticker = m.get("ticker")
            if ticker and ticker not in ticker_map:
                ticker_map[ticker] = ticker.split("-")[-1] + "_" + ticker.split("-")[1][:7] + "_WIN"
                counter += 1

        # Continue pagination
        cursor = data.get("cursor")
        if not cursor:
            break

    return ticker_map


if __name__ == "__main__":
    json_path = 'statics/statics.json'
    with open(json_path, 'r') as f:
        data = json.load(f)
    
    correlated_market_mapping = {}
    kalshi_tickers = fetch_all_market_tickers("KXNBAGAME")
    tickers = list(kalshi_tickers.keys())
    for i in range(0, len(tickers), 2):
        if i + 1 < len(tickers):
            k1 = tickers[i]
            k2 = tickers[i + 1]
            correlated_market_mapping[k1] = [k2]
            correlated_market_mapping[k2] = [k1]
    
    data["ASSET_ID_MAPPING"]["Kalshi"] = kalshi_tickers
    data["ASSET_ID_MAPPING"]["CORRELATED_MARKET_MAPPING"] = correlated_market_mapping
    
    with open(json_path, 'w') as f:
        json.dump(data, f, indent=4)

    print(data["ASSET_ID_MAPPING"]["CORRELATED_MARKET_MAPPING"])

    print(f"\nTotal fetched: {len(tickers)}")
