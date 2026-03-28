from datetime import datetime, timedelta, timezone
import json

MIN_CLOSE_TS = 1 # Set to 0 for all events
MAX_CLOSE_TS = 30 # Set to 0 for all events

def get_min_max_close_time():
    # Set market close times
    now = datetime.now(timezone.utc)
    min_close_ts = now + timedelta(days=MIN_CLOSE_TS)
    max_close_ts = now + timedelta(days=MAX_CLOSE_TS)
    return min_close_ts, max_close_ts

def update_statics_with_kalshi_events(events_path, statics_path):
    # Load events
    with open(events_path, "r") as f:
        events = json.load(f)

    # Load statics
    with open(statics_path, "r") as f:
        statics = json.load(f)

    # Prepare Kalshi mapping and correlated mapping
    kalshi_mapping = {}
    correlated_mapping = {}
    
    min_time, max_time = get_min_max_close_time()
    print(f"Min Close Time: {min_time}")
    print(f"Max Close Time: {max_time}")

    for event in events:
        # Extract event_tickers from event["markets"]
        tickers = []
        close_times = []
        for market in event["markets"]:
            tickers.append(market["ticker"])
            ct = datetime.fromisoformat(market["close_time"].replace("Z", "+00:00"))
            print(f"Min time: {min_time} | Close time: {ct} | Max time: {max_time}")
            if min_time <= ct <= max_time:
                print("Here")
                close_times.append(ct) 
            
        if len(tickers) == 2 and len(close_times) == 2:
            # Store the list in Kalshi mapping (use a unique key, e.g., first ticker)
            kalshi_mapping[tickers[0]] = tickers[0]
            kalshi_mapping[tickers[1]] = tickers[1]
            # Store correlated tickers
            correlated_mapping[tickers[0]] = [tickers[1]]
            correlated_mapping[tickers[1]] = [tickers[0]]

    # Update statics
    statics["ASSET_ID_MAPPING"]["Kalshi"] = kalshi_mapping
    statics["CORRELATED_MARKET_MAPPING"] = correlated_mapping

    # Write back to statics.json
    with open(statics_path, "w") as f:
        json.dump(statics, f, indent=4)

# Example usage:
update_statics_with_kalshi_events("statics/two_market_events.json", "statics/statics.json")