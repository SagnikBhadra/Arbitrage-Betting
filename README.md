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


**Development Setup (WSL + Python + QuickFIX)**

This project requires Linux due to native dependencies (e.g. QuickFIX).
On Windows, we use WSL (Windows Subsystem for Linux) to provide a production-like environment.

1. Why WSL Is Required

QuickFIX is a C++ FIX engine with Python bindings that:

Do not build reliably on native Windows (MSVC)

Expect a Linux / GCC toolchain

Are commonly deployed on Linux in production trading systems

WSL allows us to:

Run a real Linux environment on Windows

Use Linux Python, GCC, and networking

Match real trading infrastructure behavior

⚠️ Do not run this project using Windows Python. It will not work.

2. Set Up WSL (Ubuntu)
Install WSL

From PowerShell (Admin):
```
wsl --install
```

Reboot if prompted.

Open Ubuntu
```
wsl
```

You should now be in a Linux shell:
```
user@HOSTNAME:~$
```
3. Clone / Move the Repository into WSL

The project must live inside the Linux filesystem, not /mnt/c.

Option A: Clone directly in WSL (recommended)
```
cd ~
git clone git@github.com:<your-org>/Arbitrage-Betting.git
cd Arbitrage-Betting
```
Option B: Move an existing repo from Windows
```
cp -r /mnt/c/Users/<you>/Documents/GitHub/Arbitrage-Betting ~/
cd ~/Arbitrage-Betting
```

Verify Git is intact:
```
git status
git remote -v
```
4. Install Python Dependencies (System)

Install required system packages once:
```
sudo apt update
sudo apt install -y \
  python3-full \
  python3-venv \
  python3-dev \
  build-essential \
  libssl-dev
```

These are required for:

Python virtual environments

Compiling native extensions (QuickFIX)

5. Create and Activate a Python Virtual Environment

From the project root:
```
python3 -m venv .venv
source .venv/bin/activate
```

You should now see:
```
(.venv) user@HOSTNAME:~/Arbitrage-Betting$
```

Verify Python is correct:
```
which python
```

Expected:
```
/home/<user>/Arbitrage-Betting/.venv/bin/python
```

Upgrade tooling:
```
pip install --upgrade pip setuptools wheel
```

6. Install QuickFIX and Run the Project
Install QuickFIX
```
pip install quickfix
```

Verify:
```
python
import quickfix
print("QuickFIX installed successfully")
```
Run the project
```
python main.py
```

VS Code (Recommended)

Always launch VS Code from inside WSL:
```
cd ~/Arbitrage-Betting
code .
```

Confirm bottom-left status bar shows:

WSL: Ubuntu


Select the interpreter:
```
.python/defaultInterpreterPath = .venv/bin/python
```
