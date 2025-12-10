from collections import defaultdict
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
        if size == 0 and price in book_side:
            del book_side[price]
        else:
            book_side[price] = size
            
    def get_best_bid(self):
        if not self.bids:
            return None, None
        
        price = self.bids.peekitem(-1)[0]
        size = self.bids.peekitem(0)[1]
        
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
            price = level["price"]
            size = level["size"]
            self.update_order_book(side=0, price=price, size=size)
            
        # Update asks
        for level in snapshot["asks"]:
            price = level["price"]
            size = level["size"]
            self.update_order_book(side=0, price=price, size=size)
            
    def load_kalshi_snapshot(self, snapshot):
        asset_id = snapshot["market_ticker"]
        
        # Update bids
        for price, size in snapshot.get("bids", []):
            self.update_order_book(side=0, price=price, size=size)
            
        # Update asks
        for price, size in snapshot.get("asks", []):
            self.update_order_book(side=0, price=price, size=size)