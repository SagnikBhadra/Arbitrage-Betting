import json
import logging
from decimal import Decimal
import uuid


from kalshi_feed import KalshiWebSocket
from kalshi_http_gateway import KalshiHTTPGateway, load_private_key

from utils import get_asset_ids, get_maker_fees_kalshi, get_taker_fees_kalshi
from collections import defaultdict

class IntraKalshiArbitrage:
    def __init__(self, kalshi_client: KalshiWebSocket, kalshi_gateway: KalshiHTTPGateway, correlated_market_mapping: dict, logger=logging.getLogger(__name__)):
        """
        Detects arbitrage opportunities within Kalshi for 2-outcome moneyline markets.
        """
        self.kalshi_client = kalshi_client
        self.kalshi_gateway = kalshi_gateway
        self.correlated_market_mapping = correlated_market_mapping
        self.logger = logger

        self.overall_order_count = 0
        self.overall_profit = 0.0

        self.last_best_ask_price_by_ticker = defaultdict()
        self.last_best_bid_price_by_ticker = defaultdict()

        # Cached balance to avoid API calls on every order
        self.cached_balance = 0.0

    def check_and_update_balance(self, required_amount):
        """Check if we have sufficient balance for the trade.

        Args:
            required_amount: Amount needed in dollars

        Returns:
            bool: True if sufficient balance, False otherwise
        """
        try:
            balance_response = self.kalshi_gateway.get_balance()
            self.cached_balance = balance_response.get("balance", 0) / 100.0  # Convert cents to dollars
            return self.cached_balance >= required_amount
        except Exception as e:
            self.logger.error(f"Error fetching balance: {e}")
            return False

    def find_opportunities(self, profit_threshold=0.02):
        """Identify intra-market arbitrage opportunities within Kalshi markets.

        Args:
            profit_threshold (float): The minimum profit threshold for considering an arbitrage opportunity.
        """
        global overall_order_count, overall_profit, cached_balance

        for ticker, orderbook in self.kalshi_client.orderbooks.items():
            # Get correlated markets
            correlated_tickers = self.correlated_market_mapping.get(ticker, [])
            best_bid, best_bid_size = orderbook.get_best_bid()
            best_ask, best_ask_size = orderbook.get_best_ask()
            last_best_bid = -1
            last_correlated_best_bid = -1
            last_best_ask = -1
            last_correlated_best_ask = -1

            # Does not work for more than 2 correlated markets yet
            if correlated_tickers:
                for correlated_ticker in correlated_tickers:
                    correlated_orderbook = self.kalshi_client.orderbooks.get(correlated_ticker)
                    if correlated_orderbook:
                        correlated_best_bid, correlated_best_bid_size = correlated_orderbook.get_best_bid()
                        correlated_best_ask, correlated_best_ask_size = correlated_orderbook.get_best_ask()
                        
                        # Buy Team A yes & Buy Team B yes
                        if best_ask and correlated_best_ask:
                            if ticker in self.last_best_ask_price_by_ticker:
                                last_best_ask = self.last_best_ask_price_by_ticker[ticker]
                            self.last_best_ask_price_by_ticker[ticker] = best_ask
                            if correlated_ticker in self.last_best_ask_price_by_ticker:
                                last_correlated_best_ask = self.last_best_ask_price_by_ticker[correlated_ticker]
                            self.last_best_ask_price_by_ticker[correlated_ticker] = correlated_best_ask
                            if (last_best_ask != -1 and best_ask != last_best_ask) or (last_correlated_best_ask != -1 and correlated_best_ask != last_correlated_best_ask):
                                pass
                            else:
                                continue
                            
                            # Calculate cost of trade (including fees) and potential profit
                            fees = get_taker_fees_kalshi(float(best_ask), float(best_ask_size)) + get_taker_fees_kalshi(float(correlated_best_ask), float(correlated_best_ask_size))
                            combined_price = float(best_ask) + float(correlated_best_ask) + float(fees)

                            if combined_price <= 1.0 - profit_threshold:
                                order_size = int(min(float(best_ask_size), float(correlated_best_ask_size)))
                                
                                # Calculate required balance (cost of both orders)
                                required_balance = (float(best_ask) + float(correlated_best_ask)) * order_size
                                overall_order_count += order_size
                                overall_profit += max((1.0 - combined_price) * order_size / 100.0 , 0)
                                
                                # Check balance before placing orders
                                if not self.check_and_update_balance(required_balance):
                                    self.logger.warning(f"Insufficient balance. Required: ${required_balance:.2f}, Available: ${self.cached_balance:.2f}")
                                    continue

                                self.logger.info(f"Intra-Kalshi Arbitrage Opportunity: Buy YES on {ticker} at {best_ask} and Buy YES on {correlated_ticker} at {correlated_best_ask} of size {order_size} | Combined Price: {combined_price}")

                                # Buy YES on ticker
                                order_a = {
                                    "ticker": ticker,
                                    "action": "buy",
                                    "side": "yes",
                                    "count": order_size,
                                    "client_order_id": str(uuid.uuid4()),
                                    "yes_price": int(float(best_ask) * 100),
                                    "type": "limit",
                                }
                                try:
                                    self.kalshi_gateway.create_order(order_a)
                                except Exception as e:
                                    self.logger.error(f"Failed to place order A: {e}")
                                    continue
                                
                                # Buy YES on correlated ticker
                                order_b = {
                                    "ticker": correlated_ticker,
                                    "action": "buy",
                                    "side": "yes",
                                    "count": order_size,
                                    "client_order_id": str(uuid.uuid4()),
                                    "yes_price": int(float(correlated_best_ask) * 100),
                                    "type": "limit",
                                }
                                try:
                                    self.kalshi_gateway.create_order(order_b)
                                except Exception as e:
                                    self.logger.error(f"Failed to place order B: {e}")
                                    continue

                        # Buy Team A no & Buy Team B no
                        if best_bid and correlated_best_bid:
                            if ticker in self.last_best_bid_price_by_ticker:
                                last_best_bid = self.last_best_bid_price_by_ticker[ticker]
                            self.last_best_bid_price_by_ticker[ticker] = best_bid
                            if correlated_ticker in self.last_best_bid_price_by_ticker:
                                last_correlated_best_bid = self.last_best_bid_price_by_ticker[correlated_ticker]
                            self.last_best_bid_price_by_ticker[correlated_ticker] = correlated_best_bid
                            if (last_best_bid != -1 and best_bid != last_best_bid) or (last_correlated_best_bid != -1 and correlated_best_bid != last_correlated_best_bid):
                                pass
                            else:
                                continue
                            
                            best_no_ask = 1.0 - float(best_bid)
                            best_correlated_no_ask = 1.0 - float(correlated_best_bid)
                            fees = get_taker_fees_kalshi(float(best_bid), float(best_bid_size)) + get_taker_fees_kalshi(float(correlated_best_bid), float(correlated_best_bid_size))
                            combined_price = best_no_ask + best_correlated_no_ask + float(fees)
                            if combined_price <= 1.0 - profit_threshold:
                                order_size = int(min(float(best_bid_size), float(correlated_best_bid_size)))
                                
                                # Calculate required balance (cost of both orders)
                                required_balance = (best_no_ask + best_correlated_no_ask) * order_size
                                self.overall_order_count += order_size
                                self.overall_profit += max((1.0 - combined_price) * order_size / 100.0, 0)
                                # Check balance before placing orders
                                if not self.check_and_update_balance(required_balance):
                                    self.logger.warning(f"Insufficient balance. Required: ${required_balance:.2f}, Available: ${self.cached_balance:.2f}")
                                    continue

                                self.logger.info(f"Intra-Kalshi Arbitrage Opportunity: Buy NO on {ticker} at {best_no_ask} and Buy NO on {correlated_ticker} at {best_correlated_no_ask} of size {order_size} | Combined Price: {combined_price}")

                                # Buy NO on ticker
                                order_a = {
                                    "ticker": ticker,
                                    "action": "buy",
                                    "side": "no",
                                    "count": order_size,
                                    "client_order_id": str(uuid.uuid4()),
                                    "no_price": int(best_no_ask * 100),
                                    "type": "limit",
                                }
                                try:
                                    self.kalshi_gateway.create_order(order_a)
                                except Exception as e:
                                    self.logger.error(f"Failed to place order A: {e}")
                                    continue
                                
                                # Buy NO on correlated ticker
                                order_b = {
                                    "ticker": correlated_ticker,
                                    "action": "buy",
                                    "side": "no",
                                    "count": order_size,
                                    "client_order_id": str(uuid.uuid4()),
                                    "no_price": int(best_correlated_no_ask * 100),
                                    "type": "limit",
                                }
                                try:
                                    self.kalshi_gateway.create_order(order_b)
                                except Exception as e:
                                    self.logger.error(f"Failed to place order B: {e}")
                                    continue

                    self.logger.info(f"Overall Orders Placed: {self.overall_order_count}, Overall Potential Profit: ${self.overall_profit:.2f}, Balance: ${self.cached_balance:.2f}")
