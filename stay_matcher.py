import re
import pandas as pd
import streamlit as st
from typing import Dict, Any, List

# Paste your Google Sheet ID or full CSV URL here:
GOOGLE_SHEET_ID = "YOUR_GOOGLE_SHEET_ID_HERE"
SHEET_CSV_URL = f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}/gviz/tq?tqx=out:csv"

FALLBACK_IMAGE = "https://images.unsplash.com/photo-1544735716-392fe2489ffa?auto=format&fit=crop&w=900&q=80"

def convert_gdrive_url(url: str) -> str:
    """Transforms Google Drive sharing links to direct CDN image streams."""
    if not isinstance(url, str) or not url.strip():
        return FALLBACK_IMAGE

    url = url.strip()
    if "drive.google.com" not in url:
        return url

    # Matches /file/d/<file_id>/
    file_id_match = re.search(r"/file/d/([a-zA-Z0-9_-]+)", url)
    if file_id_match:
        return f"https://lh3.googleusercontent.com/d/{file_id_match.group(1)}"

    # Matches id=<file_id>
    id_param_match = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", url)
    if id_param_match:
        return f"https://lh3.googleusercontent.com/d/{id_param_match.group(1)}"

    return url

@st.cache_data(ttl=600)  # Caches for 10 minutes so every click doesn't hit Google Sheets
def fetch_stays_from_sheet() -> List[Dict[str, Any]]:
    """Loads the live Google Sheet into a list of property dictionaries."""
    try:
        df = pd.read_csv(SHEET_CSV_URL)
        df.columns = [c.strip().lower() for c in df.columns]
        
        # Clean string columns
        df = df.fillna("")
        records = df.to_dict(orient="records")

        # Normalize town keys and convert drive images
        for row in records:
            raw_keys = str(row.get("town_keys", ""))
            row["town_keys_list"] = [k.strip().lower() for k in raw_keys.split(",") if k.strip()]
            row["image_url"] = convert_gdrive_url(row.get("image_url", ""))

        return records
    except Exception as e:
        print(f"Error fetching Google Sheet: {e}")
        return []

def match_stay_for_day(place_name: str, route_title: str) -> Dict[str, Any]:
    stays = fetch_stays_from_sheet()
    
    if not stays:
        return {
            "stay_name": f"Curated Alpine Stay ({place_name})",
            "altitude": "Alpine Elevation",
            "property_type": "Boutique Mountain Lodge",
            "rating": "4.8 ★",
            "price_bracket": "₹₹₹",
            "image_url": FALLBACK_IMAGE,
            "vibe": "Authentic mountain hospitality with scenic valley views and warm hearths.",
        }

    search_text = f"{place_name.lower()} {route_title.lower()}"

    # Search keyword match in town_keys_list
    for property_item in stays:
        for key in property_item.get("town_keys_list", []):
            if key and key in search_text:
                return property_item

    # Default to first property in the sheet if no exact town matched
    return stays[0]