import asyncio
import websocket

from polymarket_feed import PolymarketWebSocket
from Kalshi import KalshiWebSocket

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
MARKET_TICKER = "KXNBAMVP-26-LDON"  # Replace with any open market
WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"

def crossed_markets():
    pass

def wide_spreads():
    pass

async def scan_inefficiencies(polymarket_client, kalshi_client):
    pass

async def main():
    # TODO: Add deque to best bid/ask and only compare if timestamp is within delta
    
    polymarket_client = PolymarketWebSocket(WS_URL_BASE, ASSET_IDS, CHANNEL_TYPE)
    kalshi_client = KalshiWebSocket(KEY_ID, PRIVATE_KEY_PATH, MARKET_TICKER, WS_URL)
    await asyncio.gather(
        polymarket_client.run(),
        kalshi_client.orderbook_websocket()
    )

if __name__ == "__main__":
    
    asyncio.run(main())