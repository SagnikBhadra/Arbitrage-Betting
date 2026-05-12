#pragma once

#include <string>
#include <unordered_map>
#include <vector>

namespace kalshi {

// Everything the Kalshi↔Kalshi pipeline needs to bootstrap, loaded from the existing
// repo data files: kalshi_secrets.json, Kalshi.key, statics/statics.json.
struct Config {
    // credentials
    std::string key_id;             // kalshi_secrets.json -> KEY_ID
    std::string private_key_path;   // path to the RSA private key PEM (default "Kalshi.key")
    std::string private_key_pem;    // contents of the above

    // endpoints (match main.py)
    std::string ws_host = "api.elections.kalshi.com";
    std::string ws_port = "443";
    std::string ws_path = "/trade-api/ws/v2";
    std::string http_base_url = "https://api.elections.kalshi.com/trade-api/v2";

    // statics/statics.json
    std::vector<std::string> kalshi_tickers;  // keys of ASSET_ID_MAPPING.Kalshi
    std::unordered_map<std::string, std::vector<std::string>> correlated_market_mapping;

    // strategy params (main.py: profit_threshold=0.01)
    double profit_threshold = 0.01;
};

// `repo_root` is the directory that contains kalshi_secrets.json / Kalshi.key / statics/.
Config load_config(const std::string& repo_root);

}  // namespace kalshi
