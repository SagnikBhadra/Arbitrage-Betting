📈 Prediction Market Data Engine

A real-time market data ingestion framework for Kalshi and Polymarket, with order book tracking and strategy execution.

This project provides a unified, extensible system for streaming real-time market data from prediction markets (Kalshi & Polymarket), maintaining live order books, and persisting historical data for research and automated trading strategies.

🚀 Features

Live WebSocket Streams

- Kalshi.py — Streams order book and trade events from Kalshi.

- polymarket_feed.py — Streams market data from Polymarket.

Order Book Tracking

- orderbook.py — Maintains bid/ask levels, timestamps, and sequencing for each instrument.

Historical Data Recording

- market_data.py — Normalizes and stores events in a CSV per instrument (database support planned).

Strategy-Ready Architecture

- Clean separation between data ingestion, state tracking, storage, and strategy logic.
