import asyncio
import base64
import json
import logging
import time
import websockets
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from decimal import Decimal
from pathlib import Path

from orderbook import OrderBook
from market_data import MarketData
from utils import get_asset_ids


def load_kalshi_key_id(secrets_path: str = "kalshi_secrets.json") -> str:
    with open(secrets_path, "r") as f:
        data = json.load(f)
    return data["KEY_ID"]

KEY_ID = load_kalshi_key_id()
PRIVATE_KEY_PATH = "Kalshi.key"
WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"

NUM_CONSUMERS = 16


class OrderbookDeltaLogger:
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.queue: asyncio.Queue = asyncio.Queue()
        self.latest_delta: dict[str, dict] = {}
        self.running = True

    async def run(self):
        asyncio.create_task(self._consumer())
        asyncio.create_task(self._flush_loop())

    async def _consumer(self):
        while self.running:
            market, delta = await self.queue.get()
            self.latest_delta[market] = delta

    async def _flush_loop(self):
        while self.running:
            await asyncio.sleep(30)
            self.flush()

    def flush(self):
        if not self.latest_delta:
            return

        self.logger.info("----- LATEST ORDERBOOK DELTAS (last 30s) -----")

        for market, delta in self.latest_delta.items():
            price = delta.get("price_dollars")
            side = delta.get("side")
            size = delta.get("delta_fp")
            ts = delta.get("ts")

            self.logger.info(
                f"{market} | side={side} | price={price} | delta={size} | timestamp={ts}"
            )

        self.logger.info("------------------------------------------------")
        self.latest_delta.clear()

