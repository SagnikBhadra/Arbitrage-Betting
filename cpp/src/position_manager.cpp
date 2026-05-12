#include "position_manager.hpp"

#include <stdexcept>

namespace kalshi {

PositionManager::FillSide PositionManager::parse_side(const std::string& side) {
    if (side == "YES_BUY") return FillSide::YesBuy;
    if (side == "YES_SELL") return FillSide::YesSell;
    if (side == "NO_BUY") return FillSide::NoBuy;
    if (side == "NO_SELL") return FillSide::NoSell;
    throw std::invalid_argument("Unknown side " + side);
}

void PositionManager::update_from_fill(const std::string& ticker, FillSide side, long long quantity) {
    std::lock_guard<std::mutex> lock(mu_);
    switch (side) {
        case FillSide::YesBuy:  positions_[ticker] += quantity; break;
        case FillSide::YesSell: positions_[ticker] -= quantity; break;
        case FillSide::NoBuy:   positions_[ticker] -= quantity; break;
        case FillSide::NoSell:  positions_[ticker] += quantity; break;
    }
}

void PositionManager::update_from_fill(const std::string& ticker, const std::string& side, long long quantity) {
    update_from_fill(ticker, parse_side(side), quantity);
}

long long PositionManager::get_position(const std::string& ticker) {
    std::lock_guard<std::mutex> lock(mu_);
    auto it = positions_.find(ticker);
    return it == positions_.end() ? 0 : it->second;
}

std::unordered_map<std::string, long long> PositionManager::get_all_positions() {
    std::lock_guard<std::mutex> lock(mu_);
    return positions_;
}

}  // namespace kalshi
