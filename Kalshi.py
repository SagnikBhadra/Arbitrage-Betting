import asyncio
import base64
import json
import time
import websockets
from collections import defaultdict
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding

from orderbook import OrderBook
from market_data import MarketData

# Configuration
KEY_ID = "7edd1c5d-6c0c-4458-bb77-04854221689b"
PRIVATE_KEY_PATH = "Kalshi.key"
MARKET_TICKER = "KXNBAMVP-26-LDON"  # Replace with any open market
WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"

class KalshiWebSocket:
    def __init__(self, key_id, private_key_path, market_ticker, ws_url):
        self.key_id = key_id
        self.private_key_path = private_key_path
        self.market_ticker = market_ticker
        self.ws_url = ws_url
        
        # Initialize OrderBooks
        self.orderbooks = defaultdict(OrderBook)
        #for asset_id in self.asset_ids:
        self.orderbooks[self.market_ticker] = OrderBook(self.market_ticker)
        
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
        
    def handle_snapshot(self, msg):
        asset_id = msg["market_ticker"]
        
        orderbook = self.orderbooks.get(asset_id, None)
        if not orderbook:
            print(f"Order Book with asset ID {asset_id} not found on snapshot")
            return
        
        orderbook.load_kalshi_snapshot(msg)
        
    def handle_price_change(self, msg):
        asset_id = msg["market_ticker"]
        price = float(msg["price_dollars"])
        delta = float(msg["delta"])
        side = 0 if msg["side"] == "yes" else 1
        orderbook = self.orderbooks.get(asset_id, None)
        if not orderbook:
            print(f"Order Book with asset ID {asset_id} not found on price change")
            return
        size = orderbook.get_size_at_price(side, price) + delta
        orderbook.update_order_book(side, price, size)
        #print(orderbook)
        return orderbook.get_best_bid()[0], orderbook.get_best_ask()[0]

    async def orderbook_websocket(self):
        """Connect to WebSocket and subscribe to orderbook"""
        # Load private key
        with open(self.private_key_path, 'rb') as f:
            private_key = serialization.load_pem_private_key(
                f.read(),
                password=None
            )

        # Create WebSocket headers
        ws_headers = self.create_headers(private_key, "GET", "/trade-api/ws/v2")

        async with websockets.connect(self.ws_url, additional_headers=ws_headers) as websocket:
            print(f"Connected! Subscribing to orderbook for {self.market_ticker}")

            # Subscribe to orderbook
            subscribe_msg = {
                "id": 1,
                "cmd": "subscribe",
                "params": {
                    "channels": ["orderbook_delta"],
                    "market_ticker": self.market_ticker
                }
            }
            await websocket.send(json.dumps(subscribe_msg))

            # Process messages
            async for message in websocket:
                data = json.loads(message)
                msg_type = data.get("type")
                msg_content = data["msg"]

                if msg_type == "subscribed":
                    print(f"Subscribed: {data}")

                elif msg_type == "orderbook_snapshot":
                    #print(f"Orderbook snapshot: {data}")
                    self.market_data.persist_orderbook_snapshot_event_kalshi(msg_content)
                    self.handle_snapshot(msg_content)

                elif msg_type == "orderbook_delta":
                    # The client_order_id field is optional - only present when you caused the change
                    if 'client_order_id' in data.get('data', {}):
                        #print(f"Orderbook update (your order {data['data']['client_order_id']}): {data}")
                        pass
                    else:
                        #print(f"Orderbook update: {data}")
                        best_bid, best_ask = self.handle_price_change(msg_content)
                        self.market_data.persist_orderbook_update_event_kalshi(
                            msg_content,
                            best_bid=best_bid,
                            best_ask=best_ask
                        )
                        

                elif msg_type == "error":
                    print(f"Error: {data}")

# Run the example
if __name__ == "__main__":
    client = KalshiWebSocket(KEY_ID, PRIVATE_KEY_PATH, MARKET_TICKER, WS_URL)
    asyncio.run(client.orderbook_websocket())