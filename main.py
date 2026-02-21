import asyncio
from datetime import datetime
import json
import logging
from logging.handlers import RotatingFileHandler
import websocket
import uuid
from decimal import Decimal

# Strategy modules
from intra_kalshi_arbitrage import IntraKalshiArbitrage
from cross_exchange_arbitrage import CrossExchangeArbitrage

# Market data modules
from polymarket_us_feed import PolymarketUSWebSocket
from kalshi_feed import KalshiWebSocket

# Gateway modules
from polymarket_us_http_gateway import PolymarketUSHTTPGateway
from kalshi_http_gateway import KalshiHTTPGateway, load_private_key

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


def define_logger(filename_prefix: str, logger_name: str):
    # ----------------------------
    # Create dated log filename
    # ----------------------------
    today_str = datetime.now().strftime("%Y-%m-%d")
    log_filename = f"logging/{filename_prefix}_{today_str}.log"

    # ----------------------------
    # Configure logger
    # ----------------------------
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)

    handler = RotatingFileHandler(
        log_filename,
        maxBytes=10_000_000,  # 10MB
        backupCount=5
    )

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s"
    )

    handler.setFormatter(formatter)
    logger.addHandler(handler)

    logger.propagate = False  # prevents duplicate logs
    
    return logger

def get_static_mapping(static_name: str):
    with open('statics/statics.json', 'r') as f:
        statics = json.load(f)
    return statics[static_name]

def intra_kalshi_arbitrage(kalshi_client, kalshi_gateway, correlated_market_mapping, profit_threshold=0.02):
    # Create logger
    intra_kalshi_logger = define_logger("intra_kalshi_arb", "IntraKalshiArb")

    # Create object
    intra_kalshi_arb_strategy = IntraKalshiArbitrage(
        kalshi_client,
        kalshi_gateway,
        correlated_market_mapping,
        logger=intra_kalshi_logger
    )

    # Call find_opportunities() every second and log any opportunities above profit_threshold
    intra_kalshi_arb_strategy.find_opportunities(profit_threshold=profit_threshold)

def crossed_markets(polymarket_client, kalshi_client, polymarket_kalshi_mapping):
    cross_arb_logger = define_logger("cross_exchange_arb", "CrossExchangeArb")

    cross_exchange_arb_strategy = CrossExchangeArbitrage(
        polymarket_client,
        kalshi_client,
        polymarket_kalshi_mapping,
        logger=cross_arb_logger,
        min_edge=0.02
    )

    opps = cross_exchange_arb_strategy.find_opportunities()

    for o in opps:
        cross_arb_logger.info(o)


def wide_spreads():
    pass

async def scan_inefficiencies(polymarket_client, kalshi_client, kalshi_gateway):
    # Cross exchange mapping between Polymarket and Kalshi markets
    polymarket_kalshi_mapping = get_static_mapping("POLYMARKET_KALSHI_MAPPING")
    # Intra Kalshi correlated markets mapping
    correlated_market_mapping = get_static_mapping("CORRELATED_MARKET_MAPPING")
    while True:
        crossed_markets(polymarket_client, kalshi_client, polymarket_kalshi_mapping)
        intra_kalshi_arbitrage(kalshi_client, kalshi_gateway, correlated_market_mapping, profit_threshold=0.02)
        await asyncio.sleep(1)

async def main():
    # TODO: Add deque to best bid/ask and only compare if timestamp is within delta
    # TODO: Track time span between market opportunity and when it's resolved
    
    # Initialize HTTP gateway for order execution
    private_key_pem = load_private_key(PRIVATE_KEY_PATH)
    kalshi_gateway = KalshiHTTPGateway(KEY_ID, private_key_pem)

    polymarket_us_client = PolymarketUSWebSocket(POLYMARKET_US_WS_URL_BASE, POLYMARKET_US_CHANNEL_TYPE, get_asset_ids("Polymarket_US"), POLYMARKET_US_API_KEY, POLYMARKET_US_PRIVATE_KEY_FILE_PATH)
    kalshi_client = KalshiWebSocket(KEY_ID, PRIVATE_KEY_PATH, get_asset_ids("Kalshi"), WS_URL)
    await asyncio.gather(
        polymarket_us_client.run(),
        kalshi_client.orderbook_websocket(),
        scan_inefficiencies(polymarket_us_client, kalshi_client, kalshi_gateway)
    )

if __name__ == "__main__":
    
    asyncio.run(main())