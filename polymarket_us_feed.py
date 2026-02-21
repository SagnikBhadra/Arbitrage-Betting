from orderbook import OrderBook
from market_data import MarketData
from utils import get_asset_ids

import asyncio
import base64
import json
import logging
import time
import websockets
from collections import defaultdict
from cryptography.hazmat.primitives.asymmetric import ed25519


class PolymarketUSWebSocket:
    def __init__(self, url_base, channel_type, slugs, api_key_id, key_file_path, logger=logging.getLogger(__name__)):
        self.url = f"{url_base}/v1/ws/{channel_type}"
        self.channel_type = channel_type
        self.slugs = slugs
        self.api_key_id = api_key_id
        self.key_file_path = key_file_path
        self.logger = logger

        # Load private key from file
        with open(self.key_file_path, "r") as f:
            private_key_base64 = f.read().strip()

        self.private_key = ed25519.Ed25519PrivateKey.from_private_bytes(
            base64.b64decode(private_key_base64)[:32]
        )

        # Initialize OrderBooks
        self.orderbooks = defaultdict(OrderBook)
        for slug in self.slugs:
            self.orderbooks[slug] = OrderBook(slug)
            self.orderbooks[slug + "-inverse"] = OrderBook(slug + "-inverse")

        # Initialize Market Data
        self.market_data = MarketData(market="PolymarketUS")

        # WebSocket state
        self.ws = None
        self.connected = asyncio.Event()
        
    #
    # Authentication
    #

    def _build_auth_headers(self):
        method = "GET"
        path = f"/v1/ws/{self.channel_type}"
        timestamp = str(int(time.time() * 1000))

        message = f"{timestamp}{method}{path}"
        signature = base64.b64encode(
            self.private_key.sign(message.encode())
        ).decode()

        return {
            "X-PM-Access-Key": self.api_key_id,
            "X-PM-Timestamp": timestamp,
            "X-PM-Signature": signature,
            "Content-Type": "application/json",
        }

    #
    # Connection
    #

    async def connect(self):
        while True:
            try:
                self.logger.info(f"Connecting to {self.url}")

                headers = self._build_auth_headers()
                
                
                self.ws = await websockets.connect(
                    self.url,
                    ping_interval=None,
                    max_size=None,
                    additional_headers=headers
                )

                await self.send_subscribe()
                self.connected.set()

                self.logger.info(f"Connected to {self.url}")
                return

            except Exception as e:
                self.logger.error(f"Connection failed: {e}")
                await asyncio.sleep(2)

    async def send_subscribe(self):
        subscribe_payload = {
            "subscribe": {
                "requestId": "md-sub-1",
                "subscriptionType": "SUBSCRIPTION_TYPE_MARKET_DATA",
                "marketSlugs": self.slugs
            }
        }

        await self.ws.send(json.dumps(subscribe_payload))

    #
    # Loops
    #

    async def recv_loop(self):
        while True:
            try:
                msg = await self.ws.recv()

                if msg == "PONG":
                    continue

                msgs = json.loads(msg)

                # Normalize to list
                if isinstance(msgs, dict):
                    msgs = [msgs]

                for m in msgs:
                    await self.handle_message(m)

            except websockets.ConnectionClosed:
                self.logger.warning("Connection closed, reconnecting...")
                self.connected.clear()
                await self.connect()

            except Exception as e:
                self.logger.error(f"Error in recv_loop: {e}")

    async def ping_loop(self):
        while True:
            await self.connected.wait()
            try:
                await self.ws.send("PING")
            except Exception:
                pass
            await asyncio.sleep(10)

    #
    # Message Handlers
    #

    async def handle_message(self, msg):
        #self.logger.info(f"Received message: {msg}")
        subscription_type = msg.get("subscriptionType")

        if subscription_type == "SUBSCRIPTION_TYPE_MARKET_DATA":
            #self.market_data.persist_book_event(msg)
            self.handle_snapshot(msg["marketData"])

    def handle_snapshot(self, marketData):
        #for asset in marketData:
                    
        # Polymarket US has 1 event per market
        # This means 1 team is long and 1 team is short.
        
        # Long Side
        asset_id = marketData["marketSlug"]

        orderbook = self.orderbooks.get(asset_id)
        if not orderbook:
            self.logger.warning(f"Orderbook not found for {asset_id}")
            return

        #self.logger.info(f"Loading snapshot for {asset_id}")
        #self.logger.info(f"Market Data: {marketData}")
        orderbook.load_polymarket_us_snapshot(asset_id, marketData)
        self.logger.info(f"Loaded snapshot for {orderbook}")

        # Short Side
        orderbook = self.orderbooks.get(asset_id + "-inverse")
        if not orderbook:
            self.logger.warning(f"Orderbook not found for {asset_id + '-inverse'}")
            return

        #self.logger.info(f"Loading snapshot for {asset_id + '-inverse'}")
        orderbook.load_polymarket_us_snapshot(asset_id + "-inverse", marketData)
        #self.logger.info(f"Market Data: {marketData}")
        self.logger.info(f"Loaded snapshot for {orderbook}")

    #
    # Public API
    #

    async def run(self):
        await self.connect()

        await asyncio.gather(
            self.recv_loop(),
            self.ping_loop(),
        )

    def get_best_bid(self, asset_id):
        orderbook = self.orderbooks.get(asset_id)
        if orderbook:
            return orderbook.get_best_bid()
        return None, None

    def get_best_ask(self, asset_id):
        orderbook = self.orderbooks.get(asset_id)
        if orderbook:
            return orderbook.get_best_ask()
        return None, None


#
# Example usage
#

if __name__ == "__main__":
    WS_URL_BASE = "wss://api.polymarket.us"
    CHANNEL_TYPE = "markets"  # or whatever channel you're using
    api_key_id = "8f004f3b-4858-4401-a979-ca189946cde1"
    key_file_path = "polymarket.key"

    polymarket_client = PolymarketUSWebSocket(
        WS_URL_BASE,
        CHANNEL_TYPE,
        ["aec-cbb-oregst-sea-2026-02-15"],
        api_key_id,
        key_file_path
    )

    asyncio.run(polymarket_client.run())
