#pragma once

#include <nlohmann/json.hpp>

#include <cstdint>
#include <string>
#include <vector>

namespace kalshi {

// ── filesystem / time / id helpers ───────────────────────────────────────────
std::string read_file(const std::string& path);
int64_t now_ms();          // milliseconds since the unix epoch
std::string uuid4();       // random UUID v4 string, e.g. "550e8400-e29b-41d4-a716-446655440000"
std::string join(const std::vector<std::string>& parts, const std::string& sep);

// ── JSON coercion helpers ────────────────────────────────────────────────────
// The Kalshi feed sends numbers either as JSON numbers or as decimal strings; these
// accept both (mirroring python's float(x) / Decimal(x)).
double   to_double(const nlohmann::json& v);
int      to_cents(const nlohmann::json& v);      // dollars value -> integer cents
std::string to_str(const nlohmann::json& v);     // string passthrough / number stringify

// ── Kalshi fee schedule (utils.py) ───────────────────────────────────────────
// All prices are in dollars (0.0 - 1.0); fees are returned in dollars, rounded UP to the cent.
double taker_fee_kalshi(double price, long long size);
double maker_fee_kalshi(double price, long long size);

}  // namespace kalshi
