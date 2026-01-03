import asyncio
import json
import websocket

from polymarket_feed import PolymarketWebSocket
from kalshi_feed import KalshiWebSocket
from utils import get_asset_ids

# WebSocket endpoint for Polymarket CLOB service
WS_URL_BASE = "wss://ws-subscriptions-clob.polymarket.com"

# Your target tokens (clobTokenIds)
ASSET_IDS = [
    "29048360022556021389805670398008888482908398853670829781367251641936311260707", # Shai YES
    "114528627098181527180076013437205839368323282497361602702800503052375432480589", # Shai NO
    "73768610008619570600930429495180540710817177537162503586781057110775077618432", # Jokic YES
    "88794755386871079853762415286654635832909423950620116774027006364873482091563", # Jokic NO
    "89110596788673536475065853727140488937259064164063660201050220270400840228269", # Luka YES
    "101506943049053276934626391886226570064171431948041761918666910024462041911155" # Luka NO
]

CHANNEL_TYPE = "market"  # use market for public price/book updates

# Kalshi Configuration
KEY_ID = "7edd1c5d-6c0c-4458-bb77-04854221689b"
PRIVATE_KEY_PATH = "Kalshi.key"
MARKET_TICKER = ["KXNBAMVP-26-LDON",
                "KXNBAMVP-26-SGIL",
                 "KXNBAMVP-26-NJOK"]  # Replace with any open market
WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"

def get_static_mapping(static_name: str):
    with open('statics/statics.json', 'r') as f:
        statics = json.load(f)
    return statics[static_name]

def intra_kalshi_arbitrage(kalshi_client, correlated_market_mapping, profit_threshold=0.00):
    """Identify intra-market arbitrage opportunities within Kalshi markets.

    Args:
        kalshi_client (KalshiWebSocket): The Kalshi WebSocket client instance which contains orderbooks.
    """
    # Create a dict where Team A markets map to Team B markets
    # E.g. {Team A : {Team B}, Team B : {Team A}}
    # Pull ticker, orderbook from kalshi_client.orderbooks
    
    for ticker, orderbook in kalshi_client.orderbooks.items():
        # Get correlated markets
        correlated_tickers = correlated_market_mapping.get(ticker, [])
        best_bid, best_bid_size = orderbook.get_best_bid()
        best_ask, best_ask_size = orderbook.get_best_ask()
        
        # Does not work for more than 2 correlated markets yet
        if correlated_tickers:
            for correlated_ticker in correlated_tickers:
                correlated_orderbook = kalshi_client.orderbooks.get(correlated_ticker)
                if correlated_orderbook:
                    correlated_best_bid, correlated_best_bid_size = correlated_orderbook.get_best_bid()
                    correlated_best_ask, correlated_best_ask_size = correlated_orderbook.get_best_ask()
                    
                    # Buy Team A yes & Buy Team B yes
                    if best_bid and correlated_best_bid:
                        combined_price = best_bid + correlated_best_bid
                        if combined_price < 1 - profit_threshold:
                            print(f"Intra-Kalshi Arbitrage Opportunity: Buy on {ticker} at {best_bid} and Buy on {correlated_ticker} at {correlated_best_bid} of size {min(best_bid_size, correlated_best_bid_size)} | Combined Price: {combined_price}")

                    # Buy Team A no & Buy Team B no
                    if best_ask and correlated_best_ask:
                        combined_price = best_ask + correlated_best_ask
                        if combined_price < 1 - profit_threshold:
                            print(f"Intra-Kalshi Arbitrage Opportunity: Buy on {ticker} at {best_ask} and Buy on {correlated_ticker} at {correlated_best_ask} of size {min(best_ask_size, correlated_best_ask_size)} | Combined Price: {combined_price}")

                    # Buy Team A yes & Buy Team A no
                    if best_bid and best_ask:
                        combined_price = best_bid + best_ask
                        if combined_price < 1 - profit_threshold:
                            print(f"Intra-Kalshi Arbitrage Opportunity: Buy on {ticker} at {best_bid} and Sell on {ticker} at {best_ask} of size {min(best_bid_size, best_ask_size)} | Combined Price: {combined_price}")

                    # Buy Team B yes & Buy Team B no
                    if correlated_best_bid and correlated_best_ask:
                        combined_price = correlated_best_bid + correlated_best_ask
                        if combined_price < 1 - profit_threshold:
                            print(f"Intra-Kalshi Arbitrage Opportunity: Buy on {correlated_ticker} at {correlated_best_bid} and Buy on {correlated_ticker} at {correlated_best_ask} of size {min(correlated_best_bid_size, correlated_best_ask_size)} | Combined Price: {combined_price}")

def crossed_markets(polymarket_client, kalshi_client, polymarket_kalshi_mapping):
    for poly_asset_id, kalshi_ticker in polymarket_kalshi_mapping.items():
        if polymarket_client.orderbooks.get(poly_asset_id) and kalshi_client.orderbooks.get(kalshi_ticker):
            poly_orderbook = polymarket_client.orderbooks[poly_asset_id]
            kalshi_orderbook = kalshi_client.orderbooks[kalshi_ticker]
            
            poly_best_bid, poly_best_bid_size = poly_orderbook.get_best_bid()
            poly_best_ask, poly_best_ask_size = poly_orderbook.get_best_ask()
            kalshi_best_bid, kalshi_best_bid_size = kalshi_orderbook.get_best_bid()
            kalshi_best_ask, kalshi_best_ask_size = kalshi_orderbook.get_best_ask()
            
            if poly_best_bid and kalshi_best_ask and poly_best_bid > kalshi_best_ask:
                print(f"Arbitrage Opportunity: Buy on Kalshi at {kalshi_best_ask}, Sell on Polymarket at {poly_best_bid} of size {min(poly_best_bid_size, kalshi_best_ask_size)}")
            if kalshi_best_bid and poly_best_ask and kalshi_best_bid > poly_best_ask:
                print(f"Arbitrage Opportunity: Buy on Polymarket at {poly_best_ask}, Sell on Kalshi at {kalshi_best_bid} of size {min(kalshi_best_bid_size, poly_best_ask_size)}")

def wide_spreads():
    pass

async def scan_inefficiencies(polymarket_client, kalshi_client):
    polymarket_kalshi_mapping = get_static_mapping("POLYMARKET_KALSHI_MAPPING")
    correlated_market_mapping = get_static_mapping("CORRELATED_MARKET_MAPPING")
    while True:
        #crossed_markets(polymarket_client, kalshi_client, polymarket_kalshi_mapping)
        intra_kalshi_arbitrage(kalshi_client, correlated_market_mapping)
        await asyncio.sleep(1)

async def main():
    # TODO: Add deque to best bid/ask and only compare if timestamp is within delta
    # TODO: Track time span between market opportunity and when it's resolved
    

    polymarket_client = PolymarketWebSocket(WS_URL_BASE, CHANNEL_TYPE, get_asset_ids("Polymarket"))
    kalshi_client = KalshiWebSocket(KEY_ID, PRIVATE_KEY_PATH, get_asset_ids("Kalshi"), WS_URL)
    await asyncio.gather(
        polymarket_client.run(),
        kalshi_client.orderbook_websocket(),
        scan_inefficiencies(polymarket_client, kalshi_client)
    )

if __name__ == "__main__":
    
    asyncio.run(main())