from collections import defaultdict
from decimal import Decimal
from sortedcontainers import SortedDict

class OrderBook:
    def __init__(self, asset_id):
        # Orderbook = Asset ID -> Bids, Asks
        # Bids = Price -> Quantity
        #self.orderbook = defaultdict(lambda: {"bids": {}, "asks": {}})
        
        self.asset_id = asset_id
        # SortedDict in ascending order
        self.bids = SortedDict()
        self.asks = SortedDict()
        
    def update_order_book(self, side, price, size):
        book_side = self.bids if side == 0 else self.asks
        if size <= 0 and price in book_side:
            #print(f"Removing price level {price} from {'bids' if side == 0 else 'asks'}")
            del book_side[price]
        else:
            #print(f"Updating price level {price} in {'bids' if side == 0 else 'asks'} from size {book_side.get(price, 0)} to size {size}")
            book_side[price] = size
            
    def get_size_at_price(self, side, price):
        book = self.bids if side == 0 else self.asks
        return book[price] if price in book else 0
            
    def get_best_bid(self):
        if not self.bids:
            return None, None
        
        price = self.bids.peekitem(-1)[0]
        size = self.bids.peekitem(-1)[1]
        
        return price, size
    
    def get_best_ask(self):
        if not self.asks:
            return None, None
        
        price = self.asks.peekitem(0)[0]
        size = self.asks.peekitem(0)[1]
        
        return price, size
    
    def __repr__(self):
        return f"Asset ID: {self.asset_id} | Best Bid: {self.get_best_bid()} | Best Ask: {self.get_best_ask()}"
        
    def load_polymarket_snapshot(self, snapshot):
        asset_id = snapshot["asset_id"]
        
        # Update bids
        for level in snapshot["bids"]:
            price = float(level["price"])
            size = float(level["size"])
            self.update_order_book(side=0, price=price, size=size)
            
        # Update asks
        for level in snapshot["asks"]:
            price = float(level["price"])
            size = float(level["size"])
            self.update_order_book(side=1, price=price, size=size)
            
    def load_polymarket_us_snapshot(self, asset_id, snapshot):
        self.bids.clear()
        self.asks.clear()
        
        # BIDS
        for level in snapshot.get("bids", []):
            price = Decimal(1.0) - Decimal(level["px"]["value"]) if asset_id.endswith("-inverse") else Decimal(level["px"]["value"])
            size = Decimal(level["qty"])
            side = 1 if asset_id.endswith("-inverse") else 0
            #print(f"Price: {price}, Size: {size}, Side: {'ASK' if side == 1 else 'BID'}")
            self.update_order_book(side=side, price=price, size=size)

        # ASKS (called "offers" in Polymarket)
        for level in snapshot.get("offers", []):
            price = Decimal(1.0) - Decimal(level["px"]["value"]) if asset_id.endswith("-inverse") else Decimal(level["px"]["value"])
            size = Decimal(level["qty"])
            side = 0 if asset_id.endswith("-inverse") else 1
            #print(f"Price: {price}, Size: {size}, Side: {'BID' if side == 0 else 'ASK'}")
            self.update_order_book(side=side, price=price, size=size)

    def load_kalshi_snapshot(self, snapshot):
        asset_id = snapshot["market_ticker"]

        # Update bids
        for price, size in snapshot.get("yes_dollars", []):
            self.update_order_book(side=0, price=float(price), size=float(size))
            
        # Update asks (Use 1 - price to convert from "no" to "ask" price)
        for price, size in snapshot.get("no_dollars", []):
            print(f"Price: {Decimal('1.0') - Decimal(price)}, Size: {size}")
            self.update_order_book(side=1, price=Decimal('1.0') - Decimal(price), size=float(size))