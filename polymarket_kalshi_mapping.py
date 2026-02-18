import json
from difflib import SequenceMatcher

def similar(a, b):
    return SequenceMatcher(None, a, b).ratio()

def build_mapping(data):
    kalshi_tickers = list(data["ASSET_ID_MAPPING"]["Kalshi"].keys())
    poly_slugs = list(data["ASSET_ID_MAPPING"]["Polymarket_US"].keys())

    month_map = {
        "01":"JAN","02":"FEB","03":"MAR","04":"APR","05":"MAY","06":"JUN",
        "07":"JUL","08":"AUG","09":"SEP","10":"OCT","11":"NOV","12":"DEC"
    }

    mapping = {}

    for poly in poly_slugs:
        parts = poly.split("-")

        team1 = parts[2].upper()
        team2 = parts[3].upper()
        date = '-'.join(parts[4:])

        year, month, day = date.split("-")
        kalshi_date = year[2:] + month_map[month] + day

        # -------------------------------
        # STEP 1: Find the correct GAME
        # -------------------------------
        date_candidates = []
        for ticker in kalshi_tickers:
            game_block = ticker.split("-")[1]
            if game_block.startswith(kalshi_date):
                date_candidates.append(ticker)

        if len(date_candidates) < 2:
            continue

        # Group tickers by game_block (each game has 2 tickers)
        games = {}
        for ticker in date_candidates:
            game_block = ticker.split("-")[1]
            games.setdefault(game_block, []).append(ticker)

        # Identify which game_block matches team1/team2 best
        best_game = None
        best_score = 0

        for game_block, tickers in games.items():
            teams_part = game_block[len(kalshi_date):]

            score = similar(team1, teams_part) + similar(team2, teams_part)

            if score > best_score:
                best_score = score
                best_game = tickers

        if not best_game or len(best_game) != 2:
            continue

        # -------------------------------
        # STEP 2: Assign correct sides
        # -------------------------------
        t1, t2 = best_game

        suffix1 = t1.split("-")[-1]
        suffix2 = t2.split("-")[-1]

        score1_t1 = similar(team1, suffix1)
        score1_t2 = similar(team1, suffix2)

        if score1_t1 >= score1_t2:
            kalshi_ticker = t1
            other_kalshi_ticker = t2
        else:
            kalshi_ticker = t2
            other_kalshi_ticker = t1

        mapping[poly] = {
            "kalshi_ticker": kalshi_ticker,
            "other_poly_id": f"{poly}-inverse",
            "other_kalshi_ticker": other_kalshi_ticker
        }

    return mapping


with open("statics/statics.json", "r") as f:
    data = json.load(f)


data["POLYMARKET_KALSHI_MAPPING"] = build_mapping(data)
#print("Mappings created:", data["POLYMARKET_KALSHI_MAPPING"])

with open("statics/statics.json", "w") as f:
    json.dump(data, f, indent=4)

print("Mappings created:", len(data["POLYMARKET_KALSHI_MAPPING"]))