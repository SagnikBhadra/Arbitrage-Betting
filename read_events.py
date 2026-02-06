import json
from collections import defaultdict
def read_and_display_markets(file_path="statics/two_market_events.json"):
    """Read events from JSON file and display all markets.
    
    Args:
        file_path: Path to the JSON file containing event data
    """
    with open(file_path, "r") as f:
        events = json.load(f)
    
    print(f"Total events: {len(events)}\n")
    print("="*80)
    
    total_markets = 0
    complimentary_markets = defaultdict(list)   
    namr_market = defaultdict(str)
    for event_data in events[::-1][:20]:
        event = event_data.get("event", {})
        event_ticker = event.get("event_ticker", "N/A")
        title = event.get("title", "N/A")
        markets = event_data.get("markets", [])

        
        if markets:
            print(f"\n{event_ticker}: {title}")
            print(f"  Markets ({len(markets)}):")
            complimentary_markets[markets[0]['ticker']].append(markets[1]['ticker'])
            complimentary_markets[markets[1]['ticker']].append(markets[0]['ticker'])
            namr_market[markets[0]['ticker']] = str(markets[0]['ticker'])
            namr_market[markets[1]['ticker']] = str(markets[1]['ticker'])
            """            
            for market in markets:
                # Handle both string and dict formats
                if isinstance(market, str):
                    print(f"    - {market}")
                elif isinstance(market, dict):
                    ticker = market.get("ticker", "N/A")
                    subtitle = market.get("subtitle", "N/A")
                    yes_bid = market.get("yes_bid", "N/A")
                    yes_ask = market.get("yes_ask", "N/A")
                    volume = market.get("volume", "N/A")
                    status = market.get("status", "N/A")
                    
                    print(f"    - {ticker}")
                    print(f"        {subtitle}")
                    print(f"        Bid: {yes_bid} | Ask: {yes_ask} | Volume: {volume} | Status: {status}")
                else:
                    print(f"    - {market}")
            
            total_markets += len(markets)
            """
    print(complimentary_markets)
    print(namr_market)  
    
    print(f"\n{'='*80}")
    print(f"Total markets: {total_markets}")


if __name__ == "__main__":
    read_and_display_markets()