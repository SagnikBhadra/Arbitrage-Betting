#include "kalshi_http_gateway.hpp"

#include <boost/asio/connect.hpp>
#include <boost/asio/io_context.hpp>
#include <boost/asio/ip/tcp.hpp>
#include <boost/asio/ssl.hpp>
#include <boost/beast/core.hpp>
#include <boost/beast/http.hpp>
#include <boost/beast/ssl.hpp>
#include <openssl/ssl.h>

#include <stdexcept>

#include "crypto.hpp"
#include "util.hpp"

namespace kalshi {

namespace beast = boost::beast;
namespace http  = beast::http;
namespace net   = boost::asio;
namespace ssl   = boost::asio::ssl;
using tcp = net::ip::tcp;

namespace {

// Splits "https://api.elections.kalshi.com/trade-api/v2" into (host, port, path).
void parse_url(const std::string& url, std::string& host, std::string& port, std::string& path) {
    std::string rest = url;
    std::string scheme = "https";
    if (auto p = rest.find("://"); p != std::string::npos) {
        scheme = rest.substr(0, p);
        rest = rest.substr(p + 3);
    }
    auto slash = rest.find('/');
    std::string authority = (slash == std::string::npos) ? rest : rest.substr(0, slash);
    path = (slash == std::string::npos) ? "" : rest.substr(slash);
    while (!path.empty() && path.back() == '/') path.pop_back();
    if (auto c = authority.find(':'); c != std::string::npos) {
        host = authority.substr(0, c);
        port = authority.substr(c + 1);
    } else {
        host = authority;
        port = (scheme == "http") ? "80" : "443";
    }
}

http::verb to_verb(const std::string& method) {
    if (method == "GET") return http::verb::get;
    if (method == "POST") return http::verb::post;
    if (method == "DELETE") return http::verb::delete_;
    if (method == "PUT") return http::verb::put;
    throw std::invalid_argument("unsupported HTTP method: " + method);
}

}  // namespace

nlohmann::json OrderRequest::to_json() const {
    nlohmann::json j = {
        {"ticker", ticker},
        {"action", action},
        {"side", side},
        {"count", count},
        {"client_order_id", client_order_id},
        {"type", type},
    };
    if (!time_in_force.empty()) j["time_in_force"] = time_in_force;
    if (yes_price) j["yes_price"] = *yes_price;
    if (no_price)  j["no_price"]  = *no_price;
    return j;
}

KalshiHTTPGateway::KalshiHTTPGateway(std::string api_key_id, EVP_PKEY* private_key,
                                     std::string base_url, bool dry_run)
    : api_key_id_(std::move(api_key_id)),
      key_(private_key),
      dry_run_(dry_run),
      log_(Logger::get("kalshi_http_gateway")) {
    parse_url(base_url, host_, port_, base_path_);
}

std::map<std::string, std::string> KalshiHTTPGateway::headers(const std::string& method,
                                                              const std::string& path) {
    // Kalshi signs over: timestamp + METHOD + <full path from root> ; the original
    // gateway includes the query string here (kalshi_http_gateway.py does not strip it).
    const std::string timestamp = std::to_string(now_ms());
    const std::string message = timestamp + method + (base_path_ + path);
    const std::string signature = rsa_pss_sign_base64(key_, message, PssSaltLen::Max);
    return {
        {"KALSHI-ACCESS-KEY", api_key_id_},
        {"KALSHI-ACCESS-TIMESTAMP", timestamp},
        {"KALSHI-ACCESS-SIGNATURE", signature},
        {"Content-Type", "application/json"},
    };
}

nlohmann::json KalshiHTTPGateway::request(const std::string& method, const std::string& path,
                                          const nlohmann::json* body) {
    const auto hdrs = headers(method, path);

    net::io_context ioc;
    ssl::context ctx(ssl::context::tlsv12_client);
    ctx.set_verify_mode(ssl::verify_none);  // python `requests` verifies; kept lax here for portability

    tcp::resolver resolver(ioc);
    beast::ssl_stream<beast::tcp_stream> stream(ioc, ctx);

    if (!SSL_set_tlsext_host_name(stream.native_handle(), host_.c_str())) {
        beast::error_code ec{static_cast<int>(::ERR_get_error()), net::error::get_ssl_category()};
        throw beast::system_error{ec};
    }

    auto const results = resolver.resolve(host_, port_);
    beast::get_lowest_layer(stream).connect(results);
    stream.handshake(ssl::stream_base::client);

    const std::string target = base_path_ + path;
    http::request<http::string_body> req{to_verb(method), target, 11};
    req.set(http::field::host, host_);
    req.set(http::field::user_agent, "kalshi-cpp/1.0");
    for (const auto& [k, v] : hdrs) req.set(k, v);
    if (body != nullptr) req.body() = body->dump();
    req.prepare_payload();

    http::write(stream, req);

    beast::flat_buffer buffer;
    http::response<http::string_body> res;
    http::read(stream, buffer, res);

    beast::error_code ec;
    stream.shutdown(ec);  // best-effort; ignore not_connected / stream truncated

    const int code = static_cast<int>(res.result_int());
    if (code < 200 || code >= 300) {
        throw std::runtime_error("Kalshi API error — HTTP " + std::to_string(code) + ": " + res.body());
    }
    if (res.body().empty()) return nlohmann::json::object();
    return nlohmann::json::parse(res.body());
}

long long KalshiHTTPGateway::get_balance() {
    const nlohmann::json resp = request("GET", "/portfolio/balance");
    return resp.at("balance").get<long long>();
}

std::unordered_map<std::string, long long> KalshiHTTPGateway::get_positions() {
    std::unordered_map<std::string, long long> positions;
    const nlohmann::json resp = request("GET", "/portfolio/positions");
    if (auto it = resp.find("market_positions"); it != resp.end()) {
        for (const auto& market : *it) {
            const std::string ticker = market.at("ticker").get<std::string>();
            positions[ticker] = static_cast<long long>(to_double(market.at("position_fp")));
        }
    }
    return positions;
}

nlohmann::json KalshiHTTPGateway::get_orders(const std::string& ticker, const std::string& status) {
    std::string query;
    if (!ticker.empty()) query += (query.empty() ? "?" : "&") + std::string("ticker=") + ticker;
    if (!status.empty()) query += (query.empty() ? "?" : "&") + std::string("status=") + status;
    return request("GET", "/portfolio/orders" + query);
}

void KalshiHTTPGateway::create_order(const OrderRequest& order) {
    OrderRequest o = order;
    if (o.client_order_id.empty()) o.client_order_id = uuid4();
    log_.info("Placing order with data: " + o.to_json().dump());
    if (dry_run_) return;  // matches python: the actual POST is commented out there
    // TODO: handle 409 Conflict on client_order_id by resending.
    const nlohmann::json body = o.to_json();
    request("POST", "/portfolio/orders", &body);
}

nlohmann::json KalshiHTTPGateway::batch_create_orders(const nlohmann::json& orders) {
    log_.info("Placing batched orders");
    if (dry_run_) return nlohmann::json();  // matches python: real POST commented out
    return request("POST", "/portfolio/orders/batched", &orders);
}

nlohmann::json KalshiHTTPGateway::cancel_order(const std::string& order_id) {
    log_.info("Cancelling order " + order_id);
    return request("DELETE", "/portfolio/orders/" + order_id);
}

nlohmann::json KalshiHTTPGateway::batch_cancel_orders(const nlohmann::json& orders) {
    log_.info("Batch cancelling orders");
    return request("DELETE", "/portfolio/orders/batched", &orders);
}

nlohmann::json KalshiHTTPGateway::get_market(const std::string& ticker) {
    return request("GET", "/markets/" + ticker);
}

}  // namespace kalshi
