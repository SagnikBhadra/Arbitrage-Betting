#pragma once

#include <nlohmann/json.hpp>
#include <openssl/evp.h>

#include <map>
#include <optional>
#include <string>
#include <unordered_map>

#include "logging.hpp"

namespace kalshi {

// One order to send to POST /portfolio/orders.  Mirrors the dicts built in
// intra_kalshi_arbitrage.py / kalshi_http_gateway.py.
struct OrderRequest {
    std::string ticker;
    std::string action;          // "buy" | "sell"
    std::string side;            // "yes" | "no"
    long long   count = 0;
    std::string client_order_id;
    std::string type;            // "limit" | "market"
    std::string time_in_force;   // "fill_or_kill" | "good_till_canceled" | "immediate_or_cancel"
    std::optional<int> yes_price;  // cents 1..99 (limit orders)
    std::optional<int> no_price;   // cents 1..99 (limit orders)

    nlohmann::json to_json() const;
};

// Port of kalshi_http_gateway.py (REST execution + account queries).
class KalshiHTTPGateway {
public:
    // `private_key` is borrowed, not owned (must outlive this object).
    // `dry_run`: when true, create_order / batch_create_orders only log — matching the original
    // python where the real POST is commented out.  GETs / cancels always hit the network.
    KalshiHTTPGateway(std::string api_key_id, EVP_PKEY* private_key,
                      std::string base_url = "https://api.elections.kalshi.com/trade-api/v2",
                      bool dry_run = true);

    long long get_balance();                                       // cents
    std::unordered_map<std::string, long long> get_positions();    // ticker -> position_fp
    nlohmann::json get_orders(const std::string& ticker = "", const std::string& status = "");
    void create_order(const OrderRequest& order);
    nlohmann::json batch_create_orders(const nlohmann::json& orders);
    nlohmann::json cancel_order(const std::string& order_id);
    nlohmann::json batch_cancel_orders(const nlohmann::json& orders);
    nlohmann::json get_market(const std::string& ticker);

private:
    std::map<std::string, std::string> headers(const std::string& method, const std::string& path);
    nlohmann::json request(const std::string& method, const std::string& path,
                           const nlohmann::json* body = nullptr);

    std::string api_key_id_;
    EVP_PKEY*   key_;            // borrowed
    bool        dry_run_;
    Logger&     log_;

    // parsed from base_url
    std::string host_;           // e.g. api.elections.kalshi.com
    std::string port_;           // e.g. 443
    std::string base_path_;      // e.g. /trade-api/v2  (this is also api_path_prefix for signing)
};

}  // namespace kalshi
