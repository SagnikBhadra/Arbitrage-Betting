#pragma once

#include <string>
#include <unordered_map>
#include <vector>

#include "kalshi_feed.hpp"
#include "kalshi_http_gateway.hpp"
#include "logging.hpp"
#include "order_book.hpp"
#include "position_manager.hpp"

namespace kalshi {

// Port of intra_kalshi_arbitrage.py: looks for arbitrage within Kalshi 2-outcome moneyline
// markets — buying YES on both sides (or NO on both sides) of a pair of mutually-exclusive
// markets when the combined ask is below $1 by more than `profit_threshold`.
class IntraKalshiArbitrage {
public:
    IntraKalshiArbitrage(KalshiFeed& feed, KalshiHTTPGateway& gateway, PositionManager& position_manager,
                         std::unordered_map<std::string, std::vector<std::string>> correlated_market_mapping,
                         double profit_threshold = 0.01);

    // `snapshots` is an immutable top-of-book snapshot per ticker (taken on the scan thread).
    void find_opportunities(const std::unordered_map<std::string, TopOfBook>& snapshots);

private:
    void sell_out_of_position_arb(const std::string& ticker, const TopOfBook& tob,
                                  const std::string& correlated_ticker, const TopOfBook& corr_tob);

    [[maybe_unused]] KalshiFeed& feed_;  // kept for parity with the python (legacy live-book path)
    KalshiHTTPGateway&  gateway_;
    PositionManager&    position_manager_;
    std::unordered_map<std::string, std::vector<std::string>> correlated_market_mapping_;
    double profit_threshold_;
    Logger& log_;

    long long overall_order_count_ = 0;
    double    overall_profit_ = 0.0;
    double    cached_balance_ = 5000.0;  // dollars (python also overrides the API balance with 5000)
};

}  // namespace kalshi
