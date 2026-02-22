from datetime import datetime
import logging
import logging.handlers
from pathlib import Path

def setup_logger(filename_prefix: str, logger_name: str):
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    log_dir = Path("logging")
    log_dir.mkdir(exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s"
    )
    
    handler = logging.handlers.RotatingFileHandler(
        log_dir / f"{filename_prefix}_{today_str}.log",
        maxBytes=5_000_000,
        backupCount=5,
        encoding="utf-8",
        delay=True
    )
    handler.setFormatter(formatter)

    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False  # Prevent duplicate logging

def setup_logging():
    # === 1️⃣ Strategy log files ===
    # Cross-exchange strategy log
    setup_logger("cross_exchange_strategy", "cross_exchange_strategy")

    # Intra Kalshi strategy log
    setup_logger("intra_kalshi_strategy", "intra_kalshi_strategy")

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
