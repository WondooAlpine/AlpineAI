# ===========================================================================
# WONDOO ALPINE STUDIO - PRIMARY APPLICATION SCRIPT
# Version: v1.20-STABLE-TYPING-CURSOR-EMBEDDED
# ===========================================================================

import os
import glob
import json
import uuid
import random
import re
import zlib
import base64
import difflib
from io import BytesIO, StringIO
import asyncio
import textwrap
import urllib.parse
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Dict, Any, List

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components
from google import genai
from google.genai import types
from PIL import Image, ImageDraw

from generate_itinerary import (
    generate_itinerary_content,
    render_itinerary_pages,
    TourItinerary,
)
from web_image_fetcher import search_key_spot_images
from stay_matcher import match_stay_for_day, match_all_stays_for_day
from booking_pricing import calculate_dynamic_sheet_quotation, generate_upi_qr_url
from coupon_manager import validate_coupon_for_user, record_coupon_redemption

# ---------------------------------------------------------------------------
# 1. PAGE CONFIGURATION
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Wondoo | Your Journey, Intelligently Planned",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# 2. GLOBAL STATE INITIALIZATION
# ---------------------------------------------------------------------------
if "itinerary_data" not in st.session_state:
    st.session_state.itinerary_data = None

if "active_view" not in st.session_state:
    st.session_state.active_view = "home"

if "itin_tab" not in st.session_state:
    st.session_state.itin_tab = "Itinerary"

if "user" not in st.session_state:
    st.session_state.user = None

if "booking_confirmed" not in st.session_state:
    st.session_state.booking_confirmed = None

if "auto_open_booking" not in st.session_state:
    st.session_state.auto_open_booking = False

if "applied_coupon" not in st.session_state:
    st.session_state.applied_coupon = None

if "use_wallet" not in st.session_state:
    st.session_state.use_wallet = False

if "user_wallet_balance" not in st.session_state:
    st.session_state.user_wallet_balance = 2500

if "booking_history" not in st.session_state:
    st.session_state.booking_history = [
        {
            "booking_id": "WAN-7F9B12",
            "circuit": "East Sikkim Silk Route Homestay Explorer",
            "duration": "5 Days • 4 Nights",
            "departure_date": "2026-11-15",
            "heads": 4,
            "rooms": 2,
            "vehicle": "Dedicated Bolero / Scorpio 4x4",
            "room_tier": "Standard Room",
            "grand_total": 59800,
            "advance_paid": 14950,
            "balance_due": 44850,
            "status": "CONFIRMED_LOCKED",
            "permit_status": "PERMITS_APPROVED"
        }
    ]

if "wishlist" not in st.session_state:
    st.session_state.wishlist = set()

if "compare_list" not in st.session_state:
    st.session_state.compare_list = set()

if "selected_destination" not in st.session_state:
    st.session_state.selected_destination = None

if "explore_category" not in st.session_state:
    st.session_state.explore_category = "All"

if "selected_cab" not in st.session_state:
    st.session_state.selected_cab = "Include Dedicated Cab (Innova/Scorpio)"

if "selected_room_tier" not in st.session_state:
    st.session_state.selected_room_tier = "Standard Room"

if "num_travelers" not in st.session_state:
    st.session_state.num_travelers = 4

if "selected_stays" not in st.session_state:
    st.session_state.selected_stays = {}

if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": (
                "**Wondoo Alpine Concierge**\n\n"
                "Welcome to our journey studio! Where are you planning to travel, for how many days, and who is joining your expedition?"
            ),
        }
    ]

# ---------------------------------------------------------------------------
# CONFIGURATION & SECRETS
# ---------------------------------------------------------------------------
def get_secret(key: str, default: str = "") -> str:
    try:
        if hasattr(st, "secrets") and key in st.secrets:
            return str(st.secrets[key]).strip()
    except Exception:
        pass
    return os.environ.get(key, default)

BOOKING_WEBHOOK_URL = get_secret("BOOKING_WEBHOOK_URL", "https://script.google.com/macros/s/YOUR_APPS_SCRIPT_DEPLOYMENT_ID/exec")
AGENCY_WHATSAPP_NUMBER = get_secret("AGENCY_WHATSAPP_NUMBER", "919800000000")
UPI_VPA = get_secret("UPI_VPA", "wondooexpeditions@oksbi")
UPI_PAYEE_NAME = get_secret("UPI_PAYEE_NAME", "Wondoo Alpine Studio")
RAZORPAY_KEY_ID = get_secret("RAZORPAY_KEY_ID", "rzp_test_1DP5mmOlF5G5ag")
CATALOG_SHEET_ID = get_secret("CATALOG_SHEET_ID", "1fbDtDmXR2QS15V3oY6dAIW64gcqMui3vTMrndxsOYVQ")
OPENROUTER_API_KEY = get_secret("OPENROUTER_API_KEY", "")

DEFAULT_CARD_IMG = "https://images.unsplash.com/photo-1544735716-392fe2489ffa?auto=format&fit=crop&w=900&q=80"

ROOM_TIER_PREMIUM_MAP = {
    "Standard Room": 0,
    "Deluxe Mountain/Sea View (+₹1,200/night)": 1200,
    "Executive Suite / Heritage View (+₹2,500/night)": 2500,
}

# ---------------------------------------------------------------------------
# ASSET ENCODERS & URL SANITIZATION
# ---------------------------------------------------------------------------
def sanitize_image_url(url: str, fallback_url: str = DEFAULT_CARD_IMG) -> str:
    if not url or not isinstance(url, str):
        return fallback_url
    url = url.strip()
    if not url.startswith("http"):
        return fallback_url

    if "images.unsplash.com" in url and "?" not in url:
        return f"{url}?auto=format&fit=crop&w=900&q=80"

    if "drive.google.com" in url:
        file_id_match = re.search(r"/d/([a-zA-Z0-9_-]+)", url) or re.search(r"id=([a-zA-Z0-9_-]+)", url)
        if file_id_match:
            file_id = file_id_match.group(1)
            return f"https://drive.google.com/thumbnail?id={file_id}&sz=w1200"
            
    return url

def resolve_asset_path(filename: str) -> str:
    base_name = os.path.splitext(filename)[0]
    candidate_dirs = [
        "", 
        "assets", 
        "static", 
        os.path.join(os.path.dirname(__file__), "assets"),
        os.path.join(os.path.dirname(__file__), "static")
    ]
    candidate_exts = [".png", ".PNG", ".svg", ".SVG", ".jpg", ".jpeg", ".webp"]
    
    for c_dir in candidate_dirs:
        direct_path = os.path.join(c_dir, filename) if c_dir else filename
        if os.path.isfile(direct_path):
            return direct_path
        for ext in candidate_exts:
            variant_path = os.path.join(c_dir, base_name + ext) if c_dir else base_name + ext
            if os.path.isfile(variant_path):
                return variant_path
    return None

def get_image_base64(image_path: str, fallback_url: str = DEFAULT_CARD_IMG) -> str:
    resolved = resolve_asset_path(image_path)
    if resolved and os.path.exists(resolved):
        try:
            with open(resolved, "rb") as f:
                data = base64.b64encode(f.read()).decode("utf-8")
            ext = os.path.splitext(resolved)[1].replace(".", "").lower()
            mime = "image/svg+xml" if ext == "svg" else f"image/{ext}"
            return f"data:{mime};base64,{data}"
        except Exception:
            return fallback_url
    return fallback_url

APP_LOGO_SRC = get_image_base64("logo.png", fallback_url="https://img.icons8.com/fluency/96/mountain.png")
HERO_BG_SRC = get_image_base64("hero_bg.png")

AI_ICON_SRC = get_image_base64("icon_ai.png", fallback_url="https://img.icons8.com/fluency/96/sparkling--v1.png")
ROUTE_ICON_SRC = get_image_base64("icon_route.png", fallback_url="https://img.icons8.com/fluency/96/map-pin.png")
BUDGET_ICON_SRC = get_image_base64("icon_budget.png", fallback_url="https://img.icons8.com/fluency/96/wallet.png")
GUIDE_ICON_SRC = get_image_base64("icon_guide.png", fallback_url="https://img.icons8.com/fluency/96/open-book.png")

# ---------------------------------------------------------------------------
# RESILIENT DUAL-ENGINE AI STREAMER (GEMINI -> OPENROUTER FALLBACK)
# ---------------------------------------------------------------------------
PRIMARY_GEMINI = "gemini-2.0-flash"
BACKUP_GEMINI = "gemini-1.5-flash"
OPENROUTER_MODELS = [
    "meta-llama/llama-3.3-70b-instruct",
    "deepseek/deepseek-chat",
    "google/gemini-2.0-flash-exp:free"
]

def stream_openrouter_api(messages_payload: list, system_instruction: str):
    api_key = OPENROUTER_API_KEY or os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        yield "*(System Notice: Gemini API failed and no OpenRouter API Key was found in secrets.toml)*"
        return

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://wondoo.in",
        "X-Title": "Wondoo Alpine Studio",
    }

    formatted_msgs = [{"role": "system", "content": system_instruction}]
    for m in messages_payload:
        formatted_msgs.append({"role": m["role"], "content": m["content"]})

    for model_name in OPENROUTER_MODELS:
        payload = {
            "model": model_name,
            "messages": formatted_msgs,
            "stream": True,
            "temperature": 0.35,
        }
        try:
            res = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                stream=True,
                timeout=12
            )
            if res.status_code == 200:
                for line in res.iter_lines():
                    if line:
                        decoded = line.decode("utf-8").strip()
                        if decoded.startswith("data: ") and decoded != "data: [DONE]":
                            chunk = json.loads(decoded[6:])
                            token = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                            if token:
                                yield token
                return
        except Exception:
            continue

    yield "I encountered a connectivity glitch contacting both Gemini and OpenRouter. Please try again shortly."

def stream_ai_conversation_with_fallback(gemini_client, conversation_messages: list, system_instruction: str):
    if gemini_client:
        contents = [
            types.Content(
                role="user" if m["role"] == "user" else "model",
                parts=[types.Part.from_text(text=m["content"])]
            )
            for m in conversation_messages
        ]
        for g_model in [PRIMARY_GEMINI, BACKUP_GEMINI]:
            try:
                stream = gemini_client.models.generate_content_stream(
                    model=g_model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.35,
                        max_output_tokens=2048,
                    ),
                )
                for chunk in stream:
                    if getattr(chunk, "text", None):
                        yield chunk.text
                    elif getattr(chunk, "candidates", None) and chunk.candidates[0].content:
                        for p in chunk.candidates[0].content.parts:
                            if getattr(p, "text", None):
                                yield p.text
                return
            except Exception:
                continue

    yield from stream_openrouter_api(conversation_messages, system_instruction)

# ---------------------------------------------------------------------------
# TIME & TELEMETRY
# ---------------------------------------------------------------------------
ist_tz = timezone(timedelta(hours=5, minutes=30))
now_ist = datetime.now(ist_tz)
current_hour_ist = now_ist.hour + (now_ist.minute / 60.0)
is_day_mode = 6.0 <= current_hour_ist < 18.5
ist_time_str = now_ist.strftime("%I:%M %p")
period_label = f"☀️ {ist_time_str} IST" if is_day_mode else f"🌙 {ist_time_str} IST"

COORDINATES_DB = {
    "bagdogra": (26.6812, 88.3286),
    "siliguri": (26.7271, 88.3953),
    "njp": (26.6853, 88.4414),
    "darjeeling": (27.0410, 88.2663),
    "kalimpong": (27.0594, 88.4695),
    "gangtok": (27.3389, 88.6065),
    "pelling": (27.3174, 88.2427),
    "zuluk": (27.2519, 88.7808),
    "shillong": (25.5788, 91.8933),
    "cherrapunji": (25.2986, 91.5822),
    "dawki": (25.1884, 92.0196),
    "munnar": (10.0889, 77.0595),
    "radhanagar": (11.9840, 92.9554),
    "puri": (19.8135, 85.8312),
}

