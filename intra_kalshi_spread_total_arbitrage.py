import logging
import math
import re
import time
import uuid
from collections import defaultdict
from decimal import Decimal
from itertools import combinations

from position_manager import PositionManager
from kalshi_feed import KalshiWebSocket
from kalshi_http_gateway import KalshiHTTPGateway
from utils import get_taker_fees_kalshi

# Matches suffixes like 'WHU2', 'CLB14', 'RR191', '3' (optional letters + required digits)
_SUFFIX_RE = re.compile(r'^([A-Za-z]*)(\d+)$')


def _parse_suffix(ticker: str):
    """
    Return (team_prefix, trailing_num) from the last '-' segment of a ticker.

    Examples:
        'KXEPLSPREAD-26MAY24WHULEE-WHU2'       -> ('WHU', 2)
        'KXEPLTOTAL-26MAY24WHULEE-3'           -> ('', 3)
        'KXIPLTEAMTOTAL-26MAY17RRDC-RR191'     -> ('RR', 191)
        'KXUFLSPREAD-26MAY17CLBBHM-CLB21'      -> ('CLB', 21)

    Returns None if the suffix doesn't match the expected pattern.
    """
    suffix = ticker.rsplit('-', 1)[-1]
    m = _SUFFIX_RE.match(suffix)
    return (m.group(1), int(m.group(2))) if m else None


