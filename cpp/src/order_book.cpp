#include "order_book.hpp"

#include "util.hpp"

namespace kalshi {

OrderBook::OrderBook(std::string asset_id) : asset_id_(std::move(asset_id)) {}

void OrderBook::update_level(Side side, int price_cents, double size) {
    std::lock_guard<std::mutex> lock(mu_);
    auto& book = (side == Side::Bid) ? bids_ : asks_;
    if (size <= 0.0) {
        book.erase(price_cents);
    } else {
        book[price_cents] = size;
    }
}

void OrderBook::apply_delta(Side side, int price_cents, double delta) {
    std::lock_guard<std::mutex> lock(mu_);
    auto& book = (side == Side::Bid) ? bids_ : asks_;
    auto it = book.find(price_cents);
    const double new_size = (it == book.end() ? 0.0 : it->second) + delta;
    if (new_size <= 0.0) {
        if (it != book.end()) book.erase(it);
    } else {
        book[price_cents] = new_size;
    }
}

double OrderBook::size_at(Side side, int price_cents) const {
    std::lock_guard<std::mutex> lock(mu_);
    const auto& book = (side == Side::Bid) ? bids_ : asks_;
    auto it = book.find(price_cents);
    return it == book.end() ? 0.0 : it->second;
}

bool OrderBook::best_bid(int& price_cents, double& size) const {
    std::lock_guard<std::mutex> lock(mu_);
    if (bids_.empty()) return false;
    auto it = bids_.rbegin();
    price_cents = it->first;
    size = it->second;
    return true;
}

bool OrderBook::best_ask(int& price_cents, double& size) const {
    std::lock_guard<std::mutex> lock(mu_);
    if (asks_.empty()) return false;
    auto it = asks_.begin();
    price_cents = it->first;
    size = it->second;
    return true;
}

TopOfBook OrderBook::snapshot_top() const {
    std::lock_guard<std::mutex> lock(mu_);
    TopOfBook t;
    if (!bids_.empty()) {
        auto it = bids_.rbegin();
        t.has_bid = true;
        t.bid_px = it->first;
        t.bid_sz = it->second;
    }
    if (!asks_.empty()) {
        auto it = asks_.begin();
        t.has_ask = true;
        t.ask_px = it->first;
        t.ask_sz = it->second;
    }
    return t;
}

void OrderBook::load_kalshi_snapshot(const nlohmann::json& msg) {
    // bids: "yes_dollars_fp" -> [[price_dollars, size], ...]
    if (auto it = msg.find("yes_dollars_fp"); it != msg.end()) {
        for (const auto& level : *it) {
            update_level(Side::Bid, to_cents(level.at(0)), to_double(level.at(1)));
        }
    }
    // asks: "no_dollars_fp" -> [[no_price_dollars, size], ...], converted to ask price = 1 - no_price
    if (auto it = msg.find("no_dollars_fp"); it != msg.end()) {
        for (const auto& level : *it) {
            update_level(Side::Ask, 100 - to_cents(level.at(0)), to_double(level.at(1)));
        }
    }
}

std::string OrderBook::to_string() const {
    int bp = 0, ap = 0;
    double bs = 0.0, as = 0.0;
    const bool hb = best_bid(bp, bs);
    const bool ha = best_ask(ap, as);
    std::string s = "Asset ID: " + asset_id_ + " | Best Bid: ";
    s += hb ? ("(" + std::to_string(bp / 100.0) + ", " + std::to_string(bs) + ")") : "(None, None)";
    s += " | Best Ask: ";
    s += ha ? ("(" + std::to_string(ap / 100.0) + ", " + std::to_string(as) + ")") : "(None, None)";
    return s;
}

}  // namespace kalshi
