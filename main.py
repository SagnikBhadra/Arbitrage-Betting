import asyncio
from datetime import datetime
import json
import logging
from logging.handlers import RotatingFileHandler
import time
import sys
import websocket
import uuid
from decimal import Decimal

# Position Manager
from position_manager import PositionManager

# Strategy modules
from intra_kalshi_arbitrage import IntraKalshiArbitrage
from cross_exchange_arbitrage import CrossExchangeArbitrage

# Market data modules
from polymarket_us_feed import PolymarketUSWebSocket
from kalshi_feed import KalshiWebSocket

# Gateway modules
from polymarket_us_http_gateway import PolymarketUSHTTPGateway
from kalshi_http_gateway import KalshiHTTPGateway, load_private_key

from setup_loggers import setup_logging, stop_logging
from utils import get_asset_ids, get_maker_fees_kalshi, get_taker_fees_kalshi
from collections import defaultdict

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
def load_kalshi_key_id(secrets_path: str = "kalshi_secrets.json") -> str:
    with open(secrets_path, "r") as f:
        data = json.load(f)
    return data["KEY_ID"]

KEY_ID = load_kalshi_key_id()
PRIVATE_KEY_PATH = "Kalshi.key"
MARKET_TICKER = ["KXNBAMVP-26-LDON",
                "KXNBAMVP-26-SGIL",
                 "KXNBAMVP-26-NJOK"]  # Replace with any open market
WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"

# Polymarket US Configuration
POLYMARKET_US_CHANNEL_TYPE = "markets"  # use market for public price/book updates
POLYMARKET_US_API_KEY = "8f004f3b-4858-4401-a979-ca189946cde1"
POLYMARKET_US_PRIVATE_KEY_FILE_PATH = "polymarket.key"
POLYMARKET_US_BASE_URL = "https://api.polymarket.us"
POLYMARKET_US_WS_URL_BASE = "wss://api.polymarket.us"

def get_static_mapping(filename: str, static_name: str):
    with open(filename, 'r') as f:
        statics = json.load(f)
    return statics[static_name]

def intra_kalshi_arbitrage(kalshi_client, kalshi_gateway, position_manager, correlated_market_mapping, profit_threshold=0.01):

    # Create object
    intra_kalshi_arb_strategy = IntraKalshiArbitrage(
        kalshi_client,
        kalshi_gateway,
        position_manager,
        correlated_market_mapping,
        profit_threshold
    )
    
    return intra_kalshi_arb_strategy

def crossed_markets(polymarket_client, kalshi_client, kalshi_gateway, polymarket_us_gateway, position_manager, polymarket_kalshi_mapping):

    cross_exchange_arb_strategy = CrossExchangeArbitrage(
        polymarket_client,
        kalshi_client,
        polymarket_us_gateway,
        kalshi_gateway,
        position_manager,
        polymarket_kalshi_mapping,
        min_edge=0.01
    )

    return cross_exchange_arb_strategy


def wide_spreads():
    pass

async def scan_inefficiencies(polymarket_client, kalshi_client, kalshi_gateway, polymarket_us_gateway):
    # Cross exchange mapping between Polymarket and Kalshi markets
    polymarket_kalshi_mapping = get_static_mapping("statics/cross_exchange_statics.json", "POLYMARKET_KALSHI_MAPPING")
    moneyline_events = polymarket_kalshi_mapping["Moneyline_Events"]
    # Intra Kalshi correlated markets mapping
    correlated_market_mapping = get_static_mapping("statics/statics.json", "CORRELATED_MARKET_MAPPING")
    
    # Wait until feeds are subscribed
    while not kalshi_client.subscribed:
        await asyncio.sleep(2)
    
    # Load positions
    positions = kalshi_gateway.get_positions()
    position_manager = PositionManager(positions)
    
    # Create strategy objects
    strategies = []
    # Intra Kalshi
    #strategies.append(intra_kalshi_arbitrage(kalshi_client, kalshi_gateway, position_manager, correlated_market_mapping, profit_threshold=0.01))
    # Cross exchange
    strategies.append(crossed_markets(polymarket_client, kalshi_client, kalshi_gateway, polymarket_us_gateway, position_manager, moneyline_events))

    # Call find_opportunities() every second and log any opportunities above profit_threshold
    while True:
        # Snapshot on the event loop (no contention, single-threaded)
        kalshi_book_snapshots = kalshi_client.snapshot_all_books()
        polymarket_us_book_snapshots = polymarket_client.snapshot_all_books()

        for strategy in strategies:
            # Run strategy in a worker thread so the event loop stays
            # free to process incoming WS messages (no sync-over-async)
            await asyncio.to_thread(strategy.find_opportunities, kalshi_book_snapshots, polymarket_us_book_snapshots)
        await asyncio.sleep(1)

async def main():
    # TODO: Add deque to best bid/ask and only compare if timestamp is within delta
    # TODO: Track time span between market opportunity and when it's resolved
    
    # Initialize HTTP gateway for order execution
    private_key_pem = load_private_key(PRIVATE_KEY_PATH)
    kalshi_gateway = KalshiHTTPGateway(KEY_ID, private_key_pem)
    polymarket_us_gateway = PolymarketUSHTTPGateway(POLYMARKET_US_API_KEY, POLYMARKET_US_PRIVATE_KEY_FILE_PATH, POLYMARKET_US_BASE_URL)

    polymarket_us_client = PolymarketUSWebSocket(POLYMARKET_US_WS_URL_BASE, POLYMARKET_US_CHANNEL_TYPE, get_asset_ids("Polymarket_US"), POLYMARKET_US_API_KEY, POLYMARKET_US_PRIVATE_KEY_FILE_PATH)
    kalshi_client = KalshiWebSocket(KEY_ID, PRIVATE_KEY_PATH, get_asset_ids("Kalshi"), WS_URL)
    
    await asyncio.gather(
        polymarket_us_client.run(),
        kalshi_client.orderbook_websocket(),
        scan_inefficiencies(polymarket_us_client, kalshi_client, kalshi_gateway, polymarket_us_gateway)
    )

if __name__ == "__main__":
    # Only apply this fix on Windows
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    setup_logging()
    try:
        asyncio.run(main())
    finally:
        stop_logging()