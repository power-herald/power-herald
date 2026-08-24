# src/schedule.py
import json
import datetime
import requests
from typing import List

# Example usage: python src/schedule.py <building_id>
# This script fetches pregenerated outage JSON and formats outages for today and tomorrow

OUTAGE_JSON_URL = "https://raw.githubusercontent.com/Baskerville42/outage-data-ua/main/data/outages.json"  # Example URL

def fetch_outage_data():
    resp = requests.get(OUTAGE_JSON_URL)
    resp.raise_for_status()
    return resp.json()

def format_outages_for_building(building_id: str, outages: List[dict]) -> str:
    now = datetime.datetime.now()
    today = now.date()
    tomorrow = today + datetime.timedelta(days=1)
    result = []
    for day in [today, tomorrow]:
        day_str = day.strftime("%Y-%m-%d")
        day_outages = [o for o in outages if o.get("building_id") == building_id and o.get("date") == day_str]
        if day_outages:
            result.append(f"Outages for {day_str}:")
            for o in day_outages:
                result.append(f"  {o['start']} - {o['end']}")
        else:
            result.append(f"No outages for {day_str}.")
    return "\n".join(result)

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python src/schedule.py <building_id>")
        sys.exit(1)
    building_id = sys.argv[1]
    outages = fetch_outage_data()
    print(format_outages_for_building(building_id, outages))
