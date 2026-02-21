import asyncio
import base64
import json
import logging
import time
import websockets
from collections import defaultdict
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from decimal import Decimal

from orderbook import OrderBook
from market_data import MarketData
from utils import get_asset_ids

# Configuration
KEY_ID = "7edd1c5d-6c0c-4458-bb77-04854221689b"
PRIVATE_KEY_PATH = "Kalshi.key"
MARKET_TICKER = ["KXNBAMVP-26-LDON",
                "KXNBAMVP-26-SGIL",
                 "KXNBAMVP-26-NJOK"]  # Replace with any open market
#MARKET_TICKER = ["KXNBAMVP-26-LDON"]
WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"

"""

            "KXNBAMVP-26-SGIL": "Shai",
            "KXNBAMVP-26-NJOK": "Jokic",
            "KXNBAMVP-26-LDON": "Luka",
"""

class KalshiWebSocket:
    def __init__(self, key_id, private_key_path, market_tickers, ws_url, logger=logging.getLogger(__name__)):
        self.key_id = key_id
        self.private_key_path = private_key_path
        self.market_tickers = market_tickers
        self.ws_url = ws_url
        self.logger = logger
        
        # Initialize OrderBooks
        self.orderbooks = defaultdict(OrderBook)
        #for asset_id in self.asset_ids:
        for market_ticker in self.market_tickers:
            self.orderbooks[market_ticker] = OrderBook(market_ticker, logger=self.logger)
        
        # Initialize Market Data
        self.market_data = MarketData(market="Kalshi")

    def sign_pss_text(self, private_key, text: str) -> str:
        """Sign message using RSA-PSS"""
        message = text.encode('utf-8')
        signature = private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH
            ),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode('utf-8')

    def create_headers(self, private_key, method: str, path: str) -> dict:
        """Create authentication headers"""
        timestamp = str(int(time.time() * 1000))
        msg_string = timestamp + method + path.split('?')[0]
        signature = self.sign_pss_text(private_key, msg_string)

        return {
            "Content-Type": "application/json",
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
        }
        
    def get_top_of_book(self, market_ticker):
        orderbook = self.orderbooks.get(market_ticker, None)
        if not orderbook:
            self.logger.warning(f"Order Book with market ticker {market_ticker} not found on get_top_of_book")
            return None, None
        best_bid_price, best_bid_size = orderbook.get_best_bid()
        best_ask_price, best_ask_size = orderbook.get_best_ask()
        return best_bid_price, best_ask_price
        
    def handle_snapshot(self, msg):
        asset_id = msg["market_ticker"]
        
        orderbook = self.orderbooks.get(asset_id, None)
        if not orderbook:
            self.logger.warning(f"Order Book with asset ID {asset_id} not found on snapshot")
            return
        
        orderbook.load_kalshi_snapshot(msg)
        self.logger.info(f"Loaded snapshot for {orderbook}")
        
    def handle_price_change(self, msg):
        asset_id = msg["market_ticker"]
        price = float(msg["price_dollars"]) if msg["side"] == "yes" else Decimal('1.0') - Decimal(msg["price_dollars"])
        delta = float(msg["delta"])
        side = 0 if msg["side"] == "yes" else 1
        orderbook = self.orderbooks.get(asset_id, None)
        if not orderbook:
            self.logger.warning(f"Order Book with asset ID {asset_id} not found on price change")
            return
        size = orderbook.get_size_at_price(side, price) + delta
        orderbook.update_order_book(side, price, size)
        self.logger.info(f"Updated order book for {orderbook}")
        return str(price), orderbook.get_best_bid()[0], orderbook.get_best_ask()[0]
    
    def handle_trade(self, msg):
        asset_id = msg["market_ticker"]
        yes_price = float(msg["yes_price_dollars"])
        no_price = Decimal("1.0") - Decimal(msg["no_price_dollars"])
        shares_executed = float(msg["count"])
        taker_side = 0 if msg["taker_side"] == "yes" else 1
        
        orderbook = self.orderbooks.get(asset_id, None)
        if not orderbook:
            self.logger.warning(f"Order Book with asset ID {asset_id} not found on trade")
            return
        
        # Potentially NOT NEEDED
        # Handled in handle_price_change
        
        if taker_side == 1:
            # Taker BUY NO | Remove from Bid side
            best_bid_price, best_bid_size = orderbook.get_best_bid()
            yes_size = orderbook.get_size_at_price(0, yes_price)
            #if best_bid_price != yes_price:
                #print(f"Discrepancy in YES trade price: Trade Price {yes_price} vs Best Bid {best_bid_price}")
            if yes_size:
                new_size = max(0, yes_size - shares_executed)
                #orderbook.update_order_book(0, best_bid_price, new_size)
        else:
            # Taker BUY YES | Remove from Ask side
            best_ask_price, best_ask_size = orderbook.get_best_ask()
            no_size = orderbook.get_size_at_price(1, no_price)
            #if best_ask_price != no_price:
                #print(f"Discrepancy in NO trade price: Trade Price {no_price} vs Best Ask {best_ask_price}")
            if no_size:
                new_size = max(0, no_size - shares_executed)
                #orderbook.update_order_book(1, best_ask_price, new_size)

    async def orderbook_websocket(self):
        """Connect to WebSocket and subscribe to orderbook with auto-reconnect."""
        while True:
            try:
                # Load private key
                with open(self.private_key_path, 'rb') as f:
                    private_key = serialization.load_pem_private_key(
                        f.read(),
                        password=None
                    )

                # Create WebSocket headers
                ws_headers = self.create_headers(private_key, "GET", "/trade-api/ws/v2")

                async with websockets.connect(
                    self.ws_url,
                    additional_headers=ws_headers,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                ) as websocket:
                    self.logger.info(f"Connected! Subscribing to orderbook for {', '.join(self.market_tickers)}")

                    # Subscribe to orderbook
                    subscribe_msg = {
                        "id": 1,
                        "cmd": "subscribe",
                        "params": {
                            "channels": ["orderbook_delta", "trade"],
                            "market_tickers": self.market_tickers
                        }
                    }
                    
                    await websocket.send(json.dumps(subscribe_msg))

                    # Process messages
                    async for message in websocket:
                        data = json.loads(message)
                        msg_type = data.get("type")
                        msg_content = data["msg"]

                        if msg_type == "subscribed":
                            self.logger.info(f"Subscribed: {data}")

                        elif msg_type == "orderbook_snapshot":
                            self.market_data.persist_orderbook_snapshot_event_kalshi(msg_content)
                            self.handle_snapshot(msg_content)

                        elif msg_type == "orderbook_delta":
                            if 'client_order_id' in data.get('data', {}):
                                pass
                            else:
                                price, best_bid, best_ask = self.handle_price_change(msg_content)
                                self.market_data.persist_orderbook_update_event_kalshi(
                                    msg_content,
                                    price=price,
                                    best_bid=best_bid,
                                    best_ask=best_ask
                                )

                        elif msg_type == "trade":
                            self.handle_trade(msg_content)
                            best_bid, best_ask = self.get_top_of_book(msg_content["market_ticker"])
                            self.market_data.persist_trade_event_kalshi(
                                msg_content,
                                best_bid=best_bid,
                                best_ask=best_ask
                            )

                        elif msg_type == "ticker":
                            pass

                        elif msg_type == "market_state":
                            pass

                        elif msg_type == "error":
                            self.logger.error(f"Error: {data}")

            except websockets.exceptions.ConnectionClosedError as e:
                self.logger.error(f"WebSocket connection closed: {e}")
                self.logger.info("Reconnecting in 5 seconds...")
                await asyncio.sleep(5)
            except websockets.exceptions.ConnectionClosedOK:
                self.logger.info("WebSocket connection closed normally")
                break
            except Exception as e:
                self.logger.error(f"WebSocket error: {e}")
                self.logger.info("Reconnecting in 5 seconds...")
                await asyncio.sleep(5)

    def get_best_bid(self, market_ticker):
        orderbook = self.orderbooks.get(market_ticker, None)
        if not orderbook:
            self.logger.warning(f"Order Book with market ticker {market_ticker} not found on get_best_bid")
            return None, None
        return orderbook.get_best_bid()
    
    def get_best_ask(self, market_ticker):
        orderbook = self.orderbooks.get(market_ticker, None)
        if not orderbook:
            self.logger.warning(f"Order Book with market ticker {market_ticker} not found on get_best_ask")
            return None, None
        return orderbook.get_best_ask()

# Run the example
if __name__ == "__main__":
    client = KalshiWebSocket(KEY_ID, PRIVATE_KEY_PATH, get_asset_ids("Kalshi"), WS_URL)
    asyncio.run(client.orderbook_websocket())