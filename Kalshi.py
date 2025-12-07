import asyncio
import base64
import json
import time
import websockets
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding

from orderbook import OrderBooks
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
        self.orderbooks = OrderBooks()
        
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
            "KALSHI-ACCESS-KEY": self.KEY_ID,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
        }

    async def orderbook_websocket(self):
        """Connect to WebSocket and subscribe to orderbook"""
        # Load private key
        with open(self.PRIVATE_KEY_PATH, 'rb') as f:
            private_key = serialization.load_pem_private_key(
                f.read(),
                password=None
            )

        # Create WebSocket headers
        ws_headers = self.create_headers(self, private_key, "GET", "/trade-api/ws/v2")

        async with websockets.connect(self.WS_URL, additional_headers=ws_headers) as websocket:
            print(f"Connected! Subscribing to orderbook for {self.MARKET_TICKER}")

            # Subscribe to orderbook
            subscribe_msg = {
                "id": 1,
                "cmd": "subscribe",
                "params": {
                    "channels": ["orderbook_delta"],
                    "market_ticker": self.MARKET_TICKER
                }
            }
            await websocket.send(json.dumps(subscribe_msg))

            # Process messages
            async for message in websocket:
                data = json.loads(message)
                msg_type = data.get("type")

                if msg_type == "subscribed":
                    print(f"Subscribed: {data}")

                elif msg_type == "orderbook_snapshot":
                    print(f"Orderbook snapshot: {data}")

                elif msg_type == "orderbook_delta":
                    # The client_order_id field is optional - only present when you caused the change
                    if 'client_order_id' in data.get('data', {}):
                        print(f"Orderbook update (your order {data['data']['client_order_id']}): {data}")
                    else:
                        print(f"Orderbook update: {data}")

                elif msg_type == "error":
                    print(f"Error: {data}")

# Run the example
if __name__ == "__main__":
    client = KalshiWebSocket(KEY_ID, PRIVATE_KEY_PATH, MARKET_TICKER, WS_URL)
    asyncio.run(client.orderbook_websocket())