class IntraKalshiSpreadTotalArbitrage:
    """
    Detects and executes arbitrage opportunities in Kalshi spread and total
    markets by checking for violations of the monotonic price ordering across
    ALL pairs of markets within each nested event group.

    --- Monotonic ordering invariant ---
    Within a group of markets for the same team/direction, a higher trailing
    number represents a harder-to-achieve condition:
        'wins by 2.5+' is harder than 'wins by 1.5+'
        'over 3.5 goals' is harder than 'over 2.5 goals'
    In an efficient market, YES ask prices must be monotonically decreasing
    as the trailing number increases (harder events are cheaper to bet YES on).

    --- Arbitrage structure ---
    For any (easier, harder) pair, the two-legged trade is:
        Leg 1: Buy easier YES at ask(easier)
        Leg 2: Buy harder NO  at 1 - bid(harder)

    This combination guarantees at least $1 payout per share in every scenario,
    because 'harder resolves YES' implies 'easier resolves YES', and
    'easier resolves NO' implies 'harder resolves NO':
        harder YES   → easier YES $1 + harder NO $0 = $1 payout
        only easier  → easier YES $1 + harder NO $1 = $2 payout  (bonus)
        both NO      → easier YES $0 + harder NO $1 = $1 payout

    Entry condition: ask(easier) + (1 - bid(harder)) + fees_per_share < $1

    --- All-pairs scanning ---
    All combinations of (easier, harder) within each event group are checked,
    not just adjacent ones. This catches cross-gap arbitrage (e.g. market 1
    vs market 3) even when intermediate pairs are not individually crossed.

    --- Execution priority ---
    Each scan cycle collects ALL valid opportunities, sorts them by total
    expected profit descending, then executes in that order until the
    available balance is exhausted, ensuring the highest-value trades are
    captured first.
    """

    def __init__(
        self,
        kalshi_client: KalshiWebSocket,
        kalshi_gateway: KalshiHTTPGateway,
        position_manager: PositionManager,
        spread_correlated_mapping: dict,
        total_correlated_mapping: dict,
        profit_threshold: float = 0.01,
    ):
        """
        Initialize the strategy with market mappings and execution parameters.

        Args:
            kalshi_client: WebSocket client providing real-time orderbook data.
            kalshi_gateway: HTTP gateway for order placement and account queries.
            position_manager: Tracks open positions to prevent over-exposure.
            spread_correlated_mapping: Maps each spread ticker to the other
                tickers in the same event group.
            total_correlated_mapping: Maps each total ticker to the other
                tickers in the same event group.
            profit_threshold: Minimum required profit in dollars to execute a
                trade. Filters out marginal or fee-negative opportunities.
        """
        self.kalshi_client = kalshi_client
        self.kalshi_gateway = kalshi_gateway
        self.position_manager = position_manager
        self.profit_threshold = Decimal(str(profit_threshold))
        self.logger = logging.getLogger("intra_kalshi_spread_total_strategy")

        self.cached_balance = Decimal(kalshi_gateway.get_balance()) / Decimal(100)
        self.cached_balance = Decimal(5000)

        # Pre-build all (easier_ticker, harder_ticker) pairs once at init.
        # These are static for the lifetime of the strategy object.
        self._spread_pairs = self._build_nested_pairs(spread_correlated_mapping, "spread")
        self._total_pairs = self._build_nested_pairs(total_correlated_mapping, "total")
        
        """
        for easier, harder in self._spread_pairs:
            self.logger.info(f"Spread pair: easier={easier}, harder={harder}")
        for easier, harder in self._total_pairs:
            self.logger.info(f"Total pair: easier={easier}, harder={harder}")
        """

    # ------------------------------------------------------------------ #
    # Initialization helpers                                               #
    # ------------------------------------------------------------------ #

    def _build_nested_pairs(self, correlated_mapping: dict, label: str) -> list:
        """
        Build all (easier, harder) ticker pairs across every event group.

        For each event, tickers are grouped by their team prefix (the letters
        before the trailing number). Within each group, tickers are sorted
        ascending by trailing number, and ALL combinations of (lower_N,
        higher_N) pairs are generated — not just adjacent neighbors.

        Checking all combinations (rather than only adjacent pairs) is
        important because a cross-gap opportunity such as market 1 vs market 3
        can exist even when neither the (1,2) nor the (2,3) pair is crossed,
        for example when individual market quotes are stale or temporarily
        dislocated.

        Game-total tickers (pure integer suffix, e.g. '-3') have an empty
        team prefix and are grouped as a single sequence per event.

        Team-total tickers (e.g. 'RR191', 'SF4') are grouped by their letter
        prefix, identical to spread market handling.

        Args:
            correlated_mapping: Maps each ticker to the list of correlated
                tickers that belong to the same event.
            label: Human-readable label ('spread' or 'total') for log messages.

        Returns:
            List of (easier_ticker, harder_ticker) tuples covering all valid
            combinations within each event group.
        """
        seen: set = set()
        pairs: list = []
        unparseable_events: list = []
        single_market_skips: int = 0

        for ticker, correlated in correlated_mapping.items():
            event_key = frozenset([ticker] + correlated)
            if event_key in seen:
                continue
            seen.add(event_key)

            event_tickers = list(event_key)
            by_team: dict = defaultdict(list) # team_prefix -> list of (trailing_num, ticker)
            bad: list = []

            for t in event_tickers:
                parsed = _parse_suffix(t)
                if parsed is None:
                    bad.append(t)
                else:
                    team_prefix, num = parsed
                    by_team[team_prefix].append((num, t))

            if bad:
                unparseable_events.append(event_tickers[0])
                continue

            for team, markets in by_team.items():
                if len(markets) < 2:
                    single_market_skips += 1
                    self.logger.debug(
                        f"[{label}] Single-market team '{team or '(game)'}' "
                        f"in event containing {markets[0][1]} — skipping"
                    )
                    continue
                sorted_mkts = sorted(markets, key=lambda x: x[0])
                # All combinations, not just adjacent, to catch cross-gap arbitrage.
                # Since sorted_mkts is ascending by trailing number, the first
                # element of each pair is always the easier (lower threshold) market.
                for (_, easier), (_, harder) in combinations(sorted_mkts, 2):
                    pairs.append((easier, harder))

        if unparseable_events:
            self.logger.warning(
                f"[{label}] {len(unparseable_events)} events skipped "
                f"(non-standard suffix): {unparseable_events[:5]}"
            )
        if single_market_skips:
            self.logger.info(
                f"[{label}] {single_market_skips} single-market team groups "
                f"skipped (partner filtered out by time window)"
            )

        self.logger.info(f"[{label}] Built {len(pairs)} nested pairs from {len(seen)} events")
        return pairs

    # ------------------------------------------------------------------ #
    # Shared helpers                                                       #
    # ------------------------------------------------------------------ #

    def _adjusted_size(self, cost_per_share: Decimal, requested: int) -> int:
        """
        Cap order size to what the current cached balance can fund.

        Called at execution time (after sorting) so that earlier, higher-profit
        trades have first claim on available capital.

        Args:
            cost_per_share: Total cost in dollars to execute one share of the
                two-legged trade: ask(easier) + (1 - bid(harder)).
            requested: Desired order size based on available market liquidity.

        Returns:
            Largest integer size fundable within cached_balance, or 0 if the
            balance cannot cover even a single share.
        """
        if self.cached_balance <= 0:
            self.logger.warning(f"Non-positive balance: ${self.cached_balance:.2f}")
            return 0
        if self.cached_balance >= cost_per_share * requested:
            return requested
        return math.floor(self.cached_balance / cost_per_share)

    def _place_order(self, ticker: str, action: str, side: str, price: Decimal, size: int) -> bool:
        """
        Submit a limit fill-or-kill order to Kalshi and record the position.

        Uses FOK so that partial fills do not leave unhedged exposure: either
        the full size executes or the order is cancelled.

        Args:
            ticker: Kalshi market ticker to trade.
            action: 'buy' or 'sell'.
            side: 'yes' or 'no'.
            price: Limit price in dollars (e.g. Decimal('0.67')).
            size: Number of contracts.

        Returns:
            True if the order was submitted without error, False otherwise.
            Note: True does not guarantee a fill; FOK orders may go unfilled
            if the market has moved since the opportunity was detected.
        """
        order = {
            "ticker": ticker,
            "action": action,
            "side": side,
            "count": size,
            "client_order_id": str(uuid.uuid4()),
            f"{side}_price": int(float(price) * 100),
            "type": "limit",
            "time_in_force": "fill_or_kill",
        }
        try:
            self.kalshi_gateway.create_order(order)
            fill_type = f"{side.upper()}_{'BUY' if action == 'buy' else 'SELL'}"
            self.position_manager.update_from_fill(ticker, fill_type, size)
            return True
        except Exception as e:
            self.logger.error(f"Order failed {ticker} {action} {side}@{price}: {e}")
            return False

    # ------------------------------------------------------------------ #
    # Opportunity collection and scoring                                   #
    # ------------------------------------------------------------------ #

    def _collect_opportunities(self, pairs: list, snapshots: dict) -> list:
        """
        Scan all (easier, harder) pairs and return a list of profitable
        arbitrage opportunities, scored at unconstrained market liquidity.

        For each pair, checks whether the book is crossed:
            bid(harder) > ask(easier)

        If crossed, the two-legged position pays at least $1 per share in all
        resolution scenarios (see class docstring for payout table). Expected
        profit is computed at the full available market size (min of ask_size_e
        and bid_size_h) without any balance constraint — this allows downstream
        sorting to reflect true market priority before capital is allocated.

        Also logs ordering violations where bid(easier) < ask(harder), which
        indicate stale or anomalous quotes but do not support a risk-free trade
        (buying harder YES + easier NO would expose the position to the
        intermediate scenario where easier resolves YES but harder resolves NO,
        receiving only $1 on a combined cost > $1).

        Args:
            pairs: List of (easier_ticker, harder_ticker) tuples to evaluate.
            snapshots: Dict mapping ticker -> (bid, bid_size, ask, ask_size).

        Returns:
            List of opportunity dicts. Each dict contains:
                easier_ticker  (str)      - the lower-threshold market
                harder_ticker  (str)      - the higher-threshold market
                ask_e          (Decimal)  - ask price on the easier market
                no_ask_h       (Decimal)  - cost to buy harder NO (1 - bid_h)
                cost_per_share (Decimal)  - ask_e + no_ask_h
                raw_size       (int)      - max executable size before balance cap
                expected_profit (Decimal) - raw_size - total_cost (unconstrained)
        """
        opportunities = []

        for easier_ticker, harder_ticker in pairs:
            snap_e = snapshots.get(easier_ticker)
            snap_h = snapshots.get(harder_ticker)
            if not snap_e or not snap_h:
                continue

            bid_e, bid_size_e, ask_e, ask_size_e = snap_e
            bid_h, bid_size_h, ask_h, ask_size_h = snap_h

            # Log ordering violations: harder ask priced above easier bid.
            # This is non-tradeable but may indicate a stale or erroneous quote.
            if bid_e and ask_h and bid_size_e and ask_size_h:
                bid_e_d = Decimal(str(bid_e))
                ask_h_d = Decimal(str(ask_h))
                if bid_e_d < ask_h_d:
                    pass
                    """
                    print(
                        f"Ordering violation (non-tradeable): "
                        f"bid({easier_ticker})={bid_e_d} < ask({harder_ticker})={ask_h_d} — "
                        f"harder market ask is priced ABOVE easier market bid"
                    )
                    """
                    

            if not (ask_e and bid_h and ask_size_e and bid_size_h):
                continue

            ask_e_d = Decimal(str(ask_e))
            bid_h_d = Decimal(str(bid_h))
            no_ask_h = Decimal("1") - bid_h_d
            cost_per_share = ask_e_d + no_ask_h

            if cost_per_share <= 0:
                continue

            raw_size = int(min(float(ask_size_e), float(bid_size_h)))
            if raw_size <= 0:
                continue

            # Compute fees and expected profit at the full unconstrained size.
            # Balance constraints are applied later at execution time so that
            # sorting reflects true market priority.
            fees = (get_taker_fees_kalshi(ask_e_d, raw_size)
                    + get_taker_fees_kalshi(no_ask_h, raw_size))
            total_cost = cost_per_share * raw_size + fees
            """
            self.logger.info(
                f"Evaluated pair {easier_ticker} (ask {ask_e_d}, size {ask_size_e}) + "
                f"{harder_ticker} (bid {bid_h_d}, size {bid_size_h}): "
                f"cost/share={cost_per_share:.4f} total_cost={total_cost:.4f} "
                f"fees={fees:.4f} raw_size={raw_size}"
            )
            """
            expected_profit = Decimal(raw_size) - total_cost

            if expected_profit >= self.profit_threshold:
                opportunities.append({
                    "easier_ticker": easier_ticker,
                    "harder_ticker": harder_ticker,
                    "ask_e": ask_e_d,
                    "no_ask_h": no_ask_h,
                    "cost_per_share": cost_per_share,
                    "raw_size": raw_size,
                    "expected_profit": expected_profit,
                })

        return opportunities

    def _execute_opportunity(self, opp: dict) -> None:
        """
        Execute a single arbitrage opportunity after applying balance constraints.

        Re-computes the order size against the current cached_balance (which
        may have been reduced by earlier executions this cycle), rechecks that
        the profit threshold is still met at the adjusted size, then submits
        both legs as fill-or-kill limit orders.

        The balance is decremented optimistically before order submission. If
        either leg fails (e.g. market moved), the position manager will reflect
        the discrepancy on the next position refresh cycle.

        Args:
            opp: Opportunity dict as returned by _collect_opportunities.
        """
        easier_ticker = opp["easier_ticker"]
        harder_ticker = opp["harder_ticker"]
        ask_e_d = opp["ask_e"]
        no_ask_h = opp["no_ask_h"]
        cost_per_share = opp["cost_per_share"]
        raw_size = opp["raw_size"]

        # Apply current balance constraint — earlier trades this cycle may have
        # reduced cached_balance below what raw_size requires.
        order_size = self._adjusted_size(cost_per_share, raw_size)
        if order_size <= 0:
            return

        # Recompute fees at the balance-adjusted size and recheck profitability.
        # Fees are convex in size, so a smaller size improves the fee-per-share
        # ratio; this check is therefore conservative and may still pass.
        fees = (get_taker_fees_kalshi(ask_e_d, order_size)
                + get_taker_fees_kalshi(no_ask_h, order_size))
        total_cost = cost_per_share * order_size + fees

        if total_cost > order_size - self.profit_threshold:
            return

        self.logger.info(
            f"Nested Arb: buy YES {easier_ticker}@{ask_e_d} + "
            f"buy NO {harder_ticker}@{no_ask_h} "
            f"size={order_size} cost={total_cost:.4f} "
            f"profit≥{(order_size - total_cost):.4f}"
        )
        self.cached_balance -= total_cost
        #self._place_order(easier_ticker, "buy", "yes", ask_e_d, order_size)
        #self._place_order(harder_ticker, "buy", "no", no_ask_h, order_size)

    # ------------------------------------------------------------------ #
    # Public entry point                                                   #
    # ------------------------------------------------------------------ #

    def find_opportunities(self, kalshi_book_snapshots=None, polymarket_us_book_snapshots=None):
        """
        Run a full scan across all spread and total market pairs, then execute
        the most profitable arbitrage opportunities first.

        Execution steps:
            1. Snapshot all Kalshi orderbooks (or use the provided dict).
            2. Collect all valid opportunities from spread pairs and total pairs.
               Each opportunity is scored at full unconstrained market liquidity
               so that sorting reflects true market priority.
            3. Sort all opportunities by expected_profit descending (primary)
               and raw_size descending (tiebreaker) to ensure the highest total
               dollar profit is captured when capital is limited.
            4. Execute in priority order. Balance constraints are applied at
               each execution step so that higher-value trades are funded first
               and any remaining balance funds smaller opportunities.

        Args:
            kalshi_book_snapshots: Optional pre-built snapshot dict mapping
                ticker -> (bid, bid_size, ask, ask_size). If None, snapshots
                are taken from kalshi_client.orderbooks at call time.
            polymarket_us_book_snapshots: Unused; present to match the shared
                strategy interface used by other strategy classes.
        """
        start = time.time()
        if kalshi_book_snapshots is None:
            kalshi_book_snapshots = {
                t: ob.snapshot_top()
                for t, ob in self.kalshi_client.orderbooks.items()
            }
        
        # Collect all valid opportunities across both spread and total markets.
        all_opps = self._collect_opportunities(self._spread_pairs, kalshi_book_snapshots)
        all_opps += self._collect_opportunities(self._total_pairs, kalshi_book_snapshots)
        end = time.time()
        print(f"Found {len(all_opps)} total opportunities across spread and total markets")
        print(f"Time taken to find opportunities: {end - start:.2f} seconds")

        if not all_opps:
            return

        # Sort by total expected profit descending so the most valuable trade
        # is executed first. Use raw_size as a tiebreaker to prefer more liquid
        # opportunities when profits are equal.
        all_opps.sort(key=lambda o: (o["expected_profit"], o["raw_size"]), reverse=True)

        self.logger.info(f"Found {len(all_opps)} opportunity(ies) this cycle; executing in profit order.")

        for opp in all_opps:
            if self.cached_balance <= 0:
                self.logger.warning("Balance exhausted; skipping remaining opportunities this cycle.")
                break
            self._execute_opportunity(opp)