WEATHER_CODE_MAP = {
    0: ("☀️ Clear Sky", "Optimal visibility"),
    1: ("🌤️ Mainly Clear", "Mild sunshine"),
    2: ("⛅ Partly Cloudy", "Scattered clouds"),
    3: ("☁️ Overcast", "Low cloud base"),
    45: ("🌫️ Dense Fog", "Morning mist"),
    61: ("🌧️ Light Rain", "Carry light weather-gear"),
    71: ("❄️ Snow Flurries", "High altitude chill")
}

def get_coords_for_place(place_name: str, fallback=(27.0410, 88.2663)):
    norm = place_name.lower()
    for key, coords in COORDINATES_DB.items():
        if key in norm:
            return coords
    return fallback

@st.cache_data(ttl=600)
def fetch_live_weather(lat: float, lon: float) -> dict:
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,weather_code"
        res = requests.get(url, timeout=4).json()
        current = res.get("current", {})
        temp = current.get("temperature_2m", "--")
        code = current.get("weather_code", 0)
        desc, advisory = WEATHER_CODE_MAP.get(code, ("⛅ Pleasant", "Enjoyable conditions"))
        return {"temperature": f"{temp}°C", "desc": desc, "advisory": advisory}
    except Exception:
        return {"temperature": "22°C", "desc": "⛅ Pleasant", "advisory": "Pleasant conditions"}

def generate_guest_portal_url(itinerary_data: TourItinerary) -> str:
    summary = {
        "t": itinerary_data.tour_title,
        "d": itinerary_data.duration,
        "s": itinerary_data.sector,
        "days": [
            {
                "n": day.day_number,
                "r": day.route_title,
                "p": day.place_name,
                "h": getattr(day, "stay_location", None),
                "b": day.bullets
            }
            for day in itinerary_data.days
        ]
    }
    raw_bytes = json.dumps(summary).encode("utf-8")
    compressed = zlib.compress(raw_bytes)
    encoded = base64.urlsafe_b64encode(compressed).decode("ascii")
    return f"?portal=true&data={encoded}"

# ---------------------------------------------------------------------------
# DEFAULT VERIFIED STAYS CATALOG & LOADER
# ---------------------------------------------------------------------------
DEFAULT_FALLBACK_STAYS = [
    {
        "town_keys": "darjeeling, ghoom, batasia",
        "stay_name": "Windamere Heritage Hotel",
        "altitude": "6,800 ft",
        "property_type": "Colonial Heritage Hotel",
        "rating": "4.9 ★",
        "price_bracket": "2000",
        "pricing_type": "Per Head",
        "image": "https://images.unsplash.com/photo-1544735716-392fe2489ffa?auto=format&fit=crop&w=900&q=80"
    },
    {
        "town_keys": "darjeeling, ghoom, mall road",
        "stay_name": "Kanchenjunga",
        "altitude": "6,850 ft",
        "property_type": "Colonial Heritage Hotel",
        "rating": "4.9 ★",
        "price_bracket": "2500",
        "pricing_type": "Per Head",
        "image": "https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=900&q=80"
    },
    {
        "town_keys": "kaluk, rinchenpong, west sikkim",
        "stay_name": "Mandala Kanchenjunga Eco-Resort",
        "altitude": "5,600 ft",
        "property_type": "Panoramic Mountain Eco-Lodge",
        "rating": "4.8 ★",
        "price_bracket": "1500",
        "pricing_type": "Per Head",
        "image": "https://images.unsplash.com/photo-1582719478250-c89cae4dc85b?auto=format&fit=crop&w=900&q=80"
    },
    {
        "town_keys": "kalimpong, delo, durpin",
        "stay_name": "The Elgin Silver Oaks",
        "altitude": "4,100 ft",
        "property_type": "Heritage Mountain Retreat",
        "rating": "4.8 ★",
        "price_bracket": "2200",
        "pricing_type": "Per Head",
        "image": "https://images.unsplash.com/photo-1571896349842-33c89424de2d?auto=format&fit=crop&w=900&q=80"
    }
]

@st.cache_data(ttl=60)
def load_stays_raw_from_sheet(sheet_id: str) -> List[Dict[str, Any]]:
    resolved_id = CATALOG_SHEET_ID
    candidate_urls = [
        f"https://docs.google.com/spreadsheets/d/{resolved_id}/gviz/tq?tqx=out:csv&sheet=Stays",
        f"https://docs.google.com/spreadsheets/d/{resolved_id}/export?format=csv&gid=0",
    ]

    for url in candidate_urls:
        try:
            df = pd.read_csv(url, timeout=5)
            df.columns = [str(col).strip().lower().replace(" ", "_") for col in df.columns]
            if "stay_name" in df.columns and "town_keys" in df.columns:
                records = []
                for _, row in df.iterrows():
                    name = str(row.get("stay_name", "")).strip()
                    if not name or name.lower() == "nan":
                        continue
                    raw_img = row.get("image", DEFAULT_CARD_IMG)
                    clean_img = sanitize_image_url(str(raw_img), fallback_url=DEFAULT_CARD_IMG)
                    records.append({
                        "town_keys": str(row.get("town_keys", "")).lower().strip(),
                        "stay_name": name,
                        "altitude": str(row.get("altitude", "")).strip(),
                        "property_type": str(row.get("property_type", "Boutique Lodge")).strip(),
                        "rating": str(row.get("rating", "4.8 ★")).strip(),
                        "price_bracket": str(row.get("price_bracket", "2000")).strip().replace("₹", "").replace(",", ""),
                        "pricing_type": str(row.get("pricing_type", "Per Head")).strip(),
                        "image": clean_img
                    })
                if records:
                    return records
        except Exception:
            continue
    return DEFAULT_FALLBACK_STAYS

def resolve_all_stays_for_itinerary(itinerary: TourItinerary) -> dict:
    all_sheet_stays = load_stays_raw_from_sheet(CATALOG_SHEET_ID)
    stay_days = [d for d in itinerary.days if getattr(d, "stay_location", None)] or (itinerary.days[:-1] if len(itinerary.days) > 1 else itinerary.days)
    
    nights_map = {}
    for night_idx, day in enumerate(stay_days, start=1):
        target_loc = getattr(day, "stay_location", None) or day.place_name
        raw_words = re.split(r'[,/\s\-()]+', target_loc)
        clean_words = [w.strip().lower() for w in raw_words if len(w.strip()) >= 3]
        
        matched_stays = []
        for s in all_sheet_stays:
            sheet_towns = [k.strip().lower() for k in s["town_keys"].split(",") if k.strip()]
            if any(cw in st_town or st_town in cw for cw in clean_words for st_town in sheet_towns):
                if s not in matched_stays:
                    stay_entry = dict(s)
                    stay_entry["night"] = night_idx
                    stay_entry["day_num"] = day.day_number
                    stay_entry["town"] = target_loc
                    stay_entry["status"] = "CONFIRMED_AVAILABLE"
                    matched_stays.append(stay_entry)
        
        nights_map[night_idx] = {
            "day_num": day.day_number,
            "town": target_loc,
            "stays": matched_stays
        }
    return nights_map

# ---------------------------------------------------------------------------
# DEFAULT PACKAGES & ROUTES
# ---------------------------------------------------------------------------
DEFAULT_FALLBACK_ITINERARIES = [
    {
        "title": "Classic Darjeeling & Misty Kalimpong",
        "duration": "4 Days • 3 Nights",
        "sector": "West Bengal, India",
        "elevation": "2,042m - 1,250m",
        "image": "https://images.unsplash.com/photo-1544735716-392fe2489ffa?auto=format&fit=crop&w=900&q=80",
        "highlights": ["Tiger Hill 4:00 AM Sunrise", "Batasia Loop", "Tea Tasting"],
        "default_prompt": "Plan an authentic exploration of Darjeeling and Kalimpong."
    },
    {
        "title": "Sikkim Silk Route & High Alpine Lakes",
        "duration": "5 Days • 4 Nights",
        "sector": "East Sikkim, India",
        "elevation": "1,500m - 3,753m",
        "image": "https://images.unsplash.com/photo-1626621341517-bbf3d9990a23?auto=format&fit=crop&w=900&q=80",
        "highlights": ["Zuluk 32 loops", "Kupup Lake", "Nathang Valley"],
        "default_prompt": "Plan an expedition through Zuluk and Nathang Valley."
    },
    {
        "title": "Meghalaya Living Roots & Cloud Canyons",
        "duration": "5 Days • 4 Nights",
        "sector": "Meghalaya, India",
        "elevation": "1,496m - 180m",
        "image": "https://images.unsplash.com/photo-1605649487212-47bdab064df7?auto=format&fit=crop&w=900&q=80",
        "highlights": ["Double Decker Root Bridge", "Dawki River", "Nohkalikai Falls"],
        "default_prompt": "Plan an authentic Meghalaya adventure."
    }
]

DEFAULT_FALLBACK_PACKAGES = [
    {
        "title": "East Sikkim Silk Route Homestay Explorer",
        "duration": "5 Days • 4 Nights",
        "price_per_head": "₹14,950",
        "stay_type": "Authentic Mountain View Homestays",
        "transit": "Dedicated Bolero / Scorpio 4x4",
        "meals": "AP (All Meals)",
        "features": ["Zuluk & Nathang loops", "Inner Line Permits Included", "Home-cooked meals", "Siliguri/NJP transit"]
    },
    {
        "title": "Darjeeling & Kalimpong Alpine Retreat",
        "duration": "4 Days • 3 Nights",
        "price_per_head": "₹12,499",
        "stay_type": "Heritage Tea Estate + Boutique View Lodge",
        "transit": "Dedicated Innova / Scorpio",
        "meals": "MAP (Breakfast + Dinner)",
        "features": ["Private pickup from IXB", "Curated view rooms", "Tiger Hill sunrise passes arranged"]
    }
]

@st.cache_data(ttl=0, show_spinner=False)
def load_itineraries_from_sheet(sheet_id: str) -> List[Dict[str, Any]]:
    """Instantaneous loader parsing exact headers: title, duration, sector, elevation, image, highlights, default_prompt, predefined_plan_json"""
    resolved_id = CATALOG_SHEET_ID or sheet_id
    import time
    cache_buster = int(time.time())
    candidate_urls = [
        f"https://docs.google.com/spreadsheets/d/{resolved_id}/gviz/tq?tqx=out:csv&sheet=Itineraries&cb={cache_buster}",
        f"https://docs.google.com/spreadsheets/d/{resolved_id}/export?format=csv&gid=0&cb={cache_buster}",
    ]

    for url in candidate_urls:
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200 and resp.text:
                df = pd.read_csv(StringIO(resp.text))
                df.columns = [str(col).strip().lower().replace(" ", "_") for col in df.columns]
                
                if "title" in df.columns:
                    itineraries = []
                    for _, row in df.iterrows():
                        title = str(row.get("title", "")).strip()
                        if not title or title.lower() == "nan":
                            continue

                        raw_img = (
                            row.get("image") or 
                            row.get("image_url") or 
                            row.get("photo") or 
                            row.get("cover_image") or 
                            ""
                        )
                        clean_img = sanitize_image_url(str(raw_img), fallback_url=DEFAULT_CARD_IMG)

                        raw_highlights = str(row.get("highlights", "")).strip()
                        highlights_list = [h.strip() for h in raw_highlights.split(";") if h.strip() and h.lower() != "nan"]

                        itineraries.append({
                            "title": title,
                            "duration": str(row.get("duration", "4 Days • 3 Nights")).strip(),
                            "sector": str(row.get("sector", "Himalayan Region")).strip(),
                            "elevation": str(row.get("elevation", "Scenic Elevation")).strip(),
                            "image": clean_img,
                            "highlights": highlights_list,
                            "default_prompt": str(row.get("default_prompt", f"Plan an authentic {title} tour.")).strip(),
                            "predefined_plan_json": row.get("predefined_plan_json", None)
                        })
                    if itineraries:
                        return itineraries
        except Exception:
            continue

    return DEFAULT_FALLBACK_ITINERARIES

