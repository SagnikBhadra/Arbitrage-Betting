import json
import logging
from decimal import Decimal
import math
import time
import uuid

# Position Manager
from position_manager import PositionManager

from kalshi_feed import KalshiWebSocket
from kalshi_http_gateway import KalshiHTTPGateway, load_private_key

from utils import get_asset_ids, get_maker_fees_kalshi, get_taker_fees_kalshi
from collections import defaultdict

class IntraKalshiArbitrage:
    def __init__(self, kalshi_client: KalshiWebSocket, kalshi_gateway: KalshiHTTPGateway, position_manager: PositionManager, correlated_market_mapping: dict, profit_threshold=0.01):
        """
        Detects arbitrage opportunities within Kalshi for 2-outcome moneyline markets.
        """
        self.kalshi_client = kalshi_client
        self.kalshi_gateway = kalshi_gateway
        self.position_manager = position_manager
        self.correlated_market_mapping = correlated_market_mapping
        self.profit_threshold = profit_threshold
        self.logger = logging.getLogger("intra_kalshi_strategy")

        self.overall_order_count = Decimal(0)
        self.overall_profit = Decimal(0.0)

        self.last_best_ask_price_by_ticker = defaultdict()
        self.last_best_bid_price_by_ticker = defaultdict()

        # Cached balance to avoid API calls on every order (in dollars)
        self.cached_balance = Decimal(Decimal(kalshi_gateway.get_balance()) / Decimal(100.0))
        self.cached_balance = 5000

    def check_and_update_balance(self, required_amount: Decimal):
        """Check if we have sufficient balance for the trade.

        Args:
            required_amount: Amount needed in dollars

        Returns:
            bool: True if sufficient balance, False otherwise
        """
        try:
            #balance_response = self.kalshi_gateway.get_balance()
            #self.cached_balance = balance_response / 100.0 if balance_response != 0 else 0  # Convert dollars to cents
            return self.cached_balance >= required_amount
        except Exception as e:
            self.logger.error(f"Error fetching balance: {e}")
            return False
        
    def sell_out_of_position_arb(self, ticker, best_bid: Decimal, best_bid_size: Decimal, best_ask: Decimal, best_ask_size: Decimal,
                                 correlated_ticker, correlated_best_bid: Decimal, correlated_best_bid_size: Decimal, correlated_best_ask: Decimal, correlated_best_ask_size: Decimal):
        ticker_position = int(float(self.position_manager.get_position(ticker)))
        correlated_ticker_position = int(float(self.position_manager.get_position(correlated_ticker)))
        
        if ticker_position > 0 and correlated_ticker_position > 0:
            position_size = int(min(ticker_position, correlated_ticker_position))
        elif ticker_position < 0 and correlated_ticker_position < 0:
            position_size = int(abs(max(ticker_position, correlated_ticker_position)))
        else:
            return
        
        if position_size > 0 and best_ask_size and correlated_best_ask_size:
            # Sell Team A YES and Sell Team B YES
            # If Team A bid + Team B bid - fees > $1 + profit_threshold ==>
            # If (Team A bid + Team B bid) - (order_size + fees) > profit_threshold
            
            # Calculate order size
            order_size = int(min(position_size, best_bid_size, correlated_best_bid_size))
            
            fees = Decimal(get_taker_fees_kalshi(best_bid, order_size) + get_taker_fees_kalshi(correlated_best_bid, order_size))
            combined_price = Decimal(best_bid * order_size) + Decimal(correlated_best_bid * order_size)
            if combined_price - (order_size + fees) > self.profit_threshold:
                # Send order
                self.logger.info(f"Intra-Kalshi Arbitrage Opportunity: Sell YES on {ticker} at {best_ask} and Sell YES on {correlated_ticker} at {correlated_best_ask} of size {order_size} | Combined Price: {combined_price} | Fees: {fees}")
                self.cached_balance += combined_price
                self.cached_balance -= fees

                # Sell YES on ticker
                order_a = {
                    "ticker": ticker,
                    "action": "sell",
                    "side": "yes",
                    "count": int(order_size),
                    "client_order_id": str(uuid.uuid4()),
                    "yes_price": int(float(best_bid) * 100),
                    "type": "limit",
                    "time_in_force": "fill_or_kill"
                }
                try:
                    self.kalshi_gateway.create_order(order_a)
                    self.position_manager.update_from_fill(ticker, "YES_SELL", order_size)
                except Exception as e:
                    self.logger.error(f"Failed to place order A: {e}")
                    
                # Sell YES on correlated ticker
                order_b = {
                    "ticker": correlated_ticker,
                    "action": "sell",
                    "side": "yes",
                    "count": int(order_size),
                    "client_order_id": str(uuid.uuid4()),
                    "yes_price": int(float(correlated_best_bid) * 100),
                    "type": "limit",
                    "time_in_force": "fill_or_kill"
                }
                try:
                    self.kalshi_gateway.create_order(order_b)
                    self.position_manager.update_from_fill(correlated_ticker, "YES_SELL", order_size)
                except Exception as e:
                    self.logger.error(f"Failed to place order B: {e}")
        
        
        # Sell Team A NO and Sell Team B NO
        
        

    def find_opportunities(self, book_snapshots: dict | None = None):
        """Identify intra-market arbitrage opportunities within Kalshi markets.

        Args:
            book_snapshots: {ticker: (best_bid_price, best_bid_size, best_ask_price, best_ask_size)}
                            Immutable snapshot taken on the event loop.  When *None*
                            the method falls back to reading live orderbooks (legacy path).
        """

        if book_snapshots is None:
            # Legacy / fallback: read live (only safe when called on the event loop)
            book_snapshots = {
                t: ob.snapshot_top()
                for t, ob in self.kalshi_client.orderbooks.items()
            }

        for ticker, (best_bid, best_bid_size, best_ask, best_ask_size) in book_snapshots.items():
            
            # Get correlated markets
            correlated_tickers = self.correlated_market_mapping.get(ticker, [])
            last_best_bid = -1
            last_correlated_best_bid = -1
            last_best_ask = -1
            last_correlated_best_ask = -1

            # Does not work for more than 2 correlated markets yet
            if correlated_tickers:
                for correlated_ticker in correlated_tickers:
                    correlated_snap = book_snapshots.get(correlated_ticker)
                    if correlated_snap:
                        correlated_best_bid, correlated_best_bid_size, correlated_best_ask, correlated_best_ask_size = correlated_snap
                        
                        # Buy Team A yes & Buy Team B yes
                        if best_ask and correlated_best_ask:
                            """
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
                            """
                            # Calculate order size
                            #print(f"Best Ask: {best_ask_size}, Correlated Best Ask: {correlated_best_ask_size}")
                            order_size = int(min(float(best_ask_size), float(correlated_best_ask_size)))
                            
                            # Calculate required balance (cost of both orders)
                            cost_of_single_share = Decimal(best_ask + correlated_best_ask)
                            required_balance = Decimal(cost_of_single_share * order_size)
                            
                            # Check balance before placing orders
                            if self.cached_balance < 0:
                                self.logger.warning(f"Negative balance detected: ${self.cached_balance:.2f}. Skipping trade.")
                                continue
                            if not self.cached_balance > required_balance:
                                #self.logger.warning(f"Insufficient balance. Required: ${required_balance:.2f}, Available: ${self.cached_balance:.2f}")
                                order_size = math.floor(Decimal(str(self.cached_balance)) / cost_of_single_share)
                                
                            # TODO: Skip if order size is 0 after balance check
                                
                                
                            # Track profit
                            self.overall_order_count += order_size
                            self.overall_profit += max((Decimal("1.0") - cost_of_single_share) * order_size , 0)

                            # Calculate cost of trade (including fees) and potential profit
                            fees = Decimal(get_taker_fees_kalshi(Decimal(best_ask), order_size) + get_taker_fees_kalshi(Decimal(correlated_best_ask), order_size))
                            combined_price = Decimal(best_ask * order_size) + Decimal(correlated_best_ask * order_size) + fees

                            if combined_price <= (order_size - self.profit_threshold):
                                self.logger.info(f"Intra-Kalshi Arbitrage Opportunity: Buy YES on {ticker} at {best_ask} and Buy YES on {correlated_ticker} at {correlated_best_ask} of size {order_size} | Combined Price: {combined_price}")
                                self.cached_balance -= combined_price

                                # Buy YES on ticker
                                order_a = {
                                    "ticker": ticker,
                                    "action": "buy",
                                    "side": "yes",
                                    "count": int(order_size),
                                    "client_order_id": str(uuid.uuid4()),
                                    "yes_price": int(float(best_ask) * 100),
                                    "type": "limit",
                                    "time_in_force": "fill_or_kill"
                                }
                                try:
                                    self.kalshi_gateway.create_order(order_a)
                                    self.position_manager.update_from_fill(ticker, "YES_BUY", order_size)
                                except Exception as e:
                                    self.logger.error(f"Failed to place order A: {e}")
                                    continue
                                
                                # Buy YES on correlated ticker
                                order_b = {
                                    "ticker": correlated_ticker,
                                    "action": "buy",
                                    "side": "yes",
                                    "count": int(order_size),
                                    "client_order_id": str(uuid.uuid4()),
                                    "yes_price": int(float(correlated_best_ask) * 100),
                                    "type": "limit",
                                    "time_in_force": "fill_or_kill"
                                }
                                try:
                                    self.kalshi_gateway.create_order(order_b)
                                    self.position_manager.update_from_fill(correlated_ticker, "YES_BUY", order_size)
                                except Exception as e:
                                    self.logger.error(f"Failed to place order B: {e}")
                                    continue

                        # Buy Team A no & Buy Team B no
                        if best_bid and correlated_best_bid:
                            """
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
                            """
                            # Get NO Asks
                            best_no_ask = Decimal("1.0") - Decimal(str(best_bid))
                            best_correlated_no_ask = Decimal("1.0") - Decimal(str(correlated_best_bid))
                            
                            # Calculate order size
                            #print(f"Best NO Ask: {best_bid_size}, Correlated Best NO Ask: {correlated_best_bid_size}")
                            order_size = int(min(float(best_bid_size), float(correlated_best_bid_size)))
                            
                            # Calculate required balance (cost of both orders)
                            cost_of_single_share = Decimal(best_no_ask + best_correlated_no_ask)
                            required_balance = Decimal(cost_of_single_share * order_size)
                            
                            # Check balance before placing orders
                            if self.cached_balance < 0:
                                self.logger.warning(f"Negative balance detected: ${self.cached_balance:.2f}. Skipping trade.")
                                continue
                            if not self.cached_balance > required_balance:
                                #self.logger.warning(f"Insufficient balance. Required: ${required_balance:.2f}, Available: ${self.cached_balance:.2f}")
                                order_size = math.floor(Decimal(str(self.cached_balance)) / cost_of_single_share)
                            
                            # Track profit
                            self.overall_order_count += order_size
                            self.overall_profit += max((Decimal("1.0") - cost_of_single_share) * order_size , 0)

                            # Calculate cost of trade (including fees) and potential profit
                            fees = Decimal(get_taker_fees_kalshi(Decimal(best_no_ask), order_size) + get_taker_fees_kalshi(Decimal(best_correlated_no_ask), order_size))
                            combined_price = Decimal(best_no_ask * order_size) + Decimal(best_correlated_no_ask * order_size) + fees
                            
                            if combined_price <= order_size - self.profit_threshold:
                                self.logger.info(f"Intra-Kalshi Arbitrage Opportunity: Buy NO on {ticker} at {best_no_ask} and Buy NO on {correlated_ticker} at {best_correlated_no_ask} of size {order_size} | Combined Price: {combined_price}")
                                self.cached_balance -= combined_price

                                # Buy NO on ticker
                                order_a = {
                                    "ticker": ticker,
                                    "action": "buy",
                                    "side": "no",
                                    "count": int(order_size),
                                    "client_order_id": str(uuid.uuid4()),
                                    "no_price": int(best_no_ask * 100),
                                    "type": "limit",
                                    "time_in_force": "fill_or_kill"
                                }
                                try:
                                    self.kalshi_gateway.create_order(order_a)
                                    self.position_manager.update_from_fill(ticker, "NO_BUY", order_size)
                                except Exception as e:
                                    self.logger.error(f"Failed to place order A: {e}")
                                    continue
                                
                                # Buy NO on correlated ticker
                                order_b = {
                                    "ticker": correlated_ticker,
                                    "action": "buy",
                                    "side": "no",
                                    "count": int(order_size),
                                    "client_order_id": str(uuid.uuid4()),
                                    "no_price": int(best_correlated_no_ask * 100),
                                    "type": "limit",
                                    "time_in_force": "fill_or_kill"
                                }
                                try:
                                    self.kalshi_gateway.create_order(order_b)
                                    self.position_manager.update_from_fill(correlated_ticker, "NO_BUY", order_size)
                                except Exception as e:
                                    self.logger.error(f"Failed to place order B: {e}")
                                    continue
                                
                        #self.sell_out_of_position_arb(ticker, best_bid, best_bid_size, best_ask, best_ask_size,
                        #                                correlated_ticker, correlated_best_bid, correlated_best_bid_size, correlated_best_ask, correlated_best_ask_size)

                    #self.logger.info(f"Overall Orders Placed: {self.overall_order_count}, Overall Potential Profit: ${self.overall_profit:.2f}, Balance: ${self.cached_balance:.2f}")
                        
                    
