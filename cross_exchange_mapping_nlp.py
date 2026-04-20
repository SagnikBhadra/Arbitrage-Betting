import requests
import difflib
import os
import re
import json
import time
from collections import defaultdict
from difflib import SequenceMatcher
from groq import Groq
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


PREFIX_PROMPT = f"""
You are matching prediction markets across two exchanges.
Do these two markets represent the SAME underlying real-world event?
Respond ONLY with a number between 0 and 1.
"""


def build_text(events_dict, category):
    """
    Combine all useful fields into one text blob
    """
    texts = []
    for series_name, series in events_dict[category].items():
        for event_name, event in series.items():
            title = event.get("title", "")
            subtitle = event.get("subtitle", "")
            text_dict = {
                "title": f"{title} {subtitle} {category} {series_name} {event_name}".lower(),
                "category": category,
                "series_name": series_name,
                "event_name": event_name
            }
            texts.append(text_dict)
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

def fetch_kalshi_politics(kalshi_events, category):
    kalshi_titles = build_text(kalshi_events, category)
    subset = []
    for text_dict in kalshi_titles:
        title = text_dict["title"]
        subset.append({
            "title": title,
            "category": text_dict["category"],
            "series_name": text_dict["series_name"],
            "event_name": text_dict["event_name"],
            "norm": normalize(title),
        })

    return subset


# ============================================================
# Fetch Polymarket Politics Markets (guaranteed non-zero)
# ============================================================

def fetch_polymarket_politics(poly_events, category):
    poly_titles = build_text(poly_events, category)
    subset = []
    for text_dict in poly_titles:
        title = text_dict["title"]
        subset.append({
            "title": title,
            "norm": normalize(title),
            "category": text_dict["category"],
            "series_name": text_dict["series_name"],
            "event_name": text_dict["event_name"]
        })
    return subset

# ============================================================
# LLM scoring (Groq)
# ============================================================

#LLM_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# Load API key
with open("GROQ.key", "r") as f:
    LLM_API_KEY = f.read().strip()

# ----------------------------
# Rate Limiter (30 req/min)
# ----------------------------
class RateLimiter:
    def __init__(self, max_requests_per_minute):
        self.interval = 60.0 / max_requests_per_minute
        self.last_call = 0.0

    def wait(self):
        now = time.time()
        elapsed = now - self.last_call
        if elapsed < self.interval:
            time.sleep(self.interval - elapsed)
        self.last_call = time.time()

rate_limiter = RateLimiter(30)  # 30 requests per minute
groq_client = Groq(
    api_key=LLM_API_KEY,
)