# Pre-load instantly into session state for zero-wait UI response
if "cached_live_itineraries" not in st.session_state:
    st.session_state.cached_live_itineraries = load_itineraries_from_sheet(CATALOG_SHEET_ID)

LIVE_ITINERARIES = st.session_state.cached_live_itineraries
LIVE_PACKAGES = DEFAULT_FALLBACK_PACKAGES

def get_highlights_for_title(title: str) -> List[str]:
    """Dynamically looks up highlights for a given itinerary title without mutating Pydantic models."""
    norm = title.lower().strip()
    for itin in LIVE_ITINERARIES:
        if itin["title"].lower().strip() == norm:
            return itin.get("highlights", [])
    for itin in LIVE_ITINERARIES:
        if norm in itin["title"].lower() or itin["title"].lower() in norm:
            return itin.get("highlights", [])
    return ["Scenic Lookout", "Mountain Pass", "Local Culture"]

def get_or_generate_itinerary(itin_dict: dict, requested_days: int = None) -> TourItinerary:
    """Builds TourItinerary from sheet data, parsing predefined_plan_json if available, or generating structured days."""
    predefined_json = itin_dict.get('predefined_plan_json')
    if predefined_json and pd.notna(predefined_json):
        try:
            if isinstance(predefined_json, str) and predefined_json.strip():
                data_dict = json.loads(predefined_json.strip())
                if isinstance(data_dict, dict) and "days" in data_dict:
                    return TourItinerary(
                        tour_title=itin_dict.get('title', data_dict.get('tour_title', 'Expedition')),
                        duration=itin_dict.get('duration', data_dict.get('duration', '4 Days')),
                        sector=itin_dict.get('sector', data_dict.get('sector', 'Himalayan Region')),
                        elevation=itin_dict.get('elevation', data_dict.get('elevation', 'Scenic Elevation')),
                        days=data_dict['days']
                    )
        except Exception as e:
            print(f"Error parsing predefined_plan_json for {itin_dict.get('title')}: {e}")

    # Fallback to dynamic day generation using highlights if no custom JSON is provided
    duration_str = itin_dict.get('duration', '4 Days')
    num_days_match = re.search(r'(\d+)', duration_str)
    total_days = int(num_days_match.group(1)) if num_days_match else 4
    
    sector_name = itin_dict.get('sector', 'Himalayan Region')
    highlights = itin_dict.get('highlights', ['Scenic Lookout', 'Mountain Pass', 'Local Culture'])
    
    days_list = []
    for i in range(1, total_days + 1):
        h_text = highlights[(i - 1) % len(highlights)] if highlights else "Scenic Exploration"
        day_dict = {
            "day_number": i,
            "route_title": f"Day {i}: {h_text} & Pacing",
            "place_name": sector_name.split(',')[0],
            "stay_location": sector_name.split(',')[0],
            "bullets": [
                f"Morning exploration of {h_text}.",
                "Transiting through scenic mountain roads.",
                "Evening check-in at verified boutique stay."
            ]
        }
        days_list.append(day_dict)

    return TourItinerary(
        tour_title=itin_dict['title'],
        duration=itin_dict['duration'],
        sector=itin_dict['sector'],
        elevation=itin_dict.get('elevation', 'Scenic Elevation'),
        days=days_list
    )

def get_route_from_sheet_or_ai(query: str, requested_days: int = None) -> TourItinerary:
    norm_query = query.lower().strip()
    sheet_titles = [itin["title"] for itin in LIVE_ITINERARIES]
    title_to_itin = {itin["title"].lower(): itin for itin in LIVE_ITINERARIES}
    
    matched_titles = difflib.get_close_matches(norm_query, [t.lower() for t in sheet_titles], n=1, cutoff=0.35)
    
    if matched_titles:
        matched_itin = title_to_itin.get(matched_titles[0])
        if matched_itin:
            if requested_days:
                sheet_duration_match = re.search(r'(\d+)', matched_itin['duration'])
                sheet_days = int(sheet_duration_match.group(1)) if sheet_duration_match else 0
                if sheet_days and requested_days != sheet_days:
                    prompt = f"Create a detailed, authentic structured tour itinerary for: '{matched_itin['title']}' with a strict duration of exactly {requested_days} Days."
                    return generate_itinerary_content(prompt)
            return get_or_generate_itinerary(matched_itin)
            
    clean_terms = [w.strip() for w in re.split(r'[,/\s\-()]+', norm_query) if len(w.strip()) >= 3]
    best_match = None
    max_matches = 0
    for itin in LIVE_ITINERARIES:
        t_norm = (itin["title"] + " " + itin["sector"] + " " + " ".join(itin.get("highlights", []))).lower()
        matches = sum(1 for term in clean_terms if term in t_norm)
        if matches > max_matches:
            max_matches = matches
            best_match = itin
            
    if best_match and max_matches > 0:
        if not requested_days:
            return get_or_generate_itinerary(best_match)

    prompt = f"Create a detailed, authentic structured tour itinerary for the request: '{query}'. Include daily routes, elevations, and scenic highlights."
    return generate_itinerary_content(prompt)

