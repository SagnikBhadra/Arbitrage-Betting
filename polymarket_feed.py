from orderbook import OrderBook
from market_data import MarketData

import asyncio
import json
import threading
import websockets
from collections import defaultdict
from websocket import WebSocketApp

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
        """Connect and subscribe"""
        while True:
            try:
                print(f"Connecting to {self.url}")
                self.ws = await websockets.connect(self.url, ping_interval=None)
                await self.send_subscribe()
                self.connected.set()
                print("Connected to {self.url}")
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
        """Listen for messages"""
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
        """Send periodic pings."""
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
        """Start the websocket and all loops."""
        await self.connect()

        await asyncio.gather(
            self.recv_loop(),
            self.ping_loop(),
        )
        
if __name__ == "__main__":
    polymarket_client = PolymarketWebSocket(WS_URL_BASE, ASSET_IDS, CHANNEL_TYPE)
    polymarket_client.run()


"""
class PolymarketWebSocket:
    def __init__(self, url_base, channel_type, asset_ids):
        self.url = f"{url_base}/ws/{channel_type}"
        self.channel_type = channel_type
        self.asset_ids = asset_ids
        self.ws = WebSocketApp(
            self.url,
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
        )
        
        # Initialize OrderBooks
        self.orderbooks = defaultdict(OrderBook)
        for asset_id in self.asset_ids:
            self.orderbooks[asset_id] = OrderBook(asset_id)
        
        # Initialize Market Data
        self.market_data = MarketData(market="Polymarket")

    def on_open(self, ws):
        print(f"Connected to {self.url}")
        # Subscribe to assets
        subscribe_payload = {
            "assets_ids": self.asset_ids,
            "type": self.channel_type
        }
        ws.send(json.dumps(subscribe_payload))
        # Start periodic ping to keep connection alive
        threading.Thread(target=self.ping, args=(ws,), daemon=True).start()

    def on_message(self, ws, message):
        if message == "PONG":
            return
        msgs = json.loads(message)

        # Ensure msgs is always a list
        if isinstance(msgs, dict):
            msgs = [msgs]
            
        #print(msgs)
        #print(len(msgs))

        for msg in msgs:
            event_type = msg.get("event_type")
            #print(f"\nReceived message — event_type: {event_type}")
            #print(json.dumps(msg, indent=2))

            if event_type == "book":
                self.market_data.persist_book_event(msg)
                self.handle_snapshot(msg)
            elif event_type == "price_change":
                self.market_data.persist_price_change_event(msg)
                self.handle_price_change(msg)
            elif event_type == "last_trade_price":
                self.market_data.persist_trade_event(msg)
                #self.handle_last_trade(msg)
            elif event_type == "tick_size_change":
                self.market_data.persist_tick_change_event(msg)
                #self.handle_tick_size_change(msg)
            else:
                print("Unrecognized message:", msg)
            
        # print_top_of_book()

    def on_error(self, ws, error):
        print("WebSocket error:", error)

    def on_close(self, ws, close_status_code, close_msg):
        print("WebSocket closed:", close_status_code, close_msg)

    def ping(self, ws):
        import time
        while True:
            ws.send("PING")
            time.sleep(10)

    def run(self):
        self.ws.run_forever()

    # Handler stubs — customize as needed
    def handle_snapshot(self, msg):
        asset_id = msg["asset_id"]
        # UPDATE ORDER BOOK
        #bids = {float(entry["price"]): float(entry["size"]) for entry in msg["bids"]}
        #asks = {float(entry["price"]): float(entry["size"]) for entry in msg["asks"]}
        #self.orderbooks.orderbooks[asset_id]["bids"] = bids
        #self.orderbooks.orderbooks[asset_id]["asks"] = asks
        #print(f"[BOOK SNAPSHOT] {ASSET_ID_MAPPING[asset_id]}")
        #print_top_of_book_single_assest(order_books[asset_id])
        
        orderbook = self.orderbooks.get(asset_id, None)
        if not orderbook:
            print(f"Order Book with asset ID {asset_id} not found on snapshot")
            return
        
        orderbook.load_polymarket_snapshot(msg)
            

    def handle_price_change(self, msg):
        #print("Price change update:", msg.get("changes"))
        # UPDATE ORDER BOOK
        for change in msg["price_changes"]:
            asset_id = change["asset_id"]
            price = float(change["price"])
            size = float(change["size"])
            side = 0 if change["side"] == "BUY" else 1
            orderbook = self.orderbooks.get(asset_id, None)
            if not orderbook:
                print(f"Order Book with asset ID {asset_id} not found on price change")
                continue
            orderbook.update_order_book(side, price, size)
            #print(orderbook)
            
        #print(f"[PRICE UPDATE] {ASSET_ID_MAPPING[asset_id]}")
        #print_top_of_book_single_assest(order_books[asset_id])

    def handle_last_trade(self, msg):
        # UPDATE ORDER BOOK
        #print("Last trade price:", msg.get("price"), "size:", msg.get("size"))
        pass

    def handle_tick_size_change(self, msg):
        # UPDATE ORDER BOOK
        #print("Tick size change:", msg.get("old_tick_size"), "→", msg.get("new_tick_size"))
        pass

if __name__ == "__main__":
    client = PolymarketWebSocket(WS_URL_BASE, CHANNEL_TYPE, ASSET_IDS)
    client.run()

"""