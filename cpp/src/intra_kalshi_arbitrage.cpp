#include "intra_kalshi_arbitrage.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>

#include "util.hpp"

namespace kalshi {

namespace {

std::string fmt2(double v) {
    char buf[32];
    std::snprintf(buf, sizeof(buf), "%.2f", v);
    return buf;
}

std::string fmtnum(double v) {
    char buf[32];
    std::snprintf(buf, sizeof(buf), "%g", v);
    return buf;
}

constexpr double to_dollars(int cents) { return cents / 100.0; }

}  // namespace

IntraKalshiArbitrage::IntraKalshiArbitrage(
    KalshiFeed& feed, KalshiHTTPGateway& gateway, PositionManager& position_manager,
    std::unordered_map<std::string, std::vector<std::string>> correlated_market_mapping,
    double profit_threshold)
    : feed_(feed),
      gateway_(gateway),
      position_manager_(position_manager),
      correlated_market_mapping_(std::move(correlated_market_mapping)),
      profit_threshold_(profit_threshold),
      log_(Logger::get("intra_kalshi_strategy")) {
    // The python __init__ reads the API balance then immediately overrides it with 5000.
    try {
        const double api_balance = static_cast<double>(gateway_.get_balance()) / 100.0;
        (void)api_balance;
    } catch (const std::exception& e) {
        log_.error(std::string("Error fetching balance: ") + e.what());
    }
    cached_balance_ = 5000.0;
}

void IntraKalshiArbitrage::find_opportunities(const std::unordered_map<std::string, TopOfBook>& snapshots) {
    for (const auto& [ticker, tob] : snapshots) {
        auto cm_it = correlated_market_mapping_.find(ticker);
        if (cm_it == correlated_market_mapping_.end()) continue;  // no correlated markets

        // NOTE: like the original, this only handles pairs (2 correlated markets), not more.
        for (const auto& correlated_ticker : cm_it->second) {
            auto corr_it = snapshots.find(correlated_ticker);
            if (corr_it == snapshots.end()) continue;
            const TopOfBook& corr_tob = corr_it->second;

            // ── Buy Team A YES & Buy Team B YES ─────────────────────────────
            if (tob.has_ask && tob.ask_px > 0 && corr_tob.has_ask && corr_tob.ask_px > 0) {
                const double best_ask = to_dollars(tob.ask_px);
                const double corr_ask = to_dollars(corr_tob.ask_px);
                long long order_size = static_cast<long long>(std::min(tob.ask_sz, corr_tob.ask_sz));

                const double cost_of_single_share = best_ask + corr_ask;
                const double required_balance = cost_of_single_share * static_cast<double>(order_size);

                if (cached_balance_ < 0) {
                    log_.warn("Negative balance detected: $" + fmt2(cached_balance_) + ". Skipping trade.");
                    continue;
                }
                if (!(cached_balance_ > required_balance)) {
                    order_size = static_cast<long long>(std::floor(cached_balance_ / cost_of_single_share));
                }

                overall_order_count_ += order_size;
                overall_profit_ += std::max((1.0 - cost_of_single_share) * static_cast<double>(order_size), 0.0);

                const double fees = taker_fee_kalshi(best_ask, order_size) + taker_fee_kalshi(corr_ask, order_size);
                const double combined_price = best_ask * static_cast<double>(order_size)
                                            + corr_ask * static_cast<double>(order_size) + fees;

                if (combined_price <= static_cast<double>(order_size) - profit_threshold_) {
                    log_.info("Intra-Kalshi Arbitrage Opportunity: Buy YES on " + ticker + " at " + fmtnum(best_ask)
                              + " and Buy YES on " + correlated_ticker + " at " + fmtnum(corr_ask)
                              + " of size " + std::to_string(order_size) + " | Combined Price: " + fmtnum(combined_price));
                    cached_balance_ -= combined_price;

                    OrderRequest order_a;
                    order_a.ticker = ticker;
                    order_a.action = "buy";
                    order_a.side = "yes";
                    order_a.count = order_size;
                    order_a.client_order_id = uuid4();
                    order_a.yes_price = tob.ask_px;
                    order_a.type = "limit";
                    order_a.time_in_force = "fill_or_kill";
                    try {
                        gateway_.create_order(order_a);
                        position_manager_.update_from_fill(ticker, PositionManager::FillSide::YesBuy, order_size);
                    } catch (const std::exception& e) {
                        log_.error(std::string("Failed to place order A: ") + e.what());
                        continue;
                    }

                    OrderRequest order_b;
                    order_b.ticker = correlated_ticker;
                    order_b.action = "buy";
                    order_b.side = "yes";
                    order_b.count = order_size;
                    order_b.client_order_id = uuid4();
                    order_b.yes_price = corr_tob.ask_px;
                    order_b.type = "limit";
                    order_b.time_in_force = "fill_or_kill";
                    try {
                        gateway_.create_order(order_b);
                        position_manager_.update_from_fill(correlated_ticker, PositionManager::FillSide::YesBuy, order_size);
                    } catch (const std::exception& e) {
                        log_.error(std::string("Failed to place order B: ") + e.what());
                        continue;
                    }
                }
            }

            // ── Buy Team A NO & Buy Team B NO ───────────────────────────────
            if (tob.has_bid && tob.bid_px > 0 && corr_tob.has_bid && corr_tob.bid_px > 0) {
                const double best_no_ask = to_dollars(100 - tob.bid_px);
                const double best_correlated_no_ask = to_dollars(100 - corr_tob.bid_px);
                long long order_size = static_cast<long long>(std::min(tob.bid_sz, corr_tob.bid_sz));

                const double cost_of_single_share = best_no_ask + best_correlated_no_ask;
                const double required_balance = cost_of_single_share * static_cast<double>(order_size);

                if (cached_balance_ < 0) {
                    log_.warn("Negative balance detected: $" + fmt2(cached_balance_) + ". Skipping trade.");
                    continue;
                }
                if (!(cached_balance_ > required_balance)) {
                    order_size = static_cast<long long>(std::floor(cached_balance_ / cost_of_single_share));
                }

                overall_order_count_ += order_size;
                overall_profit_ += std::max((1.0 - cost_of_single_share) * static_cast<double>(order_size), 0.0);

                const double fees = taker_fee_kalshi(best_no_ask, order_size)
                                  + taker_fee_kalshi(best_correlated_no_ask, order_size);
                const double combined_price = best_no_ask * static_cast<double>(order_size)
                                            + best_correlated_no_ask * static_cast<double>(order_size) + fees;

                if (combined_price <= static_cast<double>(order_size) - profit_threshold_) {
                    log_.info("Intra-Kalshi Arbitrage Opportunity: Buy NO on " + ticker + " at " + fmtnum(best_no_ask)
                              + " and Buy NO on " + correlated_ticker + " at " + fmtnum(best_correlated_no_ask)
                              + " of size " + std::to_string(order_size) + " | Combined Price: " + fmtnum(combined_price));
                    cached_balance_ -= combined_price;

                    OrderRequest order_a;
                    order_a.ticker = ticker;
                    order_a.action = "buy";
                    order_a.side = "no";
                    order_a.count = order_size;
                    order_a.client_order_id = uuid4();
                    order_a.no_price = 100 - tob.bid_px;
                    order_a.type = "limit";
                    order_a.time_in_force = "fill_or_kill";
                    try {
                        gateway_.create_order(order_a);
                        position_manager_.update_from_fill(ticker, PositionManager::FillSide::NoBuy, order_size);
                    } catch (const std::exception& e) {
                        log_.error(std::string("Failed to place order A: ") + e.what());
                        continue;
                    }

                    OrderRequest order_b;
                    order_b.ticker = correlated_ticker;
                    order_b.action = "buy";
                    order_b.side = "no";
                    order_b.count = order_size;
                    order_b.client_order_id = uuid4();
                    order_b.no_price = 100 - corr_tob.bid_px;
                    order_b.type = "limit";
                    order_b.time_in_force = "fill_or_kill";
                    try {
                        gateway_.create_order(order_b);
                        position_manager_.update_from_fill(correlated_ticker, PositionManager::FillSide::NoBuy, order_size);
                    } catch (const std::exception& e) {
                        log_.error(std::string("Failed to place order B: ") + e.what());
                        continue;
                    }
                }
            }

            // sell_out_of_position_arb(...) is defined below for parity but, as in the python,
            // it is not invoked here.
        }
    }
}

void IntraKalshiArbitrage::sell_out_of_position_arb(const std::string& ticker, const TopOfBook& tob,
                                                    const std::string& correlated_ticker,
                                                    const TopOfBook& corr_tob) {
    const long long ticker_position = position_manager_.get_position(ticker);
    const long long correlated_ticker_position = position_manager_.get_position(correlated_ticker);

    long long position_size;
    if (ticker_position > 0 && correlated_ticker_position > 0) {
        position_size = std::min(ticker_position, correlated_ticker_position);
    } else if (ticker_position < 0 && correlated_ticker_position < 0) {
        position_size = std::llabs(std::max(ticker_position, correlated_ticker_position));
    } else {
        return;
    }

    if (position_size > 0 && tob.has_ask && tob.ask_sz != 0.0 && corr_tob.has_ask && corr_tob.ask_sz != 0.0
        && tob.has_bid && corr_tob.has_bid) {
        // Sell YES on both sides at the resting bid.
        const long long order_size = std::min({position_size,
                                               static_cast<long long>(tob.bid_sz),
                                               static_cast<long long>(corr_tob.bid_sz)});
        const double best_bid = to_dollars(tob.bid_px);
        const double correlated_best_bid = to_dollars(corr_tob.bid_px);
        const double best_ask = to_dollars(tob.ask_px);
        const double correlated_best_ask = to_dollars(corr_tob.ask_px);

        const double fees = taker_fee_kalshi(best_bid, order_size) + taker_fee_kalshi(correlated_best_bid, order_size);
        const double combined_price = best_bid * static_cast<double>(order_size)
                                    + correlated_best_bid * static_cast<double>(order_size);

        if (combined_price - (static_cast<double>(order_size) + fees) > profit_threshold_) {
            log_.info("Intra-Kalshi Arbitrage Opportunity: Sell YES on " + ticker + " at " + fmtnum(best_ask)
                      + " and Sell YES on " + correlated_ticker + " at " + fmtnum(correlated_best_ask)
                      + " of size " + std::to_string(order_size) + " | Combined Price: " + fmtnum(combined_price)
                      + " | Fees: " + fmtnum(fees));
            cached_balance_ += combined_price;
            cached_balance_ -= fees;

            OrderRequest order_a;
            order_a.ticker = ticker;
            order_a.action = "sell";
            order_a.side = "yes";
            order_a.count = order_size;
            order_a.client_order_id = uuid4();
            order_a.yes_price = tob.bid_px;
            order_a.type = "limit";
            order_a.time_in_force = "fill_or_kill";
            try {
                gateway_.create_order(order_a);
                position_manager_.update_from_fill(ticker, PositionManager::FillSide::YesSell, order_size);
            } catch (const std::exception& e) {
                log_.error(std::string("Failed to place order A: ") + e.what());
            }

            OrderRequest order_b;
            order_b.ticker = correlated_ticker;
            order_b.action = "sell";
            order_b.side = "yes";
            order_b.count = order_size;
            order_b.client_order_id = uuid4();
            order_b.yes_price = corr_tob.bid_px;
            order_b.type = "limit";
            order_b.time_in_force = "fill_or_kill";
            try {
                gateway_.create_order(order_b);
                position_manager_.update_from_fill(correlated_ticker, PositionManager::FillSide::YesSell, order_size);
            } catch (const std::exception& e) {
                log_.error(std::string("Failed to place order B: ") + e.what());
            }
        }
    }
}

}  // namespace kalshi
