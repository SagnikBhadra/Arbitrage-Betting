import requests
import difflib
import re
import json
import time
from collections import defaultdict
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def build_text(categories):
    """
    Combine all useful fields into one text blob
    """
    texts = []
    for category in categories:
        for series_name, series in categories[category].items():
            for event_name, event in series.items():
                #print(event_name)
                title = event.get("title", "")
                subtitle = event.get("subtitle", "")
                #texts.append(f"{title} {subtitle} {category} {series_name} {event}".lower())
                texts.append(f"{title} {subtitle}".lower())
    return texts


def match_events(kalshi_events, poly_events, threshold=0.5):

    kalshi_texts = build_text(kalshi_events)
    poly_texts = build_text(poly_events)
    
    vectorizer = TfidfVectorizer(
        stop_words="english",
        ngram_range=(1, 2)  # big improvement over unigram
    )

    all_texts = kalshi_texts + poly_texts
    print(all_texts)
    tfidf_matrix = vectorizer.fit_transform(all_texts)

    kalshi_vecs = tfidf_matrix[:len(kalshi_texts)]
    poly_vecs = tfidf_matrix[len(kalshi_texts):]

    similarity = cosine_similarity(poly_vecs, kalshi_vecs)

    mappings = []

    for i, row in enumerate(similarity):
        best_idx = row.argmax()
        score = row[best_idx]

        if score >= threshold:
            mappings.append({
                "polymarket_event": poly_events[i]["slug"],
                "kalshi_event": kalshi_events[best_idx]["event_ticker"],
                "score": float(score)
            })

    return mappings

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
    with open("statics/kalshi_event_to_market_mapping.json", "r") as f:
        kalshi_events = json.load(f)

    kalshi_titles = build_text(kalshi_events)
    subset = []
    for title in kalshi_titles:
        #title = m.get("title", "")
        subset.append({
            "title": title,
            "norm": normalize(title),
        })

    return subset


# ============================================================
# Fetch Polymarket Politics Markets (guaranteed non-zero)
# ============================================================

def fetch_polymarket_politics():
    with open("statics/polymarket_us_event_to_market_mapping.json", "r") as f:
        poly_events = json.load(f)

    poly_titles = build_text(poly_events)
    subset = []
    for title in poly_titles:
        #title = m.get("title")
        subset.append({
            "title": title,
            "norm": normalize(title),
        })

    return subset

# ============================================================
# LLM scoring
# ============================================================

LLM_API_URL = "https://api.openai.com/v1/chat/completions"
LLM_API_KEY = "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"

def score_pair_llm(k_title: str, p_title: str, max_retries: int = 3) -> float:
    """Score a pair with exponential backoff for rate limit handling."""
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

    for attempt in range(max_retries):
        try:
            resp = requests.post(LLM_API_URL, headers=headers, data=json.dumps(body), timeout=20)
            
            if resp.status_code == 429:
                # Respect Retry-After header if provided
                retry_after = int(resp.headers.get("Retry-After", 2 ** attempt))
                print(f"Rate limited. Retrying after {retry_after}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(retry_after)
                continue
            
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]

            try:
                obj = json.loads(content)
                return float(obj.get("same_event_probability", 0.0))
            except Exception:
                return 0.0
                
        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                print(f"Request failed: {e}. Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                print(f"Max retries reached. Returning 0.0")
                return 0.0
    
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
        time.sleep(0.5)  # Increased from 0.2s to 0.5s between calls

    results.sort(key=lambda x: -x[0])
    return results

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
    

    """"
    mappings = match_events(kalshi_events, poly_events, threshold=0.5)

    with open("statics/event_mappings.json", "w") as f:
        json.dump(mappings, f, indent=4)

    print(f"Saved {len(mappings)} mappings to statics/event_mappings.json")
    """