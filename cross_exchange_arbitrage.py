import json
import logging
import uuid
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

    def __init__(self, polymarket_client: PolymarketUSWebSocket, kalshi_client: KalshiWebSocket, polymarket_us_gateway: PolymarketUSHTTPGateway, kalshi_gateway: KalshiHTTPGateway, mapping: dict, min_edge=0.0):
        # Market data clients
        self.polymarket_client = polymarket_client
        self.kalshi_client = kalshi_client

        # Gateways for order execution
        self.polymarket_gateway = polymarket_us_gateway
        self.kalshi_gateway = kalshi_gateway

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
        # TODO: Add maker/taker fee adjustments to edge calculation
        if poly_bid and kalshi_ask and (poly_bid - kalshi_ask) > self.min_edge:
            size = int(min(poly_bid_size, kalshi_ask_size))  # TODO: Add balance checks to size calculation
            self.logger.info({
                "type": "same_side",
                "direction": "buy_kalshi_sell_poly",
                "poly_id": poly_id,
                "kalshi_ticker": kalshi_ticker,
                "buy_price": kalshi_ask,
                "sell_price": poly_bid,
                "edge": poly_bid - kalshi_ask,
                "size": int(size)
            })
            # Send orders to gateway for execution
            # Kalshi
            order_a = {
                "ticker": kalshi_ticker,
                "action": "buy",
                "side": "yes",
                "count": int(size),
                "client_order_id": str(uuid.uuid4()),
                "yes_price": int(float(kalshi_ask) * 100),
                "type": "limit",
                "time_in_force": "fill_or_kill"
            }
            try:
                self.kalshi_gateway.create_order(order_a)
            except Exception as e:
                self.logger.error(f"Failed to place order A: {e}")
            # Polymarket - Need BUY_SHORT at 1 - bid price to sell at bid price
            try:
                if poly_id.endswith("-inverse"):
                    side = "BUY_SHORT"
                else:
                    side = "BUY_LONG"
                self.polymarket_gateway.create_order(
                    market_slug=poly_id,
                    price=float(Decimal(1.0) - poly_bid),
                    quantity=int(size),
                    side=side,
                    tif="FILL_OR_KILL",
                    order_type="LIMIT",
                )
            except Exception as e:
                self.logger.error(f"Failed to place order B: {e}")

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
                "size": int(size)
            })
            # Send orders to gateway for execution
            # Polymarket - Need BUY_LONG at ask price to buy at ask price
            try:
                side = "BUY_SHORT" if poly_id.endswith("-inverse") else "BUY_LONG"
                self.polymarket_gateway.create_order(
                    market_slug=poly_id,
                    price=float(poly_ask),
                    quantity=int(size),
                    side=side,
                    tif="FILL_OR_KILL",
                    order_type="LIMIT",
                )  
            except Exception as e:
                self.logger.error(f"Failed to place order A: {e}")
            # Kalshi - Buy NO ASK at 1 - bid price 
            order_b = {
                "ticker": kalshi_ticker,
                "action": "buy",
                "side": "no",
                "count": int(size),
                "client_order_id": str(uuid.uuid4()),
                "no_price": int(float(Decimal(1.0) - kalshi_bid) * 100),
                "type": "limit",
                "time_in_force": "fill_or_kill"
            }
            try:
                self.kalshi_gateway.create_order(order_b)
            except Exception as e:
                self.logger.error(f"Failed to place order B: {e}")

    def _double_buy_arb(self, order_A: dict, order_B: dict):
        # Synthetic arbitrage
        # If asks for Team 1 + Team 2 < $1
        # Stategies 5, 6, 9, 10
        if order_A["ask_price"] and order_B["ask_price"]:
            total_cost = Decimal(order_A["ask_price"]) + Decimal(order_B["ask_price"])
            profit = Decimal(Decimal(1) - total_cost)
            if profit > self.min_edge:
                self.logger.info({
                    "type": "double_buy",
                    "total_cost": total_cost,
                    "profit": profit,
                    "market_A": order_A["ask_market"],
                    "ask_price": order_A["ask_price"],
                    "ask_size": order_A["ask_size"],
                    "market_B": order_B["ask_market"],
                    "ask_B_price": order_B["ask_price"],
                    "ask_B_size": order_B["ask_size"]
                })
                # Need to update order if Polymarket inverse
                for order in [order_A, order_B]:
                    try:
                        if "Polymarket" in order["ask_market"]:
                            side = "BUY_SHORT" if order["ask_market"].endswith("-inverse") else "BUY_LONG"
                            self.polymarket_gateway.create_order(
                                market_slug=order["ask_market"].split(": ")[1],
                                price=float(order["ask_price"]),
                                quantity=int(order["ask_size"]),
                                side=side,
                                tif="FILL_OR_KILL",
                                order_type="LIMIT",
                            )
                        elif "Kalshi" in order["ask_market"]:
                            self.kalshi_gateway.create_order({
                                "ticker": order["ask_market"].split(": ")[1],
                                "action": "buy",
                                "side": "yes",
                                "count": int(order["ask_size"]),
                                "client_order_id": str(uuid.uuid4()),
                                "yes_price": int(float(order["ask_price"]) * 100),
                                "type": "limit",
                                "time_in_force": "fill_or_kill"
                            })
                    except Exception as e:
                        self.logger.error(f"Failed to place order: {e}")


    def _double_sell_arb(self, order_A: dict, order_B: dict):
        # Short sell
        # If we have positions, we can use arbritage to sell out of the position
        # Strategies 7, 8

        if order_A["bid_price"] and order_B["bid_price"]:
            total_sale = Decimal(order_A["bid_price"]) + Decimal(order_B["bid_price"])
            profit = Decimal(total_sale - Decimal(1))
            if profit > self.min_edge:
                self.logger.info({
                    "type": "double_sell",
                    "total_sale": total_sale,
                    "profit": profit,
                    "market_A": order_A["bid_market"],
                    "bid_A_price": order_A["bid_price"],
                    "bid_A_size": order_A["bid_size"],
                    "market_B": order_B["bid_market"],
                    "bid_B_price": order_B["bid_price"],
                    "bid_B_size": order_B["bid_size"]
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
                    order_A = {
                        "ask_price": poly_ask_A,
                        "ask_size": poly_ask_A_size,
                        "ask_market": f"Polymarket: {poly_id}"
                    }
                else:
                    order_A = {
                        "ask_price": kalshi_ask_A,
                        "ask_size": kalshi_ask_A_size,
                        "ask_market": f"Kalshi: {kalshi_ticker}"
                    }
            else:
                # self.logger.warning(f"Missing ask price for {poly_id} or {kalshi_ticker}. Skipping double buy arb.")
                continue
            if poly_ask_B and kalshi_ask_B:
                if poly_ask_B <= kalshi_ask_B:
                    order_B = {
                        "ask_price": poly_ask_B,
                        "ask_size": poly_ask_B_size,
                        "ask_market": f"Polymarket: {other_poly_id}"
                    }
                else:
                    order_B = {
                        "ask_price": kalshi_ask_B,
                        "ask_size": kalshi_ask_B_size,
                        "ask_market": f"Kalshi: {other_kalshi_ticker}"
                    }
            else:
                # self.logger.warning(f"Missing ask price for {other_poly_id} or {other_kalshi_ticker}. Skipping double buy arb.")
                continue

            self._double_buy_arb(order_A, order_B)

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
