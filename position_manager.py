import asyncio
from collections import defaultdict

class PositionManager:
    def __init__(self, positions:defaultdict):
        self.positions = positions
        self.lock = asyncio.Lock()
        
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
        return self.positions.get(ticker, 0)

    # ---------------------------------------------------------
    # Get All Positions
    # ---------------------------------------------------------
    def get_all_positions(self):
        with self.lock:
            return dict(self.positions)