import asyncio
import json
import websocket
import uuid
from decimal import Decimal

from polymarket_feed import PolymarketWebSocket
from kalshi_feed import KalshiWebSocket
from kalshi_http_gateway import KalshiHTTPGateway, load_private_key
from utils import get_asset_ids, get_maker_fees_kalshi, get_taker_fees_kalshi
from collections import defaultdict

# WebSocket endpoint for Polymarket CLOB service
WS_URL_BASE = "wss://ws-subscriptions-clob.polymarket.com"
overall_order_count = 0
overall_profit = 0.0

last_best_ask_price_by_ticker = defaultdict()
last_best_bid_price_by_ticker = defaultdict()

# Cached balance to avoid API calls on every order
cached_balance = 0.0

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

def get_static_mapping(static_name: str):
    with open('statics/statics.json', 'r') as f:
        statics = json.load(f)
    return statics[static_name]

def check_and_update_balance(kalshi_gateway, required_amount):
    """Check if we have sufficient balance for the trade.
    
    Args:
        kalshi_gateway: The Kalshi HTTP gateway
        required_amount: Amount needed in dollars
    
    Returns:
        bool: True if sufficient balance, False otherwise
    """
    global cached_balance
    try:
        balance_response = kalshi_gateway.get_balance()
        cached_balance = balance_response.get("balance", 0) / 100.0  # Convert cents to dollars
        return cached_balance >= required_amount
    except Exception as e:
        print(f"Error fetching balance: {e}")
        return False

def intra_kalshi_arbitrage(kalshi_client, kalshi_gateway, correlated_market_mapping, profit_threshold=0.00):
    """Identify intra-market arbitrage opportunities within Kalshi markets.

    Args:
        kalshi_client (KalshiWebSocket): The Kalshi WebSocket client instance which contains orderbooks.
        kalshi_gateway (KalshiHTTPGateway): The Kalshi HTTP gateway for placing orders.
    """
    global overall_order_count, overall_profit, cached_balance
    
    for ticker, orderbook in kalshi_client.orderbooks.items():
        # Get correlated markets
        correlated_tickers = correlated_market_mapping.get(ticker, [])
        best_bid, best_bid_size = orderbook.get_best_bid()
        best_ask, best_ask_size = orderbook.get_best_ask()
        last_best_bid = -1
        last_correlated_best_bid = -1
        last_best_ask = -1
        last_correlated_best_ask = -1

        # Does not work for more than 2 correlated markets yet
        if correlated_tickers:
            for correlated_ticker in correlated_tickers:
                correlated_orderbook = kalshi_client.orderbooks.get(correlated_ticker)
                if correlated_orderbook:
                    correlated_best_bid, correlated_best_bid_size = correlated_orderbook.get_best_bid()
                    correlated_best_ask, correlated_best_ask_size = correlated_orderbook.get_best_ask()
                    
                    # Buy Team A yes & Buy Team B yes
                    if best_ask and correlated_best_ask:
                        if ticker in last_best_ask_price_by_ticker:
                            last_best_ask = last_best_ask_price_by_ticker[ticker]
                        last_best_ask_price_by_ticker[ticker] = best_ask
                        if correlated_ticker in last_best_ask_price_by_ticker:
                            last_correlated_best_ask = last_best_ask_price_by_ticker[correlated_ticker]
                        last_best_ask_price_by_ticker[correlated_ticker] = correlated_best_ask
                        if (last_best_ask != -1 and best_ask != last_best_ask) or (last_correlated_best_ask != -1 and correlated_best_ask != last_correlated_best_ask):
                            pass
                        else:
                            continue
                        
                        # Calculate cost of trade (including fees) and potential profit
                        fees = get_taker_fees_kalshi(float(best_ask), float(best_ask_size)) + get_taker_fees_kalshi(float(correlated_best_ask), float(correlated_best_ask_size))
                        combined_price = float(best_ask) + float(correlated_best_ask) + float(fees)
                        profit_threshold = float(-fees)
                        if combined_price <= 1.0 - profit_threshold:
                            order_size = int(min(float(best_ask_size), float(correlated_best_ask_size)))
                            
                            # Calculate required balance (cost of both orders)
                            required_balance = (float(best_ask) + float(correlated_best_ask)) * order_size
                            overall_order_count += order_size
                            overall_profit += (1.0 - combined_price) * order_size / 100.0
                            
                            # Check balance before placing orders
                            if not check_and_update_balance(kalshi_gateway, required_balance):
                                print(f"Insufficient balance. Required: ${required_balance:.2f}, Available: ${cached_balance:.2f}")
                                continue
                            
                            print(f"Intra-Kalshi Arbitrage Opportunity: Buy YES on {ticker} at {best_ask} and Buy YES on {correlated_ticker} at {correlated_best_ask} of size {order_size} | Combined Price: {combined_price}")
                            

                            # Buy YES on ticker
                            order_a = {
                                "ticker": ticker,
                                "action": "buy",
                                "side": "yes",
                                "count": order_size,
                                "client_order_id": str(uuid.uuid4()),
                                "yes_price": int(float(best_ask) * 100),
                                "type": "limit",
                            }
                            try:
                                kalshi_gateway.create_order(order_a)
                            except Exception as e:
                                print(f"Failed to place order A: {e}")
                                continue
                            
                            # Buy YES on correlated ticker
                            order_b = {
                                "ticker": correlated_ticker,
                                "action": "buy",
                                "side": "yes",
                                "count": order_size,
                                "client_order_id": str(uuid.uuid4()),
                                "yes_price": int(float(correlated_best_ask) * 100),
                                "type": "limit",
                            }
                            try:
                                kalshi_gateway.create_order(order_b)
                            except Exception as e:
                                print(f"Failed to place order B: {e}")
                                continue

                    # Buy Team A no & Buy Team B no
                    if best_bid and correlated_best_bid:
                        if ticker in last_best_bid_price_by_ticker:
                            last_best_bid = last_best_bid_price_by_ticker[ticker]
                        last_best_bid_price_by_ticker[ticker] = best_bid
                        if correlated_ticker in last_best_bid_price_by_ticker:
                            last_correlated_best_bid = last_best_bid_price_by_ticker[correlated_ticker]
                        last_best_bid_price_by_ticker[correlated_ticker] = correlated_best_bid
                        if (last_best_bid != -1 and best_bid != last_best_bid) or (last_correlated_best_bid != -1 and correlated_best_bid != last_correlated_best_bid):
                            pass
                        else:
                            continue
                        
                        best_no_ask = 1.0 - float(best_bid)
                        best_correlated_no_ask = 1.0 - float(correlated_best_bid)
                        fees = get_taker_fees_kalshi(float(best_bid), float(best_bid_size)) + get_taker_fees_kalshi(float(correlated_best_bid), float(correlated_best_bid_size))
                        combined_price = best_no_ask + best_correlated_no_ask + float(fees)
                        profit_threshold = float(-fees)
                        if combined_price <= 1.0 - profit_threshold:
                            order_size = int(min(float(best_bid_size), float(correlated_best_bid_size)))
                            
                            # Calculate required balance (cost of both orders)
                            required_balance = (best_no_ask + best_correlated_no_ask) * order_size
                            overall_order_count += order_size
                            overall_profit += (1.0 - combined_price) * order_size / 100.0
                            # Check balance before placing orders
                            if not check_and_update_balance(kalshi_gateway, required_balance):
                                print(f"Insufficient balance. Required: ${required_balance:.2f}, Available: ${cached_balance:.2f}")
                                continue
                            
                            print(f"Intra-Kalshi Arbitrage Opportunity: Buy NO on {ticker} at {best_no_ask} and Buy NO on {correlated_ticker} at {best_correlated_no_ask} of size {order_size} | Combined Price: {combined_price}")
                            

                            # Buy NO on ticker
                            order_a = {
                                "ticker": ticker,
                                "action": "buy",
                                "side": "no",
                                "count": order_size,
                                "client_order_id": str(uuid.uuid4()),
                                "no_price": int(best_no_ask * 100),
                                "type": "limit",
                            }
                            try:
                                kalshi_gateway.create_order(order_a)
                            except Exception as e:
                                print(f"Failed to place order A: {e}")
                                continue
                            
                            # Buy NO on correlated ticker
                            order_b = {
                                "ticker": correlated_ticker,
                                "action": "buy",
                                "side": "no",
                                "count": order_size,
                                "client_order_id": str(uuid.uuid4()),
                                "no_price": int(best_correlated_no_ask * 100),
                                "type": "limit",
                            }
                            try:
                                kalshi_gateway.create_order(order_b)
                            except Exception as e:
                                print(f"Failed to place order B: {e}")
                                continue
                                
                print(f"Overall Orders Placed: {overall_order_count}, Overall Potential Profit: ${overall_profit:.2f}, Balance: ${cached_balance:.2f}")

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

