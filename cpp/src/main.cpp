// Kalshi ↔ Kalshi arbitrage — C++ port of main.py's intra-Kalshi pipeline
// (kalshi_feed.py + orderbook.py + intra_kalshi_arbitrage.py + kalshi_http_gateway.py).
//
// Usage:  intra_kalshi_arbitrage [repo_root]
//   repo_root defaults to the KALSHI_REPO_ROOT env var, or ".." (i.e. run from cpp/build).
//   It must contain kalshi_secrets.json, Kalshi.key and statics/statics.json.

#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdlib>
#include <exception>
#include <iostream>
#include <thread>

#include "config.hpp"
#include "crypto.hpp"
#include "intra_kalshi_arbitrage.hpp"
#include "kalshi_feed.hpp"
#include "kalshi_http_gateway.hpp"
#include "logging.hpp"
#include "position_manager.hpp"
#include "util.hpp"

namespace {
std::atomic<bool> g_running{true};
void on_signal(int) { g_running = false; }
}  // namespace

int main(int argc, char** argv) {
    std::signal(SIGINT, on_signal);
    std::signal(SIGTERM, on_signal);

    std::string repo_root;
    if (argc > 1) {
        repo_root = argv[1];
    } else if (const char* env = std::getenv("KALSHI_REPO_ROOT")) {
        repo_root = env;
    } else {
        repo_root = "..";
    }

    try {
        const kalshi::Config cfg = kalshi::load_config(repo_root);
        kalshi::PKeyPtr private_key = kalshi::load_private_key_pem(cfg.private_key_pem);

        kalshi::KalshiHTTPGateway gateway(cfg.key_id, private_key.get(), cfg.http_base_url,
                                          /*dry_run=*/true);
        kalshi::KalshiFeed feed(cfg.key_id, private_key.get(), cfg.kalshi_tickers,
                                cfg.ws_host, cfg.ws_port, cfg.ws_path);

        std::thread feed_thread([&feed] { feed.run(); });

        // Wait until the feed reports it has subscribed (main.py: `while not kalshi_client.subscribed`).
        while (g_running && !feed.subscribed()) {
            std::this_thread::sleep_for(std::chrono::seconds(2));
        }

        // Load current positions (best-effort — keep running with an empty book if the API call fails).
        std::unordered_map<std::string, long long> positions;
        try {
            positions = gateway.get_positions();
        } catch (const std::exception& e) {
            std::cerr << "Failed to load positions: " << e.what() << " — starting with none.\n";
        }
        kalshi::PositionManager position_manager(std::move(positions));

        kalshi::IntraKalshiArbitrage strategy(feed, gateway, position_manager,
                                              cfg.correlated_market_mapping, cfg.profit_threshold);

        // scan_inefficiencies(): every second, snapshot all books and run the strategy.
        while (g_running) {
            const auto snapshots = feed.snapshot_all_books();
            try {
                strategy.find_opportunities(snapshots);
            } catch (const std::exception& e) {
                std::cerr << "strategy error: " << e.what() << "\n";
            }
            std::this_thread::sleep_for(std::chrono::seconds(1));
        }

        feed.stop();
        feed_thread.detach();  // a blocked ws.read() won't unwind cleanly; just leave on exit
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "fatal: " << e.what() << "\n";
        return 1;
    }
}
