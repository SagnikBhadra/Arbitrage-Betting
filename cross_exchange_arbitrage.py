import json
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
        opportunities = []

        # Ask on Kalshi < Bid on Polymarket (1, 2, 3, 4)
        # Buy Kalshi, Sell Polymarket

        if poly_bid and kalshi_ask and (poly_bid - kalshi_ask) > self.min_edge:
            size = min(poly_bid_size, kalshi_ask_size)
            opportunities.append({
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
            opportunities.append({
                "type": "same_side",
                "direction": "buy_poly_sell_kalshi",
                "poly_id": poly_id,
                "kalshi_ticker": kalshi_ticker,
                "buy_price": poly_ask,
                "sell_price": kalshi_bid,
                "edge": kalshi_bid - poly_ask,
                "size": size
            })

        return opportunities

    def _double_buy_arb(self, ask_A: Decimal, ask_B: Decimal):
        # Synthetic arbitrage
        # If asks for Team 1 + Team 2 < $1
        # Stategies 5, 6, 9, 10
        if ask_A and ask_B:
            total_cost = ask_A + ask_B
            if (1 - total_cost) > self.min_edge:
                return {
                    "type": "double_buy",
                    "total_cost": total_cost,
                    "profit": 1 - total_cost
                }
        return None

    def _double_sell_arb(self, bid_A: Decimal, bid_B: Decimal):
        # Short sell
        # If we have positions, we can use arbritage to sell out of the position
        # Strategies 7, 8
        
        if bid_A and bid_B:
            total_sale = bid_A + bid_B
            if (total_sale - 1) > self.min_edge:
                return {
                    "type": "double_sell",
                    "total_sale": total_sale,
                    "profit": total_sale - 1
                }
        return None

    def find_opportunities(self):
        results = []

        for poly_id, m in self.mapping.items():
            kalshi_ticker = m["kalshi_ticker"]
            other_poly_id = m["other_poly_id"]
            other_kalshi_ticker = m["other_kalshi_ticker"]

            poly_A, kalshi_A = self._get_books(poly_id, kalshi_ticker)
            poly_B, kalshi_B = self._get_books(other_poly_id, other_kalshi_ticker)

            if not (poly_A and kalshi_A and poly_B and kalshi_B):
                print(f"Orderbook missing for {poly_id} or {kalshi_ticker} or {other_poly_id} or {other_kalshi_ticker}. Skipping.")
                continue

            poly_bid_A, poly_bid_A_size, poly_ask_A, poly_ask_A_size = self._best_prices(poly_A)
            kalshi_bid_A, kalshi_bid_A_size, kalshi_ask_A, kalshi_ask_A_size = self._best_prices(kalshi_A)
            
            poly_bid_B, poly_bid_B_size, poly_ask_B, poly_ask_B_size = self._best_prices(poly_B)
            kalshi_bid_B, kalshi_bid_B_size, kalshi_ask_B, kalshi_ask_B_size = self._best_prices(kalshi_B)
            
            poly_ask_A, poly_bid_A, poly_ask_B, poly_bid_B, kalshi_ask_A, kalshi_bid_A, kalshi_ask_B, kalshi_bid_B = map(lambda x: Decimal(x) if x else None, [poly_ask_A, poly_bid_A, poly_ask_B, poly_bid_B, kalshi_ask_A, kalshi_bid_A, kalshi_ask_B, kalshi_bid_B])

            # ---- SAME SIDE ARBS (A + B independently) ----
            # Stragies 1, 2, 3, 4
            results += self._same_side_arb(
                poly_id, kalshi_ticker,
                poly_bid_A, poly_bid_A_size, poly_ask_A, poly_ask_A_size,
                kalshi_bid_A, kalshi_bid_A_size, kalshi_ask_A, kalshi_ask_A_size
            )

            results += self._same_side_arb(
                other_poly_id, other_kalshi_ticker,
                poly_bid_B, poly_bid_B_size, poly_ask_B, poly_ask_B_size,
                kalshi_bid_B, kalshi_bid_B_size, kalshi_ask_B, kalshi_ask_B_size
            )

            # ---- DOUBLE BUY (synthetic long event) ----
            # Strategies 5, 6, 9, 10
            if poly_ask_A and kalshi_ask_A:
                best_ask_A = min(x for x in [poly_ask_A, kalshi_ask_A] if x)
            else:
                print(f"Missing ask price for {poly_id} or {kalshi_ticker}. Skipping double buy arb.")
                continue
            if poly_ask_B and kalshi_ask_B:
                best_ask_B = min(x for x in [poly_ask_B, kalshi_ask_B] if x)
            else:
                print(f"Missing ask price for {other_poly_id} or {other_kalshi_ticker}. Skipping double buy arb.")
                continue

            arb = self._double_buy_arb(best_ask_A, best_ask_B)
            if arb:
                arb["poly_id"] = poly_id
                results.append(arb)

            # ---- DOUBLE SELL (synthetic short event) ----
            if poly_bid_A and kalshi_bid_A:
                best_bid_A = max(x for x in [poly_bid_A, kalshi_bid_A] if x)
            else:
                print(f"Missing bid price for {poly_id} or {kalshi_ticker}. Skipping double sell arb.")
                continue
            if poly_bid_B and kalshi_bid_B:
                best_bid_B = max(x for x in [poly_bid_B, kalshi_bid_B] if x)
            else:
                print(f"Missing bid price for {other_poly_id} or {other_kalshi_ticker}. Skipping double sell arb.")
                continue

            arb = self._double_sell_arb(best_bid_A, best_bid_B)
            if arb:
                arb["poly_id"] = poly_id
                results.append(arb)

            # Need to create strategies for NO sides

        return results


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
