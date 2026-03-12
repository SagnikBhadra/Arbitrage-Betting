import json
import logging
import uuid
from decimal import Decimal

from polymarket_us_feed import PolymarketUSWebSocket
from polymarket_us_http_gateway import PolymarketUSHTTPGateway
from kalshi_feed import KalshiWebSocket
from kalshi_http_gateway import KalshiHTTPGateway, load_private_key
from utils import get_maker_fees_kalshi, get_taker_fees_kalshi, get_taker_fees_polymarket_us, get_maker_rebate_polymarket_us
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
        
        #Temporary balance tracking
        self.polymarket_us_balance = Decimal(self.polymarket_gateway.get_balance())
        self.kalshi_balance = Decimal(self.kalshi_gateway.get_balance())

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

    def _get_max_size(self, balance:Decimal, price:Decimal):
        if price == Decimal(0):
            return Decimal(0)
        return Decimal(balance / price)

    def _same_side_arb(self, poly_id, kalshi_ticker, poly_bid: Decimal, poly_bid_size, poly_ask: Decimal, poly_ask_size,
                       kalshi_bid: Decimal, kalshi_bid_size, kalshi_ask: Decimal, kalshi_ask_size):
        # Ask on Kalshi < Bid on Polymarket (1, 2, 3, 4)
        # Buy Kalshi, Sell Polymarket
        if poly_bid and kalshi_ask:
            # Add maker/taker fee adjustments to edge calculation
            kalshi_fee = get_taker_fees_kalshi(kalshi_ask, Decimal(1))
            polymarket_us_fee = get_taker_fees_polymarket_us(poly_bid, Decimal(1))
            fees = kalshi_fee + polymarket_us_fee
            if (poly_bid - kalshi_ask - fees) > self.min_edge:
                size = int(min(poly_bid_size, kalshi_ask_size, self._get_max_size(self.kalshi_balance, kalshi_ask), self._get_max_size(self.polymarket_us_balance, poly_bid)))  # TODO: Add balance checks to size calculation
                self.logger.info({
                    "type": "same_side",
                    "direction": "buy_kalshi_sell_poly",
                    "poly_id": poly_id,
                    "kalshi_ticker": kalshi_ticker,
                    "buy_price": kalshi_ask,
                    "sell_price": poly_bid,
                    "edge": poly_bid - kalshi_ask - fees,
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
                    response = self.kalshi_gateway.create_order(order_a)
                    if response and getattr(response, "status_code", None) == 201:
                        self.kalshi_balance -= Decimal(kalshi_ask) * Decimal(size)  # Update balance tracking
                except Exception as e:
                    self.logger.error(f"Failed to place order A: {e}")
                # Polymarket - Need BUY_SHORT at 1 - bid price to sell at bid price
                try:
                    if poly_id.endswith("-inverse"):
                        side = "BUY_SHORT"
                    else:
                        side = "BUY_LONG"
                    response = self.polymarket_gateway.create_order(
                        market_slug=poly_id,
                        price=float(Decimal(1.0) - poly_bid),
                        quantity=int(size),
                        side=side,
                        tif="FILL_OR_KILL",
                        order_type="LIMIT",
                    )
                    if response and getattr(response, "status_code", None) == 201:
                        self.polymarket_us_balance -= Decimal(Decimal(1.0) - poly_bid) * Decimal(size)  # Update balance tracking
                except Exception as e:
                    self.logger.error(f"Failed to place order B: {e}")

        # Ask on Polymarket < Bid on Kalshi
        # Buy Polymarket, Sell Kalshi
        if kalshi_bid and poly_ask:
            # Add maker/taker fee adjustments to edge calculation
            kalshi_fee = get_taker_fees_kalshi(kalshi_bid, Decimal(1))
            polymarket_us_fee = get_taker_fees_polymarket_us(poly_ask, Decimal(1))
            fees = kalshi_fee + polymarket_us_fee
            if (kalshi_bid - poly_ask - fees) > self.min_edge:
                size = min(kalshi_bid_size, poly_ask_size, self._get_max_size(self.kalshi_balance, kalshi_bid), self._get_max_size(self.polymarket_us_balance, poly_ask))
                self.logger.info({
                    "type": "same_side",
                    "direction": "buy_poly_sell_kalshi",
                    "poly_id": poly_id,
                    "kalshi_ticker": kalshi_ticker,
                    "buy_price": poly_ask,
                    "sell_price": kalshi_bid,
                    "edge": kalshi_bid - poly_ask - fees,
                    "size": int(size)
                })
                # Send orders to gateway for execution
                # Polymarket - Need BUY_LONG at ask price to buy at ask price
                try:
                    side = "BUY_SHORT" if poly_id.endswith("-inverse") else "BUY_LONG"
                    response = self.polymarket_gateway.create_order(
                        market_slug=poly_id,
                        price=float(poly_ask),
                        quantity=int(size),
                        side=side,
                        tif="FILL_OR_KILL",
                        order_type="LIMIT",
                    )
                    if response and getattr(response, "status_code", None) == 201:
                        self.polymarket_us_balance -= Decimal(poly_ask) * Decimal(size)  # Update balance tracking  
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
                    response = self.kalshi_gateway.create_order(order_b)
                    if response and getattr(response, "status_code", None) == 201:
                        self.kalshi_balance -= Decimal(Decimal(1.0) - kalshi_bid) * Decimal(size)  # Update balance tracking
                except Exception as e:
                    self.logger.error(f"Failed to place order B: {e}")

    def _double_buy_arb(self, order_A: dict, order_B: dict):
        # Synthetic arbitrage
        # If asks for Team 1 + Team 2 < $1
        # Stategies 5, 6, 9, 10
        if order_A["ask_price"] and order_B["ask_price"]:
            # Calculate fees:
            for order in [order_A, order_B]:
                if "Polymarket" in order["ask_market"]:
                    fee = get_taker_fees_polymarket_us(order["ask_price"], Decimal(1))
                    size = self._get_max_size(self.polymarket_us_balance, order["ask_price"])
                elif "Kalshi" in order["ask_market"]:
                    fee = get_taker_fees_kalshi(order["ask_price"], Decimal(1))
                    size = self._get_max_size(self.kalshi_balance, order["ask_price"])
                else:
                    print(f"Unknown market in order: {order['ask_market']}. Cannot calculate fees.")
                    return
                order["fee"] = fee
                order["max_size"] = size
            total_cost = Decimal(order_A["ask_price"]) + Decimal(order_B["ask_price"]) + Decimal(order_A["fee"]) + Decimal(order_B["fee"])
            profit = Decimal(Decimal(1) - total_cost)
            if profit > self.min_edge:
                size = min(order_A["ask_size"], order_B["ask_size"], order_A["max_size"], order_B["max_size"])
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
                            response =self.polymarket_gateway.create_order(
                                market_slug=order["ask_market"].split(": ")[1],
                                price=float(order["ask_price"]),
                                quantity=int(order["max_size"]),
                                side=side,
                                tif="FILL_OR_KILL",
                                order_type="LIMIT",
                            )
                            if response and getattr(response, "status_code", None) == 201:
                                self.polymarket_us_balance -= Decimal(order["ask_price"]) * Decimal(order["max_size"])  # Update balance tracking
                        elif "Kalshi" in order["ask_market"]:
                            response = self.kalshi_gateway.create_order({
                                "ticker": order["ask_market"].split(": ")[1],
                                "action": "buy",
                                "side": "yes",
                                "count": int(order["max_size"]),
                                "client_order_id": str(uuid.uuid4()),
                                "yes_price": int(float(order["ask_price"]) * 100),
                                "type": "limit",
                                "time_in_force": "fill_or_kill"
                            })
                            if response and getattr(response, "status_code", None) == 201:
                                self.kalshi_balance -= Decimal(Decimal(1.0) - Decimal(order["ask_price"])) * Decimal(order["max_size"])  # Update balance tracking
                    except Exception as e:
                        self.logger.error(f"Failed to place order: {e}")


    def _double_sell_arb(self, order_A: dict, order_B: dict):
        # Short sell
        # If we have positions, we can use arbritage to sell out of the position
        # Strategies 7, 8

        if order_A["bid_price"] and order_B["bid_price"]:
            # Calculate fees:
            for order in [order_A, order_B]:
                if "Polymarket" in order["ask_market"]:
                    fee = get_taker_fees_polymarket_us(order["ask_price"], Decimal(1))
                elif "Kalshi" in order["ask_market"]:
                    fee = get_taker_fees_kalshi(order["ask_price"], Decimal(1))
                else:
                    print(f"Unknown market in order: {order['ask_market']}. Cannot calculate fees.")
                    return
                order["fee"] = fee
            total_sale = Decimal(order_A["bid_price"]) + Decimal(order_B["bid_price"]) - (order_A["fee"] + order_B["fee"])
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
                
    def _sell_out_of_position_arb(self):
        pass

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
