import time
import base64
import json
import requests

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import serialization

# Kalshi Configuration
KEY_ID = "7edd1c5d-6c0c-4458-bb77-04854221689b"
PRIVATE_KEY_PATH = "Kalshi.key"
BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

class KalshiHTTPGateway:
    def __init__(self, api_key_id: str, private_key_pem: str, base_url: str = "https://api.elections.kalshi.com/trade-api/v2"):
        """
        api_key_id: your Kalshi API Key ID
        private_key_pem: your RSA private key (PKCS8 PEM string)
        base_url: base endpoint
        """
        self.api_key_id = api_key_id
        self.base_url = base_url.rstrip("/")

        # load RSA key
        self.private_key = serialization.load_pem_private_key(
            private_key_pem.encode(),
            password=None
        )

    def _get_headers(self, method: str, path: str) -> dict:
        """
        Create the required signed headers for Kalshi.
        method: e.g. "POST"
        path: e.g. "/trade-api/v2/portfolio/orders"
        """
        timestamp = str(int(time.time() * 1000))
        message = timestamp + method.upper() + path

        # RSA-PSS signature
        signature_bytes = self.private_key.sign(
            message.encode("utf-8"),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
        signature = base64.b64encode(signature_bytes).decode()

        return {
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "Content-Type": "application/json"
        }

    def _request(self, method: str, path: str, json_body: dict = None):
        """
        Generic request helper.
        """
        headers = self._get_headers(method, path)
        url = f"{self.base_url}{path}"

        response = requests.request(method, url, headers=headers, json=json_body)

        try:
            response.raise_for_status()
        except Exception as e:
            # expose debug info
            raise RuntimeError(f"HTTP {response.status_code}: {response.text}") from e

        return response.json()

    def create_order(self, order_data: dict):
        """
        Place an order with Kalshi.

        order_data should include at least:
            - "ticker": string
            - "action": "buy" or "sell"
            - "side": "yes" or "no"
            - "count": int
            - "client_order_id": unique string
        Optional fields include:
            "type", "yes_price", "no_price", "time_in_force", etc.
        See Kalshi docs for all options. :contentReference[oaicite:2]{index=2}
        """
        path = "/portfolio/orders"
        return self._request("POST", path, json_body=order_data)

if __name__ == "__main__":
    gateway_client = KalshiHTTPGateway(
        api_key_id=KEY_ID,
        private_key_pem=open(PRIVATE_KEY_PATH).read(),
        base_url=BASE_URL
    )
    # Example: place a market buy order for 10 YES contracts on a market