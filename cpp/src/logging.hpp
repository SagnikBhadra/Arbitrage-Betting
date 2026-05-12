#pragma once

#include <fstream>
#include <mutex>
#include <string>
#include <unordered_map>

namespace kalshi {

// Minimal stand-in for the per-module rotating file loggers used in Python
// (setup_loggers.py).  Each named logger appends to logging/<name>_<YYYY-MM-DD>.log
// and echoes to stdout.  Thread-safe.  Log rotation is intentionally omitted.
class Logger {
public:
    void info(const std::string& msg) { write("INFO", msg); }
    void warn(const std::string& msg) { write("WARNING", msg); }
    void error(const std::string& msg) { write("ERROR", msg); }

    // Returns the process-wide logger registered under `name`, creating it on first use.
    static Logger& get(const std::string& name);

private:
    explicit Logger(std::string name);
    void write(const char* level, const std::string& msg);

    std::string name_;
    std::ofstream file_;
    std::mutex mu_;
};

}  // namespace kalshi
