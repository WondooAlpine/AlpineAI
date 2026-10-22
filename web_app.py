import os
import glob
import json
import uuid
import random
import re
import zlib
import base64
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
BOOKING_WEBHOOK_URL = os.environ.get(
    "BOOKING_WEBHOOK_URL",
    "https://script.google.com/macros/s/YOUR_APPS_SCRIPT_DEPLOYMENT_ID/exec",
)
AGENCY_WHATSAPP_NUMBER = os.environ.get("AGENCY_WHATSAPP_NUMBER", "919800000000")
UPI_VPA = os.environ.get("UPI_VPA", "wondooexpeditions@oksbi")
UPI_PAYEE_NAME = os.environ.get("UPI_PAYEE_NAME", "Wondoo Alpine Studio")
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "rzp_test_1DP5mmOlF5G5ag")
CATALOG_SHEET_ID = os.environ.get(
    "CATALOG_SHEET_ID",
    "1fbDtDmXR2QS15V3oY6dAIW64gcqMui3vTMrndxsOYVQ",
)

DEFAULT_CARD_IMG = "https://images.unsplash.com/photo-1544735716-392fe2489ffa?auto=format&fit=crop&w=900&q=80"

ROOM_TIER_PREMIUM_MAP = {
    "Standard Room": 0,
    "Deluxe Mountain/Sea View (+₹1,200/night)": 1200,
    "Executive Suite / Heritage View (+₹2,500/night)": 2500,
}

# ---------------------------------------------------------------------------
# ASSET ENCODERS
# ---------------------------------------------------------------------------
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

APP_LOGO_SRC = get_image_base64("logo.png")
HERO_BG_SRC = get_image_base64("hero_bg.png")

AI_ICON_SRC = get_image_base64("icon_ai.png", fallback_url="https://img.icons8.com/fluency/96/sparkling--v1.png")
ROUTE_ICON_SRC = get_image_base64("icon_route.png", fallback_url="https://img.icons8.com/fluency/96/map-pin.png")
BUDGET_ICON_SRC = get_image_base64("icon_budget.png", fallback_url="https://img.icons8.com/fluency/96/wallet.png")
GUIDE_ICON_SRC = get_image_base64("icon_guide.png", fallback_url="https://img.icons8.com/fluency/96/open-book.png")

# ---------------------------------------------------------------------------
# GEMINI STREAMER
# ---------------------------------------------------------------------------
PRIMARY_MODEL = "gemini-2.0-flash"
BACKUP_MODEL = "gemini-1.5-flash"