class KalshiWebSocket:
    def __init__(self, key_id, private_key_path, market_tickers, ws_url):
        self.key_id = key_id
        self.private_key_path = private_key_path
        self.market_tickers = market_tickers
        self.ws_url = ws_url
        self.logger = logging.getLogger("kalshi_feed")
        self.subscribed = False

        # OrderBooks
        self.orderbooks: dict[str, OrderBook] = defaultdict(OrderBook)
        for market_ticker in self.market_tickers:
            self.orderbooks[market_ticker] = OrderBook(market_ticker)

        # Market Data
        self.market_data = MarketData(market="Kalshi")

        # Delta logging
        self.delta_logger = OrderbookDeltaLogger(self.logger)

        # Snapshot tracking
        self.snapshot_loaded: set[str] = set()
        self.delta_buffer: dict[str, list[dict]] = defaultdict(list)

        # Async message queue (from WebSocket to workers)
        self.message_queue: asyncio.Queue[str] = asyncio.Queue()

        # Thread pool for CPU-bound work
        self.executor = ThreadPoolExecutor(max_workers=NUM_CONSUMERS)

    def sign_pss_text(self, private_key, text: str) -> str:
        message = text.encode("utf-8")
        signature = private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode("utf-8")

    def create_headers(self, private_key, method: str, path: str) -> dict:
        timestamp = str(int(time.time() * 1000))
        msg_string = timestamp + method + path.split("?")[0]
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
            self.logger.warning(
                f"Order Book with market ticker {market_ticker} not found on get_top_of_book"
            )
            return None, None
        best_bid_price, best_bid_size = orderbook.get_best_bid()
        best_ask_price, best_ask_size = orderbook.get_best_ask()
        return best_bid_price, best_ask_price

    def _apply_delta(self, msg_content):
        price, best_bid, best_ask = self.handle_price_change(msg_content)
        return
        self.market_data.persist_orderbook_update_event_kalshi(
            msg_content,
            price=price,
            best_bid=best_bid,
            best_ask=best_ask,
        )

    def handle_snapshot(self, msg):
        asset_id = msg["market_ticker"]

        orderbook = self.orderbooks.get(asset_id, None)
        if not orderbook:
            self.logger.warning(
                f"Order Book with asset ID {asset_id} not found on snapshot"
            )
            return

        orderbook.load_kalshi_snapshot(msg)

        self.snapshot_loaded.add(asset_id)

        if asset_id in self.delta_buffer:
            for delta_msg in self.delta_buffer[asset_id]:
                self._apply_delta(delta_msg)
            del self.delta_buffer[asset_id]

        self.logger.info(f"Loaded snapshot for {orderbook}")

    def handle_price_change(self, msg):
        asset_id = msg["market_ticker"]
        price = (
            float(msg["price_dollars"])
            if msg["side"] == "yes"
            else Decimal("1.0") - Decimal(msg["price_dollars"])
        )
        delta = float(msg["delta_fp"])
        side = 0 if msg["side"] == "yes" else 1
        orderbook = self.orderbooks.get(asset_id, None)
        if not orderbook:
            self.logger.warning(
                f"Order Book with asset ID {asset_id} not found on price change"
            )
            return
        orderbook.apply_delta(side, price, delta)
        return str(price), orderbook.get_best_bid()[0], orderbook.get_best_ask()[0]

    def handle_trade(self, msg):
        asset_id = msg["market_ticker"]
        yes_price = float(msg["yes_price_dollars"])
        no_price = Decimal("1.0") - Decimal(msg["no_price_dollars"])
        shares_executed = float(msg["count_fp"])
        taker_side = 0 if msg["taker_side"] == "yes" else 1

        orderbook = self.orderbooks.get(asset_id, None)
        if not orderbook:
            self.logger.warning(
                f"Order Book with asset ID {asset_id} not found on trade"
            )
            return

        # (Your trade handling logic here, if needed)

    def _process_single_message(self, message: str):
        data = json.loads(message)
        msg_type = data.get("type")
        
        msg_content = data["msg"]
        
        if msg_type == "subscribed":
            self.logger.info(f"Subscribed: {data}")
            self.subscribed = True

        elif msg_type == "orderbook_snapshot":
            #self.market_data.persist_orderbook_snapshot_event_kalshi(msg_content)
            self.handle_snapshot(msg_content)
        
            
        elif msg_type == "orderbook_delta":
            if "client_order_id" in data.get("data", {}):
                return

            market = msg_content["market_ticker"]
            
            # send to async logger (non-blocking)
            try:
                self.delta_logger.queue.put_nowait((market, msg_content))
            except asyncio.QueueFull:
                pass
            
            if market not in self.snapshot_loaded:
                self.delta_buffer[market].append(msg_content)
                return
            
            self._apply_delta(msg_content)

        elif msg_type == "trade":
            self.handle_trade(msg_content)
            best_bid, best_ask = self.get_top_of_book(
                msg_content["market_ticker"]
            )
            self.market_data.persist_trade_event_kalshi(
                msg_content,
                best_bid=best_bid,
                best_ask=best_ask,
            )

        elif msg_type == "ticker":
            pass

        elif msg_type == "market_state":
            pass

        elif msg_type == "error":
            self.logger.error(f"Error: {data}")

    async def _consumer_loop(self):
        loop = asyncio.get_running_loop()
        while True:
            message = await self.message_queue.get()
            #print(self.message_queue.qsize())
            # Offload CPU-heavy work to thread pool
            await loop.run_in_executor(self.executor, self._process_single_message, message)

    async def orderbook_websocket(self):
        asyncio.create_task(self.delta_logger.run())
        for _ in range(NUM_CONSUMERS):
            asyncio.create_task(self._consumer_loop())

        while True:
            try:
                with open(self.private_key_path, "rb") as f:
                    private_key = serialization.load_pem_private_key(
                        f.read(),
                        password=None,
                    )

                ws_headers = self.create_headers(
                    private_key, "GET", "/trade-api/ws/v2"
                )

                async with websockets.connect(
                    self.ws_url,
                    additional_headers=ws_headers,
                    ping_interval=30,
                    ping_timeout=60,
                    close_timeout=10,
                    open_timeout=10,
                    max_queue=None,
                ) as websocket:
                    self.logger.info(
                        f"Connected! Subscribing to orderbook for {', '.join(self.market_tickers)}"
                    )

                    subscribe_msg = {
                        "id": 1,
                        "cmd": "subscribe",
                        "params": {
                            "channels": ["orderbook_delta"],
                            "market_tickers": self.market_tickers,
                        },
                    }

                    await websocket.send(json.dumps(subscribe_msg))

                    async for message in websocket:
                        await self.message_queue.put(message)

            except websockets.exceptions.ConnectionClosedError as e:
                self.logger.error(f"WebSocket connection closed: {e}")
                self.logger.info("Reconnecting in 5 seconds...")
                await asyncio.sleep(5)
            except websockets.exceptions.ConnectionClosedOK:
                self.logger.info("WebSocket connection closed normally")
                break
            except Exception as e:
                self.logger.error(f"WebSocket error: {e}")
                print(f"WebSocket error: {e}")
                self.logger.info("Reconnecting in 5 seconds...")
                await asyncio.sleep(5)

    def snapshot_all_books(self):
        return {ticker: ob.snapshot_top() for ticker, ob in self.orderbooks.items()}

    def get_best_bid(self, market_ticker):
        orderbook = self.orderbooks.get(market_ticker, None)
        if not orderbook:
            self.logger.warning(
                f"Order Book with market ticker {market_ticker} not found on get_best_bid"
            )
            return None, None
        return orderbook.get_best_bid()

    def get_best_ask(self, market_ticker):
        orderbook = self.orderbooks.get(market_ticker, None)
        if not orderbook:
            self.logger.warning(
                f"Order Book with market ticker {market_ticker} not found on get_best_ask"
            )
            return None, None
        return orderbook.get_best_ask()


if __name__ == "__main__":
    from setup_loggers import setup_logging

    setup_logging()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    client = KalshiWebSocket(KEY_ID, PRIVATE_KEY_PATH, get_asset_ids("Kalshi"), WS_URL)
    asyncio.run(client.orderbook_websocket())