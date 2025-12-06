import csv
import json
import os
from datetime import datetime

# TODO: 
# Create subclasses for Polymarket and Kalshi
class MarketData():
    def __init__(self):
        pass
    
    #Polymarket
    
    def get_csv_filename(self, asset_id):
        with open("statics/statics.json", "r") as json_data:
            data = json_data.load()
        mapped = data["ASSET_ID_MAPPING"].get(asset_id, asset_id[:8])
        return f"Polymarket_{mapped}.csv"
    
    # Create new CSV file if one doesn't exist for Asset ID
    def init_csv_if_needed(self, filename):
        if not os.path.exists(filename):
            with open(filename, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["timestamp", "event_type","price","side","size","best_bid","best_ask"])
    
    def write_row(self, asset_id, timestamp, event_type, price="", side="",
              size="", best_bid="", best_ask=""):
        filename = self.get_csv_filename(asset_id)
        self.init_csv_if_needed(filename)
        
        # TODO:
        # Order data types from largest to smallest
        # Multiply floats by 1000 and store as shorts
        # Convert side to byte data type
        
        with open(filename, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([timestamp, event_type, price, side, size, best_bid, best_ask])
            
    # Write Book Message to CSV
    def persist_book_event(self, message):
        asset_id = message["asset_id"]
        timestamp = message["timestamp"]
        bids = message.get("bids", [])
        asks = message.get("asks", [])

        # Best bid = highest price
        best_bid_price = bids[-1]["price"] if bids else ""
        best_bid_size = bids[-1]["size"] if bids else ""
        # Best ask = lowest price
        best_ask_price = asks[-1]["price"] if asks else ""
        best_ask_size = asks[-1]["size"] if asks else ""

        # Write BUY side
        self.write_row(asset_id, timestamp, "book",
                price=best_bid_price, side="BUY", size=best_bid_size,
                best_bid=best_bid_price, best_ask=best_ask_price)
        
        #Write SELL side
        self.write_row(asset_id, timestamp, "book",
                price=best_ask_price, side="SELL", size=best_ask_size,
                best_bid=best_bid_price, best_ask=best_ask_price)
        
    # Write Price Change to CSV
    def persist_price_change_event(self, message):
        timestamp = message["timestamp"]
        
        for pc in message["price_changes"]:
            self.write_row(
                asset_id=pc["asset_id"],
                timestamp=timestamp,
                event_type="price_change",
                price=pc.get("price", ""),
                side=pc.get("side", ""),
                size=pc.get("size", ""),
                best_bid=pc.get("best_bid", ""),
                best_ask=pc.get("best_ask", "")
            )
            
    # Write tick size change event to CSV
    def persist_tick_change_event(self, message):
        asset_id = message["asset_id"]
        timestamp = message["timestamp"]
        # No price/side/size/best bid/ask for this event
        self.write_row(asset_id, timestamp, "tick_size_change")
        
    # Write last trade event to CSV
    def persist_trade_event(self, message):
        asset_id = message["asset_id"]
        timestamp = message["timestamp"]

        self.write_row(
            asset_id=asset_id,
            timestamp=timestamp,
            event_type="last_trade_price",
            price=message.get("price", ""),
            side=message.get("side", ""),
            size=message.get("size", ""),
            best_bid="",  # Not provided
            best_ask=""
        )
        