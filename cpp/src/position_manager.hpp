#pragma once

#include <mutex>
#include <string>
#include <unordered_map>
#include <unordered_set>

namespace kalshi {

// Port of position_manager.py.  Positions are kept as integers (Kalshi `position_fp`).
class PositionManager {
public:
    explicit PositionManager(std::unordered_map<std::string, long long> positions = {})
        : positions_(std::move(positions)) {}

    enum class FillSide { YesBuy, YesSell, NoBuy, NoSell };
    // Parses "YES_BUY" / "YES_SELL" / "NO_BUY" / "NO_SELL"; throws on anything else.
    static FillSide parse_side(const std::string& side);

    void update_from_fill(const std::string& ticker, FillSide side, long long quantity);
    void update_from_fill(const std::string& ticker, const std::string& side, long long quantity);

    long long get_position(const std::string& ticker);
    std::unordered_map<std::string, long long> get_all_positions();

private:
    std::unordered_map<std::string, long long> positions_;
    std::mutex mu_;
};

}  // namespace kalshi
