"""
Orderbook Snapshot Collector for Kalshi Events

This script connects to Kalshi's WebSocket API and collects orderbook snapshots
of related market events at a configurable interval (default: 1 second).
"""

import asyncio
import base64
import csv
import json
import os
import time
from datetime import datetime
from collections import defaultdict
from decimal import Decimal

import websockets
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from sortedcontainers import SortedDict


# Configuration
SNAPSHOT_INTERVAL = 1  # seconds (change to 10 if 1 second is an issue)
OUTPUT_DIR = "snapshots"
WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"


def load_kalshi_key_id(secrets_path: str = "kalshi_secrets.json") -> str:
    """Load Kalshi API Key ID from secrets file."""
    with open(secrets_path, "r") as f:
        data = json.load(f)
    return data["KEY_ID"]


def load_kalshi_tickers() -> list:
    """Load Kalshi tickers from statics.json."""
    with open("statics/statics.json", "r") as f:
        statics = json.load(f)
    return list(statics["ASSET_ID_MAPPING"]["Kalshi"].keys())


def load_private_key(path: str):
    """Load RSA private key from file."""
    with open(path, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


class SimpleOrderBook:
    """Minimal orderbook implementation for snapshot collection."""
    
    def __init__(self, ticker: str):
        self.ticker = ticker
        self.bids = SortedDict()  # price -> size (YES side)
        self.asks = SortedDict()  # price -> size (NO side, converted)
        self.last_update_time = None
    
    def update(self, side: int, price: float, size: float):
        """Update orderbook. side: 0=bid, 1=ask"""
        book = self.bids if side == 0 else self.asks
        if size <= 0 and price in book:
            del book[price]
        else:
            book[price] = size
        self.last_update_time = datetime.now()
    
    def load_snapshot(self, msg: dict):
        """Load initial orderbook snapshot from Kalshi."""
        # Clear existing data
        self.bids.clear()
        self.asks.clear()
        
        # Load YES (bids)
        for price, size in msg.get("yes_dollars", []):
            self.update(0, float(price), float(size))
        
        # Load NO (asks) - convert price
        for price, size in msg.get("no_dollars", []):
            ask_price = float(Decimal("1.0") - Decimal(price))
            self.update(1, ask_price, float(size))
    
    def handle_delta(self, msg: dict):
        """Handle orderbook delta update."""
        price = float(msg["price_dollars"])
        delta = float(msg["delta"])
        
        if msg["side"] == "yes":
            current_size = self.bids.get(price, 0)
            self.update(0, price, current_size + delta)
        else:
            # Convert NO price to ask price
            ask_price = float(Decimal("1.0") - Decimal(msg["price_dollars"]))
            current_size = self.asks.get(ask_price, 0)
            self.update(1, ask_price, current_size + delta)
    
    def get_best_bid(self):
        """Get best bid price and size."""
        if not self.bids:
            return None, None
        return self.bids.peekitem(-1)
    
    def get_best_ask(self):
        """Get best ask price and size."""
        if not self.asks:
            return None, None
        return self.asks.peekitem(0)
    
    def get_snapshot(self) -> dict:
        """Get current orderbook state as a snapshot."""
        best_bid_price, best_bid_size = self.get_best_bid()
        best_ask_price, best_ask_size = self.get_best_ask()
        
        return {
            "ticker": self.ticker,
            "timestamp": datetime.now().isoformat(),
            "best_bid_price": best_bid_price,
            "best_bid_size": best_bid_size,
            "best_ask_price": best_ask_price,
            "best_ask_size": best_ask_size,
            "bid_levels": len(self.bids),
            "ask_levels": len(self.asks),
            "full_bids": dict(self.bids),
            "full_asks": dict(self.asks),
        }


class OrderbookSnapshotCollector:
    """Collects orderbook snapshots from Kalshi WebSocket."""
    
    def __init__(self, tickers: list, key_id: str, private_key_path: str = "Kalshi.key"):
        self.tickers = tickers
        self.key_id = key_id
        self.private_key_path = private_key_path
        self.orderbooks = {ticker: SimpleOrderBook(ticker) for ticker in tickers}
        self.snapshots = []
        self.running = False
        
        # Create output directory
        os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    def sign_pss_text(self, private_key, text: str) -> str:
        """Sign message using RSA-PSS."""
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
        """Create authentication headers for Kalshi WebSocket."""
        timestamp = str(int(time.time() * 1000))
        msg_string = timestamp + method + path.split("?")[0]
        signature = self.sign_pss_text(private_key, msg_string)
        
        return {
            "Content-Type": "application/json",
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
        }
    
    def handle_message(self, data: dict):
        """Process incoming WebSocket message."""
        msg_type = data.get("type")
        msg_content = data.get("msg", {})
        
        if msg_type == "subscribed":
            print(f"Subscribed: {data}")
        
        elif msg_type == "orderbook_snapshot":
            ticker = msg_content.get("market_ticker")
            if ticker in self.orderbooks:
                self.orderbooks[ticker].load_snapshot(msg_content)
                print(f"Loaded snapshot for {ticker}")
        
        elif msg_type == "orderbook_delta":
            ticker = msg_content.get("market_ticker")
            if ticker in self.orderbooks:
                self.orderbooks[ticker].handle_delta(msg_content)
        
        elif msg_type == "error":
            print(f"Error: {data}")
    
    def collect_snapshot(self) -> dict:
        """Collect current snapshot of all orderbooks."""
        timestamp = datetime.now().isoformat()
        snapshot = {
            "timestamp": timestamp,
            "orderbooks": {}
        }
        
        for ticker, orderbook in self.orderbooks.items():
            snapshot["orderbooks"][ticker] = orderbook.get_snapshot()
        
        return snapshot
    
    def save_snapshot_to_csv(self, snapshot: dict):
        """Save snapshot to CSV file."""
        timestamp_str = datetime.now().strftime("%Y%m%d")
        filename = os.path.join(OUTPUT_DIR, f"orderbook_snapshots_{timestamp_str}.csv")
        
        file_exists = os.path.exists(filename)
        
        with open(filename, "a", newline="") as f:
            writer = csv.writer(f)
            
            # Write header if new file
            if not file_exists:
                writer.writerow([
                    "timestamp",
                    "ticker",
                    "best_bid_price",
                    "best_bid_size",
                    "best_ask_price",
                    "best_ask_size",
                    "bid_levels",
                    "ask_levels",
                    "spread",
                ])
            
            # Write snapshot data for each ticker
            for ticker, ob_data in snapshot["orderbooks"].items():
                spread = None
                if ob_data["best_ask_price"] and ob_data["best_bid_price"]:
                    spread = round(ob_data["best_ask_price"] - ob_data["best_bid_price"], 4)
                
                writer.writerow([
                    snapshot["timestamp"],
                    ticker,
                    ob_data["best_bid_price"],
                    ob_data["best_bid_size"],
                    ob_data["best_ask_price"],
                    ob_data["best_ask_size"],
                    ob_data["bid_levels"],
                    ob_data["ask_levels"],
                    spread,
                ])
    
    def print_snapshot(self, snapshot: dict):
        """Print snapshot to console."""
        print(f"\n{'='*60}")
        print(f"Snapshot at {snapshot['timestamp']}")
        print(f"{'='*60}")
        
        for ticker, ob_data in snapshot["orderbooks"].items():
            best_bid = ob_data["best_bid_price"]
            best_ask = ob_data["best_ask_price"]
            spread = None
            if best_bid and best_ask:
                spread = round(best_ask - best_bid, 4)
            
            print(f"\n{ticker}:")
            print(f"  Best Bid: {best_bid} (size: {ob_data['best_bid_size']})")
            print(f"  Best Ask: {best_ask} (size: {ob_data['best_ask_size']})")
            print(f"  Spread: {spread}")
            print(f"  Levels: {ob_data['bid_levels']} bids, {ob_data['ask_levels']} asks")
    
    async def snapshot_loop(self):
        """Periodically collect and save snapshots."""
        while self.running:
            await asyncio.sleep(SNAPSHOT_INTERVAL)
            
            snapshot = self.collect_snapshot()
            self.snapshots.append(snapshot)
            
            # Print to console
            self.print_snapshot(snapshot)
            
            # Save to CSV
            self.save_snapshot_to_csv(snapshot)
    
    async def websocket_loop(self):
        """Connect to WebSocket and process messages with auto-reconnect."""
        while self.running:
            try:
                private_key = load_private_key(self.private_key_path)
                headers = self.create_headers(private_key, "GET", "/trade-api/ws/v2")
                
                async with websockets.connect(
                    WS_URL,
                    additional_headers=headers,
                    ping_interval=20,  # Send ping every 20 seconds
                    ping_timeout=10,   # Wait 10 seconds for pong
                    close_timeout=5,
                ) as websocket:
                    print(f"Connected to Kalshi WebSocket")
                    print(f"Subscribing to orderbooks for: {', '.join(self.tickers)}")
                    
                    # Subscribe to orderbook
                    subscribe_msg = {
                        "id": 1,
                        "cmd": "subscribe",
                        "params": {
                            "channels": ["orderbook_delta"],
                            "market_tickers": self.tickers,
                        },
                    }
                    await websocket.send(json.dumps(subscribe_msg))
                    
                    # Process messages
                    async for message in websocket:
                        if not self.running:
                            break
                        data = json.loads(message)
                        self.handle_message(data)
                        
            except websockets.exceptions.ConnectionClosedError as e:
                print(f"WebSocket connection closed: {e}")
                if self.running:
                    print("Reconnecting in 5 seconds...")
                    await asyncio.sleep(5)
            except websockets.exceptions.ConnectionClosedOK:
                print("WebSocket connection closed normally")
                break
            except Exception as e:
                print(f"WebSocket error: {e}")
                if self.running:
                    print("Reconnecting in 5 seconds...")
                    await asyncio.sleep(5)
    
    async def run(self):
        """Run the snapshot collector."""
        self.running = True
        
        print(f"Starting Orderbook Snapshot Collector")
        print(f"Tickers: {self.tickers}")
        print(f"Snapshot interval: {SNAPSHOT_INTERVAL} second(s)")
        print(f"Output directory: {OUTPUT_DIR}")
        
        try:
            await asyncio.gather(
                self.websocket_loop(),
                self.snapshot_loop(),
            )
        except KeyboardInterrupt:
            print("\nShutting down...")
            self.running = False
        except asyncio.CancelledError:
            print("\nTask cancelled, shutting down...")
            self.running = False
        except Exception as e:
            print(f"Error: {e}")
            self.running = False
            raise


async def main():
    """Main entry point."""
    # Load configuration
    key_id = load_kalshi_key_id()
    tickers = load_kalshi_tickers()
    
    print(f"Loaded {len(tickers)} tickers from statics.json: {tickers}")
    
    if len(tickers) < 2:
        print("Warning: Less than 2 tickers found. Add more tickers to statics.json")
    
    # Create and run collector
    collector = OrderbookSnapshotCollector(
        tickers=tickers,
        key_id=key_id,
        private_key_path="Kalshi.key",
    )
    
    await collector.run()


if __name__ == "__main__":
    asyncio.run(main())
