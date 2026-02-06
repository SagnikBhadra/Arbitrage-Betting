import json
from decimal import Decimal, ROUND_CEILING

def get_asset_ids(market):
    with open("statics/statics.json", "r") as json_file:
        data = json.load(json_file)
    return list(data["ASSET_ID_MAPPING"][market].keys()) if market in data["ASSET_ID_MAPPING"] else []

def get_maker_fees_kalshi(price, size):
    """
    Calculate maker fees for Kalshi based on price and size.
    
    Args:
        price: Price of the asset (float)
        size: Size of the order (float)

    Returns:
        Maker fees (float)
    """
    # Kalshi charges a maker fee of 0.1% for limit orders
    maker_fee_rate = Decimal("0.0175")
    price = Decimal(str(price))
    size = Decimal(str(size))
    fee = maker_fee_rate * size * price * (Decimal("1.0") - price)
    # Round up to 2 decimal places
    fee_ceiling = fee.quantize(Decimal("0.01"), rounding=ROUND_CEILING)
    return fee_ceiling

def get_taker_fees_kalshi(price, size):
    """
    Calculate taker fees for Kalshi based on price and size.

    Args:
        price: Price of the asset (float)
        size: Size of the order (float)

    Returns:
        Taker fees (float)
    """
    taker_fee_rate = Decimal("0.07")
    price = Decimal(str(price))
    size = Decimal(str(size))
    fee = taker_fee_rate * size * price * (Decimal("1.0") - price)
    # Round up to 2 decimal places
    fee_ceiling = fee.quantize(Decimal("0.01"), rounding=ROUND_CEILING)
    return fee_ceiling