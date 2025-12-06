from collections import defaultdict

class OrderBooks:
    def __init__(self):
        # Orderbook = Asset ID -> Bids, Asks
        # Bids = Price -> Quantity
        self.orderbooks = defaultdict(lambda: {"bids": {}, "asks": {}})
        
    def update_order_book(self, asset_id, side, price, size):
        book_side = self.orderbooks[asset_id]["bids"] if side == 0 else self.orderbooks[asset_id]["asks"]
        if size == 0:
            book_side.pop(price, None)
        else:
            book_side[price] = size
    
    def print_top_of_book(self):
        # Print top of book for all assets
        for asset_id in self.orderbooks.keys():
            self.print_top_of_book_single_asset(asset_id)
    
    def print_top_of_book_single_asset(self, asset_id):
        # Print top of book for given asset
        top_bid = max(self.orderbooks[asset_id]["bids"].items(), key=lambda x: x[0], default= (None, None))
        top_ask = min(self.orderbooks[asset_id]["asks"].items(), key=lambda x: x[0], default= (None, None))
        print(f"Asset ID: {asset_id} | Best Bid: {top_bid} | Best Ask: {top_ask}")