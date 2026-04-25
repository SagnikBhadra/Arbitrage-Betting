import json
import logging
import math
import uuid
from decimal import Decimal

from polymarket_us_feed import PolymarketUSWebSocket
from polymarket_us_http_gateway import PolymarketUSHTTPGateway
from kalshi_feed import KalshiWebSocket
from kalshi_http_gateway import KalshiHTTPGateway, load_private_key
from position_manager import PositionManager
from utils import get_maker_fees_kalshi, get_taker_fees_kalshi, get_taker_fees_polymarket_us, get_maker_rebate_polymarket_us
from collections import defaultdict

class WideSpreadArbitrage:
    def __init__(self, polymarket_ws, polymarket_http, kalshi_ws, kalshi_http, position_manager):
        self.polymarket_ws = polymarket_ws
        self.polymarket_http = polymarket_http
        self.kalshi_ws = kalshi_ws
        self.kalshi_http = kalshi_http
        self.position_manager = position_manager
        self.logger = logging.getLogger("WideSpreadArbitrageBot")
        self.logger.setLevel(logging.INFO)