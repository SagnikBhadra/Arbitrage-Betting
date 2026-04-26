from datetime import datetime
import logging
import logging.handlers
import queue
from pathlib import Path

# Track listeners so we can drain & stop them on shutdown
_listeners: list[logging.handlers.QueueListener] = []


def setup_logger(filename_prefix: str, logger_name: str):
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    log_dir = Path("logging")
    log_dir.mkdir(exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s"
    )
    
    # File handler — runs only on the QueueListener's background thread
    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / f"{filename_prefix}_{today_str}.log",
        maxBytes=5_000_000,
        backupCount=5,
        encoding="utf-8",
        delay=True
    )
    file_handler.setFormatter(formatter)

    # Non-blocking queue: callers just enqueue and return immediately
    log_queue: queue.Queue = queue.Queue(-1)          # unbounded
    queue_handler = logging.handlers.QueueHandler(log_queue)

    listener = logging.handlers.QueueListener(
        log_queue, file_handler, respect_handler_level=True
    )
    listener.start()
    _listeners.append(listener)

    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    logger.addHandler(queue_handler)
    logger.propagate = False  # Prevent duplicate logging


def stop_logging():
    """Drain every queue and stop background listener threads.

    Call once at process shutdown (e.g. in a finally block).
    """
    for listener in _listeners:
        listener.stop()
    _listeners.clear()


def setup_logging():
    # === 1️⃣ Strategy log files ===
    # Cross-exchange strategy log
    setup_logger("cross_exchange_strategy", "cross_exchange_strategy")

    # Intra Kalshi strategy log
    setup_logger("intra_kalshi_strategy", "intra_kalshi_strategy")

    # Wide Spread strategy log
    setup_logger("wide_spread_strategy", "wide_spread_strategy")

    # === 2️⃣ Feed log files ===
    # Kalshi feed log
    setup_logger("kalshi_feed", "kalshi_feed")

    # Polymarket US feed log
    setup_logger("polymarket_us_feed", "polymarket_us_feed")
    
    # === 3️⃣ Gateway log files ===
    setup_logger("kalshi_http_gateway", "kalshi_http_gateway")
    setup_logger("polymarket_us_http_gateway", "polymarket_us_http_gateway")
    
    # === 4️⃣ orderbook log file ===
    setup_logger("orderbook", "orderbook")
