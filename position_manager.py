import threading
from collections import defaultdict

class PositionManager:
    def __init__(self, positions:defaultdict, open_orders: defaultdict = defaultdict(dict)):
        self.positions = positions
        self.open_orders = open_orders # Map of cleint_order_id to order details
        self.open_orders_by_ticker = defaultdict(set)  # Map ticker to set of client_order_id
        self.associated_orders = defaultdict(set)  # Map ticker to set of associated client_order_ids
        self.lock = threading.Lock()
        
    # ---------------------------------------------------------
    # Local Update From Trade Fill
    # ---------------------------------------------------------
    def update_from_fill(self, ticker, side, quantity):
        """
        Update position after a trade fill.

        side:
            "YES_BUY"
            "YES_SELL"
            "NO_BUY"
            "NO_SELL"
        """
        with self.lock:
            if side == "YES_BUY":
                self.positions[ticker] += quantity

            elif side == "YES_SELL":
                self.positions[ticker] -= quantity

            elif side == "NO_BUY":
                self.positions[ticker] -= quantity

            elif side == "NO_SELL":
                self.positions[ticker] += quantity

            else:
                raise ValueError(f"Unknown side {side}")

    # ---------------------------------------------------------
    # Get Position
    # ---------------------------------------------------------
    def get_position(self, ticker):
        with self.lock:
            return self.positions.get(ticker, 0)

    # ---------------------------------------------------------
    # Get All Positions
    # ---------------------------------------------------------
    def get_all_positions(self):
        with self.lock:
            return dict(self.positions)

    # ---------------------------------------------------------
    # Update Open Orders
    # ---------------------------------------------------------
    def add_open_order(self, ticker, order):
        with self.lock:
            self.open_orders[order["client_order_id"]] = order
            self.open_orders_by_ticker[ticker].add(order["client_order_id"])
            
    def get_open_order(self,client_order_id):
        with self.lock:
            return self.open_orders.get(client_order_id)

    def remove_open_order(self, ticker, order):
        with self.lock:
            del self.open_orders[order["client_order_id"]]
            self.open_orders_by_ticker[ticker].discard(order["client_order_id"])
            
    # ---------------------------------------------------------
    # Created Associated Orders
    # ---------------------------------------------------------
    # TODO: We might be able to use group orders feature in Kalshi to associate orders
    def add_associated_order(self, client_order_id, associated_order_id):
        with self.lock:
            if isinstance(associated_order_id, str):
                self.associated_orders[client_order_id].add(associated_order_id)
            else:
                self.associated_orders[client_order_id].update(associated_order_id)
            
    def get_associated_orders(self, client_order_id):
        with self.lock:
            return self.associated_orders[client_order_id]
        
    def remove_associated_order(self,client_order_id, associated_order_id):
        with self.lock:
            self.associated_orders[client_order_id].discard(associated_order_id)
            
    def remove_client_order_id_from_associated_orders(self, client_order_id):
        with self.lock:
            del self.associated_orders[client_order_id]

    # ---------------------------------------------------------
    # Retrieve Open Orders
    # ---------------------------------------------------------
    def get_open_orders_for_ticker(self, ticker):
        with self.lock:
            return self.open_orders_by_ticker[ticker]