def score_pair_llm(k_title: str, p_title: str, max_retries: int = 3) -> float:
    """Score a pair using Groq with rate limiting + retries."""
    prompt = f"""
    Market A: "{k_title}"
    Market B: "{p_title}"
    """

    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }

    body = {
        "model": "llama-3.3-70b-versatile",  # Groq model
        "messages": [
            {"role": "system", "content": "You are a precise market-matching assistant."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
    }

    for attempt in range(max_retries):
        try:
            # 🔒 Rate limit BEFORE request
            rate_limiter.wait()
            #print(f"Attempt {attempt}: Market A: {k_title} | Market B: {p_title}")
            
            resp = groq_client.chat.completions.create(
                model= "llama-3.3-70b-versatile",  # Groq model
                #model="llama-3.1-8b-instant",  # Cheaper, faster Groq model for testing
                messages=[
                    {"role": "system", "content": "You are a precise market-matching assistant."},
                    {"role": "user", "content": PREFIX_PROMPT + prompt},
                ],
                temperature=0.0
            )
            #print(resp)
            #print(resp.choices[0].message.content)
            #resp = resp.choices[0].message.content
            """
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 2 ** attempt))
                print(f"Rate limited. Retrying after {retry_after}s")
                time.sleep(retry_after)
                continue
            """
            #resp.raise_for_status()
            content = resp.choices[0].message.content

            try:
                #obj = json.loads(content)
                #print(obj)
                return float(content.strip('```\n').strip('\n```'))
            except Exception as e:
                print(f"Error parsing LLM response: {e}")
                return 0.0

        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                print(f"Request failed: {e}. Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                print("Max retries reached. Returning 0.0")
                return 0.0

    return 0.0


# ============================================================
# Correlate
# ============================================================

def extract_event_date(event_name):
    """
    Extract date from event_name in either Polymarket or Kalshi format.
    
    Polymarket: ufc-seddum-jacmcv-2026-04-25 -> 2026-04-25
    Kalshi:     KXNBAGAME-26APR26SASPOR -> 26APR26
    
    Returns date object or None if no date found.
    """
    from datetime import datetime
    
    # Polymarket format: YYYY-MM-DD
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", event_name)
    if m:
        try:
            return datetime.strptime(m.group(1) + m.group(2) + m.group(3), "%Y%m%d").date()
        except ValueError:
            pass
    
    # Kalshi format: YYMMMDD (e.g., 26APR26)
    m = re.search(r"(\d{1,2})([A-Z]{3})(\d{2})", event_name)
    if m:
        try:
            return datetime.strptime(m.group(1) + m.group(2) + m.group(3), "%y%b%d").date()
        except ValueError:
            pass
    
    return None

def correlate_small(kalshi, poly, cheap_threshold=0.45, llm_threshold=0.9):
    candidates = []
    try:
        for k in kalshi:
            for p in poly:
                # Only consider pairs that have the same date for sports category
                if p["category"].lower() == 'sports':
                    k_date = extract_event_date(k["event_name"])
                    p_date = extract_event_date(p["event_name"])
                    if k_date and p_date and k_date != p_date:
                        continue
                s = cheap_similarity(k["norm"], p["norm"])
                if s >= cheap_threshold:
                    candidates.append((s, k, p))
        
        results = []
        for cheap_score, k, p in candidates:
            llm_score = score_pair_llm(k["title"], p["title"])
            if llm_score >= llm_threshold:
                print(f"Cheap score: {cheap_score:.2f} | LLM score: {llm_score:.2f} | Kalshi: {k['title']} | Polymarket: {p['title']}")
                results.append((llm_score, cheap_score, k, p))
                if len(results) >= 10:  # Limit to top 10 matches for testing
                    break
                continue
            time.sleep(0.5)  # Increased from 0.2s to 0.5s between calls
    except Exception as e:
        print(f"Error during correlation: {e}")

    print(results)
    results.sort(key=lambda x: -x[0])
    return results

# ============================================================
# Save Mappings
# ============================================================

def similar(a, b):
    return SequenceMatcher(None, a, b).ratio()

def build_mapping(ticker_data):
    polymarket_ticker = ticker_data["polymarket_ticker"]
    kalshi_ticker_1 = ticker_data["kalshi_ticker_1"]
    kalshi_ticker_2 = ticker_data["kalshi_ticker_2"]

    month_map = {
        "01":"JAN","02":"FEB","03":"MAR","04":"APR","05":"MAY","06":"JUN",
        "07":"JUL","08":"AUG","09":"SEP","10":"OCT","11":"NOV","12":"DEC"
    }

    mapping = {}

    parts = polymarket_ticker.split("-")

    team1 = parts[2].upper()
    team2 = parts[3].upper()
    date = '-'.join(parts[4:])

    year, month, day = date.split("-")
    kalshi_date = year[2:] + month_map[month] + day

    # -------------------------------
    # STEP 2: Assign correct sides
    # -------------------------------

    suffix1 = kalshi_ticker_1.split("-")[-1]
    suffix2 = kalshi_ticker_2.split("-")[-1]

    score1_t1 = similar(team1, suffix1)
    score1_t2 = similar(team1, suffix2)

    if score1_t1 >= score1_t2:
        kalshi_ticker = kalshi_ticker_1
        other_kalshi_ticker = kalshi_ticker_2
    else:
        kalshi_ticker = kalshi_ticker_2
        other_kalshi_ticker = kalshi_ticker_1

    mapping = {
        "polymarket_ticker": polymarket_ticker,
        "kalshi_ticker": kalshi_ticker,
        "other_poly_id": f"{polymarket_ticker}-inverse",
        "other_kalshi_ticker": other_kalshi_ticker
    }

    return mapping

def save_cross_exchange_mappings(matches, kalshi_events, poly_events, output_path="statics/cross_exchange_statics.json"):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    payload = {"POLYMARKET_KALSHI_MAPPING": {"Moneyline_Events": {}}}
    for category, match_list in matches.items():
        category_matches = []
        for _, _, k, p in match_list:
            kalshi_ticker_1 = kalshi_events[k["category"]][k["series_name"]][k["event_name"]]["market_slugs"][0]
            polymarket_ticker = poly_events[p["category"]][p["series_name"]][p["event_name"]]["market_slugs"][0]
            kalshi_ticker_2 = kalshi_events[k["category"]][k["series_name"]][k["event_name"]]["market_slugs"][1] if len(kalshi_events[k["category"]][k["series_name"]][k["event_name"]]["market_slugs"]) > 1 else ""
            mapping = build_mapping({
                "polymarket_ticker": polymarket_ticker,
                "kalshi_ticker_1": kalshi_ticker_1,
                "kalshi_ticker_2": kalshi_ticker_2
            })

            category_matches.append(mapping)
        payload["POLYMARKET_KALSHI_MAPPING"]["Moneyline_Events"][category] = category_matches
        
    print(payload)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

if __name__ == "__main__":
    # Fetch events from all exchanges
    with open("statics/polymarket_us_event_to_market_mapping.json", "r") as f:
        poly_events = json.load(f)
        
    with open("statics/kalshi_event_to_market_mapping.json", "r") as f:
        kalshi_events = json.load(f)
    
    # Find common categories (e.g. politics, sports, etc.)
    kalshi_categories = set(kalshi_events.keys())
    poly_categories = set(poly_events.keys())
    print(f"Kalshi categories: {kalshi_categories}")
    print(f"Polymarket categories: {poly_categories}")
    common_categories = set(k.lower() for k in kalshi_categories) & set(p.lower() for p in poly_categories)
    print(f"Common categories: {common_categories}")
    
    matches = defaultdict(list)
    
    # For each common category, build texts and correlate
    for common_category in common_categories:
        print(f"\n=== Processing category: {common_category} ===")
        
        print("Fetching Kalshi markets...")
        kalshi = fetch_kalshi_politics(kalshi_events, common_category.capitalize())
        print(f"Kalshi markets: {len(kalshi)}")

        print("Fetching Polymarket markets...")
        poly = fetch_polymarket_politics(poly_events, common_category)
        print(f"Polymarket markets: {len(poly)}")

        print("\nCorrelating...\n")
        matches[common_category] = correlate_small(kalshi, poly)

        print(f"\nTotal candidate matches: {len(matches[common_category])}")
        print("=== High-confidence matches (POC) ===\n")
        for llm_score, cheap_score, k, p in matches[common_category]:
            print(f"LLM score: {llm_score:.2f} | cheap: {cheap_score:.2f}")
            print(f"  Kalshi:     {k['title']}")
            print(f"  Polymarket: {p['title']}")
            print()
    
    ## `save_cross_exchange_mappings` function
    save_cross_exchange_mappings(matches, kalshi_events, poly_events)
