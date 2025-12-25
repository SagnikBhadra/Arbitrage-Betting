from orderbook import OrderBook
from market_data import MarketData

import asyncio
import json
import websockets
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

class PolymarketWebSocket:
    def __init__(self, url_base, channel_type, asset_ids):
        self.url = f"{url_base}/ws/{channel_type}"
        self.channel_type = channel_type
        self.asset_ids = asset_ids
        
        # Initialize OrderBooks
        self.orderbooks = defaultdict(OrderBook)
        for asset_id in self.asset_ids:
            self.orderbooks[asset_id] = OrderBook(asset_id)
        
        # Initialize Market Data
        self.market_data = MarketData(market="Polymarket")
        
        # Initialize Websocket
        self.ws = None
        self.connected = asyncio.Event()
        
    async def connect(self):
        #Connect and subscribe
        while True:
            try:
                print(f"Connecting to {self.url}")
                self.ws = await websockets.connect(self.url, ping_interval=None)
                await self.send_subscribe()
                self.connected.set()
                print(f"Connected to {self.url}")
                return
            except Exception as e:
                print(f"Connection failed: {e}")
                asyncio.sleep(2)
                
    async def send_subscribe(self):
        # Subscribe to assets
        subscribe_payload = {
            "assets_ids": self.asset_ids,
            "type": self.channel_type
        }
        await self.ws.send(json.dumps(subscribe_payload))

    async def recv_loop(self):
        #Listen for messages
        while True:
            try:
                msg = await self.ws.recv()
                
                if msg == "PONG":
                    continue
                
                msgs = json.loads(msg)

                # Ensure msgs is always a list
                if isinstance(msgs, dict):
                    msgs = [msgs]
                    
                #print(msgs)
                #print(len(msgs))
                
                for m in msgs:
                    await self.handle_message(m)

            except websockets.ConnectionClosed:
                print("Connection closed, reconnecting...")
                self.connected.clear()
                await self.connect()

            except Exception as e:
                print("Error in recv_loop:", e)

    async def ping_loop(self):
        #Send periodic pings.
        while True:
            await self.connected.wait()
            try:
                await self.ws.send("PING")
            except Exception:
                pass
            await asyncio.sleep(10)

    #
    # Message handlers (same logic as before)
    #

    async def handle_message(self, msg):
        event_type = msg.get("event_type")

        if event_type == "book":
            self.market_data.persist_book_event(msg)
            self.handle_snapshot(msg)

        elif event_type == "price_change":
            self.market_data.persist_price_change_event(msg)
            self.handle_price_change(msg)

        elif event_type == "last_trade_price":
            self.market_data.persist_trade_event(msg)

        elif event_type == "tick_size_change":
            self.market_data.persist_tick_change_event(msg)

    def handle_snapshot(self, msg):
        asset_id = msg["asset_id"]
        orderbook = self.orderbooks.get(asset_id)
        if orderbook is None:
            print(f"Orderbook not found for {asset_id}")
            return
        orderbook.load_polymarket_snapshot(msg)

    def handle_price_change(self, msg):
        for change in msg["price_changes"]:
            asset_id = change["asset_id"]
            price = float(change["price"])
            size = float(change["size"])
            side = 0 if change["side"] == "BUY" else 1

            orderbook = self.orderbooks.get(asset_id)
            if orderbook:
                orderbook.update_order_book(side, price, size)

    #
    # Public API
    #

    async def run(self):
        #Start the websocket and all loops.
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
        
if __name__ == "__main__":
    polymarket_client = PolymarketWebSocket(WS_URL_BASE, CHANNEL_TYPE, ASSET_IDS)
    asyncio.run(polymarket_client.run())
