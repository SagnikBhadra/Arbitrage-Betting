#include "config.hpp"

#include <nlohmann/json.hpp>

#include "util.hpp"

namespace kalshi {

Config load_config(const std::string& repo_root) {
    using nlohmann::json;
    const std::string root = repo_root.empty() ? "." : repo_root;

    Config cfg;

    // ── credentials ──────────────────────────────────────────────────────────
    const json secrets = json::parse(read_file(root + "/kalshi_secrets.json"));
    cfg.key_id = secrets.at("KEY_ID").get<std::string>();
    cfg.private_key_path = "Kalshi.key";
    cfg.private_key_pem = read_file(root + "/" + cfg.private_key_path);

    // ── statics ──────────────────────────────────────────────────────────────
    const json statics = json::parse(read_file(root + "/statics/statics.json"));

    const auto& asset_id_mapping = statics.at("ASSET_ID_MAPPING");
    if (asset_id_mapping.contains("Kalshi")) {
        for (auto it = asset_id_mapping.at("Kalshi").begin(); it != asset_id_mapping.at("Kalshi").end(); ++it) {
            cfg.kalshi_tickers.push_back(it.key());
        }
    }

    if (statics.contains("CORRELATED_MARKET_MAPPING")) {
        for (auto it = statics.at("CORRELATED_MARKET_MAPPING").begin();
             it != statics.at("CORRELATED_MARKET_MAPPING").end(); ++it) {
            std::vector<std::string> related;
            for (const auto& t : it.value()) related.push_back(t.get<std::string>());
            cfg.correlated_market_mapping.emplace(it.key(), std::move(related));
        }
    }

    return cfg;
}

}  // namespace kalshi
