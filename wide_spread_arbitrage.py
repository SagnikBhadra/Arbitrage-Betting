import json
import logging
import math
import uuid
from decimal import Decimal

from polymarket_us_feed import PolymarketUSWebSocket
from polymarket_us_http_gateway import PolymarketUSHTTPGateway
from kalshi_feed import KalshiWebSocket
from kalshi_http_gateway import KalshiHTTPGateway, load_private_key
from position_manager import PositionManager
from utils import get_maker_fees_kalshi, get_taker_fees_kalshi, get_taker_fees_polymarket_us, get_maker_rebate_polymarket_us
from collections import defaultdict

class WideSpreadArbitrage:
    def __init__(self, polymarket_client: PolymarketUSWebSocket, kalshi_client: KalshiWebSocket, polymarket_us_gateway: PolymarketUSHTTPGateway, kalshi_gateway: KalshiHTTPGateway, position_manager: PositionManager, mapping: dict, spread_threshold: Decimal = Decimal(0.05), min_edge: Decimal = Decimal(0.01)):
        self.polymarket_client = polymarket_client
        self.polymarket_us_gateway = polymarket_us_gateway
        self.kalshi_client = kalshi_client
        self.kalshi_gateway = kalshi_gateway
        self.position_manager = position_manager
        self.spread_threshold = Decimal(spread_threshold)

        #Temporary balance tracking
        self.polymarket_us_balance = Decimal(self.polymarket_us_gateway.get_balance())
        self.kalshi_balance = Decimal(self.kalshi_gateway.get_balance())
        
        # Tracking overall performance
        self.overall_order_count = Decimal(0)
        self.overall_profit = Decimal(0.0)

        self.mapping = mapping
        self.min_edge = Decimal(min_edge)  # buffer for fees/slippage
        self.logger = logging.getLogger("wide_spread_strategy")
        
        # Cached balance to avoid API calls on every order (in dollars)
        self.cached_balance = Decimal(Decimal(kalshi_gateway.get_balance()) / Decimal(100.0))
        self.cached_balance = 5000

    def find_oppurtunities(self, kalshi_book_snapshots: dict | None = None, polymarket_us_book_snapshots: dict | None = None):
        # Iterate over all polymarket/kalshi books
        batch_create_orders = {
            "orders": []
        }
        batch_cancel_orders = {
            "orders": []
        }
        for ticker, (best_bid, best_bid_size, best_ask, best_ask_size) in kalshi_book_snapshots.items():
            # If the spread is above threshold, place bid and ask at top of book 
            spread = (best_ask - best_bid)
            ticker_open_orders = self.position_manager.get_open_orders_for_ticker(ticker)
            # Need to check if no open orders 
            if spread >= self.spread_threshold and not ticker_open_orders:
                # TODO: We want to prioritize tickers which end soon, have some volume (not too much)
                # Set size based on market volume and spread
                # Bid Order
                bid_order = {
                    "ticker": ticker,
                    "action": "buy",
                    "side": "yes",
                    "count": 5,
                    "client_order_id": "WBRSSS" + str(uuid.uuid4()),
                    "yes_price": int(float(best_ask) * 100) + 1,
                    "type": "limit",
                    "time_in_force": "good_till_canceled"
                }

                #Ask Order
                ask_order = {
                    "ticker": ticker,
                    "action": "buy",
                    "side": "no",
                    "count": 5,
                    "client_order_id": "WBRSSS" + str(uuid.uuid4()),
                    "no_price": int(float(best_ask) * 100) - 1,
                    "type": "limit",
                    "time_in_force": "good_till_canceled"
                }

                batch_create_orders["orders"].extend([bid_order, ask_order])

                # TODO: Move to outside for loop and add method in position manager to bulk update open orders
                self.position_manager.add_open_orders(bid_order)
                self.position_manager.add_open_orders(ask_order)
                self.logger.info(bid_order)
                self.logger.info(ask_order)

            # If spread is below threshold, cancel any resting orders
            # Or if current orders are not at top of book, cancel resting orders
            if ticker_open_orders and spread < self.spread_threshold:
                for open_order in ticker_open_orders:
                    if open_order["client_order_id"].startswith("WBRSSS"):
                        batch_cancel_orders["orders"].append({"order_id": open_order["client_order_id"]})
                        

        # Also need to listen for trades with wide spread clOrdIds 
        # When we get a trade wide spread clOrdId, we need to cancel corresponding 
        pass

if __name__ == "__main__":
    pass