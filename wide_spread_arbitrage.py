from concurrent.futures import ThreadPoolExecutor
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
from utils import get_maker_fees_kalshi, get_taker_fees_kalshi, get_taker_fees_polymarket_us, get_maker_rebate_polymarket_us, read_file_data
from collections import defaultdict

class WideSpreadArbitrage:
    def __init__(self, polymarket_client: PolymarketUSWebSocket, kalshi_client: KalshiWebSocket, polymarket_us_gateway: PolymarketUSHTTPGateway, kalshi_gateway: KalshiHTTPGateway, position_manager: PositionManager, spread_threshold: Decimal = Decimal(0.05), min_edge: Decimal = Decimal(0.01)):
        self.polymarket_client = polymarket_client
        self.polymarket_us_gateway = polymarket_us_gateway
        self.kalshi_client = kalshi_client
        self.kalshi_gateway = kalshi_gateway
        self.position_manager = position_manager
        self.spread_threshold = Decimal(spread_threshold)
        self.allowed_tickers = set()
        self.store_volume_data()

        #Temporary balance tracking
        self.polymarket_us_balance = Decimal(self.polymarket_us_gateway.get_balance())
        self.kalshi_balance = Decimal(self.kalshi_gateway.get_balance())
        
        # Tracking overall performance
        # TODO: Track profit for wide spread strategy
        self.overall_order_count = Decimal(0)
        self.overall_profit = Decimal(0.0)

        self.min_edge = Decimal(min_edge)  # buffer for fees/slippage
        self.logger = logging.getLogger("wide_spread_strategy")
        
        # Cached balance to avoid API calls on every order (in dollars)
        self.cached_balance = Decimal(Decimal(kalshi_gateway.get_balance()) / Decimal(100.0))
        self.cached_balance = Decimal("5000")  # Start with $5000 for testing
        
        # Cosume from user fill queue to track fills for wide spread strategy
        self.running = True
        self.executor = ThreadPoolExecutor(max_workers=1)
        
    def update_cached_balance_before_create_order(self, order, fees):
        # Update the cached balance before creating the order to ensure we are accounting for the new order when finding opportunities
        if order["side"] == "yes":
            self.cached_balance -= (Decimal(order["count"]) * Decimal(order.get("yes_price", 0) / Decimal(100.0)) + fees)
        else:
            self.cached_balance -= (Decimal(order["count"]) * Decimal(order.get("no_price", 0) / Decimal(100.0)) + fees)

    def update_cached_balance_from_create_order(self, order_response):
        # Only update cached balance for market orders since limit orders may not fill immediately
        if order_response["type"] == "market":
            if order_response["side"] == "yes":
                self.cached_balance -= (Decimal(order_response["fill_count_fp"]) * Decimal(order_response.get("yes_price_dollars", 0)) + Decimal(order_response.get("taker_fees_dollars", 0)))
            else:
                self.cached_balance -= (Decimal(order_response["fill_count_fp"]) * Decimal(order_response.get("no_price_dollars", 0)) + Decimal(order_response.get("taker_fees_dollars", 0)))

    async def process_user_fills(self):
        # Logging to verify process_user_fills is working correctly and we are consuming fills from the queue
        self.logger.info("Starting to process user fills for wide spread strategy")
        
        while self.running:
            fill_msg = await self.kalshi_client.fill_queue.get()
            ticker = fill_msg.get("market_ticker", "")
            client_order_id = fill_msg.get("client_order_id", "")
            count= fill_msg.get("count_fp", 0)
            associated_order_ids = self.position_manager.get_associated_orders(client_order_id)
            
            # Log trade details
            self.logger.info(f"Processing fill message: {client_order_id} | Ticker: {ticker} | Count: {count}")
            
            # Cancel other side of the order
            for associated_order_id in associated_order_ids:
                response = self.kalshi_gateway.cancel_order(associated_order_id)
                
                # Verify we were able to cancel and that the other side was not filled already
                if not response.get("order") or not int(float(response["order"].get("remaining_count_fp", 0))) == 0:
                    self.logger.error(f"Failed to cancel associated order {associated_order_id} for fill {client_order_id}. Response: {response}")
                else: 
                    associated_order = self.position_manager.get_open_order(associated_order_id)
                    side = associated_order["side"]
                    # Send market order on the associated side
                    order = {
                        "ticker": associated_order_id,
                        "action": "buy",
                        "side": side,
                        "count": count,
                        "client_order_id": str(uuid.uuid4()),
                        "type": "market",
                        "time_in_force": "good_till_canceled"
                    }
                    create_order_reponse = self.kalshi_gateway.create_order(order)
                    
                    # Update position manager on associated side of the trade
                    self.position_manager.remove_open_order(ticker, associated_order_id)
                    self.position_manager.remove_client_order_id_from_associated_orders(associated_order_id)
                    
                    # Update balance tracking
                    # self.update_cached_balance_from_create_order(create_order_reponse)
            
            
            # Update position manager on filled side of the trade
            self.position_manager.remove_open_order(ticker, client_order_id)
            self.position_manager.remove_client_order_id_from_associated_orders(client_order_id)
            
            # Update balance tracking
            # self.update_cached_balance_from_create_order(fill_msg)

        
    def store_volume_data(self):
        self.volume_data = read_file_data("statics/kalshi_volume_per_market.json")
        for ticker, volume in self.volume_data.items():
            volume = int(float(volume))
            if volume > 1000 and volume < 10000:
                self.allowed_tickers.add(ticker)

    def find_opportunities(self, kalshi_book_snapshots: dict | None = None, polymarket_us_book_snapshots: dict | None = None):
        # Iterate over all polymarket/kalshi books
        batch_create_orders = {
            "orders": []
        }
        batch_cancel_orders = {
            "orders": []
        }
        for ticker, (best_bid, best_bid_size, best_ask, best_ask_size) in kalshi_book_snapshots.items():
            # If the spread is above threshold, place bid and ask at top of book 
            if not best_bid or not best_ask:
                continue
            spread = Decimal(Decimal(best_ask) - Decimal(best_bid))
            ticker_open_orders = self.position_manager.get_open_orders_for_ticker(ticker)
            # Need to check if no open orders 
            if ticker in self.allowed_tickers and spread >= self.spread_threshold and spread <= Decimal(0.15) and not ticker_open_orders:
                #print(f"Ticker {ticker} has spread {spread}. Best bid: {best_bid}, best ask: {best_ask}")
                # TODO: We want to prioritize tickers which end soon, have some volume (not too much)
                # Set size based on market volume and spread
                # Bid Order
                bid_order = {
                    "ticker": ticker,
                    "action": "buy",
                    "side": "yes",
                    "count": 5,
                    "client_order_id": "WBRSSS" + str(uuid.uuid4()),
                    "yes_price": int(float(best_bid) * 100) + 1,
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
                    "no_price": int(float(Decimal("1.0") - Decimal(best_ask)) * 100) + 1,
                    "type": "limit",
                    "time_in_force": "good_till_canceled"
                }
                
                # Calculate maker fees
                maker_fee_bid = get_maker_fees_kalshi(best_bid, bid_order["count"])
                maker_fee_ask = get_maker_fees_kalshi(best_ask, ask_order["count"])

                # Update cached balance for both orders
                self.update_cached_balance_before_create_order(bid_order, maker_fee_bid)
                self.update_cached_balance_before_create_order(ask_order, maker_fee_ask)
                
                if not self.cached_balance < Decimal(0):
                    batch_create_orders["orders"].extend([bid_order, ask_order])

                    # TODO: Move to outside for loop and add method in position manager to bulk update open orders
                    self.position_manager.add_open_order(ticker, bid_order)
                    self.position_manager.add_open_order(ticker, ask_order)
                    
                    self.position_manager.add_associated_order(client_order_id=bid_order["client_order_id"], associated_order_id=ask_order["client_order_id"])
                    self.position_manager.add_associated_order(client_order_id=ask_order["client_order_id"], associated_order_id=bid_order["client_order_id"])

                self.logger.info(bid_order)
                self.logger.info(ask_order)

            # If spread is below threshold, cancel any resting orders
            # Or if current orders are not at top of book, cancel resting orders
            # TODO: We want to cancel orders before adding new orders
            # TODO: We probably want to separate out the logic for canceling orders so we don't block the thread from finding opportunities
            # TODO: If it's just that the orders are not at the top of the book, we can just update those orders instead of canceling and creating new ones
            if ticker_open_orders and spread < self.spread_threshold:
                for open_order_id in ticker_open_orders:
                    if open_order_id.startswith("WBRSSS"):
                        batch_cancel_orders["orders"].append({"order_id": open_order_id})
                        

        # Also need to listen for trades with wide spread clOrdIds 
        # When we get a trade wide spread clOrdId, we need to cancel corresponding 
        pass

if __name__ == "__main__":
    pass