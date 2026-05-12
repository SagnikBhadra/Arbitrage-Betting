#include "kalshi_feed.hpp"

#include <boost/asio/connect.hpp>
#include <boost/asio/io_context.hpp>
#include <boost/asio/ip/tcp.hpp>
#include <boost/asio/ssl.hpp>
#include <boost/beast/core.hpp>
#include <boost/beast/ssl.hpp>
#include <boost/beast/websocket.hpp>
#include <boost/beast/websocket/ssl.hpp>
#include <openssl/ssl.h>

#include <chrono>
#include <iostream>
#include <thread>

#include "crypto.hpp"
#include "util.hpp"

namespace kalshi {

namespace beast     = boost::beast;
namespace http      = beast::http;
namespace websocket = beast::websocket;
namespace net       = boost::asio;
namespace ssl       = boost::asio::ssl;
using tcp = net::ip::tcp;

KalshiFeed::KalshiFeed(std::string key_id, EVP_PKEY* private_key, std::vector<std::string> tickers,
                       std::string host, std::string port, std::string path)
    : key_id_(std::move(key_id)),
      key_(private_key),
      tickers_(std::move(tickers)),
      host_(std::move(host)),
      port_(std::move(port)),
      path_(std::move(path)),
      log_(Logger::get("kalshi_feed")) {
    for (const auto& ticker : tickers_) {
        books_.emplace(ticker, std::make_unique<OrderBook>(ticker));
    }
}

OrderBook* KalshiFeed::book(const std::string& ticker) {
    auto it = books_.find(ticker);
    return it == books_.end() ? nullptr : it->second.get();
}

bool KalshiFeed::best_bid(const std::string& ticker, int& price_cents, double& size) const {
    auto it = books_.find(ticker);
    if (it == books_.end()) {
        log_.warn("Order Book with market ticker " + ticker + " not found on get_best_bid");
        return false;
    }
    return it->second->best_bid(price_cents, size);
}

bool KalshiFeed::best_ask(const std::string& ticker, int& price_cents, double& size) const {
    auto it = books_.find(ticker);
    if (it == books_.end()) {
        log_.warn("Order Book with market ticker " + ticker + " not found on get_best_ask");
        return false;
    }
    return it->second->best_ask(price_cents, size);
}

std::unordered_map<std::string, TopOfBook> KalshiFeed::snapshot_all_books() const {
    std::unordered_map<std::string, TopOfBook> out;
    out.reserve(books_.size());
    for (const auto& [ticker, ob] : books_) out.emplace(ticker, ob->snapshot_top());
    return out;
}

// ── message handling ─────────────────────────────────────────────────────────

void KalshiFeed::handle_snapshot(const nlohmann::json& msg) {
    const std::string asset_id = msg.at("market_ticker").get<std::string>();
    OrderBook* ob = book(asset_id);
    if (!ob) {
        log_.warn("Order Book with asset ID " + asset_id + " not found on snapshot");
        return;
    }
    ob->load_kalshi_snapshot(msg);
    snapshot_loaded_.insert(asset_id);

    if (auto it = delta_buffer_.find(asset_id); it != delta_buffer_.end()) {
        for (const auto& delta_msg : it->second) handle_price_change(delta_msg);
        delta_buffer_.erase(it);
    }
    log_.info("Loaded snapshot for " + ob->to_string());
}

void KalshiFeed::handle_price_change(const nlohmann::json& msg) {
    const std::string asset_id = msg.at("market_ticker").get<std::string>();
    const bool is_yes = (msg.at("side").get<std::string>() == "yes");
    const int price_cents = is_yes ? to_cents(msg.at("price_dollars"))
                                   : 100 - to_cents(msg.at("price_dollars"));
    const double delta = to_double(msg.at("delta_fp"));
    const Side side = is_yes ? Side::Bid : Side::Ask;

    OrderBook* ob = book(asset_id);
    if (!ob) {
        log_.warn("Order Book with asset ID " + asset_id + " not found on price change");
        return;
    }
    ob->apply_delta(side, price_cents, delta);
}

void KalshiFeed::handle_trade(const nlohmann::json& msg) {
    const std::string asset_id = msg.at("market_ticker").get<std::string>();
    OrderBook* ob = book(asset_id);
    if (!ob) {
        log_.warn("Order Book with asset ID " + asset_id + " not found on trade");
        return;
    }
    // (no trade-specific bookkeeping in the original code)
}

void KalshiFeed::handle_user_fill(const nlohmann::json& msg) {
    // The python version forwards fills tagged "WBRSSS" to the wide-spread strategy's queue.
    // That strategy isn't part of the Kalshi↔Kalshi pipeline, so this is a no-op stub.
    (void)msg;
}

void KalshiFeed::process_message(const std::string& message) {
    nlohmann::json data;
    try {
        data = nlohmann::json::parse(message);
    } catch (const std::exception& e) {
        log_.error(std::string("failed to parse message: ") + e.what());
        return;
    }

    const std::string msg_type = data.value("type", std::string{});
    const nlohmann::json& msg = data.contains("msg") ? data.at("msg") : data;

    if (msg_type == "subscribed") {
        log_.info("Subscribed: " + data.dump());
        subscribed_ = true;
    } else if (msg_type == "orderbook_snapshot") {
        handle_snapshot(msg);
    } else if (msg_type == "orderbook_delta") {
        const std::string market = msg.at("market_ticker").get<std::string>();
        if (snapshot_loaded_.find(market) == snapshot_loaded_.end()) {
            delta_buffer_[market].push_back(msg);
            return;
        }
        handle_price_change(msg);
    } else if (msg_type == "trade") {
        handle_trade(msg);
    } else if (msg_type == "fill") {
        handle_user_fill(msg);
    } else if (msg_type == "market_state") {
        // ignore
    } else if (msg_type == "error") {
        log_.error("Error: " + data.dump());
    }
}

// ── connection / read loop ───────────────────────────────────────────────────

void KalshiFeed::run() {
    while (running_) {
        try {
            net::io_context ioc;
            ssl::context ctx(ssl::context::tlsv12_client);
            ctx.set_verify_mode(ssl::verify_none);  // python `websockets` verifies; kept lax for portability

            tcp::resolver resolver(ioc);
            websocket::stream<ssl::stream<tcp::socket>> ws(ioc, ctx);

            auto const results = resolver.resolve(host_, port_);
            net::connect(beast::get_lowest_layer(ws), results);

            if (!SSL_set_tlsext_host_name(ws.next_layer().native_handle(), host_.c_str())) {
                beast::error_code ec{static_cast<int>(::ERR_get_error()), net::error::get_ssl_category()};
                throw beast::system_error{ec};
            }
            ws.next_layer().handshake(ssl::stream_base::client);

            // enables automatic ping / keep-alive timeouts (replaces python's ping_interval=30)
            ws.set_option(websocket::stream_base::timeout::suggested(beast::role_type::client));

            const std::string timestamp = std::to_string(now_ms());
            const std::string signature =
                rsa_pss_sign_base64(key_, timestamp + "GET" + path_, PssSaltLen::Digest);
            ws.set_option(websocket::stream_base::decorator(
                [&](websocket::request_type& req) {
                    req.set("KALSHI-ACCESS-KEY", key_id_);
                    req.set("KALSHI-ACCESS-SIGNATURE", signature);
                    req.set("KALSHI-ACCESS-TIMESTAMP", timestamp);
                }));

            ws.handshake(host_ + ":" + port_, path_);
            log_.info("Connected! Subscribing to orderbook for " + join(tickers_, ", "));

            nlohmann::json subscribe_msg = {
                {"id", 1},
                {"cmd", "subscribe"},
                {"params", {{"channels", {"orderbook_delta", "fill"}}, {"market_tickers", tickers_}}},
            };
            ws.write(net::buffer(subscribe_msg.dump()));

            beast::flat_buffer buffer;
            while (running_) {
                buffer.consume(buffer.size());
                ws.read(buffer);
                process_message(beast::buffers_to_string(buffer.data()));
            }
            beast::error_code ec;
            ws.close(websocket::close_code::normal, ec);
        } catch (const beast::system_error& e) {
            if (e.code() == websocket::error::closed) {
                log_.info("WebSocket connection closed normally");
            } else {
                log_.error(std::string("WebSocket connection closed: ") + e.what());
            }
            if (!running_) break;
            log_.info("Reconnecting in 5 seconds...");
            std::this_thread::sleep_for(std::chrono::seconds(5));
        } catch (const std::exception& e) {
            log_.error(std::string("WebSocket error: ") + e.what());
            std::cerr << "WebSocket error: " << e.what() << "\n";
            if (!running_) break;
            log_.info("Reconnecting in 5 seconds...");
            std::this_thread::sleep_for(std::chrono::seconds(5));
        }
    }
}

}  // namespace kalshi
