import os
import re
from typing import Dict, Any, List
import pandas as pd

# ---------------------------------------------------------------------------
# GOOGLE SHEET CONFIGURATION FOR STAYS INVENTORY
# ---------------------------------------------------------------------------
CATALOG_SHEET_ID = os.environ.get(
    "CATALOG_SHEET_ID",
    "1fbDtDmXR2QS15V3oY6dAIW64gcqMui3vTMrndxsOYVQ",  # <-- Put your Sheet ID here
)

# ---------------------------------------------------------------------------
# GOOGLE SHEET INVENTORY FETCHING
# ---------------------------------------------------------------------------
def fetch_inventory_from_sheet(sheet_id: str) -> List[Dict[str, Any]]:
    """
    Fetches the 'Stays' tab from the Google Sheet.
    Supports column headers: town_keys / location, price_bracket / rate.
    """
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet=Stays"
    try:
        df = pd.read_csv(url)
        # Normalize column names: strip spaces and convert to lowercase
        df.columns = [str(col).strip().lower().replace(" ", "_") for col in df.columns]

        inventory = []
        for _, row in df.iterrows():
            stay_name = str(row.get("stay_name", "")).strip()
            if not stay_name or stay_name.lower() == "nan":
                continue

            # Support both 'town_keys' and 'location'
            town_keys = str(row.get("town_keys", row.get("location", ""))).strip()
            if not town_keys or town_keys.lower() == "nan":
                continue

            # Support both 'price_bracket' and 'rate'
            raw_rate = str(row.get("price_bracket", row.get("rate", "0"))).strip()
            rate_clean = re.sub(r"[^\d]", "", raw_rate)
            rate_val = float(rate_clean) if rate_clean else 0.0

            inventory.append({
                "stay_name": stay_name,
                "town_keys": town_keys.lower(),
                "location": town_keys,
                "altitude": str(row.get("altitude", "Elevation N/A")).strip(),
                "property_type": str(row.get("property_type", "Heritage / Resort")).strip(),
                "rating": str(row.get("rating", "4.8 ★")).strip(),
                "pricing_type": str(row.get("pricing_type", "Per Room")).strip(),
                "plan": str(row.get("plan", "EP")).strip().upper(),
                "rate": rate_val,
                "image_url": str(row.get("image_url", "https://images.unsplash.com/photo-1544735716-392fe2489ffa?auto=format&fit=crop&w=900&q=80")).strip(),
                "vibe": str(row.get("vibe", "Scenic view rooms with authentic local hospitality.")).strip()
            })

        return inventory
    except Exception as e:
        print(f"Notice: Failed to fetch inventory from Google Sheet ({e})")
        return []


# ---------------------------------------------------------------------------
# MATCHING LOGIC (RETURNS ALL MATCHING HOTELS)
# ---------------------------------------------------------------------------
def match_all_stays_for_day(place_name: str, route_title: str = "") -> List[Dict[str, Any]]:
    """
    Returns ALL hotels in inventory whose comma-separated town_keys match
    the day's destination, route title, or region context.
    """
    inventory = fetch_inventory_from_sheet(CATALOG_SHEET_ID)
    if not inventory:
        return []

    # Clean and tokenize the day's spot and route title
    search_context = f"{place_name} {route_title}".lower()
    search_tokens = set(re.findall(r"\b\w{3,}\b", search_context))

    matched_stays: List[Dict[str, Any]] = []

    for stay in inventory:
        # Split comma-separated keys like ['darjeeling', 'ghoom']
        keys = [k.strip() for k in stay["town_keys"].split(",") if k.strip()]

        is_match = False
        for key in keys:
            # 1. Direct substring in search context (e.g. "darjeeling" inside "Darjeeling Sightseeing")
            if key in search_context:
                is_match = True
                break
            # 2. Token overlap (e.g. key words matching)
            key_tokens = set(re.findall(r"\b\w{3,}\b", key))
            if key_tokens & search_tokens:
                is_match = True
                break

        if is_match and stay not in matched_stays:
            matched_stays.append(stay)

    return matched_stays


def match_stay_for_day(place_name: str, route_title: str = "") -> Dict[str, Any]:
    """
    Returns the first matching hotel or a placeholder if none found.
    """
    all_stays = match_all_stays_for_day(place_name, route_title)
    if all_stays:
        return all_stays[0]

    return {
        "stay_name": "Not Available",
        "location": place_name,
        "town_keys": place_name,
        "property_type": "N/A",
        "altitude": "N/A",
        "plan": "N/A",
        "pricing_type": "Per Room",
        "rate": 0.0,
        "rating": "N/A",
        "image_url": "",
        "vibe": f"No registered properties found in inventory for {place_name}."
    }