async def scan_inefficiencies(polymarket_client, kalshi_client, kalshi_gateway):
    polymarket_kalshi_mapping = get_static_mapping("POLYMARKET_KALSHI_MAPPING")
    correlated_market_mapping = get_static_mapping("CORRELATED_MARKET_MAPPING")
    while True:
        #crossed_markets(polymarket_client, kalshi_client, polymarket_kalshi_mapping)
        intra_kalshi_arbitrage(kalshi_client, kalshi_gateway, correlated_market_mapping, profit_threshold=0.02)
        await asyncio.sleep(1)

async def main():
    # TODO: Add deque to best bid/ask and only compare if timestamp is within delta
    # TODO: Track time span between market opportunity and when it's resolved
    
    # Initialize HTTP gateway for order execution
    private_key_pem = load_private_key(PRIVATE_KEY_PATH)
    kalshi_gateway = KalshiHTTPGateway(KEY_ID, private_key_pem)

    polymarket_client = PolymarketWebSocket(WS_URL_BASE, CHANNEL_TYPE, get_asset_ids("Polymarket"))
    kalshi_client = KalshiWebSocket(KEY_ID, PRIVATE_KEY_PATH, get_asset_ids("Kalshi"), WS_URL)
    await asyncio.gather(
        #polymarket_client.run(),
        kalshi_client.orderbook_websocket(),
        scan_inefficiencies(polymarket_client, kalshi_client, kalshi_gateway)
    )

if __name__ == "__main__":
    
    asyncio.run(main())