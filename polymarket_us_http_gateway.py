import os
import time
import json
import base64
import logging
import uuid
import requests

from cryptography.hazmat.primitives.asymmetric import ed25519


# ─────────────────────────────────────────────────────────────
# Config (use env vars in production)
# ─────────────────────────────────────────────────────────────
API_KEY = "8f004f3b-4858-4401-a979-ca189946cde1"
PRIVATE_KEY_FILE_PATH = "polymarket.key"
BASE_URL = "https://api.polymarket.us"


def load_private_key_from_base64(b64_key: str):
    """
    Polymarket provides an Ed25519 private key encoded in base64.
    We use the first 32 bytes to construct the signing key.
    """
    key_bytes = base64.b64decode(b64_key)[:32]
    return ed25519.Ed25519PrivateKey.from_private_bytes(key_bytes)


class PolymarketUSHTTPGateway:
    def __init__(
        self,
        api_key_id: str,
        key_file_path: str,
        base_url: str = "https://api.polymarket.us",
        logger=logging.getLogger(__name__),
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key_id = api_key_id
        self.key_file_path = key_file_path
        self.logger = logger

        # Load private key from file
        with open(self.key_file_path, "r") as f:
            private_key_base64 = f.read().strip()

        self.private_key = ed25519.Ed25519PrivateKey.from_private_bytes(
            base64.b64decode(private_key_base64)[:32]
        )

    # ────────────────────────────────────────────────────────
    # Auth
    # ────────────────────────────────────────────────────────
    def _sign_headers(self, method: str, path: str) -> dict:
        """
        Signature spec from Polymarket US docs:

        message = timestamp + method + path
        """
        timestamp = str(int(time.time() * 1000))
        message = f"{timestamp}{method.upper()}{path}"

        signature = base64.b64encode(
            self.private_key.sign(message.encode("utf-8"))
        ).decode()

        return {
            "X-PM-Access-Key": self.api_key_id,
            "X-PM-Timestamp": timestamp,
            "X-PM-Signature": signature,
            "Content-Type": "application/json",
        }

    # ─────────────────────────────────────────────────────────
    # Core request
    # ─────────────────────────────────────────────────────────
    def _request(self, method: str, path: str, body: dict = None):
        url = f"{self.base_url}{path}"
        headers = self._sign_headers(method, path)

        response = requests.request(method, url, headers=headers, json=body)

        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            raise RuntimeError(
                f"Polymarket API error — HTTP {response.status_code}: {response.text}"
            ) from e

        return response.json()

    # ─────────────────────────────────────────────────────────
    # Public methods
    # ─────────────────────────────────────────────────────────
    def get_balance(self) -> dict:
        """GET /v1/account/balances — current available cash balance."""
        return self._request("GET", "/v1/account/balances")

    def create_order(
        self,
        market_slug: str,
        price: float,
        quantity: int,
        side: str = "BUY_LONG",
        tif: str = "GOOD_TILL_CANCEL",
        order_type: str = "LIMIT",
    ) -> dict:
        """
        Place a limit order.

        side:
            BUY_SHORT | BUY_LONG | SELL_SHORT | SELL_LONG

        tif:
            GOOD_TILL_CANCEL | IOC | FOK

        order_type:
            LIMIT | MARKET
        """

        order = {
            "marketSlug": market_slug,
            "type": f"ORDER_TYPE_{order_type}",
            "price": {
                "value": str(price),
                "currency": "USD",
            },
            "quantity": quantity,
            "tif": f"TIME_IN_FORCE_{tif}",
            "intent": f"ORDER_INTENT_{side}",
            "clientOrderId": str(uuid.uuid4()),
        }

        self.logger.info(f"Placing order: {order}")

        #return self._request("POST", "/v1/orders", order)

    def cancel_order(self, order_id: str, market_slug: str = None):
        body = {
            "marketSlug": market_slug,
        }
        self.logger.info(f"Cancelling order {order_id} with body: {body}")
        return self._request("POST", f"/v1/order/{order_id}/cancel", body)

    def get_orders(self):
        self.logger.info(f"Getting open orders")
        return self._request("GET", "/v1/orders/open")

    def get_order(self, order_id: str):
        self.logger.info(f"Getting order {order_id}")
        return self._request("GET", f"/v1/orders/{order_id}")
    
    def get_positions(self) -> dict:
        """GET /v1/portfolio/positions"""
        self.logger.info(f"Getting portfolio positions")
        return self._request("GET", "/v1/portfolio/positions")


# ─────────────────────────────────────────────────────────────
# Example usage
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    gateway = PolymarketUSHTTPGateway(
        api_key_id=API_KEY,
        key_file_path=PRIVATE_KEY_FILE_PATH,
        base_url=BASE_URL,
    )
    
    print("Current balance:")
    balance = gateway.get_balance()
    print(json.dumps(balance, indent=2))
    
    print("\nGet orders:")
    orders = gateway.get_orders()
    print(json.dumps(orders, indent=2))

    print("\nCancel order:")
    gateway.cancel_order("88E6SRT0CG1V", "aec-cbb-oregst-sea-2026-02-15")
    print("Order canceled.")

    print("\nGet orders:")
    orders = gateway.get_orders()
    print(json.dumps(orders, indent=2))

    """
    print("Placing test order...")

    response = gateway.create_order(
        market_slug="aec-cbb-oregst-sea-2026-02-15",
        price=0.999,
        quantity=1,
        side="BUY_SHORT",
    )

    print(json.dumps(response, indent=2))
    """
