import os
import time
import base64
import json
import uuid
import requests
import uuid

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import serialization

# Kalshi Configuration — override via environment variables for security
KEY_ID = os.getenv("KALSHI_API_KEY_ID", "7edd1c5d-6c0c-4458-bb77-04854221689b")
PRIVATE_KEY_PATH = os.getenv("KALSHI_PRIVATE_KEY_PATH", "Kalshi.key")
BASE_URL = os.getenv("KALSHI_BASE_URL", "https://api.elections.kalshi.com/trade-api/v2")


def load_private_key(path: str) -> str:
    """Load the RSA private key from a file, with helpful error messages."""
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"Private key file not found: {path}\n"
            "Please ensure the file exists or set KALSHI_PRIVATE_KEY_PATH env var."
        )
    with open(path, "r") as f:
        return f.read()


class KalshiHTTPGateway:
    def __init__(
        self,
        api_key_id: str,
        private_key_pem: str,
        base_url: str = "https://api.elections.kalshi.com/trade-api/v2",
    ):
        """
        api_key_id: your Kalshi API Key ID
        private_key_pem: your RSA private key (PKCS8 PEM string)
        base_url: base endpoint (e.g. https://api.elections.kalshi.com/trade-api/v2)
        """
        self.api_key_id = api_key_id
        self.base_url = base_url.rstrip("/")

        # Extract API path prefix for signing (e.g. "/trade-api/v2")
        # Kalshi requires signing over the full path from root
        from urllib.parse import urlparse
        parsed = urlparse(self.base_url)
        self.api_path_prefix = parsed.path.rstrip("/")

        # Load RSA key
        self.private_key = serialization.load_pem_private_key(
            private_key_pem.encode(),
            password=None,
        )

    def _get_headers(self, method: str, path: str) -> dict:
        """
        Create the required signed headers for Kalshi.
        method: e.g. "POST"
        path: relative path like "/portfolio/orders"
        """
        # Full path for signing (e.g. "/trade-api/v2/portfolio/orders")
        full_path = self.api_path_prefix + path

        timestamp = str(int(time.time() * 1000))
        message = timestamp + method.upper() + full_path

        # RSA-PSS signature
        signature_bytes = self.private_key.sign(
            message.encode("utf-8"),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )
        signature = base64.b64encode(signature_bytes).decode()

        return {
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, json_body: dict = None):
        """
        Generic request helper.
        path: relative path (e.g. "/portfolio/orders")
        """
        headers = self._get_headers(method, path)
        url = f"{self.base_url}{path}"
        print(f"headers: {headers}")
        print(f"URL: {url}")

        response = requests.request(method, url, headers=headers, json=json_body)

        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            raise RuntimeError(
                f"Kalshi API error — HTTP {response.status_code}: {response.text}"
            ) from e

        return response.json()

    # ────────────────────────────────────────────────────────────────────────
    # Public API methods
    # ────────────────────────────────────────────────────────────────────────
    def get_balance(self) -> dict:
        """Get your current account balance."""
        return self._request("GET", "/portfolio/balance")

    def get_positions(self) -> dict:
        """Get your current positions."""
        return self._request("GET", "/portfolio/positions")

    def get_orders(self, ticker: str = None, status: str = None) -> dict:
        """
        Get orders. Optionally filter by ticker and/or status.
        status: 'resting', 'canceled', 'executed', etc.
        """
        params = []
        if ticker:
            params.append(f"ticker={ticker}")
        if status:
            params.append(f"status={status}")
        query = ("?" + "&".join(params)) if params else ""
        return self._request("GET", f"/portfolio/orders{query}")

    def create_order(self, order_data: dict) -> dict:
        """
        Place an order with Kalshi.

        Required fields:
            - ticker: str          (market ticker)
            - action: "buy" | "sell"
            - side: "yes" | "no"
            - count: int           (number of contracts)
            - type: "market" | "limit"
            - client_order_id: str (unique per order — auto-generated if missing)

        For limit orders also include:
            - yes_price or no_price (in cents, 1-99)

        Returns the order confirmation from Kalshi.
        """
        # Auto-generate client_order_id if not provided
        if "client_order_id" not in order_data:
            order_data["client_order_id"] = str(uuid.uuid4())
            


        return self._request("POST", "/portfolio/orders", json_body=order_data)
        #return 

    def cancel_order(self, order_id: str) -> dict:
        """Cancel an open order by order_id."""
        return self._request("DELETE", f"/portfolio/orders/{order_id}")

    def get_market(self, ticker: str) -> dict:
        """Get details for a specific market."""
        return self._request("GET", f"/markets/{ticker}")


# ────────────────────────────────────────────────────────────────────────────
# CLI / Example usage
# ────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Loading Kalshi credentials...")
    private_key_pem = load_private_key(PRIVATE_KEY_PATH)

    gateway = KalshiHTTPGateway(
        api_key_id=KEY_ID,
        private_key_pem=private_key_pem,
        base_url=BASE_URL,
    )

    # Quick connectivity test: fetch account balance
    print("Fetching account balance...")
    try:
        balance = gateway.get_balance()
        print(f"✓ Connected! Balance: {json.dumps(balance, indent=2)}")
        
        # Example: place a market buy order for 10 YES contracts on a market
        """
        order_data = {
            "ticker": "KXT20WORLDCUP-26-IND",
            "action": "buy",
            "side": "yes",
            "count": 1,
            "client_order_id": str(uuid.uuid4()),
            "yes_price": 1,
            "type": "limit",
        }
        
        response = gateway.create_order(order_data)
        print("Order placed:", response)
        """
        
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        exit(1)

    