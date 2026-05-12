# Kalshi ↔ Kalshi arbitrage (C++ port)

C++17 port of the intra-Kalshi arbitrage pipeline from the Python project. It mirrors:

| Python                       | C++                                                   |
|------------------------------|-------------------------------------------------------|
| `orderbook.py`               | `src/order_book.{hpp,cpp}`                             |
| `kalshi_feed.py`             | `src/kalshi_feed.{hpp,cpp}` (WS feed + book state)    |
| `kalshi_http_gateway.py`     | `src/kalshi_http_gateway.{hpp,cpp}` (REST execution)  |
| `intra_kalshi_arbitrage.py`  | `src/intra_kalshi_arbitrage.{hpp,cpp}`                |
| `position_manager.py`        | `src/position_manager.{hpp,cpp}`                      |
| `utils.py` (fees, ids)       | `src/util.{hpp,cpp}`, `src/config.{hpp,cpp}`          |
| `setup_loggers.py`           | `src/logging.{hpp,cpp}`                               |
| `main.py` (`scan_inefficiencies`, intra-Kalshi only) | `src/main.cpp`                |

## Dependencies

- A C++17 compiler
- CMake ≥ 3.16
- Boost ≥ 1.74 (header-only Beast/Asio — no compiled Boost libs needed)
- OpenSSL 3.x (RSA-PSS signing, TLS)
- nlohmann/json ≥ 3.2 (fetched automatically if not installed)

macOS:
```sh
brew install cmake boost openssl@3 nlohmann-json
```
Debian/Ubuntu:
```sh
sudo apt install -y cmake g++ libboost-dev libssl-dev nlohmann-json3-dev
```

## Build

```sh
cd cpp
cmake -S . -B build
cmake --build build -j
```

## Run

The binary reads the same data files the Python uses — `kalshi_secrets.json`, `Kalshi.key`
and `statics/statics.json` — relative to a "repo root":

```sh
# from cpp/build, repo root defaults to ".."
./build/intra_kalshi_arbitrage

# or pass it explicitly / via env
./build/intra_kalshi_arbitrage /path/to/Arbitrage-Betting
KALSHI_REPO_ROOT=/path/to/Arbitrage-Betting ./build/intra_kalshi_arbitrage
```

Logs are written to `logging/<name>_<date>.log` (relative to the working directory) and echoed
to stderr, matching the Python module names (`kalshi_feed`, `kalshi_http_gateway`,
`intra_kalshi_strategy`).

## Notes / intentional deviations from the Python

- **Order book keys are integer cents** instead of Python's mixed `float`/`Decimal` keys. Kalshi
  prices are whole cents, so this is economically identical but exact, and avoids float-as-dict-key
  hazards. The strategy still does its arithmetic in `double` dollars like the Python.
- **`create_order` is dry-run by default** (`dry_run=true` in `KalshiHTTPGateway`), exactly like the
  Python where the actual `POST /portfolio/orders` is commented out. `get_balance` / `get_positions` /
  `cancel_order` *do* hit the network. Flip the constructor flag in `main.cpp` to actually trade.
- **Single-threaded message processing**: the Python fans WS message parsing out to a 16-worker
  thread pool (to dodge the GIL on JSON parsing). One C++ thread handles it comfortably; a separate
  thread runs the once-a-second scan loop, and each `OrderBook` keeps its mutex for cross-thread reads.
- **TLS certificate verification is disabled** (`ssl::verify_none`) for portability across platforms
  where the default trust store isn't wired up. The Python `requests`/`websockets` libraries verify;
  enable `verify_peer` + a CA bundle if you want the same behavior.
- **Omitted** (not part of the Kalshi↔Kalshi path): the `OrderbookDeltaLogger`, the `fill` queue /
  wide-spread "WBRSSS" handling, `market_data.py` CSV persistence (already a no-op in Python), and
  Polymarket feeds/gateways. `sell_out_of_position_arb` is ported for parity but, as in the Python,
  not invoked. Periodic client-side WS pings are replaced by Beast's built-in keep-alive timeouts.
- The Kalshi message field names (`price_dollars`, `delta_fp`, `yes_dollars_fp`, `no_dollars_fp`,
  `position_fp`, …) are taken verbatim from the Python; if the live API uses different names, update
  them in both code bases.
