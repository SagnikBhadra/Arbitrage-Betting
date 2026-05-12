#include "logging.hpp"

#include <chrono>
#include <ctime>
#include <iostream>
#include <memory>
#include <sys/stat.h>

namespace kalshi {

namespace {

std::string today_string() {
    std::time_t t = std::time(nullptr);
    std::tm tm{};
#if defined(_WIN32)
    localtime_s(&tm, &t);
#else
    localtime_r(&t, &tm);
#endif
    char buf[16];
    std::strftime(buf, sizeof(buf), "%Y-%m-%d", &tm);
    return buf;
}

std::string timestamp_string() {
    using namespace std::chrono;
    auto now = system_clock::now();
    auto ms = duration_cast<milliseconds>(now.time_since_epoch()) % 1000;
    std::time_t t = system_clock::to_time_t(now);
    std::tm tm{};
#if defined(_WIN32)
    localtime_s(&tm, &t);
#else
    localtime_r(&t, &tm);
#endif
    char buf[32];
    std::strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S", &tm);
    char out[40];
    std::snprintf(out, sizeof(out), "%s,%03lld", buf, static_cast<long long>(ms.count()));
    return out;
}

}  // namespace

Logger::Logger(std::string name) : name_(std::move(name)) {
    ::mkdir("logging", 0755);  // no-op if it already exists
    const std::string path = "logging/" + name_ + "_" + today_string() + ".log";
    file_.open(path, std::ios::app);
}

void Logger::write(const char* level, const std::string& msg) {
    const std::string line = timestamp_string() + " | " + level + " | " + msg + "\n";
    std::lock_guard<std::mutex> lock(mu_);
    if (file_.is_open()) {
        file_ << line;
        file_.flush();
    }
    std::clog << "[" << name_ << "] " << line;
}

Logger& Logger::get(const std::string& name) {
    static std::mutex registry_mu;
    static std::unordered_map<std::string, std::unique_ptr<Logger>> registry;
    std::lock_guard<std::mutex> lock(registry_mu);
    auto it = registry.find(name);
    if (it == registry.end()) {
        it = registry.emplace(name, std::unique_ptr<Logger>(new Logger(name))).first;
    }
    return *it->second;
}

}  // namespace kalshi
