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

def get_polymarket_kalshi_mapping():
    with open('statics/statics.json', 'r') as f:
        statics = json.load(f)
    return statics["POLYMARKET_KALSHI_MAPPING"]

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

async def scan_inefficiencies(polymarket_client, kalshi_client, polymarket_kalshi_mapping):
    while True:
        crossed_markets(polymarket_client, kalshi_client, polymarket_kalshi_mapping)
        await asyncio.sleep(1)

async def main():
    # TODO: Add deque to best bid/ask and only compare if timestamp is within delta
    # TODO: Track time span between market opportunity and when it's resolved
    
    polymarket_kalshi_mapping = get_polymarket_kalshi_mapping()
    
    polymarket_client = PolymarketWebSocket(WS_URL_BASE, CHANNEL_TYPE, get_asset_ids("Polymarket"))
    kalshi_client = KalshiWebSocket(KEY_ID, PRIVATE_KEY_PATH, get_asset_ids("Kalshi"), WS_URL)
    await asyncio.gather(
        polymarket_client.run(),
        kalshi_client.orderbook_websocket(),
        scan_inefficiencies(polymarket_client, kalshi_client, polymarket_kalshi_mapping)
    )

if __name__ == "__main__":
    
    asyncio.run(main())