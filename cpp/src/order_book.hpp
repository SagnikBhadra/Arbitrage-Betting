#pragma once

#include <nlohmann/json.hpp>

#include <map>
#include <mutex>
#include <string>

namespace kalshi {

// Mirrors orderbook.py.  Prices are stored as integer cents (Kalshi prices are whole cents,
// 1..99) instead of python's float/Decimal keys — economically identical but exact.
// `Side::Bid` == python side 0, `Side::Ask` == python side 1.
enum class Side { Bid = 0, Ask = 1 };

struct TopOfBook {
    bool has_bid = false;
    int  bid_px  = 0;     // cents
    double bid_sz = 0.0;
    bool has_ask = false;
    int  ask_px  = 0;     // cents
    double ask_sz = 0.0;
};

class OrderBook {
public:
    explicit OrderBook(std::string asset_id);

    // set the absolute resting size at `price_cents` (removes the level if size <= 0)
    void update_level(Side side, int price_cents, double size);
    // add `delta` to the resting size at `price_cents` (removes the level if it drops to <= 0)
    void apply_delta(Side side, int price_cents, double delta);

    double size_at(Side side, int price_cents) const;
    bool best_bid(int& price_cents, double& size) const;   // returns false if that side is empty
    bool best_ask(int& price_cents, double& size) const;
    TopOfBook snapshot_top() const;

    // Loads a Kalshi `orderbook_snapshot` message body (`yes_dollars_fp` / `no_dollars_fp`).
    void load_kalshi_snapshot(const nlohmann::json& msg);

    const std::string& asset_id() const { return asset_id_; }
    std::string to_string() const;   // like python __repr__

private:
    std::string asset_id_;
    // ascending in price; best bid = rbegin(), best ask = begin()
    std::map<int, double> bids_;
    std::map<int, double> asks_;
    mutable std::mutex mu_;
};

}  // namespace kalshi
