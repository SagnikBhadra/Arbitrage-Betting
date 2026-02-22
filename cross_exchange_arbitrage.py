import json
import logging
from decimal import Decimal

from polymarket_us_feed import PolymarketUSWebSocket
from polymarket_us_http_gateway import PolymarketUSHTTPGateway
from kalshi_feed import KalshiWebSocket
from kalshi_http_gateway import KalshiHTTPGateway, load_private_key
from utils import get_maker_fees_kalshi, get_taker_fees_kalshi
from collections import defaultdict
class CrossExchangeArbitrage:
    """
    Detects arbitrage opportunities between Polymarket US and Kalshi
    for 2-outcome moneyline markets.

    Required orderbook interface:
        orderbook.get_best_bid() -> (price, size) or (None, None)
        orderbook.get_best_ask() -> (price, size) or (None, None)
    """

    def __init__(self, polymarket_client: PolymarketUSWebSocket, kalshi_client: KalshiWebSocket, mapping: dict, min_edge=0.0):
        self.polymarket_client = polymarket_client
        self.kalshi_client = kalshi_client
        self.mapping = mapping
        self.min_edge = Decimal(min_edge)  # buffer for fees/slippage
        self.logger = logging.getLogger("cross_exchange_strategy")

    def _get_books(self, poly_id, kalshi_ticker):
        poly_ob = self.polymarket_client.orderbooks.get(poly_id)
        kalshi_ob = self.kalshi_client.orderbooks.get(kalshi_ticker)
        return poly_ob, kalshi_ob

    def _best_prices(self, orderbook):
        if not orderbook:
            return None, None, None, None
        bid, bid_size = orderbook.get_best_bid()
        ask, ask_size = orderbook.get_best_ask()
        return bid, bid_size, ask, ask_size

    def _same_side_arb(self, poly_id, kalshi_ticker, poly_bid: Decimal, poly_bid_size, poly_ask: Decimal, poly_ask_size,
                       kalshi_bid: Decimal, kalshi_bid_size, kalshi_ask: Decimal, kalshi_ask_size):

        # Ask on Kalshi < Bid on Polymarket (1, 2, 3, 4)
        # Buy Kalshi, Sell Polymarket

        if poly_bid and kalshi_ask and (poly_bid - kalshi_ask) > self.min_edge:
            size = min(poly_bid_size, kalshi_ask_size)
            self.logger.info({
                "type": "same_side",
                "direction": "buy_kalshi_sell_poly",
                "poly_id": poly_id,
                "kalshi_ticker": kalshi_ticker,
                "buy_price": kalshi_ask,
                "sell_price": poly_bid,
                "edge": poly_bid - kalshi_ask,
                "size": size
            })

        # Ask on Polymarket < Bid on Kalshi
        # Buy Polymarket, Sell Kalshi
        if kalshi_bid and poly_ask and (kalshi_bid - poly_ask) > self.min_edge:
            size = min(kalshi_bid_size, poly_ask_size)
            self.logger.info({
                "type": "same_side",
                "direction": "buy_poly_sell_kalshi",
                "poly_id": poly_id,
                "kalshi_ticker": kalshi_ticker,
                "buy_price": poly_ask,
                "sell_price": kalshi_bid,
                "edge": kalshi_bid - poly_ask,
                "size": size
            })

    def _double_buy_arb(self, ask_A_price: Decimal, ask_A_size: Decimal, ask_A_market: str, ask_B_price: Decimal, ask_B_size: Decimal, ask_B_market: str):
        # Synthetic arbitrage
        # If asks for Team 1 + Team 2 < $1
        # Stategies 5, 6, 9, 10
        if ask_A_price and ask_B_price:
            total_cost = ask_A_price + ask_B_price
            profit = Decimal(1) - total_cost
            if profit > self.min_edge:
                self.logger.info({
                    "type": "double_buy",
                    "total_cost": total_cost,
                    "profit": profit,
                    "market_A": ask_A_market,
                    "ask_A_price": ask_A_price,
                    "ask_A_size": ask_A_size,
                    "market_B": ask_B_market,
                    "ask_B_price": ask_B_price,
                    "ask_B_size": ask_B_size
                })

    def _double_sell_arb(self, bid_A_price: Decimal, bid_A_size: Decimal, bid_A_market: str, bid_B_price: Decimal, bid_B_size: Decimal, bid_B_market: str):
        # Short sell
        # If we have positions, we can use arbritage to sell out of the position
        # Strategies 7, 8

        if bid_A_price and bid_B_price:
            total_sale = bid_A_price + bid_B_price
            profit = total_sale - Decimal(1)
            if profit > self.min_edge:
                self.logger.info({
                    "type": "double_sell",
                    "total_sale": total_sale,
                    "profit": profit,
                    "market_A": bid_A_market,
                    "bid_A_price": bid_A_price,
                    "bid_A_size": bid_A_size,
                    "market_B": bid_B_market,
                    "bid_B_price": bid_B_price,
                    "bid_B_size": bid_B_size
                })

    def find_opportunities(self):

        for poly_id, m in self.mapping.items():
            kalshi_ticker = m["kalshi_ticker"]
            other_poly_id = m["other_poly_id"]
            other_kalshi_ticker = m["other_kalshi_ticker"]

            poly_A, kalshi_A = self._get_books(poly_id, kalshi_ticker)
            poly_B, kalshi_B = self._get_books(other_poly_id, other_kalshi_ticker)

            if not (poly_A and kalshi_A and poly_B and kalshi_B):
                self.logger.warning(
                    f"Orderbook missing for {poly_id} or {kalshi_ticker} "
                    f"or {other_poly_id} or {other_kalshi_ticker}. Skipping."
                )
                continue

            poly_bid_A, poly_bid_A_size, poly_ask_A, poly_ask_A_size = self._best_prices(poly_A)
            kalshi_bid_A, kalshi_bid_A_size, kalshi_ask_A, kalshi_ask_A_size = self._best_prices(kalshi_A)
            
            poly_bid_B, poly_bid_B_size, poly_ask_B, poly_ask_B_size = self._best_prices(poly_B)
            kalshi_bid_B, kalshi_bid_B_size, kalshi_ask_B, kalshi_ask_B_size = self._best_prices(kalshi_B)
            
            poly_ask_A, poly_bid_A, poly_ask_B, poly_bid_B, kalshi_ask_A, kalshi_bid_A, kalshi_ask_B, kalshi_bid_B = map(lambda x: Decimal(x) if x else None, [poly_ask_A, poly_bid_A, poly_ask_B, poly_bid_B, kalshi_ask_A, kalshi_bid_A, kalshi_ask_B, kalshi_bid_B])

            # ---- SAME SIDE ARBS (A + B independently) ----
            # Stragies 1, 2, 3, 4
            self._same_side_arb(
                poly_id, kalshi_ticker,
                poly_bid_A, poly_bid_A_size, poly_ask_A, poly_ask_A_size,
                kalshi_bid_A, kalshi_bid_A_size, kalshi_ask_A, kalshi_ask_A_size
            )

            self._same_side_arb(
                other_poly_id, other_kalshi_ticker,
                poly_bid_B, poly_bid_B_size, poly_ask_B, poly_ask_B_size,
                kalshi_bid_B, kalshi_bid_B_size, kalshi_ask_B, kalshi_ask_B_size
            )

            # ---- DOUBLE BUY (synthetic long event) ----
            # Strategies 5, 6, 9, 10
            if poly_ask_A and kalshi_ask_A:
                if poly_ask_A <= kalshi_ask_A:
                    best_ask_A = poly_ask_A
                    best_ask_A_size = poly_ask_A_size
                    best_ask_A_market = "Polymarket"
                else:
                    best_ask_A = kalshi_ask_A
                    best_ask_A_size = kalshi_ask_A_size
                    best_ask_A_market = "Kalshi"
            else:
                self.logger.warning(f"Missing ask price for {poly_id} or {kalshi_ticker}. Skipping double buy arb.")
                continue
            if poly_ask_B and kalshi_ask_B:
                if poly_ask_B <= kalshi_ask_B:
                    best_ask_B = poly_ask_B
                    best_ask_B_size = poly_ask_B_size
                    best_ask_B_market = "Polymarket"
                else:
                    best_ask_B = kalshi_ask_B
                    best_ask_B_size = kalshi_ask_B_size
                    best_ask_B_market = "Kalshi"
            else:
                self.logger.warning(f"Missing ask price for {other_poly_id} or {other_kalshi_ticker}. Skipping double buy arb.")
                continue

            self._double_buy_arb(best_ask_A, best_ask_A_size, best_ask_A_market, best_ask_B, best_ask_B_size, best_ask_B_market)

            # ---- DOUBLE SELL (synthetic short event) ----
            """
            if poly_bid_A and kalshi_bid_A:
                if poly_bid_A >= kalshi_bid_A:
                    best_bid_A = poly_bid_A
                    best_bid_A_size = poly_bid_A_size
                    best_bid_A_market = "Polymarket"
                else:
                    best_bid_A = kalshi_bid_A
                    best_bid_A_size = kalshi_bid_A_size
                    best_bid_A_market = "Kalshi"
            else:
                self.logger.warning(f"Missing bid price for {poly_id} or {kalshi_ticker}. Skipping double sell arb.")
                continue
            if poly_bid_B and kalshi_bid_B:
                if poly_bid_B >= kalshi_bid_B:
                    best_bid_B = poly_bid_B
                    best_bid_B_size = poly_bid_B_size
                    best_bid_B_market = "Polymarket"
                else:
                    best_bid_B = kalshi_bid_B
                    best_bid_B_size = kalshi_bid_B_size
                    best_bid_B_market = "Kalshi"
            else:
                self.logger.warning(f"Missing bid price for {other_poly_id} or {other_kalshi_ticker}. Skipping double sell arb.")
                continue

            self._double_sell_arb(best_bid_A, best_bid_A_size, best_bid_A_market, best_bid_B, best_bid_B_size, best_bid_B_market)
            """
            # Need to create strategies for NO sides



if __name__ == "__main__":
    # Example usage
    """
    arb_engine = CrossExchangeArbitrage(
        polymarket_client,
        kalshi_client,
        polymarket_kalshi_mapping,
        min_edge=0.01
    )
    

    opps = arb_engine.find_opportunities()

    for o in opps:
        print(o)
        
    """
    pass
