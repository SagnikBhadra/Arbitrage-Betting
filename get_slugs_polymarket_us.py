import time, base64, requests
import json
from datetime import datetime, timedelta
from cryptography.hazmat.primitives.asymmetric import ed25519

# Your credentials
with open("polymarket.key", "r") as f:
    private_key_base64 = f.read().strip()
api_key_id = "8f004f3b-4858-4401-a979-ca189946cde1"

def get_start_end_of_day_timestamps():
    # Get today's date
    today = datetime.today() + timedelta(days=1)  # UTC time

    # Start of day (00:00:00 UTC)
    start_of_day = today.replace(hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")

    # End of day (23:59:59 UTC)
    end_of_day = today.replace(hour=23, minute=59, second=59, microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")

    print("Start of day:", start_of_day)
    print("End of day:", end_of_day)
    
    return start_of_day, end_of_day

# API documentation: https://docs.polymarket.com/#authentication

# Load private key (first 32 bytes are the seed)
private_key = ed25519.Ed25519PrivateKey.from_private_bytes(
    base64.b64decode(private_key_base64)[:32]
)

def sign_request(method, path):
    "Generate authentication headers for api.polymarket.us"
    timestamp = str(int(time.time() * 1000))
    message = f"{timestamp}{method}{path}"
    signature = base64.b64encode(private_key.sign(message.encode())).decode()

    return {
        "X-PM-Access-Key": api_key_id,
        "X-PM-Timestamp": timestamp,
        "X-PM-Signature": signature,
        "Content-Type": "application/json"
    }

def load_slugs_to_static_file(slugs):
    # Load statics.json
    statics_path = "statics/statics.json"
    with open(statics_path, "r") as f:
        statics = json.load(f)
        
    # Update Polymarket_US mapping
    polymarket_us_mapping = {slug: slug for slug in slugs}
    statics["ASSET_ID_MAPPING"]["Polymarket_US"] = polymarket_us_mapping
            
    with open(statics_path, "w") as f:
        json.dump(statics, f, indent=4)

# Example GET request
path = "/v1/markets"
# GET /v1/events?active=true&categories=sports&eventDate=2026-02-13&ended=false&live=false
start_of_day, end_of_day = get_start_end_of_day_timestamps()
# Only getting 200 markets for testing purposes, need to implement pagination to get all markets
# Should add the following filter on paylod:  'endDateMax': end_of_day,
payload = {'categories': 'sports', 'endDateMin': start_of_day, 'limit': 200}
#payload = {'active': True, 'closed': False, 'archived': False}
headers = sign_request("GET", path)
response = requests.get(f"https://api.polymarket.us{path}", headers=headers, params=payload).json()
print(response)

#response = dict(response)
# Markets
slugs = []

for market in response["markets"]:
    if "nba" in market["slug"]:
        print(f"Market ID: {market['id']}, Name: {market['question']}, Slug: {market['slug']}")
        slugs.append(market['slug'])

load_slugs_to_static_file(slugs)