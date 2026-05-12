#pragma once

#include <nlohmann/json.hpp>
#include <openssl/evp.h>

#include <atomic>
#include <memory>
#include <set>
#include <string>
#include <unordered_map>
#include <vector>

#include "logging.hpp"
#include "order_book.hpp"

namespace kalshi {

// Port of kalshi_feed.py (KalshiWebSocket): connects to the Kalshi trade-api websocket,
// subscribes to orderbook_delta + fill for a fixed set of market tickers, and maintains an
// OrderBook per ticker.  Runs single-threaded on its own connection (the python version fans
// JSON parsing out to a thread pool; one thread is plenty in C++).
class KalshiFeed {
public:
    // `private_key` is borrowed, not owned (must outlive this object).
    KalshiFeed(std::string key_id, EVP_PKEY* private_key, std::vector<std::string> tickers,
               std::string host = "api.elections.kalshi.com", std::string port = "443",
               std::string path = "/trade-api/ws/v2");

    void run();                       // blocking: connect / read loop with reconnection
    void stop() { running_ = false; } // best-effort; a blocked read won't return until the next msg

    bool subscribed() const { return subscribed_.load(); }

    // top-of-book snapshot for every subscribed ticker (taken under each book's lock)
    std::unordered_map<std::string, TopOfBook> snapshot_all_books() const;
    bool best_bid(const std::string& ticker, int& price_cents, double& size) const;
    bool best_ask(const std::string& ticker, int& price_cents, double& size) const;
    OrderBook* book(const std::string& ticker);  // nullptr if unknown

private:
    void process_message(const std::string& message);
    void handle_snapshot(const nlohmann::json& msg);
    void handle_price_change(const nlohmann::json& msg);  // == python handle_price_change / _apply_delta
    void handle_trade(const nlohmann::json& msg);
    void handle_user_fill(const nlohmann::json& msg);

    std::string key_id_;
    EVP_PKEY*   key_;  // borrowed
    std::vector<std::string> tickers_;
    std::string host_, port_, path_;

    // populated once in the constructor (one book per ticker), then read concurrently
    std::unordered_map<std::string, std::unique_ptr<OrderBook>> books_;

    // touched only by the feed thread
    std::set<std::string> snapshot_loaded_;
    std::unordered_map<std::string, std::vector<nlohmann::json>> delta_buffer_;

    std::atomic<bool> subscribed_{false};
    std::atomic<bool> running_{true};
    Logger& log_;
};

}  // namespace kalshi
