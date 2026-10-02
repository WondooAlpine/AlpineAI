import os
import re
from typing import Any, Dict, List
import pandas as pd
import streamlit as st

GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "1fbDtDmXR2QS15V3oY6dAIW64gcqMui3vTMrndxsOYVQ")
SHEET_CSV_URL = f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}/gviz/tq?tqx=out:csv"
FALLBACK_IMAGE = "https://images.unsplash.com/photo-1544735716-392fe2489ffa?auto=format&fit=crop&w=900&q=80"

PLAN_INFO = {
    "EP": {"name": "European Plan", "desc": "Room Only (No meals)"},
    "CP": {"name": "Continental Plan", "desc": "Room + Breakfast"},
    "MAP": {
        "name": "Modified American Plan",
        "desc": "Room + Breakfast + 1 Major Meal (Lunch/Dinner)",
    },
    "AP": {"name": "American Plan", "desc": "Room + All Meals (B + L + D)"},
}


def convert_gdrive_url(url: str) -> str:
  if not isinstance(url, str) or not url.strip():
    return FALLBACK_IMAGE
  url = url.strip()
  if "drive.google.com" not in url:
    return url
  m1 = re.search(r"/file/d/([a-zA-Z0-9_-]+)", url)
  if m1:
    return f"https://lh3.googleusercontent.com/d/{m1.group(1)}"
  m2 = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", url)
  if m2:
    return f"https://lh3.googleusercontent.com/d/{m2.group(1)}"
  return url


def clean_price(val: Any, default: float = 1500.0) -> float:
  if pd.isna(val) or val == "":
    return default
  if isinstance(val, (int, float)):
    return float(val)
  cleaned = re.sub(r"[^\d.]", "", str(val))
  try:
    return float(cleaned) if cleaned else default
  except ValueError:
    return default


@st.cache_data(ttl=600)
def fetch_stays_from_sheet() -> List[Dict[str, Any]]:
  try:
    df = pd.read_csv(SHEET_CSV_URL)
    df.columns = [c.strip().lower() for c in df.columns]
    df = df.fillna("")
    records = df.to_dict(orient="records")

    for row in records:
      raw_keys = str(row.get("town_keys", ""))
      row["town_keys_list"] = [
          k.strip().lower() for k in raw_keys.split(",") if k.strip()
      ]
      row["rate"] = clean_price(row.get("price_bracket", 1500))

      raw_type = str(row.get("pricing_type", "Per Room")).strip().lower()
      row["pricing_type"] = "Per Head" if "head" in raw_type else "Per Room"

      raw_plan = str(row.get("plan", "EP")).strip().upper()
      row["plan"] = raw_plan if raw_plan in PLAN_INFO else "EP"
      row["plan_desc"] = PLAN_INFO[row["plan"]]["desc"]

      row["image_url"] = convert_gdrive_url(row.get("image_url", ""))
      if not row.get("vibe"):
        row["vibe"] = (
            f"Mountain hospitality at {row.get('altitude', 'the Himalayas')}."
        )

    return records
  except Exception as e:
    print(f"Error fetching Google Sheet: {e}")
    return []


def match_stay_for_day(place_name: str, route_title: str) -> Dict[str, Any]:
  stays = fetch_stays_from_sheet()
  if not stays:
    return {
        "stay_name": f"Curated Alpine Stay ({place_name})",
        "altitude": "5,600 ft",
        "property_type": "Boutique Mountain Stay",
        "rating": "4.8 ★",
        "rate": 1500.0,
        "pricing_type": "Per Head",
        "plan": "MAP",
        "plan_desc": "Room + Breakfast + Dinner",
        "image_url": FALLBACK_IMAGE,
        "vibe": "Panoramic valley views.",
    }

  search_text = f"{place_name.lower()} {route_title.lower()}"
  for property_item in stays:
    for key in property_item.get("town_keys_list", []):
      if key and key in search_text:
        return property_item

  return stays[0]