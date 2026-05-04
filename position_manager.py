import threading
from collections import defaultdict

class PositionManager:
    def __init__(self, positions:defaultdict, open_orders: defaultdict(defaultdict) = defaultdict(defaultdict)):
        self.positions = positions
        self.open_orders = open_orders
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
    def add_open_orders(self, ticker, order):
        with self.lock:
            self.open_orders[ticker][order["client_order_id"]] = order

    def remove_open_order(self, ticker, order):
        with self.lock:
            self.open_orders[ticker].pop(order["client_order_id"])

    # ---------------------------------------------------------
    # Retrieve Open Orders
    # ---------------------------------------------------------
    def get_open_orders_for_ticker(self, ticker):
        with self.lock:
            return self.open_orders[ticker]