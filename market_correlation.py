import requests
import difflib
import re
import json
import time

# ============================================================
# Helpers
# ============================================================

def normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r'[^a-z0-9 ]+', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def cheap_similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


# ============================================================
# Fetch Kalshi Politics Markets (guaranteed non-zero)
# ============================================================

def fetch_kalshi_politics():
    url = "https://api.elections.kalshi.com/trade-api/v2/markets"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()

    subset = []
    for m in data.get("markets", []):
        if m.get("category") == "Politics":
            title = m.get("title", "")
            subset.append({
                "ticker": m.get("ticker"),
                "title": title,
                "norm": normalize(title),
            })

    return subset


# ============================================================
# Fetch Polymarket Politics Markets (guaranteed non-zero)
# ============================================================

def fetch_polymarket_politics():
    url = "https://clob.polymarket.com/markets"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()

    subset = []
    for m in data:
        if not isinstance(m, dict):
            continue

        if m.get("category") != "Politics":
            continue

        title = m.get("question") or m.get("title") or ""
        subset.append({
            "id": m.get("id"),
            "title": title,
            "norm": normalize(title),
        })

    return subset


# ============================================================
# LLM scoring
# ============================================================

LLM_API_URL = "https://api.openai.com/v1/chat/completions"
LLM_API_KEY = "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"

def score_pair_llm(k_title: str, p_title: str) -> float:
    prompt = f"""
You are matching prediction markets across two exchanges.

Market A: "{k_title}"
Market B: "{p_title}"

Do these two markets represent the SAME underlying real-world event?

Respond ONLY with JSON:
{{"same_event_probability": <number between 0 and 1>}}
"""

    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }

    body = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": "You are a precise market-matching assistant."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
    }

    resp = requests.post(LLM_API_URL, headers=headers, data=json.dumps(body), timeout=20)
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]

    try:
        obj = json.loads(content)
        return float(obj.get("same_event_probability", 0.0))
    except Exception:
        return 0.0


# ============================================================
# Correlate
# ============================================================

def correlate_small(kalshi, poly, cheap_threshold=0.45, llm_threshold=0.75):
    candidates = []

    for k in kalshi:
        for p in poly:
            s = cheap_similarity(k["norm"], p["norm"])
            if s >= cheap_threshold:
                candidates.append((s, k, p))

    results = []
    for cheap_score, k, p in candidates:
        llm_score = score_pair_llm(k["title"], p["title"])
        if llm_score >= llm_threshold:
            results.append((llm_score, cheap_score, k, p))
        time.sleep(0.2)

    results.sort(key=lambda x: -x[0])
    return results


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    print("Fetching Kalshi politics markets...")
    kalshi = fetch_kalshi_politics()
    print(f"Kalshi politics markets: {len(kalshi)}")

    print("Fetching Polymarket politics markets...")
    poly = fetch_polymarket_politics()
    print(f"Polymarket politics markets: {len(poly)}")

    print("\nCorrelating...\n")
    matches = correlate_small(kalshi, poly)

    print("=== High-confidence matches (POC) ===\n")
    for llm_score, cheap_score, k, p in matches:
        print(f"LLM score: {llm_score:.2f} | cheap: {cheap_score:.2f}")
        print(f"  Kalshi:     {k['ticker']} — {k['title']}")
        print(f"  Polymarket: {p['id']} — {p['title']}")
        print()

