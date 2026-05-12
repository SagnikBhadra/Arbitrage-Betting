#include "util.hpp"

#include <chrono>
#include <cmath>
#include <cstdio>
#include <fstream>
#include <random>
#include <sstream>
#include <stdexcept>

namespace kalshi {

std::string read_file(const std::string& path) {
    std::ifstream f(path, std::ios::binary);
    if (!f) throw std::runtime_error("could not open file: " + path);
    std::ostringstream ss;
    ss << f.rdbuf();
    return ss.str();
}

int64_t now_ms() {
    using namespace std::chrono;
    return duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count();
}

std::string uuid4() {
    static thread_local std::mt19937_64 rng{std::random_device{}()};
    std::uniform_int_distribution<uint64_t> dist;
    uint64_t a = dist(rng), b = dist(rng);
    unsigned char bytes[16];
    for (int i = 0; i < 8; ++i) bytes[i] = static_cast<unsigned char>(a >> (8 * i));
    for (int i = 0; i < 8; ++i) bytes[8 + i] = static_cast<unsigned char>(b >> (8 * i));
    bytes[6] = static_cast<unsigned char>((bytes[6] & 0x0F) | 0x40);  // version 4
    bytes[8] = static_cast<unsigned char>((bytes[8] & 0x3F) | 0x80);  // variant 1
    char buf[37];
    std::snprintf(buf, sizeof(buf),
                  "%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",
                  bytes[0], bytes[1], bytes[2], bytes[3], bytes[4], bytes[5], bytes[6], bytes[7],
                  bytes[8], bytes[9], bytes[10], bytes[11], bytes[12], bytes[13], bytes[14], bytes[15]);
    return buf;
}

std::string join(const std::vector<std::string>& parts, const std::string& sep) {
    std::string out;
    for (size_t i = 0; i < parts.size(); ++i) {
        if (i) out += sep;
        out += parts[i];
    }
    return out;
}

double to_double(const nlohmann::json& v) {
    if (v.is_number()) return v.get<double>();
    if (v.is_string()) return std::stod(v.get<std::string>());
    if (v.is_null()) return 0.0;
    if (v.is_boolean()) return v.get<bool>() ? 1.0 : 0.0;
    throw std::runtime_error("to_double: unexpected json type");
}

int to_cents(const nlohmann::json& v) {
    return static_cast<int>(std::lround(to_double(v) * 100.0));
}

std::string to_str(const nlohmann::json& v) {
    if (v.is_string()) return v.get<std::string>();
    return v.dump();
}

namespace {
// Round x up to two decimal places, with a tiny tolerance so floating-point noise on a value
// that is mathematically a whole number of cents doesn't bump it to the next cent.
double ceil_to_cents(double x) {
    return std::ceil(x * 100.0 - 1e-9) / 100.0;
}
}  // namespace

double taker_fee_kalshi(double price, long long size) {
    const double fee = 0.07 * static_cast<double>(size) * price * (1.0 - price);
    return ceil_to_cents(fee);
}

double maker_fee_kalshi(double price, long long size) {
    const double fee = 0.0175 * static_cast<double>(size) * price * (1.0 - price);
    return ceil_to_cents(fee);
}

}  // namespace kalshi
