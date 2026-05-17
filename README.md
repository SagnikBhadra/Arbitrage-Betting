# Prediction Market Arbitrage Engine

A real-time algorithmic trading system for prediction markets. Connects to **Kalshi** and **Polymarket US**, streams live order book data via WebSocket, and runs multiple arbitrage strategies simultaneously.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Directory Structure](#directory-structure)
- [Module Reference](#module-reference)
  - [Entry Point](#entry-point)
  - [Market Data Feeds](#market-data-feeds)
  - [Order Book](#order-book)
  - [HTTP Gateways](#http-gateways)
  - [Arbitrage Strategies](#arbitrage-strategies)
  - [Static Data Builders](#static-data-builders)
  - [Supporting Modules](#supporting-modules)
- [Strategies In Depth](#strategies-in-depth)
- [Fee Model](#fee-model)
- [Logging](#logging)
- [Static Data](#static-data)
- [Development Setup](#development-setup)

---

## Overview

The engine operates in a continuous loop:

1. **Connect** to Kalshi and Polymarket US WebSocket feeds simultaneously.
2. **Maintain** a live, thread-safe order book for every subscribed market.
3. **Snapshot** all order books every second and pass them to each strategy.
4. **Execute** profitable trades via REST HTTP gateways using fill-or-kill limit orders.

Markets are priced as probabilities between $0.00 and $1.00. Contracts pay $1.00 if the event resolves YES and $0.00 if NO. This binary structure creates well-defined arbitrage conditions when prices across related markets are internally inconsistent.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                            main.py                                  │
│                                                                     │
│  asyncio.gather(                                                    │
│    polymarket_us_client.run(),       ← Polymarket WS feed          │
│    kalshi_client.orderbook_websocket(),  ← Kalshi WS feed          │
│    scan_inefficiencies(...)          ← Strategy loop                │
│  )                                                                  │
└───────────────┬─────────────────────────────┬───────────────────────┘
                │                             │
   ┌────────────▼────────────┐   ┌────────────▼────────────┐
   │  PolymarketUSWebSocket  │   │    KalshiWebSocket      │
   │  (polymarket_us_feed.py)│   │    (kalshi_feed.py)     │
   │                         │   │                         │
   │  Ed25519 Auth           │   │  RSA-PSS Auth           │
   │  recv_loop + ping_loop  │   │  16-worker thread pool  │
   │  handle_snapshot()      │   │  handle_snapshot()      │
   │                         │   │  handle_price_change()  │
   └────────────┬────────────┘   └────────────┬────────────┘
                │                             │
        ┌───────▼─────────────────────────────▼───────┐
        │              OrderBook (orderbook.py)        │
        │                                              │
        │   SortedDict bids / SortedDict asks          │
        │   apply_delta()   snapshot_top()             │
        │   get_best_bid()  get_best_ask()             │
        └───────────────────┬──────────────────────────┘
                            │  snapshot_all_books() called each second
                            │
        ┌───────────────────▼──────────────────────────┐
        │           scan_inefficiencies()               │
        │                                              │
        │  strategy.find_opportunities(                │
        │    kalshi_snapshots,                         │
        │    polymarket_snapshots                      │
        │  )                                           │
        └──┬───────────────┬───────────────┬───────────┘
           │               │               │
  ┌────────▼──────┐ ┌──────▼──────┐ ┌─────▼───────────────────────┐
  │ IntraKalshi   │ │ CrossExch-  │ │ IntraKalshiSpreadTotal       │
  │ Arbitrage     │ │ ange Arb    │ │ Arbitrage                    │
  └────────┬──────┘ └──────┬──────┘ └─────┬───────────────────────┘
           │               │               │
        ┌──▼───────────────▼───────────────▼──┐
        │         HTTP Gateways               │
        │                                     │
        │  KalshiHTTPGateway   (RSA-PSS)      │
        │  PolymarketUSHTTPGateway (Ed25519)  │
        └─────────────────────────────────────┘
```

---

## Directory Structure

```
Arbitrage-Betting/
│
├── main.py                                  # Application entry point
│
├── # ── Strategies ──────────────────────────────────────────────────
├── intra_kalshi_arbitrage.py               # Intra-Kalshi moneyline arb
├── intra_kalshi_spread_total_arbitrage.py  # Intra-Kalshi spread/total arb
├── cross_exchange_arbitrage.py             # Kalshi ↔ Polymarket US arb
├── wide_spread_arbitrage.py               # Wide-spread market-making on Kalshi
│
├── # ── Feeds (WebSocket clients) ────────────────────────────────────
├── kalshi_feed.py                          # Kalshi real-time order book stream
├── polymarket_us_feed.py                   # Polymarket US real-time order book stream
├── polymarket_feed.py                      # Legacy Polymarket CLOB feed (unused)
│
├── # ── HTTP Gateways (order execution) ─────────────────────────────
├── kalshi_http_gateway.py                  # Kalshi REST API client
├── polymarket_us_http_gateway.py           # Polymarket US REST API client
├── kalshi_fix_gateway.py                   # Kalshi FIX gateway (stub)
├── polymarket_fix_gateway.py               # Polymarket FIX gateway (stub)
│
├── # ── Core Data Structures ─────────────────────────────────────────
├── orderbook.py                            # Thread-safe order book
├── position_manager.py                     # Position and open-order tracker
│
├── # ── Static Data Builders (run offline) ──────────────────────────
├── get_all_events.py                       # Fetches and categorises Kalshi events
├── get_all_markets.py                      # Fetches Kalshi market tickers
├── get_slugs_polymarket_us.py              # Fetches Polymarket US event/market slugs
├── update_kalshi_tickers_with_moneyline_events.py  # Builds Kalshi statics.json entries
├── cross_exchange_mapping_nlp.py           # LLM-based cross-exchange market correlation
├── polymarket_kalshi_mapping.py            # Rule-based cross-exchange market pairing
├── market_correlation.py                  # Legacy OpenAI-based market correlator
│
├── # ── Utilities ────────────────────────────────────────────────────
├── utils.py                               # Fee calculators and asset ID loader
├── setup_loggers.py                       # Non-blocking async rotating file loggers
├── market_data.py                         # CSV persistence layer (currently disabled)
├── orderbook_snapshot.py                  # Standalone orderbook snapshot collector
├── read_events.py                         # Debug utility: prints Kalshi event tickers
│
├── # ── Static Data ──────────────────────────────────────────────────
├── statics/
│   ├── statics.json                       # Master ticker mapping (loaded at runtime)
│   ├── cross_exchange_statics.json        # Polymarket ↔ Kalshi market pairs
│   ├── kalshi_event_to_market_mapping.json
│   ├── kalshi_spread_event_to_market_mapping.json
│   ├── kalshi_total_event_to_market_mapping.json
│   ├── kalshi_spread_events.json
│   ├── kalshi_total_events.json
│   ├── kalshi_volume_per_market.json      # Volume used by wide-spread filter
│   ├── mutually_exclusive_events.json
│   ├── non_mutually_exclusive_events.json
│   ├── two_market_events.json
│   ├── polymarket_us_event_to_market_mapping.json
│   ├── polymarket_us_spread_event_to_market_mapping.json
│   └── polymarket_us_total_event_to_market_mapping.json
│
├── logging/                               # Rotating daily log files (auto-created)
│
└── cpp/                                   # C++ rewrite of hot paths (in progress)
```

---

## Module Reference

### Entry Point

#### `main.py`

Bootstraps and runs the entire system via `asyncio.gather`. Three coroutines run concurrently:

| Coroutine | Role |
|---|---|
| `polymarket_us_client.run()` | Polymarket WS feed + ping loop |
| `kalshi_client.orderbook_websocket()` | Kalshi WS feed + message consumer pool |
| `scan_inefficiencies(...)` | Waits for feeds to subscribe, then runs strategy loop every second |

**Strategy loop (`scan_inefficiencies`):**
1. Waits until Kalshi confirms subscription.
2. Fetches current positions from Kalshi HTTP gateway → initialises `PositionManager`.
3. Constructs strategy objects from `statics/statics.json`.
4. Each second: calls `snapshot_all_books()` on both feeds, then dispatches each snapshot to every active strategy via `asyncio.to_thread` (keeps the event loop free for incoming WS messages).

Currently active strategy: `IntraKalshiSpreadTotalArbitrage`. Others (`IntraKalshiArbitrage`, `CrossExchangeArbitrage`, `WideSpreadArbitrage`) are instantiated but commented out.

---

### Market Data Feeds

#### `kalshi_feed.py` — `KalshiWebSocket`

Streams real-time order book data from Kalshi via WebSocket.

**Authentication:** RSA-PSS signature over `timestamp + "GET" + path`, sent as HTTP headers on the WebSocket upgrade request.

**Message processing pipeline:**

```
WebSocket recv() ──► asyncio.Queue ──► 16 ThreadPoolExecutor workers
                                           │
                                           ▼
                              _process_single_message()
                                           │
                    ┌──────────────────────┼───────────────────────────┐
                    ▼                      ▼                           ▼
           orderbook_snapshot    orderbook_delta              fill / trade
           handle_snapshot()     handle_price_change()     handle_user_fill()
```

- **`orderbook_snapshot`**: Calls `OrderBook.load_kalshi_snapshot()`. Replays any buffered deltas that arrived before the snapshot.
- **`orderbook_delta`**: Calls `OrderBook.apply_delta()`. If a snapshot has not yet arrived for that market, the delta is buffered.
- **`fill`**: Routes fills whose `client_order_id` starts with `WBRSSS` to `fill_queue` for `WideSpreadArbitrage` to process.
- **`OrderbookDeltaLogger`**: Collects deltas into a deduplication buffer and flushes a summary to the log every 30 seconds.

**Key methods:**

| Method | Description |
|---|---|
| `snapshot_all_books()` | Returns `{ticker: (bid, bid_size, ask, ask_size)}` atomically |
| `get_best_bid(ticker)` | Best bid price and size for a single market |
| `get_best_ask(ticker)` | Best ask price and size for a single market |

---

#### `polymarket_us_feed.py` — `PolymarketUSWebSocket`

Streams real-time order book data from Polymarket US via WebSocket.

**Authentication:** Ed25519 signature over `timestamp + "GET" + path`, sent as HTTP headers.

**Inverse market handling:** Polymarket US provides a single order book per event, representing one team as "long". For the opposing team, the feed creates a mirror `-inverse` order book, flipping bids/asks and inverting prices (`1 - price`). This allows strategies to directly look up either side as a normal order book.

```
marketData received
       │
       ├──► load_polymarket_us_snapshot(slug)          ← long side
       └──► load_polymarket_us_snapshot(slug+"-inverse") ← short side (prices flipped)
```

**Loops:**
- `recv_loop`: Receives messages, calls `handle_message()`, auto-reconnects on disconnect.
- `ping_loop`: Sends `PING` every 10 seconds to keep the connection alive.

---

#### `polymarket_feed.py` — `PolymarketWebSocket`

Legacy WebSocket client for the original Polymarket CLOB service. Not used in the main trading loop. Retained for reference.

---

### Order Book

#### `orderbook.py` — `OrderBook`

A thread-safe, price-level order book backed by `SortedDict` from `sortedcontainers`.

```
OrderBook
├── bids: SortedDict  {price → size}  ascending by price
├── asks: SortedDict  {price → size}  ascending by price
└── lock: threading.Lock
```

**Bid/Ask convention:**
- `get_best_bid()` → `bids.peekitem(-1)` (highest price)
- `get_best_ask()` → `asks.peekitem(0)` (lowest price)

**Key methods:**

| Method | Description |
|---|---|
| `apply_delta(side, price, delta)` | Adds `delta` to existing size at `price`; removes level if size ≤ 0 |
| `snapshot_top()` | Returns `(bid_price, bid_size, ask_price, ask_size)` under lock |
| `load_kalshi_snapshot(msg)` | Loads from Kalshi snapshot format (`yes_dollars_fp`, `no_dollars_fp`) |
| `load_polymarket_us_snapshot(slug, msg)` | Loads from Polymarket US format, handles inverse price inversion |
| `load_polymarket_snapshot(msg)` | Loads from legacy Polymarket CLOB format |

**Kalshi price convention:** Kalshi expresses NO prices. The order book stores YES prices as bids and converts NO prices to ask prices via `ask = 1 - no_price`.

---

### HTTP Gateways

#### `kalshi_http_gateway.py` — `KalshiHTTPGateway`

REST client for the Kalshi Trade API. All requests are signed with RSA-PSS.

**Key methods:**

| Method | Description |
|---|---|
| `get_balance()` | Returns account balance in cents |
| `get_positions()` | Returns open positions as `{ticker: net_position}` |
| `create_order(order)` | Places a limit or market order |
| `cancel_order(order_id)` | Cancels an open resting order |
| `get_orders()` | Returns all open orders |

**Order format** (passed to `create_order`):
```python
{
    "ticker": "KXNBAMVP-26-LDON",
    "action": "buy",           # "buy" or "sell"
    "side": "yes",             # "yes" or "no"
    "count": 10,               # number of contracts
    "client_order_id": "...",  # UUID
    "yes_price": 67,           # price in cents (1–99)
    "type": "limit",
    "time_in_force": "fill_or_kill"
}
```

---

#### `polymarket_us_http_gateway.py` — `PolymarketUSHTTPGateway`

REST client for the Polymarket US API. Requests are signed with Ed25519.

**Key methods:**

| Method | Description |
|---|---|
| `get_balance()` | Returns USDC balance |
| `create_order(...)` | Places a limit or market order |
| `cancel_order(order_id)` | Cancels a resting order |
| `get_positions()` | Returns open positions |

**Order sides:** `BUY_LONG` (buy YES equivalent) or `BUY_SHORT` (buy NO / inverse market).

---

#### `kalshi_fix_gateway.py` / `polymarket_fix_gateway.py`

Stub implementations of FIX protocol gateways using `aiopyfix`. Intended as lower-latency replacements for the HTTP gateways. Not yet integrated into the main trading loop.

---

### Arbitrage Strategies

All strategies implement the same interface:

```python
def find_opportunities(
    self,
    kalshi_book_snapshots: dict,       # {ticker: (bid, bid_size, ask, ask_size)}
    polymarket_us_book_snapshots: dict # {ticker: (bid, bid_size, ask, ask_size)}
) -> None
```

Called every second from `scan_inefficiencies` in a thread pool worker.

---

#### `intra_kalshi_arbitrage.py` — `IntraKalshiArbitrage`

Detects mispricings within Kalshi for mutually exclusive 2-outcome moneyline events (e.g. Team A vs Team B).

**Invariant:** In a correctly priced binary market, `P(YES_A) + P(YES_B) = 1`. If the sum of ask prices falls below $1.00 minus fees, a risk-free profit exists.

**Two trade types:**

```
Double YES (buy both YES sides):
  Cost = ask(A_YES) + ask(B_YES) + fees
  Profit if cost < $1.00

Double NO (buy both NO sides):
  Equivalent to selling both YES sides.
  Cost = (1 - bid(A_YES)) + (1 - bid(B_YES)) + fees
  Profit if cost < $1.00
```

Both legs are sent as fill-or-kill limit orders simultaneously. Position manager is updated after each fill.

---

#### `intra_kalshi_spread_total_arbitrage.py` — `IntraKalshiSpreadTotalArbitrage`

Detects pricing violations of the **monotonic ordering invariant** across spread and total markets.

**Invariant:** Within a group of nested markets (e.g. "win by 1.5+", "win by 2.5+", "win by 3.5+"), a higher threshold is harder to achieve, so its YES price must be lower than an easier threshold's YES price. Formally:

```
ask(easier YES) ≥ ask(harder YES)
```

If this is violated, a risk-free two-legged trade exists:

```
Leg 1: Buy easier YES  at ask(easier)
Leg 2: Buy harder NO   at 1 - bid(harder)

Payout table:
  harder resolves YES → easier YES pays $1, harder NO pays $0  → total $1
  only easier YES     → easier YES pays $1, harder NO pays $1  → total $2 (bonus)
  both resolve NO     → easier YES pays $0, harder NO pays $1  → total $1

Entry condition: ask(easier) + (1 - bid(harder)) + fees < $1
```

**Pair construction:** At initialisation, all `(easier, harder)` pairs within each event group are precomputed. Tickers are grouped by team prefix and sorted by trailing number. All combinations are checked (not just adjacent), to catch cross-gap arbitrage.

**Execution priority:** Each scan cycle collects all valid opportunities, scores them by expected profit at unconstrained market liquidity, sorts descending, then executes in order — highest-profit trades get first claim on available balance.

```
Scan cycle:
  _collect_opportunities(spread_pairs, snapshots)  ]
  _collect_opportunities(total_pairs,  snapshots)  ] → sort by profit → execute
```

---

#### `cross_exchange_arbitrage.py` — `CrossExchangeArbitrage`

Detects arbitrage between the same underlying event listed on both Kalshi and Polymarket US.

**Three trade types:**

**1. Same-side arb** — direct price discrepancy on the same outcome:
```
Buy Kalshi ask < Sell Polymarket bid  →  profit = poly_bid - kalshi_ask - fees
Buy Polymarket ask < Sell Kalshi bid  →  profit = kalshi_bid - poly_ask - fees
```

**2. Double-buy** — buy both outcomes across exchanges cheaper than $1:
```
Best ask(Team A, across both exchanges) + Best ask(Team B, across both exchanges) < $1
→ Guaranteed $1 payout regardless of outcome
```

**3. Double-sell** — sell both outcomes across exchanges for more than $1:
```
Best bid(Team A) + Best bid(Team B) > $1
→ Collect more than the maximum payout (currently logging only, orders not sent)
```

The mapping loaded from `statics/cross_exchange_statics.json` links each Polymarket market slug to its corresponding Kalshi ticker and their respective "other side" counterparts.

---

#### `wide_spread_arbitrage.py` — `WideSpreadArbitrage`

A market-making strategy targeting Kalshi markets with unusually wide bid-ask spreads.

**Logic:**
1. Filter to markets with volume between 1,000–10,000 contracts (liquid enough to trade, not so liquid that spreads are tight).
2. If `spread ≥ 5%` and `spread ≤ 15%` and no open orders exist for that ticker:
   - Place a YES bid 1 cent above the current best bid.
   - Place a NO bid 1 cent above the equivalent NO best bid (i.e. 1 cent inside the current ask).
3. When one leg fills (detected via `fill_queue` from `KalshiWebSocket`):
   - Cancel the unfilled resting order.
   - Immediately send a market order on the opposing side to close the position.
4. Cancel resting orders if the spread tightens below threshold.

Orders use client IDs prefixed `WBRSSS` to distinguish them from other strategies' orders.

---

### Static Data Builders

These scripts are run offline (not during live trading) to populate `statics/`.

#### `get_all_events.py`

Fetches all Kalshi events via paginated REST API. Separates events into:
- `mutually_exclusive_events.json` — events where exactly one outcome can win (suitable for intra-Kalshi arb)
- `non_mutually_exclusive_events.json` — all other events
- `kalshi_spread_events.json` / `kalshi_total_events.json` — markets identified as spread or total via `competition_scope` and ticker suffix patterns

#### `get_all_markets.py`

Fetches individual market tickers from Kalshi. Optionally filters by series ticker or time window. Builds correlated market pairs within each event for the intra-Kalshi strategy.

#### `get_slugs_polymarket_us.py`

Fetches all Polymarket US events and constructs `ASSET_ID_MAPPING` entries for moneyline, spread, and total markets. Updates `statics.json` with slug-to-asset-ID mappings.

#### `update_kalshi_tickers_with_moneyline_events.py`

Builds the `ASSET_ID_MAPPING` (Kalshi section) and `CORRELATED_MARKET_MAPPING` in `statics.json`. Groups Kalshi markets by event and market type (moneyline, spread, total). Supports configurable close-time windows to filter out near-expiry markets.

#### `cross_exchange_mapping_nlp.py`

Uses a two-stage pipeline to match Kalshi markets to Polymarket US markets for the same underlying event:
1. **TF-IDF cosine similarity** — fast pre-filter to find candidate pairs.
2. **Groq LLM (Llama-3)** — validates candidate pairs by asking the model if the two markets describe the same event, with configurable confidence threshold.

Output written to `statics/cross_exchange_statics.json`.

#### `polymarket_kalshi_mapping.py`

Rule-based alternative to `cross_exchange_mapping_nlp.py`. Uses date parsing and team-name similarity scoring to pair moneyline markets without an LLM.

#### `market_correlation.py`

Legacy module. Uses OpenAI GPT-4o-mini to correlate Kalshi politics markets with Polymarket markets. Superseded by `cross_exchange_mapping_nlp.py`.

---

### Supporting Modules

#### `utils.py`

Fee calculation functions used by all strategies. All fees use the formula:

```
fee = fee_rate × size × price × (1 - price)
```

| Function | Exchange | Rate | Rounding |
|---|---|---|---|
| `get_taker_fees_kalshi` | Kalshi | 7.00% | ceiling to $0.01 |
| `get_maker_fees_kalshi` | Kalshi | 1.75% | ceiling to $0.01 |
| `get_taker_fees_polymarket_us` | Polymarket US | 5.00% | half-up to $0.01 |
| `get_maker_rebate_polymarket_us` | Polymarket US | 1.25% | half-up to $0.01 |

Also provides `get_asset_ids(market)` which reads the master `statics/statics.json` and returns the list of ticker IDs for a given exchange/market-type key.

---

#### `position_manager.py` — `PositionManager`

Thread-safe tracker for open positions and resting orders.

```
PositionManager
├── positions: {ticker → net_quantity}       # positive = long YES
├── open_orders: {client_order_id → order}
├── open_orders_by_ticker: {ticker → {client_order_ids}}
└── associated_orders: {client_order_id → {associated_ids}}
```

Position convention:
- `YES_BUY` → position increases
- `NO_BUY` → position decreases (equivalent to short YES)
- `YES_SELL` / `NO_SELL` → reverse of above

`associated_orders` links the two legs of a wide-spread pair so that when one leg fills, the other can be immediately cancelled.

---

#### `setup_loggers.py`

Configures non-blocking async logging using Python's `QueueHandler` / `QueueListener` pattern. Callers write to an in-memory queue and return immediately; a background thread writes to rotating daily log files.

Log files created in `logging/`:

| Logger name | File prefix | Content |
|---|---|---|
| `cross_exchange_strategy` | `cross_exchange_strategy_YYYY-MM-DD.log` | Cross-exchange arb opportunities |
| `intra_kalshi_strategy` | `intra_kalshi_strategy_YYYY-MM-DD.log` | Intra-Kalshi moneyline arb |
| `intra_kalshi_spread_total_strategy` | `intra_kalshi_spread_total_strategy_YYYY-MM-DD.log` | Spread/total arb |
| `wide_spread_strategy` | `wide_spread_strategy_YYYY-MM-DD.log` | Wide-spread market-making |
| `kalshi_feed` | `kalshi_feed_YYYY-MM-DD.log` | WS connection events, delta summaries |
| `polymarket_us_feed` | `polymarket_us_feed_YYYY-MM-DD.log` | WS connection events |
| `kalshi_http_gateway` | `kalshi_http_gateway_YYYY-MM-DD.log` | HTTP requests/responses |
| `polymarket_us_http_gateway` | `polymarket_us_http_gateway_YYYY-MM-DD.log` | HTTP requests/responses |
| `orderbook` | `orderbook_YYYY-MM-DD.log` | Order book warnings |

Each file rotates at 5 MB with 5 backups retained.

---

#### `market_data.py`

CSV persistence layer for order book snapshots, price changes, and trades. Currently disabled (calls are commented out in feed files). Intended for backtesting data collection.

#### `orderbook_snapshot.py`

Standalone script that connects to the Kalshi WebSocket, maintains order books, and periodically writes snapshots with spread calculations to CSV files. Used for offline data collection, independent of the main trading loop.

#### `read_events.py`

Debug utility. Reads `statics/two_market_events.json` and prints each event's market tickers with their correlated counterparts.

---

## Strategies In Depth

### Intra-Kalshi Spread/Total — Monotonic Ordering

```
Example: Soccer match "West Ham vs Leeds"

Spread markets for West Ham:
  KXEPLSPREAD-...-WHU1   "West Ham win by 1.5+"   ask = $0.55
  KXEPLSPREAD-...-WHU2   "West Ham win by 2.5+"   ask = $0.35
  KXEPLSPREAD-...-WHU3   "West Ham win by 3.5+"   ask = $0.20

Check pair (WHU1, WHU2):
  Cost = ask(WHU1) + (1 - bid(WHU2))
  If bid(WHU2) = $0.38:
    Cost = $0.55 + (1 - $0.38) = $0.55 + $0.62 = $1.17  ← no arb

  If bid(WHU2) = $0.52 (anomaly):
    Cost = $0.55 + (1 - $0.52) = $0.55 + $0.48 = $1.03  ← still no arb

  If ask(WHU1) falls to $0.30 and bid(WHU2) = $0.80:
    Cost = $0.30 + (1 - $0.80) = $0.30 + $0.20 = $0.50 < $1.00 ← ARB
    Buy WHU1 YES at $0.30 + Buy WHU2 NO at $0.20
    Guaranteed ≥ $1.00 payout per contract
```

### Cross-Exchange — Same-Side Arb

```
Event: "Luka Doncic wins NBA MVP"

Polymarket US:   bid = $0.72,  ask = $0.73
Kalshi:          bid = $0.68,  ask = $0.69

Opportunity: Kalshi ask ($0.69) < Polymarket bid ($0.72)
  Buy YES on Kalshi at $0.69
  Sell YES on Polymarket at $0.72  (via BUY_SHORT on inverse market)
  Gross spread = $0.03
  After fees ≈ $0.015 net profit per contract
```

---

## Fee Model

Both exchanges charge fees as a fraction of the variance of the contract price, not a flat rate:

```
fee = rate × size × price × (1 − price)
```

This means:
- Fees are **highest near $0.50** (maximum variance).
- Fees approach **zero near $0.00 or $1.00** (near certainty).
- A fee-inclusive profit check `combined_cost + fees < payout` is run before every order.

---

## Logging

All logs are written asynchronously. The main thread never blocks on I/O. To tail a live strategy log:

```bash
tail -f logging/intra_kalshi_spread_total_strategy_$(date +%Y-%m-%d).log
```

---

## Static Data

`statics/statics.json` is the master runtime configuration. Its top-level keys:

| Key | Description |
|---|---|
| `ASSET_ID_MAPPING` | Maps exchange+type → `{ticker: asset_id}` for all subscribed markets |
| `CORRELATED_MARKET_MAPPING` | Kalshi moneyline: maps each ticker to its opposing team's ticker |
| `CORRELATED_SPREAD_MARKET_MAPPING` | Kalshi spread: maps each ticker to others in the same event group |
| `CORRELATED_TOTAL_MARKET_MAPPING` | Kalshi total: maps each ticker to others in the same event group |

`statics/cross_exchange_statics.json`:

| Key | Description |
|---|---|
| `POLYMARKET_KALSHI_MAPPING` | Cross-exchange market pairs by category (Moneyline_Events, etc.) |

---

## Development Setup

This project supports native Windows (Python 3.12+) and WSL/Linux.

### Prerequisites

```bash
pip install -r requirements.txt
```

Key dependencies: `websockets`, `cryptography`, `sortedcontainers`, `groq` (for NLP mapping scripts).

### Credentials

Create the following files in the project root:

| File | Content |
|---|---|
| `kalshi_secrets.json` | `{"KEY_ID": "your-kalshi-key-id"}` |
| `Kalshi.key` | RSA private key in PEM format |
| `polymarket.key` | Ed25519 private key, base64-encoded |

### Run

```bash
python main.py
```

### WSL / Linux (required for QuickFIX FIX gateway)

The FIX protocol gateways depend on QuickFIX, which requires a Linux/GCC toolchain. If using the FIX gateways, run under WSL:

```bash
wsl --install          # from PowerShell (Admin)
wsl
cd ~/Arbitrage-Betting
python3 -m venv .venv && source .venv/bin/activate
pip install quickfix
python main.py
```

### Rebuild Static Data

Run these scripts in order when markets change or new events need to be added:

```bash
python get_all_events.py                           # 1. Fetch Kalshi events
python update_kalshi_tickers_with_moneyline_events.py  # 2. Build Kalshi statics
python get_slugs_polymarket_us.py                  # 3. Fetch Polymarket US slugs
python cross_exchange_mapping_nlp.py               # 4. Match markets across exchanges
```