# ---------------------------------------------------------------------------
# CENTRALIZED DYNAMIC BUDGET RECALCULATION
# ---------------------------------------------------------------------------
def compute_transparent_budget(data: TourItinerary) -> dict:
    num_heads = int(st.session_state.get("num_travelers", 4))
    num_rooms = max(1, (num_heads + 1) // 2)
    total_days = len(data.days)
    
    cab_choice = st.session_state.get("selected_cab", "Include Dedicated Cab (Innova/Scorpio)")
    if "Innova" in cab_choice:
        cab_daily_rate = 3800
    elif "Bolero" in cab_choice:
        cab_daily_rate = 4200
    else:
        cab_daily_rate = 0
    total_cab_cost = cab_daily_rate * total_days

    tier_supplement = ROOM_TIER_PREMIUM_MAP.get(st.session_state.get("selected_room_tier", "Standard Room"), 0)
    nights_data = resolve_all_stays_for_itinerary(data)
    
    if not st.session_state.get("selected_stays"):
        st.session_state.selected_stays = {}
        for night_idx, n_info in nights_data.items():
            if n_info["stays"]:
                st.session_state.selected_stays[night_idx] = n_info["stays"][0]
            else:
                st.session_state.selected_stays[night_idx] = {
                    "stay_name": f"Curated Stay in {n_info['town']}",
                    "price_bracket": "2000",
                    "pricing_type": "Per Head"
                }

    total_stays_cost = 0
    for night_idx in sorted(st.session_state.selected_stays.keys()):
        stay = st.session_state.selected_stays[night_idx]
        try:
            raw_p = str(stay.get("price_bracket", 2000)).replace("₹", "").replace(",", "").strip()
            base_price = float(raw_p)
        except Exception:
            base_price = 2000.0

        p_type = str(stay.get("pricing_type", "Per Head")).strip().lower()
        if "room" in p_type:
            night_fare = (base_price + tier_supplement) * num_rooms
        else:
            night_fare = (base_price + (tier_supplement / 2.0)) * num_heads
        
        total_stays_cost += night_fare

    grand_total = total_cab_cost + total_stays_cost
    per_head = grand_total / max(1, num_heads)

    return {
        "grand_total": grand_total,
        "per_head": per_head,
        "num_heads": num_heads,
        "num_rooms": num_rooms,
        "cab_cost": total_cab_cost,
        "stays_cost": total_stays_cost
    }

# ---------------------------------------------------------------------------
# WHATSAPP RESERVATION RECEIPT ENCODER
# ---------------------------------------------------------------------------
def format_whatsapp_reservation_receipt(info: dict) -> str:
    message = (
        f"🏔️ *WONDOO ALPINE STUDIO — RESERVATION RECEIPT*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏷️ *Booking Ref*: #{info['booking_id']}\n"
        f"👤 *Lead Traveler*: {info['lead_name']}\n"
        f"📱 *Phone*: {info['phone']}\n"
        f"📅 *Departure*: {info['departure_date']}\n"
        f"🗺️ *Expedition*: {info['circuit']} ({info['duration']})\n"
        f"👥 *Travelers*: {info['heads']} Adults | {info['rooms']} Rooms\n"
        f"🚗 *Vehicle*: {info['vehicle'].split('(')[0].strip()}\n"
        f"🏡 *Room Category*: {info.get('room_tier', 'Standard Room')}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 *FINANCIAL SUMMARY*\n"
        f"• Grand Package Fare: ₹{info['grand_total']:,.0f}\n"
        f"• 25% Advance Token Paid: ₹{info['advance_paid']:,.0f}\n"
        f"• Balance Due on Arrival: ₹{info['balance_due']:,.0f}\n"
        f"• Payment Ref / Tx: {info['transaction_utr']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ *Status*: Confirmed & Locked"
    )
    return urllib.parse.quote(message)

# ---------------------------------------------------------------------------
# BOOKING MODAL
# ---------------------------------------------------------------------------
@st.dialog("Expedition Reservation & Token Lock", width="large")
def open_package_booking_dialog(itinerary: TourItinerary, matched_stays: list, selected_room_tier: str = "Standard Room"):
    st.markdown(
        f"""<div style="margin-bottom:12px;">
<div style="font-family:'Playfair Display', serif; font-size:1.35rem; font-weight:700; color:#1A3828;">
🌿 {itinerary.tour_title}
</div>
<div style="font-size:13px; color:#557461; font-weight:500;">
{itinerary.duration} • {itinerary.sector} • Handpicked Verified Stays
</div>
</div>""",
        unsafe_allow_html=True
    )

    tab_specs, tab_payment = st.tabs(["1. Traveler & Circuit Specs", "2. Fare Summary & Checkout"])

    with tab_specs:
        col_c1, col_c2 = st.columns(2, gap="small")
        with col_c1:
            lead_name = st.text_input("Lead Traveler Name *", value=st.session_state.user["name"] if st.session_state.get("user") else "", placeholder="e.g. Joydeep Das")
            lead_phone = st.text_input("WhatsApp Number *", value=st.session_state.user["phone"] if st.session_state.get("user") and "phone" in st.session_state.user else "", placeholder="10-digit mobile number")
        with col_c2:
            lead_email = st.text_input("Email ID (Optional)", placeholder="for voucher delivery")
            travel_date = st.date_input("Target Departure Date", min_value=datetime.now().date() + timedelta(days=1))

        col_p1, col_p2, col_p3 = st.columns(3, gap="small")
        with col_p1:
            heads = st.number_input("Adult Travelers", min_value=1, max_value=24, value=int(st.session_state.get("num_travelers", 4)), step=1)
        with col_p2:
            rooms = st.number_input("Rooms Required", min_value=1, max_value=12, value=max(1, (heads + 1) // 2), step=1)
        with col_p3:
            cab_default_idx = 0 if "Innova" in st.session_state.selected_cab else (1 if "Bolero" in st.session_state.selected_cab else 2)
            cab_choice = st.selectbox(
                "Dedicated Transit Vehicle",
                ["Include Dedicated Cab (Innova/Scorpio)", "Include Bolero 4x4", "Self Transit / Exclude Vehicle"],
                index=cab_default_idx
            )

        col_tier1, col_tier2 = st.columns([2, 1.5], gap="small")
        with col_tier1:
            room_tier_list = list(ROOM_TIER_PREMIUM_MAP.keys())
            current_saved_tier = st.session_state.get("selected_room_tier", "Standard Room")
            cur_tier_idx = room_tier_list.index(current_saved_tier) if current_saved_tier in room_tier_list else 0
            chosen_tier = st.selectbox("Room Category Tier", room_tier_list, index=cur_tier_idx)
        with col_tier2:
            coupon_input = st.text_input("Promotional Code", placeholder="e.g. ALPINE10", key="dlg_coupon_code")
            apply_cpn = st.button("Apply Code", key="btn_dlg_apply_cpn", use_container_width=True)

        if apply_cpn and coupon_input.strip():
            user_id = lead_phone.strip() or "guest"
            valid, discount, msg = validate_coupon_for_user(coupon_input.strip().upper(), user_id)
            if valid:
                st.session_state.applied_coupon = {"code": coupon_input.strip().upper(), "discount": discount}
                st.success(f"Coupon applied: {msg}")
            else:
                st.session_state.applied_coupon = None
                st.error(msg)

    calc_cab_mode = "Include Dedicated Cab" if "Include Dedicated" in cab_choice else ("Include Bolero 4x4" if "Bolero" in cab_choice else "Self Transit")
    
    room_supplement = ROOM_TIER_PREMIUM_MAP.get(chosen_tier, 0)
    adjusted_stays_for_calc = []
    for s in matched_stays:
        s_copy = dict(s)
        try:
            base_p = float(str(s_copy.get("price_bracket", 2000)).replace("₹", "").replace(",", "").strip())
        except Exception:
            base_p = 2000.0
        s_copy["price_bracket"] = str(base_p + room_supplement)
        adjusted_stays_for_calc.append(s_copy)

    quotation = calculate_dynamic_sheet_quotation(
        matched_stays=adjusted_stays_for_calc,
        total_days=len(itinerary.days),
        num_heads=heads,
        num_rooms=rooms,
        cab_option=calc_cab_mode
    )

    base_total = quotation.get("grand_total", len(itinerary.days) * 3500 * heads)
    discount_amount = 0
    if st.session_state.get("applied_coupon"):
        discount_rate = st.session_state.applied_coupon.get("discount", 0)
        discount_amount = (base_total * discount_rate) if discount_rate < 1.0 else discount_rate

    final_grand_total = max(0, base_total - discount_amount)
    advance_token = round(final_grand_total * 0.25)
    balance_payable = final_grand_total - advance_token
    booking_ref = f"WAN-{uuid.uuid4().hex[:6].upper()}"

    with tab_payment:
        st.markdown(
            f"""<div style="background:#F4F7F4; border:1.5px solid rgba(26,56,40,0.1); border-radius:18px; padding:16px 20px; margin-bottom:14px;">
<div style="display:flex; justify-content:space-between; margin-bottom:6px; font-size:14px;">
  <span>Base Package ({heads} Travelers • {rooms} Rooms):</span>
  <b>₹{base_total:,.0f}</b>
</div>
<div style="display:flex; justify-content:space-between; margin-bottom:6px; font-size:13px; color:#557461;">
  <span>Room Category:</span>
  <span><b>{chosen_tier.split('(')[0].strip()}</b></span>
</div>
<div style="display:flex; justify-content:space-between; margin-bottom:6px; font-size:13px; color:#557461;">
  <span>Transit Vehicle:</span>
  <span>{cab_choice.split('(')[0].strip()}</span>
</div>
<hr style="border-color: rgba(26,56,40,0.1); margin: 8px 0;">
<div style="display:flex; justify-content:space-between; margin-bottom:4px; font-size:16px; font-weight:800; color:#1A3828;">
  <span>Grand Total:</span>
  <span>₹{final_grand_total:,.0f}</span>
</div>
<div style="display:flex; justify-content:space-between; font-size:13.5px; color:#244E37; font-weight:700;">
  <span>25% Advance Lock Token:</span>
  <span>₹{advance_token:,.0f}</span>
</div>
<div style="display:flex; justify-content:space-between; font-size:12px; color:#6B8073;">
  <span>Balance on Arrival:</span>
  <span>₹{balance_payable:,.0f}</span>
</div>
</div>""",
            unsafe_allow_html=True
        )

        clean_name = (lead_name or "Traveler").replace('"', '')
        clean_email = (lead_email or "guest@wondoo.in").replace('"', '')
        clean_phone = (lead_phone or "9800000000").replace('"', '')

        checkout_html = """<!DOCTYPE html>
<html>
<head>
<script src="https://checkout.razorpay.com/v1/checkout.js"></script>
<style>
  body { margin:0; padding:0; background:transparent; font-family:-apple-system, sans-serif; }
  .rzp-btn {
    width:100%;
    background:#244E37;
    color:#FFFFFF;
    border:none;
    padding:13px;
    font-size:14px;
    font-weight:700;
    border-radius:9999px;
    cursor:pointer;
    box-shadow:0 4px 12px rgba(36,78,55,0.2);
    display:flex;
    align-items:center;
    justify-content:center;
    gap:8px;
  }
  .rzp-btn:hover { background:#1A3828; }
</style>
</head>
<body>
<button class="rzp-btn" id="rzp-button">💳 Launch Payment Gateway (₹AMOUNT_DISPLAY)</button>
<script>
var options = {
    "key": "KEY_ID_PLACEHOLDER",
    "amount": "AMOUNT_PLACEHOLDER",
    "currency": "INR",
    "name": "Wondoo Alpine Studio",
    "description": "25% Advance Token",
    "image": "LOGO_PLACEHOLDER",
    "handler": function (response){
        const parentUrl = new URL(window.parent.location.href);
        parentUrl.searchParams.set('paid_tx', response.razorpay_payment_id);
        parentUrl.searchParams.set('book_ref', 'REF_PLACEHOLDER');
        window.parent.location.assign(parentUrl.href);
    },
    "prefill": {
        "name": "NAME_PLACEHOLDER",
        "email": "EMAIL_PLACEHOLDER",
        "contact": "PHONE_PLACEHOLDER"
    },
    "theme": {
        "color": "#244E37"
    }
};
document.getElementById('rzp-button').onclick = function(e){
    try {
        var rzp = new Razorpay(options);
        rzp.open();
    } catch (err) {
        alert("Payment initialization error: " + err.message);
    }
    e.preventDefault();
};
</script>
</body>
</html>"""

        checkout_html = checkout_html.replace("AMOUNT_DISPLAY", f"{advance_token:,.0f}")
        checkout_html = checkout_html.replace("KEY_ID_PLACEHOLDER", RAZORPAY_KEY_ID)
        checkout_html = checkout_html.replace("AMOUNT_PLACEHOLDER", str(int(advance_token * 100)))
        checkout_html = checkout_html.replace("LOGO_PLACEHOLDER", APP_LOGO_SRC)
        checkout_html = checkout_html.replace("REF_PLACEHOLDER", booking_ref)
        checkout_html = checkout_html.replace("NAME_PLACEHOLDER", clean_name)
        checkout_html = checkout_html.replace("EMAIL_PLACEHOLDER", clean_email)
        checkout_html = checkout_html.replace("PHONE_PLACEHOLDER", clean_phone)

        components.html(checkout_html, height=60)
        st.caption("🔒 Secured with Razorpay 256-bit encryption. Supports PhonePe, GPay, Cards & NetBanking.")

        with st.expander("Or Pay manually via Static UPI QR"):
            upi_pay_url = generate_upi_qr_url(vpa=UPI_VPA, payee_name=UPI_PAYEE_NAME, amount=advance_token, transaction_ref=booking_ref)
            col_qr, col_tx = st.columns([1, 1.4], gap="medium")
            with col_qr:
                st.image(upi_pay_url, caption="Scan with any UPI App", width=140)
            with col_tx:
                manual_utr = st.text_input("12-Digit UPI Reference / UTR Number", placeholder="e.g. 423984029384", key="manual_utr_input")
                if st.button("Confirm via UPI Reference ➔", use_container_width=True):
                    if not lead_name.strip() or not lead_phone.strip():
                        st.error("Please enter traveler name and WhatsApp contact number.")
                    elif not manual_utr.strip() or len(manual_utr.strip()) < 8:
                        st.error("Please provide a valid UPI Bank Reference / UTR Number.")
                    else:
                        booking_payload = {
                            "booking_id": booking_ref,
                            "lead_name": lead_name.strip(),
                            "phone": lead_phone.strip(),
                            "email": lead_email.strip(),
                            "circuit": itinerary.tour_title,
                            "duration": itinerary.duration,
                            "departure_date": str(travel_date),
                            "heads": int(heads),
                            "rooms": int(rooms),
                            "vehicle": cab_choice,
                            "room_tier": chosen_tier,
                            "base_total": float(base_total),
                            "discount": float(discount_amount),
                            "grand_total": float(final_grand_total),
                            "advance_paid": float(advance_token),
                            "balance_due": float(balance_payable),
                            "coupon_applied": st.session_state.applied_coupon["code"] if st.session_state.get("applied_coupon") else "NONE",
                            "transaction_utr": manual_utr.strip(),
                            "status": "CONFIRMED_LOCKED",
                            "permit_status": "PROCESSING",
                            "timestamp": datetime.now(ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")
                        }
                        st.session_state.booking_history.insert(0, booking_payload)
                        st.session_state.booking_confirmed = booking_payload
                        st.rerun()

# ---------------------------------------------------------------------------
# GLOBAL ACTION & PAYMENT REDIRECT LISTENER
# ---------------------------------------------------------------------------
if "action" in st.query_params:
    act = st.query_params["action"]
    st.query_params.clear()
    if act == "ai":
        st.session_state.active_view = "ai_concierge"
        st.rerun()
    elif act == "explore":
        st.session_state.active_view = "explore"
        st.rerun()
    elif act == "route":
        st.session_state.active_view = "smart_route"
        st.rerun()
    elif act == "budget":
        st.session_state.active_view = "budget_plan"
        st.rerun()
    elif act == "userspace":
        st.session_state.active_view = "user_space"
        st.rerun()

if "paid_tx" in st.query_params and "book_ref" in st.query_params:
    tx_id = st.query_params["paid_tx"]
    b_ref = st.query_params["book_ref"]
    st.query_params.clear()

    active_circuit_name = st.session_state.itinerary_data.tour_title if st.session_state.itinerary_data else "Himalayan Expedition"
    active_circuit_dur = st.session_state.itinerary_data.duration if st.session_state.itinerary_data else "4 Days"
    lead_n = st.session_state.user["name"] if st.session_state.user else "Valued Traveler"
    lead_p = st.session_state.user["phone"] if st.session_state.user and "phone" in st.session_state.user else "9800000000"

    auto_payload = {
        "booking_id": b_ref,
        "lead_name": lead_n,
        "phone": lead_p,
        "email": "traveler@wondoo.in",
        "circuit": active_circuit_name,
        "duration": active_circuit_dur,
        "departure_date": str(datetime.now().date() + timedelta(days=14)),
        "heads": int(st.session_state.num_travelers),
        "rooms": max(1, (int(st.session_state.num_travelers) + 1) // 2),
        "vehicle": st.session_state.selected_cab,
        "room_tier": st.session_state.selected_room_tier,
        "base_total": 45000.0,
        "discount": 0.0,
        "grand_total": 45000.0,
        "advance_paid": 11250.0,
        "balance_due": 33750.0,
        "coupon_applied": "NONE",
        "transaction_utr": f"RZP-{tx_id}",
        "status": "CONFIRMED_LOCKED",
        "permit_status": "PROCESSING",
        "timestamp": datetime.now(ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")
    }
    st.session_state.booking_history.insert(0, auto_payload)
    st.session_state.booking_confirmed = auto_payload
    st.rerun()

# ---------------------------------------------------------------------------
# RESPONSIVE CUSTOM CSS & VISIBILITY REPAIRS
# ---------------------------------------------------------------------------
st.markdown(
    """<style>
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,500;0,600;0,700;1,500;1,600&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

html, body, [data-testid="stAppViewContainer"], section.main, .stApp {
  background-color: #F4F7F4 !important;
  font-family: 'Plus Jakarta Sans', sans-serif !important;
  color: #1A3828 !important;
}

header[data-testid="stHeader"] {
  display: none !important;
  height: 0 !important;
}

.block-container {
  max-width: 1240px !important;
  padding-top: 0.8rem !important;
  padding-bottom: 3.5rem !important;
  padding-left: 1.2rem !important;
  padding-right: 1.2rem !important;
}

/* --------------------------------------------------------------------------
   LAYOUT A: UNIFIED TOP CAPSULE APP BAR (MOBILE OVERLAP FIXED)
   -------------------------------------------------------------------------- */
.unified-top-bar {
  display: flex !important;
  align-items: center !important;
  justify-content: space-between !important;
  background: #FFFFFF !important;
  border: 1.5px solid rgba(26, 56, 40, 0.1) !important;
  border-radius: 24px !important;
  padding: 8px 12px 8px 14px !important;
  box-shadow: 0 4px 20px rgba(26, 56, 40, 0.05) !important;
  margin-bottom: 18px !important;
  width: 100% !important;
  box-sizing: border-box !important;
  gap: 8px !important;
}

.brand-section {
  display: flex !important;
  align-items: center !important;
  gap: 10px !important;
  min-width: 0 !important;
  flex: 1 1 auto !important;
}

.brand-logo {
  width: 32px !important;
  height: 32px !important;
  border-radius: 8px !important;
  object-fit: cover !important;
  flex-shrink: 0 !important;
}

.brand-text {
  display: flex !important;
  flex-direction: column !important;
  min-width: 0 !important;
}

.brand-title {
  font-family: 'Playfair Display', serif !important;
  font-size: 1.15rem !important;
  font-weight: 700 !important;
  color: #1A3828 !important;
  line-height: 1.15 !important;
  white-space: nowrap !important;
}

.brand-title span {
  font-style: italic !important;
  color: #376E4B !important;
}

.brand-sub {
  font-size: 10.5px !important;
  color: #557461 !important;
  font-weight: 500 !important;
  white-space: nowrap !important;
  overflow: hidden !important;
  text-overflow: ellipsis !important;
}

.actions-section {
  display: flex !important;
  align-items: center !important;
  gap: 6px !important;
  flex-shrink: 0 !important;
}

.telemetry-tag {
  font-size: 11px !important;
  font-weight: 700 !important;
  color: #376E4B !important;
  background: #F4F7F4 !important;
  padding: 5px 10px !important;
  border-radius: 9999px !important;
  border: 1.5px solid rgba(26, 56, 40, 0.08) !important;
  white-space: nowrap !important;
}

.myspace-pill-btn {
  display: inline-flex !important;
  align-items: center !important;
  gap: 4px !important;
  background: #244E37 !important;
  color: #FFFFFF !important;
  font-size: 11.5px !important;
  font-weight: 700 !important;
  padding: 6px 12px !important;
  border-radius: 9999px !important;
  text-decoration: none !important;
  box-shadow: 0 3px 10px rgba(36, 78, 55, 0.2) !important;
  white-space: nowrap !important;
}

.myspace-pill-btn:hover {
  background: #1A3828 !important;
}

@media (max-width: 768px) {
  .brand-sub {
    display: none !important;
  }
  .unified-top-bar {
    padding: 8px 10px !important;
  }
  .telemetry-tag {
    display: none !important;
  }
  .brand-title {
    font-size: 1.05rem !important;
  }
}

/* HERO SCENE */
.hero-illustrated-scene {
  position: relative;
  border-radius: 28px;
  overflow: hidden;
  background-position: center center !important;
  background-repeat: no-repeat !important;
  background-size: cover !important;
  padding: 30px 36px 32px 36px;
  margin-bottom: 18px;
  box-shadow: 0 10px 30px rgba(26, 56, 40, 0.05);
  border: 1.5px solid rgba(255, 255, 255, 0.8);
}

.hero-scene-content {
  position: relative;
  z-index: 2;
  max-width: 620px;
}

.hero-headline-serif {
  font-family: 'Playfair Display', Georgia, serif;
  font-size: 2.75rem;
  line-height: 1.12;
  font-weight: 700;
  color: #1A3828;
  letter-spacing: -0.6px;
  margin-bottom: 6px;
}

.hero-headline-serif span {
  color: #2E5E3F;
}

.hero-subline-sans {
  font-size: 14px;
  color: #244737;
  font-weight: 600;
  line-height: 1.45;
  margin-bottom: 0px;
}

/* --------------------------------------------------------------------------
   STRICT FORM PILL STYLING WITH TYPING ANIMATION OVERLAY
   -------------------------------------------------------------------------- */
div[data-testid="stForm"] {
  border: 1.5px solid rgba(26, 56, 40, 0.16) !important;
  border-radius: 9999px !important;
  background: #FFFFFF !important;
  padding: 0 8px 0 16px !important;
  box-shadow: 0 8px 24px rgba(26, 56, 40, 0.08) !important;
  max-width: 820px !important;
  margin: 0 auto 20px auto !important;
  height: 54px !important;
  min-height: 54px !important;
  max-height: 54px !important;
  box-sizing: border-box !important;
  overflow: hidden !important;
  display: flex !important;
  align-items: center !important;
  position: relative !important;
}

div[data-testid="stForm"]:focus-within {
  border-color: #244E37 !important;
  box-shadow: 0 12px 34px rgba(36, 78, 55, 0.16) !important;
}

div[data-testid="stForm"] div[data-testid="stVerticalBlock"],
div[data-testid="stForm"] [data-testid="stVerticalBlock"] {
  display: flex !important;
  flex-direction: row !important;
  flex-wrap: nowrap !important;
  align-items: center !important;
  justify-content: space-between !important;
  width: 100% !important;
  height: 100% !important;
  margin: 0 !important;
  padding: 0 !important;
  gap: 8px !important;
}

div[data-testid="stForm"] [data-testid="stVerticalBlock"] > div:first-child {
  flex: 1 1 auto !important;
  min-width: 0 !important;
  margin: 0 !important;
  padding: 0 !important;
}

div[data-testid="stForm"] [data-testid="stVerticalBlock"] > div:last-child {
  flex: 0 0 38px !important;
  width: 38px !important;
  min-width: 38px !important;
  max-width: 38px !important;
  height: 38px !important;
  margin: 0 !important;
  padding: 0 !important;
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
}

div[data-testid="stForm"] div[data-testid="stTextInput"] {
  width: 100% !important;
  margin: 0 !important;
  padding: 0 !important;
}

div[data-testid="stForm"] div[data-testid="stTextInput"] > div > div {
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
  padding: 0 !important;
}

div[data-testid="stForm"] input[aria-label="home_search_bar_input"] {
  color: #1A3828 !important;
  font-family: 'Plus Jakarta Sans', sans-serif !important;
  font-size: 14.5px !important;
  font-weight: 600 !important;
  background-color: transparent !important;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='18' height='18' viewBox='0 0 24 24' fill='none' stroke='%23376E4B' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='11' cy='11' r='8'%3E%3C/circle%3E%3Cline x1='21' y1='21' x2='16.65' y2='16.65'%3E%3C/line%3E%3C/svg%3E") !important;
  background-repeat: no-repeat !important;
  background-position: 2px center !important;
  background-size: 18px 18px !important;
  padding: 0 10px 0 32px !important;
  height: 44px !important;
  line-height: 44px !important;
  border: none !important;
  outline: none !important;
  box-sizing: border-box !important;
  width: 100% !important;
  position: relative !important;
  z-index: 2 !important;
}

div[data-testid="stForm"] input::placeholder {
  color: transparent !important;
}

div[data-testid="stForm"] button {
  background-color: #244E37 !important;
  color: #FFFFFF !important;
  border-radius: 50% !important;
  width: 38px !important;
  height: 38px !important;
  min-width: 38px !important;
  max-width: 38px !important;
  padding: 0 !important;
  margin: 0 !important;
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
  font-size: 16px !important;
  font-weight: 700 !important;
  border: none !important;
  box-shadow: 0 3px 10px rgba(36, 78, 55, 0.25) !important;
  cursor: pointer !important;
  z-index: 2 !important;
}

div[data-testid="stForm"] button:hover {
  background-color: #1A3828 !important;
  transform: scale(1.04) !important;
}

@keyframes cursor-blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

.typing-cursor-container {
  font-family: 'Plus Jakarta Sans', sans-serif !important;
  font-size: 14.5px !important;
  font-weight: 600 !important;
  color: #4A6E57 !important;
  display: flex !important;
  align-items: center !important;
  position: absolute !important;
  pointer-events: none !important;
  left: 38px !important;
  top: 50% !important;
  transform: translateY(-50%) !important;
  z-index: 1 !important;
}

.cursor-bar {
  display: inline-block !important;
  width: 2px !important;
  height: 16px !important;
  background-color: #244E37 !important;
  margin-left: 2px !important;
  animation: cursor-blink 0.8s infinite !important;
}

/* QUICK ACTION TILES */
.quick-action-grid-wrap {
  display: grid !important;
  grid-template-columns: repeat(4, 1fr) !important;
  gap: 16px !important;
  width: 100% !important;
  margin-top: 8px !important;
}

.square-action-card-tile {
  background: #FFFFFF !important;
  border: 1.5px solid rgba(26, 56, 40, 0.08) !important;
  border-radius: 24px !important;
  aspect-ratio: 1 / 1 !important;
  display: flex !important;
  flex-direction: column !important;
  align-items: center !important;
  justify-content: center !important;
  padding: 18px 12px !important;
  box-shadow: 0 4px 18px rgba(26, 56, 40, 0.04) !important;
  text-decoration: none !important;
  color: #1A3828 !important;
  transition: transform 0.18s ease, box-shadow 0.18s ease !important;
  cursor: pointer !important;
  box-sizing: border-box !important;
}

.square-action-card-tile:hover {
  transform: translateY(-4px) !important;
  box-shadow: 0 12px 28px rgba(26, 56, 40, 0.1) !important;
  border-color: rgba(36, 78, 55, 0.28) !important;
}

.square-card-icon-bubble {
  width: 54px !important;
  height: 54px !important;
  border-radius: 18px !important;
  background: #EBF3EC !important;
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
  margin-bottom: 12px !important;
}

.square-card-icon-bubble img {
  width: 32px !important;
  height: 32px !important;
  object-fit: contain !important;
}

.square-card-title-text {
  font-family: 'Plus Jakarta Sans', sans-serif !important;
  font-size: 14.5px !important;
  font-weight: 700 !important;
  color: #1A3828 !important;
  text-align: center !important;
  line-height: 1.25 !important;
}

.square-card-badge-text {
  font-size: 11px !important;
  color: #557461 !important;
  font-weight: 600 !important;
  margin-top: 4px !important;
  text-align: center !important;
}

@media (max-width: 768px) {
  .quick-action-grid-wrap {
    grid-template-columns: repeat(2, 1fr) !important;
    gap: 12px !important;
  }
}

/* DESTINATION CARDS */
.dest-card-styled {
  position: relative;
  border-radius: 20px;
  overflow: hidden;
  height: 220px;
  box-shadow: 0 6px 18px rgba(26, 56, 40, 0.06);
  margin-bottom: 10px;
}

.dest-card-styled img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.dest-scrim-overlay {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  padding: 16px;
  background: linear-gradient(180deg, transparent 0%, rgba(26, 56, 40, 0.9) 100%);
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  color: #FFFFFF;
}

.dest-card-title {
  font-family: 'Playfair Display', serif;
  font-size: 18px;
  font-weight: 700;
}

.dest-card-sub {
  font-size: 12px;
  color: #E2EDE4;
}

/* STREAMLIT TABS */
div[data-baseweb="tab-list"] button,
button[data-baseweb="tab"],
button[data-testid="stTab"] {
  color: #2E5E3F !important;
  font-family: 'Plus Jakarta Sans', sans-serif !important;
  font-weight: 600 !important;
  font-size: 14.5px !important;
  padding: 10px 18px !important;
  background: transparent !important;
  border: none !important;
}

div[data-baseweb="tab-list"] button[aria-selected="true"],
button[data-baseweb="tab"][aria-selected="true"],
button[data-testid="stTab"][aria-selected="true"] {
  color: #1A3828 !important;
  border-bottom: 2.5px solid #244E37 !important;
  font-weight: 800 !important;
}
/* --- THEMED BUTTON OVERRIDES FOR #244E37 DEEP FOREST GREEN --- */
div.stButton > button,
button[kind="primary"],
button[kind="secondary"] {
  background-color: #244E37 !important;
  border: 1.5px solid #244E37 !important;
  color: #FFFFFF !important;
  font-weight: 700 !important;
  border-radius: 9999px !important;
  padding: 9px 22px !important;
}

div.stButton > button:hover,
button[kind="primary"]:hover,
button[kind="secondary"]:hover {
  background-color: #1A3828 !important;
  border-color: #1A3828 !important;
  color: #FFFFFF !important;
}

div.stButton > button p,
div.stButton > button span,
div.stButton > button div {
  color: #FFFFFF !important;
}
/* --- FIX RADIO BUTTON LABEL VISIBILITY --- */
div[data-testid="stRadio"] label,
div[data-testid="stRadio"] label p,
div[data-testid="stRadio"] label span,
div[data-testid="stRadio"] label div {
  color: #1A3828 !important;
  font-family: 'Plus Jakarta Sans', sans-serif !important;
  font-weight: 700 !important;
  font-size: 14px !important;
}
</style>""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# TOP COMMAND BAR (UNIFIED CAPSULE BAR - LAYOUT A)
# ---------------------------------------------------------------------------
user_space_active = (st.session_state.active_view == "user_space")
btn_action_target = "home" if user_space_active else "userspace"
btn_label = "✦ Home" if user_space_active else "👤 My Space"
btn_bg_style = "background: #1A3828; border: 1.5px solid rgba(255,255,255,0.2);" if user_space_active else "background: #244E37;"

unified_top_bar_html = f"""
<div class="unified-top-bar">
  <div class="brand-section">
    <img src="{APP_LOGO_SRC}" class="brand-logo" alt="Logo" />
    <div class="brand-text">
      <div class="brand-title">Wondoo <span>Alpine Studio</span></div>
      <div class="brand-sub">Autonomous Circuit Architect • Curated Mountain Stays • Brochure Studio</div>
    </div>
  </div>
  <div class="actions-section">
    <div class="telemetry-tag">● {period_label}</div>
    <a href="?action={btn_action_target}" target="_self" class="myspace-pill-btn" style="{btn_bg_style}">{btn_label}</a>
  </div>
</div>
"""

st.markdown(unified_top_bar_html, unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# CONFIRMATION BANNER
# ---------------------------------------------------------------------------
if st.session_state.get("booking_confirmed"):
    info = st.session_state.booking_confirmed
    wa_encoded_summary = format_whatsapp_reservation_receipt(info)
    wa_direct_url = f"https://api.whatsapp.com/send?phone={AGENCY_WHATSAPP_NUMBER}&text={wa_encoded_summary}"

    st.markdown(
        f"""<div style="background:#FFFFFF; border:1.5px solid rgba(26,56,40,0.08); border-radius:24px; padding:22px; margin-bottom:20px; box-shadow:0 8px 24px rgba(26,56,40,0.06);">
<div style="font-family:'Playfair Display', serif; font-size:1.3rem; font-weight:700; color:#1A3828; margin-bottom:4px;">
🎉 Reservation #{info['booking_id']} Locked & Confirmed!
</div>
<div style="font-size:14px; color:#314B3B; line-height:1.55; margin-bottom:14px;">
Thank you, <b>{info['lead_name']}</b>. Your expedition package for <b>{info['circuit']}</b> is locked.
</div>
<a href="{wa_direct_url}" target="_blank" style="display:inline-block; background:#244E37; color:#FFFFFF; text-decoration:none; padding:12px 22px; border-radius:9999px; font-weight:700; font-size:13px;">
💬 Send Booking Summary to WhatsApp
</a>
</div>""",
        unsafe_allow_html=True
    )
    if st.button("✕ Dismiss Notification", key="dismiss_banner"):
        st.session_state.booking_confirmed = None
        st.rerun()

# ---------------------------------------------------------------------------
# MAIN WORKSPACE ROUTING
# ---------------------------------------------------------------------------

# VIEW U: TRAVELER STUDIO & USER SPACE
if st.session_state.get("active_view") == "user_space":
    c_back, _ = st.columns([1.5, 4.5])
    with c_back:
        if st.button("← Back to Expeditions", key="btn_back_from_userspace", use_container_width=True):
            st.session_state.active_view = "home"
            st.rerun()

    st.markdown(
        f"""<div style="background: linear-gradient(135deg, #1A3828 0%, #29573B 100%); border-radius: 26px; padding: 26px 30px; color: #FFFFFF; margin: 10px 0 20px 0; box-shadow: 0 8px 24px rgba(26,56,40,0.12);">
  <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:16px;">
    <div>
      <div style="font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:0.8px; color:#A4C4AF;">Wondoo Expeditions Passbook</div>
      <div style="font-family:'Playfair Display', serif; font-size:2.2rem; font-weight:700; margin-top:2px;">Traveler Studio</div>
      <div style="font-size:13.5px; color:#D2E4D7;">Manage confirmed vouchers, trip wallet credits, and frontier permits.</div>
    </div>
    <div style="background: rgba(255,255,255,0.12); border: 1.5px solid rgba(255,255,255,0.22); border-radius: 20px; padding: 14px 22px; text-align:right;">
      <div style="font-size:11px; text-transform:uppercase; letter-spacing:0.5px; color:#C2D9C9; font-weight:700;">Alpine Wallet Balance</div>
      <div style="font-size:1.85rem; font-weight:800; color:#FFFFFF;">₹{st.session_state.user_wallet_balance:,.0f}</div>
      <div style="font-size:11px; color:#A4C4AF;">Usable towards any expedition lock</div>
    </div>
  </div>
</div>""",
        unsafe_allow_html=True
    )

    tab_bookings, tab_wallet, tab_permits = st.tabs([
        "📜 Confirmed Reservations",
        "💳 Alpine Wallet & Rewards",
        "🪪 Frontier Permits Locker"
    ])

    with tab_bookings:
        if not st.session_state.get("booking_history"):
            st.info("You don't have any confirmed expeditions yet.")
        else:
            for b in st.session_state.booking_history:
                permit_tag = (
                    "<span style='background:#E2EDE4; color:#1A3828; font-weight:700; font-size:11px; padding:3px 9px; border-radius:6px;'>✔ Permits Approved</span>"
                    if b.get("permit_status") == "PERMITS_APPROVED"
                    else "<span style='background:#FFF4E5; color:#8A5300; font-weight:700; font-size:11px; padding:3px 9px; border-radius:6px;'>⏳ Permits Under Clearance</span>"
                )

                st.markdown(
                    f"""<div style="background:#FFFFFF; border:1.5px solid rgba(26,56,40,0.08); border-radius:22px; padding:20px; margin-bottom:14px; box-shadow:0 4px 18px rgba(26,56,40,0.03);">
  <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:10px; flex-wrap:wrap; gap:10px;">
    <div>
      <div style="font-size:11.5px; font-weight:700; color:#2E5E3F; text-transform:uppercase; letter-spacing:0.5px;">Ref #{b['booking_id']} • {b['departure_date']}</div>
      <div style="font-family:'Playfair Display', serif; font-size:1.35rem; font-weight:700; color:#1A3828; margin-top:2px;">{b['circuit']}</div>
      <div style="font-size:12.5px; color:#557461; margin-top:3px;">
        ⏱️ {b['duration']} • 👥 {b['heads']} Travelers • 🏡 {b.get('room_tier', 'Standard Room')} • 🚗 {b['vehicle'].split('(')[0].strip()}
      </div>
    </div>
    <div style="text-align:right;">
      <div style="font-size:1.35rem; font-weight:800; color:#244E37;">₹{b['grand_total']:,.0f}</div>
      <div style="font-size:11px; color:#688574;">25% Token Paid: <b>₹{b['advance_paid']:,.0f}</b></div>
      <div style="font-size:11.5px; color:#C25438; font-weight:700;">Balance Due on Arrival: ₹{b['balance_due']:,.0f}</div>
    </div>
  </div>
  <div style="display:flex; justify-content:space-between; align-items:center; border-top:1.5px solid rgba(26,56,40,0.06); padding-top:12px; margin-top:8px;">
    <div>{permit_tag}   <span style="background:#EBF3EC; color:#244E37; font-weight:700; font-size:11px; padding:3px 9px; border-radius:6px;">✦ Locked & Active</span></div>
    <div style="font-size:12px; color:#557461;">Chauffeur details dispatch 24h prior to arrival.</div>
  </div>
</div>""",
                    unsafe_allow_html=True
                )

                col_wa_sup, _ = st.columns([1.5, 4.5], gap="small")
                with col_wa_sup:
                    wa_help = urllib.parse.quote(f"Hi Wondoo Concierge, I have an inquiry regarding my booking #{b['booking_id']}.")
                    st.markdown(
                        f'<a href="https://api.whatsapp.com/send?phone={AGENCY_WHATSAPP_NUMBER}&text={wa_help}" target="_blank" style="display:block; text-align:center; background:#FFFFFF; border:1.5px solid rgba(26,56,40,0.18); border-radius:9999px; padding:9px; font-size:12.5px; font-weight:700; color:#244E37; text-decoration:none;">💬 Chat with Coordinator</a>',
                        unsafe_allow_html=True
                    )

    with tab_wallet:
        st.markdown(
            f"""<div style="background:#FFFFFF; border:1.5px solid rgba(26,56,40,0.08); border-radius:22px; padding:22px; box-shadow:0 4px 18px rgba(26,56,40,0.03);">
<div style="font-size:11.5px; font-weight:700; color:#2E5E3F; text-transform:uppercase;">Store Credit Balance</div>
<div style="font-family:'Playfair Display', serif; font-size:2.2rem; font-weight:800; color:#244E37; margin:6px 0;">₹{st.session_state.user_wallet_balance:,.0f}</div>
<div style="font-size:12.5px; color:#557461; line-height:1.55;">
Credits can be applied at checkout toward any advance token payment across our boutique circuits.
</div>
</div>""",
            unsafe_allow_html=True
        )

    with tab_permits:
        st.markdown(
            """<div style="background:#FFFFFF; border:1.5px solid rgba(26,56,40,0.08); border-radius:22px; padding:22px; box-shadow:0 4px 18px rgba(26,56,40,0.03);">
<div style="font-family:'Playfair Display', serif; font-size:1.2rem; font-weight:700; color:#1A3828; margin-bottom:6px;">Protected Area Permits (PAP / ILP)</div>
<div style="font-size:13px; color:#557461; line-height:1.6; margin-bottom:12px;">
Frontier mountain zones require state administration permits arranged 24h prior.
</div>
<div style="background:#F4F7F4; border-radius:14px; padding:12px 16px; font-size:13px; color:#244E37;">
✔ <b>Document Checklist</b>: 2 Passport-sized photos per traveler & Government Photo ID (Voter ID / Passport / Driving License).
</div>
</div>""",
            unsafe_allow_html=True
        )

# VIEW: EXPLORE PLACES CATALOG (DIRECT SHEET LOADING - NO AI)
elif st.session_state.get("active_view") == "explore" and not st.session_state.get("itinerary_data"):
    col_back, _ = st.columns([1.5, 4.5])
    with col_back:
        if st.button("← Back to Discover", key="back_from_explore", use_container_width=True):
            st.session_state.active_view = "home"
            st.rerun()

    st.markdown(
        """<div style="margin: 10px 0 20px 0;">
<div style="font-family:'Playfair Display', serif; font-size: 2.1rem; font-weight:700; color:#1A3828; margin-bottom:4px;">Explore Sanctuaries</div>
<div style="font-size:14px; color:#557461;">Discover handpicked serene destinations across Bengal, Sikkim, and the Eastern Himalayas.</div>
</div>""",
        unsafe_allow_html=True
    )

    dest_cols = st.columns(3, gap="medium")
    for idx, d in enumerate(LIVE_ITINERARIES):
        with dest_cols[idx % 3]:
            card_img = sanitize_image_url(d.get("image"), fallback_url=DEFAULT_CARD_IMG)
            st.markdown(
                f"""<div class="dest-card-styled">
<img src="{card_img}" alt="{d['title']}" onerror="this.src='{DEFAULT_CARD_IMG}'" />
<div class="dest-scrim-overlay">
<div>
<div class="dest-card-title">{d['title'].split('&')[0].strip()}</div>
<div class="dest-card-sub">{d['sector']} • {d['duration']}</div>
</div>
</div>
</div>""",
                unsafe_allow_html=True
            )
            if st.button(f"Plan {d['title'].split('&')[0].strip()}", key=f"btn_explore_card_{idx}", use_container_width=True):
                with st.spinner(f"Loading {d['title']} from Sheet Catalog..."):
                    plan = get_or_generate_itinerary(d)
                    st.session_state.itinerary_data = plan
                    st.session_state.active_view = "home"
                    st.rerun()

# VIEW: SMART ROUTE CATALOG (DIRECT SHEET LOADING - NO AI)
elif st.session_state.get("active_view") == "smart_route" and not st.session_state.get("itinerary_data"):
    col_back, _ = st.columns([1.5, 4.5])
    with col_back:
        if st.button("← Back to Discover", key="back_from_sr", use_container_width=True):
            st.session_state.active_view = "home"
            st.rerun()

    st.markdown(
        """<div style="margin: 10px 0 20px 0;">
<div style="font-family:'Playfair Display', serif; font-size: 2.1rem; font-weight:700; color:#1A3828; margin-bottom:4px;">Smart Verified Routes</div>
<div style="font-size:14px; color:#557461;">Optimized mountain elevation transitions with verified vehicle transit times.</div>
</div>""",
        unsafe_allow_html=True
    )

    grid_cols = st.columns(2, gap="medium")
    for idx, itin in enumerate(LIVE_ITINERARIES):
        with grid_cols[idx % 2]:
            img_src = sanitize_image_url(itin.get("image"), fallback_url=DEFAULT_CARD_IMG)
            highlights_li = "".join([f"<li style='margin-bottom:4px;'>✦ {h}</li>" for h in itin.get("highlights", [])])
            st.markdown(
                f"""<div style="background:#FFFFFF; border:1.5px solid rgba(26,56,40,0.08); border-radius:20px; overflow:hidden; box-shadow:0 4px 18px rgba(26,56,40,0.04); margin-bottom:14px;">
  <img src="{img_src}" style="width:100%; height:180px; min-height:180px; object-fit:cover; display:block;" onerror="this.onerror=null;this.src='{DEFAULT_CARD_IMG}';" />
  <div style="padding:16px;">
    <div style="font-size:11px; text-transform:uppercase; color:#2E5E3F; font-weight:700;">{itin['sector']} • {itin['duration']}</div>
    <div style="font-family:'Playfair Display', serif; font-size:18px; font-weight:700; color:#1A3828; margin:4px 0;">{itin['title']}</div>
    <div style="font-size:12.5px; color:#557461; margin-bottom:10px;">Altitude: {itin['elevation']}</div>
    <ul style="list-style:none; padding-left:0; margin:0 0 12px 0; font-size:13px; color:#314B3B;">{highlights_li}</ul>
  </div>
</div>""",
                unsafe_allow_html=True
            )
            if st.button(f"Generate Route ({itin['duration']})", key=f"btn_sr_{idx}", type="primary", use_container_width=True):
                with st.spinner("Loading verified route from sheet catalog..."):
                    plan = get_or_generate_itinerary(itin)
                    st.session_state.itinerary_data = plan
                    st.session_state.active_view = "home"
                    st.rerun()

# VIEW: BUDGET PLAN CATALOG
elif st.session_state.get("active_view") == "budget_plan" and not st.session_state.get("itinerary_data"):
    col_back, _ = st.columns([1.5, 4.5])
    with col_back:
        if st.button("← Back to Discover", key="back_from_bp", use_container_width=True):
            st.session_state.active_view = "home"
            st.rerun()

    st.markdown(
        """<div style="margin: 10px 0 20px 0;">
<div style="font-family:'Playfair Display', serif; font-size: 2.1rem; font-weight:700; color:#1A3828; margin-bottom:4px;">Fixed Budget Packages</div>
<div style="font-size:14px; color:#557461;">Direct transparent quotes including dedicated transport, meals, and stays.</div>
</div>""",
        unsafe_allow_html=True
    )

    pkg_cols = st.columns(2, gap="medium")
    for idx, pkg in enumerate(LIVE_PACKAGES):
        with pkg_cols[idx % 2]:
            features_li = "".join([f"<li style='margin-bottom:5px;'>✔ {f}</li>" for f in pkg.get("features", [])])
            st.markdown(
                f"""<div style="background:#FFFFFF; border:1.5px solid rgba(26,56,40,0.08); border-radius:20px; padding:18px; margin-bottom:14px;">
  <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:8px;">
    <div>
      <div style="font-family:'Playfair Display', serif; font-size:18px; font-weight:700; color:#1A3828;">{pkg['title']}</div>
      <div style="font-size:13px; color:#557461; font-weight:600;">{pkg['duration']}</div>
    </div>
    <div style="text-align:right;">
      <div style="font-size:20px; font-weight:800; color:#244E37;">{pkg['price_per_head']}</div>
      <div style="font-size:11px; color:#688574;">per head</div>
    </div>
  </div>
  <div style="font-size:12px; color:#314B3B; margin-bottom:12px;">🏡 {pkg['stay_type']} • 🚗 {pkg['transit']}</div>
  <ul style="list-style:none; padding-left:0; margin:0 0 14px 0; font-size:13px; color:#314B3B;">{features_li}</ul>
</div>""",
                unsafe_allow_html=True
            )
            wa_pkg_text = urllib.parse.quote(f"Hi Wondoo Team, I would like to reserve '{pkg['title']}' ({pkg['duration']}).")
            st.markdown(
                f'<a href="https://api.whatsapp.com/send?phone={AGENCY_WHATSAPP_NUMBER}&text={wa_pkg_text}" target="_blank" style="display:block; text-align:center; background:#244E37; color:#FFFFFF; font-size:13px; font-weight:700; padding:10px; border-radius:9999px; text-decoration:none; margin-top:-6px; margin-bottom:18px;">💬 Inquire via WhatsApp</a>',
                unsafe_allow_html=True
            )

# VIEW 1: DEDICATED AI CONCIERGE CHAT PAGE
elif st.session_state.get("active_view") == "ai_concierge" and not st.session_state.get("itinerary_data"):
    col_back, _ = st.columns([1.5, 4.5])
    with col_back:
        if st.button("← Back to Discover", key="back_to_discover_ai", use_container_width=True):
            st.session_state.active_view = "home"
            st.rerun()

    st.markdown(
        """<div style="margin: 10px 0 20px 0;">
<div style="font-family:'Playfair Display', serif; font-size: 2.1rem; font-weight:700; color:#1A3828; margin-bottom:4px;">Alpine AI Concierge</div>
<div style="font-size:14px; color:#557461;">Converse with our expedition architect to brainstorm pacing, high-altitude passes, and boutique stays.</div>
</div>""",
        unsafe_allow_html=True
    )

    for msg in st.session_state.messages:
        role = msg["role"]
        avatar = "👤" if role == "user" else "🌿"
        with st.chat_message(role, avatar=avatar):
            st.markdown(msg["content"])

    if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
        with st.chat_message("assistant", avatar="🌿"):
            api_key = get_secret("GEMINI_API_KEY", "")
            client = genai.Client(api_key=api_key) if api_key else None
            system_instruction = "You are the senior AI Travel Concierge at Wondoo Alpine Studio."
            full_reply = st.write_stream(
                stream_ai_conversation_with_fallback(client, st.session_state.messages, system_instruction)
            )
        st.session_state.messages.append({"role": "assistant", "content": full_reply})
        st.rerun()

    user_prompt = st.chat_input("Ask Alpine — Where would you like to wander?")
    if user_prompt:
        st.session_state.messages.append({"role": "user", "content": user_prompt})
        st.rerun()

# VIEW 4: PRIMARY HOME SCREEN
elif not st.session_state.get("itinerary_data"):
    hero_markup = f"""<div class="hero-illustrated-scene" style="background-image: url('{HERO_BG_SRC}');">
<div class="hero-scene-content">
<div class="hero-headline-serif">Your Journey,<br><span>Intelligently</span> Planned.</div>
<div class="hero-subline-sans">AI-powered travel planning made effortless. Converse with our Expedition Architect to create tailored routes.</div>
</div>
</div>"""
    st.markdown(hero_markup, unsafe_allow_html=True)

    with st.form("home_search_capsule_form", clear_on_submit=False):
        home_query = st.text_input("home_search_bar_input", placeholder="", label_visibility="collapsed")
        submitted = st.form_submit_button("➔")

    # Animated typing & omitting cursor effect overlay script
    typing_cursor_html = """
    <script>
    (function() {
        const phrases = [
            "Where would you like to wander?",
            "Plan a 5-day Sikkim Silk Route expedition...",
            "Explore Darjeeling tea estates & sunrise points...",
            "Design a custom mountain escape..."
        ];
        
        let pIdx = 0;
        let charIdx = 0;
        let isDeleting = false;
        
        function initTyping() {
            const container = window.parent.document.querySelector("div[data-testid='stForm']");
            if (!container) {
                setTimeout(initTyping, 300);
                return;
            }
            
            if (window.parent.document.getElementById("alpine-typing-overlay")) return;
            
            const overlay = window.parent.document.createElement("div");
            overlay.id = "alpine-typing-overlay";
            overlay.style.cssText = "position:absolute; left:48px; top:50%; transform:translateY(-50%); pointer-events:none; font-family:'Plus Jakarta Sans',sans-serif; font-size:14.5px; font-weight:600; color:#4A6E57; z-index:10; display:flex; align-items:center;";
            
            const textSpan = window.parent.document.createElement("span");
            textSpan.id = "alpine-typing-text";
            
            const cursorSpan = window.parent.document.createElement("span");
            cursorSpan.style.cssText = "display:inline-block; width:2px; height:16px; background-color:#244E37; margin-left:2px; animation:cursor-blink 0.8s infinite;";
            
            overlay.appendChild(textSpan);
            overlay.appendChild(cursorSpan);
            container.appendChild(overlay);
            
            const inputEl = container.querySelector("input[aria-label='home_search_bar_input']");
            
            function typeLoop() {
                if (!textSpan || !inputEl) return;
                
                if (inputEl.value.length > 0) {
                    overlay.style.display = "none";
                } else {
                    overlay.style.display = "flex";
                }
                
                const current = phrases[pIdx];
                if (isDeleting) {
                    textSpan.textContent = current.substring(0, charIdx - 1);
                    charIdx--;
                } else {
                    textSpan.textContent = current.substring(0, charIdx + 1);
                    charIdx++;
                }
                
                let speed = isDeleting ? 35 : 75;
                if (!isDeleting && charIdx === current.length) {
                    speed = 2200;
                    isDeleting = true;
                } else if (isDeleting && charIdx === 0) {
                    isDeleting = false;
                    pIdx = (pIdx + 1) % phrases.length;
                    speed = 400;
                }
                setTimeout(typeLoop, speed);
            }
            typeLoop();
        }
        setTimeout(initTyping, 500);
    })();
    </script>
    <style>
    @keyframes cursor-blink {
      0%, 100% { opacity: 1; }
      50% { opacity: 0; }
    }
    </style>
    """
    components.html(typing_cursor_html, height=0)

    ticker_cards = ""
    for d in LIVE_ITINERARIES:
        c_img = sanitize_image_url(d.get("image"), fallback_url=DEFAULT_CARD_IMG)
        t_name = d['title'].split('&')[0].strip()
        t_dur = d.get('duration', '4 Days')
        t_sec = d.get('sector', 'Himalaya')
        ticker_cards += f'<div style="display:inline-flex; align-items:center; background:#FFFFFF; border:1.5px solid rgba(26,56,40,0.1); border-radius:18px; padding:8px 16px; margin-right:16px; box-shadow:0 4px 12px rgba(26,56,40,0.04); min-width:240px; flex-shrink:0;"><img src="{c_img}" style="width:120px; height:120px; border-radius:12px; object-fit:cover; margin-right:12px;" /><div><div style="font-family:\'Playfair Display\', serif; font-size:14px; font-weight:700; color:#1A3828; white-space:nowrap;">{t_name}</div><div style="font-size:11px; color:#557461; white-space:nowrap;">{t_dur} • {t_sec}</div></div></div>'

    st.markdown(f"""
    <style>
    @keyframes scrollTicker {{
      0% {{ transform: translateX(0); }}
      100% {{ transform: translateX(-50%); }}
    }}
    .ticker-track {{
      display: flex;
      width: max-content;
      animation: scrollTicker 60s linear infinite;
    }}
    .ticker-track:hover {{
      animation-play-state: paused;
    }}
    .ticker-container {{
      overflow: hidden;
      width: 100%;
      padding: 10px 0 20px 0;
      position: relative;
    }}
    </style>
    <div style="font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:0.8px; color:#376E4B; margin-bottom:8px;">
      ✦ Live Circuit Feed
    </div>
    <div class="ticker-container">
      <div class="ticker-track">
        {ticker_cards}
        {ticker_cards}
      </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("### Inspiring Destinations")
    dest_cols = st.columns(3, gap="medium")
    for idx, d in enumerate(LIVE_ITINERARIES[:3]):
        with dest_cols[idx]:
            card_img = sanitize_image_url(d.get("image"), fallback_url=DEFAULT_CARD_IMG)
            st.markdown(f"""<div class="dest-card-styled"><img src="{card_img}" /><div class="dest-scrim-overlay"><div class="dest-card-title">{d['title']}</div></div></div>""", unsafe_allow_html=True)
            if st.button(f"Explore {d['title']}", key=f"dest_btn_{idx}", use_container_width=True):
                plan = get_or_generate_itinerary(d)
                st.session_state.itinerary_data = plan
                st.rerun()

    st.markdown("### Quick Actions")
    square_tiles_html = f"""<div class="quick-action-grid-wrap">
  <a href="?action=ai" target="_self" class="square-action-card-tile">
    <div class="square-card-icon-bubble"><img src="{AI_ICON_SRC}" alt="AI" /></div>
    <div class="square-card-title-text">AI Itinerary</div>
    <div class="square-card-badge-text">Custom Plan</div>
  </a>
  <a href="?action=explore" target="_self" class="square-action-card-tile">
    <div class="square-card-icon-bubble"><img src="{ROUTE_ICON_SRC}" alt="Explore" /></div>
    <div class="square-card-title-text">Explore Places</div>
    <div class="square-card-badge-text">Sanctuaries</div>
  </a>
  <a href="?action=route" target="_self" class="square-action-card-tile">
    <div class="square-card-icon-bubble"><img src="{GUIDE_ICON_SRC}" alt="Smart Route" /></div>
    <div class="square-card-title-text">Smart Route</div>
    <div class="square-card-badge-text">Verified Pacing</div>
  </a>
  <a href="?action=budget" target="_self" class="square-action-card-tile">
    <div class="square-card-icon-bubble"><img src="{BUDGET_ICON_SRC}" alt="Budget" /></div>
    <div class="square-card-title-text">Budget Plan</div>
    <div class="square-card-badge-text">Transparent Fares</div>
  </a>
</div>"""
    st.markdown(square_tiles_html, unsafe_allow_html=True)

# VIEW 5: STRUCTURED ITINERARY WORKSPACE
else:
    data: TourItinerary = st.session_state.itinerary_data

    c_btn_back, c_title_center, _ = st.columns([0.8, 4.4, 0.8], gap="small")
    with c_btn_back:
        if st.button("←", key="nav_back_arrow", help="Back to Discover"):
            st.session_state.itinerary_data = None
            st.session_state.booking_confirmed = None
            st.session_state.auto_open_booking = False
            st.session_state.active_view = "home"
            st.rerun()

    with c_title_center:
        st.markdown("<div style='text-align:center; font-family:\"Playfair Display\", serif; font-size:1.45rem; font-weight:700; color:#1A3828;'>Your Itinerary</div>", unsafe_allow_html=True)

    primary_spot = getattr(data.days[0], "stay_location", None) or data.days[0].place_name
    coords = get_coords_for_place(primary_spot)
    weather_data = fetch_live_weather(coords[0], coords[1])

    # Dynamically fetch highlights without mutating Pydantic model
    highlights_list = get_highlights_for_title(data.tour_title)
    highlights_display = ", ".join(highlights_list) if highlights_list else "Scenic Exploration & Local Landmarks"

    st.markdown(
        f"""<div style="display:flex; align-items:center; justify-content:space-between; gap:20px; margin: 12px 0 16px 0; width:100%;">
  <div style="flex:1; min-width:0;">
    <div style="font-family:'Playfair Display', Georgia, serif; font-size:1.85rem; font-weight:700; color:#1A3828; line-height:1.2; margin-bottom:4px;">
      {data.tour_title}
    </div>
    <div style="font-size:13.5px; color:#557461; font-weight:600; margin-bottom:6px;">
      {data.duration} • {data.sector}
    </div>
    <div style="font-size:12.5px; color:#376E4B; font-weight:700;">
      📍 Key Points to Cover: {highlights_display}
    </div>
  </div>
  <div style="flex-shrink:0;">
    <img src="{DEFAULT_CARD_IMG}" style="width:140px; height:95px; border-radius:18px; object-fit:cover;" />
  </div>
</div>""",
        unsafe_allow_html=True
    )

    tab_cols = st.columns(3, gap="small")
    tabs_list = ["Itinerary", "Transport", "Stay"]
    for idx, tab_name in enumerate(tabs_list):
        with tab_cols[idx]:
            is_active = (st.session_state.itin_tab == tab_name)
            if st.button(tab_name, key=f"tab_nav_{tab_name.lower()}", type="primary" if is_active else "secondary", use_container_width=True):
                st.session_state.itin_tab = tab_name
                st.rerun()

    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)

    if st.session_state.itin_tab == "Itinerary":
        for idx, day in enumerate(data.days):
            day_num = getattr(day, "day_number", idx + 1)
            route_title = getattr(day, "route_title", f"Day {day_num} Exploration")
            st.markdown(f"**Day {day_num}: {route_title}**")
            bullets = getattr(day, "bullets", [])
            for b in bullets:
                st.markdown(f"- {b}")

    elif st.session_state.itin_tab == "Transport":
        cab_options = [
            ("Include Dedicated Cab (Innova/Scorpio)", "₹3,800 / day"),
            ("Include Bolero 4x4", "₹4,200 / day"),
            ("Self Transit / Exclude Vehicle", "₹0")
        ]
        for cab_name, price_tag in cab_options:
            is_selected = (st.session_state.selected_cab == cab_name)
            col_info, col_btn = st.columns([4.2, 1.2], gap="small")
            with col_info:
                st.markdown(f"**{cab_name}** — `{price_tag}`")
            with col_btn:
                if st.button("Selected" if is_selected else "Select", key=f"btn_cab_{cab_name}", type="primary" if is_selected else "secondary", use_container_width=True, disabled=is_selected):
                    st.session_state.selected_cab = cab_name
                    st.rerun()

    elif st.session_state.itin_tab == "Stay":
        room_tier_list = list(ROOM_TIER_PREMIUM_MAP.keys())
        current_saved_tier = st.session_state.get("selected_room_tier", "Standard Room")
        cur_tier_idx = room_tier_list.index(current_saved_tier) if current_saved_tier in room_tier_list else 0

        chosen_tier_radio = st.radio(
            "Select Room Tier",
            room_tier_list,
            index=cur_tier_idx,
            horizontal=True,
            key="room_tier_radio_selector"
        )
        if chosen_tier_radio != st.session_state.selected_room_tier:
            st.session_state.selected_room_tier = chosen_tier_radio
            st.rerun()

        nights_data = resolve_all_stays_for_itinerary(data)
        
        if "selected_stays" not in st.session_state:
            st.session_state.selected_stays = {}

        for night_idx, n_info in nights_data.items():
            st.markdown(f"**Night {night_idx} in {n_info['town']}**")
            available_stays = n_info["stays"]
            
            if available_stays:
                stay_labels = [f"{s['stay_name']} (₹{s['price_bracket']}/{s['pricing_type'].lower()})" for s in available_stays]
                
                current_selection = st.session_state.selected_stays.get(night_idx, available_stays[0])
                curr_label_idx = 0
                for idx, s in enumerate(available_stays):
                    if s["stay_name"] == current_selection.get("stay_name"):
                        curr_label_idx = idx
                        break

                chosen_stay_label = st.radio(
                    f"Choose accommodation for Night {night_idx}",
                    stay_labels,
                    index=curr_label_idx,
                    key=f"stay_radio_night_{night_idx}"
                )
                
                selected_idx = stay_labels.index(chosen_stay_label)
                st.session_state.selected_stays[night_idx] = available_stays[selected_idx]
            else:
                st.info(f"No specific catalog listings matched '{n_info['town']}'. Default standard stay applied.")

    if st.button("✨ Lock Reservation & Pay Advance ➔", type="primary", use_container_width=True):
        nights_dict = resolve_all_stays_for_itinerary(data)
        flat_matched_stays = []
        for n_info in nights_dict.values():
            flat_matched_stays.extend(n_info["stays"])
        
        open_package_booking_dialog(data, flat_matched_stays)