def stream_gemini_with_fallback(client, contents, system_instruction):
    candidate_models = [PRIMARY_MODEL, BACKUP_MODEL]
    for model_name in candidate_models:
        try:
            return client.models.generate_content_stream(
                model=model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.35,
                    max_output_tokens=2048,
                ),
            )
        except Exception:
            if model_name != candidate_models[-1]:
                continue
            raise

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
    resolved_id = sheet_id
    if "CATALOG_SHEET_ID" in os.environ:
        resolved_id = os.environ["CATALOG_SHEET_ID"]

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
                    records.append({
                        "town_keys": str(row.get("town_keys", "")).lower().strip(),
                        "stay_name": name,
                        "altitude": str(row.get("altitude", "")).strip(),
                        "property_type": str(row.get("property_type", "Boutique Lodge")).strip(),
                        "rating": str(row.get("rating", "4.8 ★")).strip(),
                        "price_bracket": str(row.get("price_bracket", "2000")).strip().replace("₹", "").replace(",", ""),
                        "pricing_type": str(row.get("pricing_type", "Per Head")).strip(),
                        "image": str(row.get("image", DEFAULT_CARD_IMG)).strip() if "image" in df.columns and str(row.get("image")).startswith("http") else DEFAULT_CARD_IMG
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

@st.cache_data(ttl=60)
def load_itineraries_from_sheet(sheet_id: str) -> List[Dict[str, Any]]:
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet=Itineraries"
    try:
        df = pd.read_csv(url)
        df.columns = [str(col).strip().lower() for col in df.columns]
        itineraries = []
        for _, row in df.iterrows():
            title = str(row.get("title", "")).strip()
            if not title or title.lower() == "nan":
                continue
            itineraries.append({
                "title": title,
                "duration": str(row.get("duration", "4 Days • 3 Nights")).strip(),
                "sector": str(row.get("sector", "")).strip(),
                "elevation": str(row.get("elevation", "")).strip(),
                "image": str(row.get("image", DEFAULT_CARD_IMG)).strip(),
                "highlights": [h.strip() for h in str(row.get("highlights", "")).split(";") if h.strip()],
                "default_prompt": str(row.get("default_prompt", f"Plan an authentic {title} tour.")).strip(),
                "predefined_plan_json": None
            })
        return itineraries if itineraries else DEFAULT_FALLBACK_ITINERARIES
    except Exception:
        return DEFAULT_FALLBACK_ITINERARIES

LIVE_ITINERARIES = load_itineraries_from_sheet(CATALOG_SHEET_ID)
LIVE_PACKAGES = DEFAULT_FALLBACK_PACKAGES

def get_or_generate_itinerary(itin_dict: dict, requested_days: int = None) -> TourItinerary:
    days_clause = f"Strict Duration: Exactly {requested_days} Days / {requested_days - 1} Nights.\n" if requested_days else f"Duration: {itin_dict['duration']}.\n"
    prompt = f"Create an authentic, structured tour itinerary for: {itin_dict['title']}.\n{days_clause}Sector: {itin_dict['sector']}."
    return generate_itinerary_content(prompt)

# ---------------------------------------------------------------------------
# BOOKING MODAL (DEFINED BEFORE VIEW 5 USAGE TO PREVENT NAMEERROR)
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
            cur_tier_idx = room_tier_list.index(selected_room_tier) if selected_room_tier in room_tier_list else 0
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
            f"""<div style="background:#F4F7F4; border:1px solid rgba(26,56,40,0.1); border-radius:18px; padding:16px 20px; margin-bottom:14px;">
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

        # Seamless Gateway Form Submit
        checkout_html = f"""<!DOCTYPE html>
<html>
<head>
<script src="https://checkout.razorpay.com/v1/checkout.js"></script>
<style>
  body {{ margin:0; padding:0; background:transparent; font-family:-apple-system, sans-serif; }}
  .rzp-btn {{
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
  }}
  .rzp-btn:hover {{ background:#1A3828; }}
</style>
</head>
<body>
<button class="rzp-btn" id="rzp-button">💳 Launch Payment Gateway (₹{advance_token:,.0f})</button>
<script>
var options = {{
    "key": "{RAZORPAY_KEY_ID}",
    "amount": "{int(advance_token * 100)}",
    "currency": "INR",
    "name": "Wondoo Alpine Studio",
    "description": "25% Advance Token - {itinerary.tour_title[:30]}",
    "image": "{APP_LOGO_SRC}",
    "handler": function (response){{
        const parentUrl = new URL(window.parent.location.href);
        parentUrl.searchParams.set('paid_tx', response.razorpay_payment_id);
        parentUrl.searchParams.set('book_ref', '{booking_ref}');
        window.parent.location.assign(target.href);
    }},
    "prefill": {{
        "name": "{clean_name}",
        "email": "{clean_email}",
        "contact": "{clean_phone}"
    }},
    "theme": {{
        "color": "#244E37"
    }}
}};
document.getElementById('rzp-button').onclick = function(e){{
    try {{
        var rzp = new Razorpay(options);
        rzp.open();
    }} catch (err) {{
        alert("Payment initialization error: " + err.message);
    }}
    e.preventDefault();
}};
</script>
</body>
</html>"""
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
# GLOBAL SEARCH & PAYMENT GATEWAY REDIRECT LISTENER
# ---------------------------------------------------------------------------
raw_q = st.query_params.get("q", "")
if isinstance(raw_q, list):
    raw_q = raw_q[0] if raw_q else ""
user_q = str(raw_q).strip()

if user_q:
    st.query_params.clear()
    st.session_state.messages.append({"role": "user", "content": user_q})
    st.session_state.active_view = "ai_concierge"
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
# RESPONSIVE CUSTOM CSS & HIGH CONTRAST TAB ENFORCEMENT
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

/* TOP COMMAND APP BAR */
.editorial-app-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 18px;
  background: #FFFFFF;
  border-radius: 22px;
  border: 1px solid rgba(26, 56, 40, 0.06);
  box-shadow: 0 4px 18px rgba(26, 56, 40, 0.04);
  margin-bottom: 16px;
}

.bar-brand-wrap {
  display: flex;
  align-items: center;
  gap: 12px;
}

.bar-logo-img {
  height: 36px;
  width: auto;
  border-radius: 8px;
}

.bar-title-text {
  font-family: 'Playfair Display', serif;
  font-size: 1.35rem;
  font-weight: 700;
  color: #1A3828;
  margin: 0;
  line-height: 1.1;
}

.bar-title-text span {
  color: #376E4B;
  font-style: italic;
}

.bar-sub-text {
  font-size: 11px;
  color: #557461;
  font-weight: 500;
}

.bar-telemetry-pill {
  font-size: 12px;
  font-weight: 700;
  color: #557461;
  background: #F4F7F4;
  padding: 6px 14px;
  border-radius: 9999px;
  border: 1px solid rgba(26, 56, 40, 0.06);
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
  border: 1px solid rgba(255, 255, 255, 0.8);
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

.dest-arrow-pill {
  background: #FFFFFF;
  color: #1A3828;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
}

/* QUICK ACTION TILES */
.quick-action-grid-wrap {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  width: 100%;
  margin-top: 8px;
}

.square-action-card-tile {
  background: #FFFFFF;
  border: 1px solid rgba(26, 56, 40, 0.08);
  border-radius: 24px;
  aspect-ratio: 1 / 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 18px 12px;
  box-shadow: 0 4px 18px rgba(26, 56, 40, 0.04);
  text-decoration: none !important;
  color: #1A3828 !important;
  transition: transform 0.18s ease, box-shadow 0.18s ease;
  cursor: pointer;
  box-sizing: border-box;
}

.square-action-card-tile:hover {
  transform: translateY(-4px);
  box-shadow: 0 12px 28px rgba(26, 56, 40, 0.1);
}

.square-card-icon-bubble {
  width: 54px;
  height: 54px;
  border-radius: 18px;
  background: #EBF3EC;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 12px;
}

.square-card-icon-bubble img {
  width: 32px;
  height: 32px;
  object-fit: contain;
}

.square-card-title-text {
  font-family: 'Plus Jakarta Sans', sans-serif;
  font-size: 14.5px;
  font-weight: 700;
  color: #1A3828;
  text-align: center;
}

.square-card-badge-text {
  font-size: 11px;
  color: #557461;
  font-weight: 600;
  margin-top: 4px;
}

/* --------------------------------------------------------------------------
   STREAMLIT TABS HIGH-CONTRAST DARK TEXT (FIXES INVISIBLE WHITE TABS)
   -------------------------------------------------------------------------- */
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

div[data-baseweb="tab-list"] button p,
div[data-baseweb="tab-list"] button span,
div[data-baseweb="tab-list"] button div,
button[data-baseweb="tab"] p,
button[data-baseweb="tab"] span,
button[data-baseweb="tab"] div,
button[data-testid="stTab"] p,
button[data-testid="stTab"] span,
button[data-testid="stTab"] div {
  color: #2E5E3F !important;
  font-weight: 600 !important;
}

div[data-baseweb="tab-list"] button[aria-selected="true"],
button[data-baseweb="tab"][aria-selected="true"],
button[data-testid="stTab"][aria-selected="true"] {
  color: #1A3828 !important;
  border-bottom: 2.5px solid #244E37 !important;
}

div[data-baseweb="tab-list"] button[aria-selected="true"] p,
div[data-baseweb="tab-list"] button[aria-selected="true"] span,
button[data-baseweb="tab"][aria-selected="true"] p,
button[data-baseweb="tab"][aria-selected="true"] span,
button[data-testid="stTab"][aria-selected="true"] p,
button[data-testid="stTab"][aria-selected="true"] span {
  color: #1A3828 !important;
  font-weight: 800 !important;
}

/* CHAT MESSAGE TEXT */
[data-testid="stChatMessage"] {
  background: #FFFFFF !important;
  border: 1px solid rgba(26, 56, 40, 0.08) !important;
  border-radius: 20px !important;
  padding: 16px 20px !important;
  margin-bottom: 14px !important;
  box-shadow: 0 4px 16px rgba(26, 56, 40, 0.04) !important;
}

[data-testid="stChatMessage"] p,
[data-testid="stChatMessage"] span,
[data-testid="stChatMessage"] div,
[data-testid="stChatMessage"] li {
  color: #1A3828 !important;
  font-family: 'Plus Jakarta Sans', sans-serif !important;
  line-height: 1.65 !important;
  font-size: 14px !important;
}

div.stButton > button[kind="primary"] {
  background: #244E37 !important;
  border: 1px solid #244E37 !important;
  color: #FFFFFF !important;
  font-weight: 700 !important;
  border-radius: 9999px !important;
  padding: 9px 22px !important;
}

div.stButton > button[kind="secondary"] {
  background: #FFFFFF !important;
  border: 1.5px solid rgba(26, 56, 40, 0.18) !important;
  color: #1A3828 !important;
  font-weight: 700 !important;
  border-radius: 9999px !important;
}
</style>""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# TOP COMMAND BAR
# ---------------------------------------------------------------------------
user_initial = (
    st.session_state.user["name"][0].upper()
    if st.session_state.get("user") and st.session_state.user.get("name")
    else "👤"
)

col_bar_brand, col_bar_nav = st.columns([3.8, 1.4], gap="small")

with col_bar_brand:
    st.markdown(
        f"""<div class="editorial-app-bar" style="margin-bottom:0; padding:10px 16px;">
<div class="bar-brand-wrap">
<img src="{APP_LOGO_SRC}" class="bar-logo-img" alt="Logo" />
<div>
<div class="bar-title-text">Wondoo <span>Alpine Studio</span></div>
<div class="bar-sub-text">Autonomous Circuit Architect • Curated Mountain Stays • Brochure Studio</div>
</div>
</div>
</div>""",
        unsafe_allow_html=True
    )

with col_bar_nav:
    c_tel, c_usr = st.columns([1.5, 1.2], gap="small")
    with c_tel:
        st.markdown(f"<div class=\"bar-telemetry-pill\" style=\"margin-top:12px; text-align:center;\">● {period_label}</div>", unsafe_allow_html=True)
    with c_usr:
        st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
        user_space_active = (st.session_state.active_view == "user_space")
        btn_profile_label = "✦ Home" if user_space_active else f"👤 My Space"
        if st.button(btn_profile_label, key="btn_top_toggle_userspace", use_container_width=True, type="primary" if user_space_active else "secondary"):
            st.session_state.active_view = "home" if user_space_active else "user_space"
            st.rerun()

st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# CONFIRMATION BANNER
# ---------------------------------------------------------------------------
if st.session_state.get("booking_confirmed"):
    info = st.session_state.booking_confirmed
    wa_encoded_summary = format_whatsapp_reservation_receipt(info)
    wa_direct_url = f"https://api.whatsapp.com/send?phone={AGENCY_WHATSAPP_NUMBER}&text={wa_encoded_summary}"

    st.markdown(
        f"""<div style="background:#FFFFFF; border:1px solid rgba(26,56,40,0.08); border-radius:24px; padding:22px; margin-bottom:20px; box-shadow:0 8px 24px rgba(26,56,40,0.06);">
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
        unsafe_allow_html=True,
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
    <div style="background: rgba(255,255,255,0.12); border: 1px solid rgba(255,255,255,0.22); border-radius: 20px; padding: 14px 22px; text-align:right;">
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
                    f"""<div style="background:#FFFFFF; border:1px solid rgba(26,56,40,0.08); border-radius:22px; padding:20px; margin-bottom:14px; box-shadow:0 4px 18px rgba(26,56,40,0.03);">
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
  <div style="display:flex; justify-content:space-between; align-items:center; border-top:1px solid rgba(26,56,40,0.06); padding-top:12px; margin-top:8px;">
    <div>{permit_tag} &nbsp; <span style="background:#EBF3EC; color:#244E37; font-weight:700; font-size:11px; padding:3px 9px; border-radius:6px;">✦ Locked & Active</span></div>
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
            f"""<div style="background:#FFFFFF; border:1px solid rgba(26,56,40,0.08); border-radius:22px; padding:22px; box-shadow:0 4px 18px rgba(26,56,40,0.03);">
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
            """<div style="background:#FFFFFF; border:1px solid rgba(26,56,40,0.08); border-radius:22px; padding:22px; box-shadow:0 4px 18px rgba(26,56,40,0.03);">
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

    last_user_query = ""
    for m in reversed(st.session_state.messages):
        if m["role"] == "user":
            last_user_query = m["content"].lower()
            break

    suggested_packages = []
    if last_user_query:
        for pkg in LIVE_PACKAGES:
            title_norm = pkg["title"].lower()
            if any(term in last_user_query for term in ["sikkim", "silk route", "gangtok", "pelling", "zuluk"]) and "sikkim" in title_norm:
                suggested_packages.append(pkg)
            elif any(term in last_user_query for term in ["darjeeling", "kalimpong", "ghoom"]) and "darjeeling" in title_norm:
                suggested_packages.append(pkg)

    if suggested_packages:
        st.markdown("<div style='font-size:13px; font-weight:700; color:#2E5E3F; margin:14px 0 8px 4px;'>🎯 Matched Fixed Tour Packages</div>", unsafe_allow_html=True)
        p_cols = st.columns(len(suggested_packages), gap="small")
        for p_idx, pkg in enumerate(suggested_packages):
            with p_cols[p_idx]:
                features_html = "".join([f"<li style='margin-bottom:3px;'>✔ {f}</li>" for f in pkg.get("features", [])[:3]])
                st.markdown(
                    f"""<div style="background:#FFFFFF; border:1px solid rgba(26,56,40,0.1); border-radius:18px; padding:16px; margin-bottom:10px;">
  <div style="font-family:'Playfair Display', serif; font-size:16.5px; font-weight:700; color:#1A3828;">{pkg['title']}</div>
  <div style="font-size:12px; color:#557461; margin-bottom:6px;">⏱️ {pkg['duration']}</div>
  <div style="font-size:18px; font-weight:800; color:#244E37; margin-bottom:8px;">{pkg['price_per_head']} <span style="font-size:11px; font-weight:500; color:#688574;">/ person</span></div>
  <div style="font-size:11.5px; color:#314B3B; line-height:1.45; margin-bottom:8px;">
    🏡 <b>Stay</b>: {pkg['stay_type']}<br>🚗 <b>Transit</b>: {pkg['transit']}
  </div>
  <ul style="list-style:none; padding-left:0; margin:0 0 10px 0; font-size:11.5px; color:#557461;">{features_html}</ul>
</div>""",
                    unsafe_allow_html=True
                )
                if st.button("⚡ Load & Book", key=f"chat_book_pkg_{p_idx}", type="primary", use_container_width=True):
                    with st.spinner(f"Preparing {pkg['title']} itinerary..."):
                        target_route = next((r for r in LIVE_ITINERARIES if any(w in r["title"].lower() for w in pkg["title"].lower().split()[:2])), LIVE_ITINERARIES[0])
                        plan = get_or_generate_itinerary(target_route)
                        st.session_state.itinerary_data = plan
                        st.session_state.auto_open_booking = True
                        st.session_state.active_view = "home"
                        st.rerun()

    user_prompt = st.chat_input("Ask Alpine — Where would you like to wander?")
    if user_prompt:
        st.session_state.messages.append({"role": "user", "content": user_prompt})
        with st.chat_message("user", avatar="👤"):
            st.markdown(user_prompt)

        with st.chat_message("assistant", avatar="🌿"):
            api_key = os.environ.get("GEMINI_API_KEY", "")
            client = genai.Client(api_key=api_key) if api_key else genai.Client()

            pkg_context = "\n".join([f"- {p['title']} ({p['duration']}): {p['price_per_head']}/head" for p in LIVE_PACKAGES])
            system_instruction = (
                "You are the senior AI Travel Concierge at Wondoo Studio.\n"
                f"AVAILABLE PACKAGES:\n{pkg_context}\n"
                "Keep answers concise and highlight matched packages with pricing."
            )

            contents = [
                types.Content(role="user" if m["role"] == "user" else "model", parts=[types.Part.from_text(text=m["content"])])
                for m in st.session_state.messages
            ]
            response_stream = stream_gemini_with_fallback(client, contents, system_instruction)

            def stream_text_generator():
                for chunk in response_stream:
                    if getattr(chunk, "text", None):
                        yield chunk.text
                    elif getattr(chunk, "candidates", None) and chunk.candidates[0].content:
                        for p in chunk.candidates[0].content.parts:
                            if getattr(p, "text", None):
                                yield p.text

            full_reply = st.write_stream(stream_text_generator())

        st.session_state.messages.append({"role": "assistant", "content": full_reply})
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

    components.html(
        """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap');
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: transparent;
    font-family: 'Plus Jakarta Sans', -apple-system, sans-serif;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: flex-start;
    overflow: hidden;
  }
  .search-container {
    width: 100%;
    max-width: 820px;
  }
  .pill-wrapper {
    width: 100%;
    background: #FFFFFF;
    border: 1.5px solid rgba(26, 56, 40, 0.12);
    border-radius: 9999px;
    display: flex;
    align-items: center;
    padding: 6px 8px 6px 20px;
    box-shadow: 0 10px 28px rgba(26, 56, 40, 0.07);
    transition: border-color 0.2s ease, box-shadow 0.2s ease;
  }
  .pill-wrapper:focus-within {
    border-color: #244E37;
    box-shadow: 0 12px 34px rgba(36, 78, 55, 0.15);
  }
  .search-icon {
    font-size: 18px;
    margin-right: 12px;
    user-select: none;
    line-height: 1;
  }
  input {
    flex: 1;
    border: none;
    outline: none;
    background: transparent;
    font-family: inherit;
    font-size: 14.5px;
    font-weight: 500;
    color: #1A3828;
  }
  input::placeholder {
    color: #688574;
    opacity: 0.95;
    transition: opacity 0.15s ease;
  }
  .send-btn {
    background-color: #244E37;
    border: none;
    outline: none;
    border-radius: 50%;
    width: 40px;
    height: 40px;
    min-width: 40px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    box-shadow: 0 4px 12px rgba(36, 78, 55, 0.22);
    transition: transform 0.15s ease, background-color 0.15s ease;
  }
  .send-btn:hover {
    background-color: #1A3828;
    transform: scale(1.05);
  }
  .send-btn svg {
    width: 17px;
    height: 17px;
    fill: none;
    stroke: #FFFFFF;
    stroke-width: 2.5;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
</style>
</head>
<body>
  <div class="search-container">
    <div class="pill-wrapper">
      <div class="search-icon">🔍</div>
      <input type="text" id="alpineInput" placeholder="Ask Alpine — Where would you like to wander?" autocomplete="off" />
      <button type="button" class="send-btn" id="sendBtn" title="Search">
        <svg viewBox="0 0 24 24">
          <line x1="5" y1="12" x2="19" y2="12"></line>
          <polyline points="12 5 19 12 12 19"></polyline>
        </svg>
      </button>
    </div>
  </div>

  <script>
    function doSubmit() {
      const input = document.getElementById('alpineInput');
      let val = input.value.trim();
      
      if (!val) {
        val = input.getAttribute('placeholder') || '';
        val = val.replace(/^Ask Alpine —\\s*/i, '').replace(/[?]/g, '').trim();
      }
      if (!val) return;

      try {
        const target = new URL(window.parent.location.href);
        target.searchParams.set('q', val);
        window.parent.location.assign(target.href);
      } catch (err) {
        try {
          const target = new URL(window.top.location.href);
          target.searchParams.set('q', val);
          window.top.location.assign(target.href);
        } catch (err2) {
          const origin = window.location.ancestorOrigins ? window.location.ancestorOrigins[0] : window.location.origin;
          const target = new URL(origin);
          target.searchParams.set('q', val);
          window.open(target.href, '_top');
        }
      }
    }

    document.getElementById('sendBtn').addEventListener('click', doSubmit);
    document.getElementById('alpineInput').addEventListener('keydown', function(e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        doSubmit();
      }
    });

    const phrases = [
      "Ask Alpine — Where would you like to wander?",
      "Plan a 5-day Sikkim Silk Route expedition?",
      "Find heritage mountain lodges in Darjeeling?",
      "Explore living root bridges & canyons in Meghalaya?",
      "Curate a scenic 4-day tour with a dedicated cab?"
    ];

    let phraseIdx = 0;
    let charIdx = phrases[0].length;
    let isDeleting = true;
    let isUserTyping = false;
    const inputElem = document.getElementById('alpineInput');

    inputElem.addEventListener('focus', () => { isUserTyping = true; });
    inputElem.addEventListener('blur', () => {
      if (inputElem.value.trim().length === 0) {
        isUserTyping = false;
      }
    });
    inputElem.addEventListener('input', () => {
      isUserTyping = inputElem.value.length > 0;
    });

    function typeLoop() {
      if (!isUserTyping && inputElem.value.length === 0) {
        const currentPhrase = phrases[phraseIdx];
        if (isDeleting) {
          inputElem.setAttribute('placeholder', currentPhrase.substring(0, charIdx));
          charIdx--;
          if (charIdx < 0) {
            isDeleting = false;
            phraseIdx = (phraseIdx + 1) % phrases.length;
            charIdx = 0;
            setTimeout(typeLoop, 350);
            return;
          }
        } else {
          inputElem.setAttribute('placeholder', currentPhrase.substring(0, charIdx));
          charIdx++;
          if (charIdx > currentPhrase.length) {
            isDeleting = true;
            setTimeout(typeLoop, 2200);
            return;
          }
        }
      }
      const speed = isDeleting ? 25 : 50;
      setTimeout(typeLoop, speed);
    }
    setTimeout(typeLoop, 2200);
  </script>
</body>
</html>""",
        height=76,
    )

    st.markdown(
        """<div style="display:flex; justify-content:space-between; align-items:center; margin: 20px 4px 12px 4px;">
<div style="font-size:1.2rem; font-weight:700; color:#1A3828;">Inspiring Destinations</div>
<div style="font-size:13px; color:#557461; font-weight:600;">Signature Circuits</div>
</div>""",
        unsafe_allow_html=True
    )

    dest_cols = st.columns(3, gap="medium")
    for idx, d in enumerate(LIVE_ITINERARIES[:3]):
        with dest_cols[idx]:
            card_html = f"""<div class="dest-card-styled">
<img src="{d['image']}" alt="{d['title']}" onerror="this.src='{DEFAULT_CARD_IMG}'" />
<div class="dest-scrim-overlay">
<div>
<div class="dest-card-title">{d['title'].split('&')[0].strip()}</div>
<div class="dest-card-sub">{d['sector']} • {d['duration']}</div>
</div>
<div class="dest-arrow-pill">→</div>
</div>
</div>"""
            st.markdown(card_html, unsafe_allow_html=True)
            if st.button(f"Explore {d['title'].split('&')[0].strip()}", key=f"dest_btn_{idx}", use_container_width=True):
                with st.spinner(f"Loading {d['title']} Expedition..."):
                    plan = get_or_generate_itinerary(d)
                    st.session_state.itinerary_data = plan
                    st.rerun()

    st.markdown(
        """<div style="display:flex; justify-content:space-between; align-items:center; margin: 24px 4px 12px 4px;">
<div style="font-size:1.2rem; font-weight:700; color:#1A3828;">Quick Actions</div>
<div style="font-size:12.5px; color:#557461; font-weight:600;">Explore Modes</div>
</div>""",
        unsafe_allow_html=True
    )

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

    # CONSTRAINED THUMBNAIL (140x95 - PREVENTS IMAGE BLOWOUT)
    primary_spot = getattr(data.days[0], "stay_location", None) or data.days[0].place_name
    coords = get_coords_for_place(primary_spot)
    weather_data = fetch_live_weather(coords[0], coords[1])

    st.markdown(
        f"""<div style="display:flex; align-items:center; justify-content:space-between; gap:20px; margin: 12px 0 16px 0; width:100%;">
  <div style="flex:1; min-width:0;">
    <div style="font-family:'Playfair Display', Georgia, serif; font-size:1.85rem; font-weight:700; color:#1A3828; line-height:1.2; margin-bottom:4px;">
      {data.tour_title}
    </div>
    <div style="font-size:13.5px; color:#557461; font-weight:600; margin-bottom:10px;">
      {data.duration} • {data.sector}
    </div>
    <div style="display:flex; align-items:center; gap:0px;">
      <img src="https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=100&q=80" style="width:34px; height:34px; border-radius:50%; border:2px solid #FFFFFF; object-fit:cover; margin-right:-8px;" />
      <img src="https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?auto=format&fit=crop&w=100&q=80" style="width:34px; height:34px; border-radius:50%; border:2px solid #FFFFFF; object-fit:cover; margin-right:-8px;" />
      <img src="https://images.unsplash.com/photo-1500648767791-00dcc994a43e?auto=format&fit=crop&w=100&q=80" style="width:34px; height:34px; border-radius:50%; border:2px solid #FFFFFF; object-fit:cover; margin-right:-8px;" />
      <div style="width:34px; height:34px; border-radius:50%; background:#EBF3EC; border:2px solid #FFFFFF; display:flex; align-items:center; justify-content:center; font-size:11px; font-weight:700; color:#244E37;">+2</div>
    </div>
  </div>
  <div style="flex-shrink:0;">
    <img src="{DEFAULT_CARD_IMG}" style="width:140px; height:95px; min-width:140px; max-width:140px; border-radius:18px; object-fit:cover; box-shadow:0 6px 18px rgba(26,56,40,0.1); border:1px solid rgba(255,255,255,0.8);" />
  </div>
</div>""",
        unsafe_allow_html=True
    )

    telemetry_placeholder = st.empty()

    tab_cols = st.columns(3, gap="small")
    tabs_list = ["Itinerary", "Transport", "Stay"]
    for idx, tab_name in enumerate(tabs_list):
        with tab_cols[idx]:
            is_active = (st.session_state.itin_tab == tab_name)
            if st.button(tab_name, key=f"tab_nav_{tab_name.lower()}", type="primary" if is_active else "secondary", use_container_width=True):
                st.session_state.itin_tab = tab_name
                st.rerun()

    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)

    with ThreadPoolExecutor(max_workers=min(len(data.days), 6)) as executor:
        photos_results = list(executor.map(lambda d: search_key_spot_images(d.place_name, max_results=1), data.days))

    # ITINERARY TAB
    if st.session_state.itin_tab == "Itinerary":
        for idx, day in enumerate(data.days):
            spot_img = photos_results[idx][0]["url"] if (idx < len(photos_results) and photos_results[idx]) else DEFAULT_CARD_IMG
            col_rail, col_card, col_thumb = st.columns([0.6, 6.0, 1.4], gap="small")
            with col_rail:
                st.markdown(
                    f"""<div style="display:flex; flex-direction:column; align-items:center; margin-top:6px;">
  <div style="font-size:10px; font-weight:700; color:#557461; text-transform:uppercase;">Day</div>
  <div style="width:34px; height:34px; border-radius:50%; background:#244E37; color:#FFFFFF; font-size:14px; font-weight:700; display:flex; align-items:center; justify-content:center;">{day.day_number}</div>
  <div style="width:2px; height:65px; border-left:2px dashed rgba(36,78,55,0.25);"></div>
</div>""",
                    unsafe_allow_html=True
                )
            with col_card:
                st.markdown(f"<div style='font-family:\"Playfair Display\", serif; font-size:17px; font-weight:700; color:#1A3828;'>{day.route_title}</div>", unsafe_allow_html=True)
                bullets_list = day.bullets if isinstance(day.bullets, list) else [str(day.bullets)]
                for b in bullets_list[:3]:
                    if b:
                        st.markdown(f"<div style='font-size:13px; color:#314B3B; line-height:1.55;'>✦ {b.strip()}</div>", unsafe_allow_html=True)
            with col_thumb:
                st.markdown(f'<img src="{spot_img}" style="width:90px; height:90px; border-radius:16px; object-fit:cover;" />', unsafe_allow_html=True)

    # TRANSPORT TAB
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

    # STAY TAB
    elif st.session_state.itin_tab == "Stay":
        nights_data = resolve_all_stays_for_itinerary(data)
        room_tier_list = list(ROOM_TIER_PREMIUM_MAP.keys())
        cur_tier_idx = room_tier_list.index(st.session_state.selected_room_tier) if st.session_state.selected_room_tier in room_tier_list else 0

        chosen_tier_radio = st.radio("Select Room Tier", room_tier_list, index=cur_tier_idx, horizontal=True)
        if chosen_tier_radio != st.session_state.selected_room_tier:
            st.session_state.selected_room_tier = chosen_tier_radio
            st.rerun()

        for night_idx, n_info in nights_data.items():
            st.markdown(f"**Night {night_idx} — {n_info['town']}**")
            current_selected = st.session_state.selected_stays.get(night_idx, {}).get("stay_name", "")
            for s_idx, s in enumerate(n_info["stays"]):
                is_selected = (s["stay_name"] == current_selected)
                c_c, c_b = st.columns([4.4, 1.4], gap="small")
                with c_c:
                    st.markdown(f"🏡 **{s['stay_name']}** ({s['property_type']}) — ₹{s['price_bracket']} {s.get('pricing_type', 'Per Head')}")
                with c_b:
                    if is_selected:
                        st.markdown('<div class="stay-active-capsule">✦ Reserved</div>', unsafe_allow_html=True)
                    else:
                        if st.button("Select Stay", key=f"btn_pick_stay_{night_idx}_{s_idx}", use_container_width=True):
                            st.session_state.selected_stays[night_idx] = s
                            st.rerun()

    # Dynamic Telemetry Card Render
    pricing_result = compute_transparent_budget(data)
    est_total_budget = pricing_result["grand_total"]
    est_per_head = pricing_result["per_head"]
    cur_pax = pricing_result["num_heads"]
    est_total_distance = sum([45 + (d.day_number * 10) for d in data.days])

    telemetry_html = textwrap.dedent(f"""
    <div style="background:#FFFFFF; border:1px solid rgba(26,56,40,0.08); border-radius:22px; padding:18px 22px; box-shadow:0 4px 18px rgba(26,56,40,0.04); margin-bottom:18px; width:100%;">
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <div>
          <div style="font-size:11px; color:#688574; font-weight:600; text-transform:uppercase;">Est. Distance</div>
          <div style="font-size:15px; font-weight:800; color:#1A3828;">{est_total_distance} km</div>
        </div>
        <div style="width:1px; height:26px; background:rgba(26,56,40,0.08);"></div>
        <div>
          <div style="font-size:11px; color:#688574; font-weight:600; text-transform:uppercase;">Est. Budget ({cur_pax} Travelers)</div>
          <div style="font-size:16px; font-weight:800; color:#1A3828;">₹{est_total_budget:,.0f} <span style="font-size:11.5px; font-weight:600; color:#2E5E3F;">(₹{est_per_head:,.0f}/head)</span></div>
        </div>
        <div style="width:1px; height:26px; background:rgba(26,56,40,0.08);"></div>
        <div>
          <div style="font-size:11px; color:#688574; font-weight:600; text-transform:uppercase;">Live Weather</div>
          <div style="font-size:15px; font-weight:800; color:#1A3828;">{weather_data['temperature']}</div>
        </div>
      </div>
    </div>
    """).strip()
    telemetry_placeholder.markdown(telemetry_html, unsafe_allow_html=True)

    if st.session_state.get("auto_open_booking"):
        st.session_state.auto_open_booking = False
        current_chosen_stays = list(st.session_state.selected_stays.values())
        open_package_booking_dialog(data, current_chosen_stays, selected_room_tier=st.session_state.selected_room_tier)

    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
    deck_c1, deck_c2 = st.columns([4, 1], gap="small")
    with deck_c1:
        if st.button("✨ Lock Reservation & Pay Advance ➔", type="primary", use_container_width=True):
            current_chosen_stays = list(st.session_state.selected_stays.values())
            open_package_booking_dialog(data, current_chosen_stays, selected_room_tier=st.session_state.selected_room_tier)
    with deck_c2:
        guest_url = generate_guest_portal_url(data)
        st.markdown(
            f'<a href="{guest_url}" target="_blank" style="display:flex; align-items:center; justify-content:center; background:#FFFFFF; border:1px solid rgba(26,56,40,0.12); height:44px; border-radius:9999px; font-weight:700; text-decoration:none; font-size:13px; color:#244E37;">📱 Pass</a>',
            unsafe_allow_html=True
        )
