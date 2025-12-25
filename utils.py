import json

def get_asset_ids(market):
    with open("statics/statics.json", "r") as json_file:
        data = json.load(json_file)
    return list(data["ASSET_ID_MAPPING"][market].keys()) if market in data["ASSET_ID_MAPPING"] else []
