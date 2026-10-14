import os
import glob
import json
import uuid
import random
import re
import zlib
import base64
from io import BytesIO
import asyncio
import textwrap
import urllib.parse
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
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

if "applied_coupon" not in st.session_state:
    st.session_state.applied_coupon = None

if "use_wallet" not in st.session_state:
    st.session_state.use_wallet = False

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

# Your exact Google Spreadsheet ID
CATALOG_SHEET_ID = os.environ.get(
    "CATALOG_SHEET_ID",
    "1fbDtDmXR2QS15V3oY6dAIW64gcqMui3vTMrndxsOYVQ",
)

DEFAULT_CARD_IMG = "https://images.unsplash.com/photo-1544735716-392fe2489ffa?auto=format&fit=crop&w=900&q=80"

# ---------------------------------------------------------------------------
# ASSET ENCODERS (AUTOMATIC MULTI-FOLDER & EXTENSION RESOLVER)
# ---------------------------------------------------------------------------
def resolve_asset_path(filename: str) -> str:
    """Checks the root folder, assets/, static/, and case variations."""
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
        # 1. Exact filename match
        direct_path = os.path.join(c_dir, filename) if c_dir else filename
        if os.path.isfile(direct_path):
            return direct_path
        
        # 2. Extension variation match
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

# Automatic resolution for your logo, hero background, and action icons
APP_LOGO_SRC = get_image_base64("logo.png")
HERO_BG_SRC = get_image_base64("hero_bg.png")

AI_ICON_SRC = get_image_base64("icon_ai.png", fallback_url="https://img.icons8.com/fluency/96/sparkling--v1.png")
ROUTE_ICON_SRC = get_image_base64("icon_route.png", fallback_url="https://img.icons8.com/fluency/96/map-pin.png")
BUDGET_ICON_SRC = get_image_base64("icon_budget.png", fallback_url="https://img.icons8.com/fluency/96/wallet.png")
GUIDE_ICON_SRC = get_image_base64("icon_guide.png", fallback_url="https://img.icons8.com/fluency/96/open-book.png")

# ---------------------------------------------------------------------------
# ROBUST GEMINI STREAMER WITH AUTOMATIC CAPACITY FALLBACK
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
# GUEST DIGITAL PASS PORTAL (STANDALONE CLIENT LINK)
# ---------------------------------------------------------------------------
def check_and_render_guest_portal():
    params = st.query_params
    if params.get("portal") == "true" and "data" in params:
        try:
            encoded = params.get("data")
            raw_bytes = zlib.decompress(base64.urlsafe_b64decode(encoded))
            summary = json.loads(raw_bytes.decode("utf-8"))

            st.markdown(
                """<style>
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,600;0,700;1,600&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap');
html, body, [data-testid="stAppViewContainer"] {
  background: #F4F7F4 !important;
  font-family: 'Plus Jakarta Sans', sans-serif !important;
  color: #1A3828 !important;
}
.guest-card {
  background: #ffffff;
  border: 1px solid rgba(34, 71, 48, 0.08);
  border-radius: 20px;
  padding: 22px;
  margin-bottom: 16px;
  box-shadow: 0 4px 20px rgba(34, 71, 48, 0.04);
}
</style>""",
                unsafe_allow_html=True
            )

            st.markdown(f"<h1 style='font-family:\"Playfair Display\", serif; color:#1A3828; font-size:2rem;'>🌿 {summary['t']}</h1>", unsafe_allow_html=True)
            st.caption(f"📍 {summary['s']} • ⏱️ {summary['d']} • Wondoo Digital Itinerary Pass")
            st.markdown("<hr style='border-color: rgba(34,71,48,0.12); margin: 12px 0 20px 0;'>", unsafe_allow_html=True)

            for d in summary.get("days", []):
                halt_info = (
                    f"<span style='color:#1A3828; font-weight:700; background:#E2EDE4; padding:3px 9px; border-radius:8px;'>🌙 Stay at: {d['h']}</span>"
                    if d.get("h")
                    else "<span style='color:#6B8073;'>🛫 Departure / Drop-off</span>"
                )
                bullets_html = "".join([f"<li style='color:#314B3B; margin-bottom:6px; line-height:1.6;'>✦ {b}</li>" for b in d.get("b", [])])
                st.markdown(
                    f"""<div class="guest-card">
<div style="font-family:'Playfair Display', serif; font-size:19px; font-weight:700; color:#1A3828; margin-bottom:4px;">
Day {d['n']}: {d['r']}
</div>
<div style="font-size:13px; color:#557461; font-weight:600; margin-bottom:12px;">
📍 Key Spot: <b style="color:#1A3828;">{d['p']}</b> &nbsp;|&nbsp; {halt_info}
</div>
<ul style="list-style:none; padding-left:0; margin:0;">{bullets_html}</ul>
</div>""",
                    unsafe_allow_html=True
                )

            wa_chat_text = urllib.parse.quote(f"Hi Wondoo Team, I am viewing my guest itinerary pass for '{summary['t']}'.")
            st.markdown(
                f"""<a href="https://api.whatsapp.com/send?phone={AGENCY_WHATSAPP_NUMBER}&text={wa_chat_text}" target="_blank" style="
display:block; text-align:center; background:#1A3828; color:#FFFFFF; padding:14px;
border-radius:9999px; font-weight:700; text-decoration:none; margin-top:20px; font-size:15px;
">💬 Connect with Tour Concierge on WhatsApp</a>""",
                unsafe_allow_html=True
            )
            st.stop()
        except Exception:
            st.error("Invalid or expired digital guest itinerary link.")
            st.stop()

check_and_render_guest_portal()

# ---------------------------------------------------------------------------
# TIME & TELEMETRY
# ---------------------------------------------------------------------------
ist_tz = timezone(timedelta(hours=5, minutes=30))
now_ist = datetime.now(ist_tz)
current_hour_ist = now_ist.hour + (now_ist.minute / 60.0)
is_day_mode = 6.0 <= current_hour_ist < 18.5
ist_time_str = now_ist.strftime("%I:%M %p")
period_label = f"☀️ {ist_time_str} IST" if is_day_mode else f"🌙 {ist_time_str} IST"

ALPINE_FACTS = [
    "🏔️ **Tiger Hill Sunrise**: Morning sunlight illuminates Mt. Everest and Mt. Kanchenjunga simultaneously before valleys catch dawn.",
    "🍵 **Darjeeling First Flush**: Harvested from mid-March to May across steep slope elevations, producing a prized light floral muscatel cup.",
    "🚗 **Mountain Pacing**: Hill drives across Sikkim, Himachal, and Uttarakhand average 20–25 km/h due to winding hairpin bends.",
    "🪪 **Protected Area Permits**: High-altitude frontiers like Nathula, Tsomgo, and Tawang require registered permits arranged 24h prior.",
    "🌴 **Kerala Backwaters**: Vembanad Lake connects over 900 km of palm-fringed lagoons, best navigated on traditional Kettuvallam houseboats.",
    "🏝️ **Andaman Horizons**: Radhanagar Beach on Havelock Island features shallow turquoise reefs ranked among Asia's cleanest shorelines.",
    "🛕 **Odisha Heritage**: Konark's 13th-century Sun Temple is engineered as a colossal 24-wheel stone chariot aligned with the sun's trajectory."
]

COORDINATES_DB = {
    "bagdogra": (26.6812, 88.3286),
    "siliguri": (26.7271, 88.3953),
    "njp": (26.6853, 88.4414),
    "darjeeling": (27.0410, 88.2663),
    "kalimpong": (27.0594, 88.4695),
    "gangtok": (27.3389, 88.6065),
    "pelling": (27.3174, 88.2427),
    "zuluk": (27.2519, 88.7808),
    "nathang": (27.3228, 88.8267),
    "shillong": (25.5788, 91.8933),
    "cherrapunji": (25.2986, 91.5822),
    "dawki": (25.1884, 92.0196),
    "munnar": (10.0889, 77.0595),
    "alleppey": (9.4981, 76.3388),
}

WEATHER_CODE_MAP = {
    0: ("☀️ Clear Sky", "Optimal mountain visibility"),
    1: ("🌤️ Mainly Clear", "Mild sunshine"),
    2: ("⛅ Partly Cloudy", "Scattered ridge mist"),
    3: ("☁️ Overcast", "Low cloud base"),
    45: ("🌫️ Dense Fog", "Early morning hill mist"),
    61: ("🌧️ Light Rain", "Carry water-resistant layers"),
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
        desc, advisory = WEATHER_CODE_MAP.get(code, ("⛅ Alpine Breeze", "Pleasant weather"))
        return {"temperature": f"{temp}°C", "desc": desc, "advisory": advisory}
    except Exception:
        return {"temperature": "14°C", "desc": "⛅ Alpine Air", "advisory": "Comfortable woolen layer advised"}

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
# DEFAULT VERIFIED STAYS CATALOG (SEED DATA FROM YOUR SHEET)
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
        "town_keys": "rinchenpong, chayatal, bermiok",
        "stay_name": "The Yangsum Farm Retreat",
        "altitude": "5,570 ft",
        "property_type": "Heritage Organic Farmstay",
        "rating": "4.9 ★",
        "price_bracket": "5000",
        "pricing_type": "Per Room",
        "image": "https://images.unsplash.com/photo-1520250497591-112f2f40a3f4?auto=format&fit=crop&w=900&q=80"
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
    },
    {
        "town_keys": "kalimpong, rishi road, delo",
        "stay_name": "Morgan House Heritage Lodge",
        "altitude": "4,250 ft",
        "property_type": "British Colonial Villa",
        "rating": "4.7 ★",
        "price_bracket": "1800",
        "pricing_type": "Per Head",
        "image": "https://images.unsplash.com/photo-1542314831-068cd1dbfeeb?auto=format&fit=crop&w=900&q=80"
    }
]

# ---------------------------------------------------------------------------
# EXACT GOOGLE SHEET STAY MATCHER (MULTIPLE TABS + FALLBACK)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=60)
def load_stays_raw_from_sheet(sheet_id: str) -> List[Dict[str, Any]]:
    resolved_id = sheet_id
    try:
        if "CATALOG_SHEET_ID" in st.secrets:
            resolved_id = st.secrets["CATALOG_SHEET_ID"]
    except Exception:
        pass
    
    if "CATALOG_SHEET_ID" in os.environ:
        resolved_id = os.environ["CATALOG_SHEET_ID"]

    candidate_urls = [
        f"https://docs.google.com/spreadsheets/d/{resolved_id}/gviz/tq?tqx=out:csv&sheet=Stays",
        f"https://docs.google.com/spreadsheets/d/{resolved_id}/gviz/tq?tqx=out:csv&sheet=stays",
        f"https://docs.google.com/spreadsheets/d/{resolved_id}/gviz/tq?tqx=out:csv&sheet=STAYS",
        f"https://docs.google.com/spreadsheets/d/{resolved_id}/gviz/tq?tqx=out:csv&sheet=Stay",
        f"https://docs.google.com/spreadsheets/d/{resolved_id}/gviz/tq?tqx=out:csv&sheet=Sheet1",
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
            
            is_match = False
            for cw in clean_words:
                if any(cw in st_town or st_town in cw for st_town in sheet_towns):
                    is_match = True
                    break
            
            if is_match and s not in matched_stays:
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

def resolve_stays_for_itinerary(itinerary: TourItinerary) -> list:
    nights_data = resolve_all_stays_for_itinerary(itinerary)
    flattened_stays = []
    for night_idx, info in nights_data.items():
        if info["stays"]:
            flattened_stays.append(info["stays"][0])
        else:
            flattened_stays.append({
                "night": night_idx,
                "day_num": info["day_num"],
                "town": info["town"],
                "stay_name": f"Curated Boutique Stay in {info['town']}",
                "property_type": "Handpicked Mountain Lodge",
                "altitude": "Scenic Elevation",
                "rating": "4.8 ★",
                "price_bracket": "2000",
                "pricing_type": "Per Head",
                "image": DEFAULT_CARD_IMG,
                "status": "ALLOCATED_AT_CHECKOUT"
            })
    return flattened_stays

# ---------------------------------------------------------------------------
# FALLBACK CATALOG LOADERS
# ---------------------------------------------------------------------------
DEFAULT_FALLBACK_ITINERARIES = [
    {
        "title": "Classic Darjeeling & Misty Kalimpong",
        "duration": "4 Days • 3 Nights",
        "sector": "West Bengal, India",
        "elevation": "2,042m - 1,250m",
        "image": "https://images.unsplash.com/photo-1544735716-392fe2489ffa?auto=format&fit=crop&w=900&q=80",
        "highlights": [
            "Tiger Hill 4:00 AM Sunrise over Mt. Kanchenjunga",
            "Heritage UNESCO Toy Train joyride & Batasia Loop",
            "Tea garden walk & organic brew tasting at Happy Valley",
            "Delo Hill viewpoints & cactus nurseries in Kalimpong"
        ],
        "default_prompt": "Plan an authentic exploration of Darjeeling and Kalimpong focusing on tea estates, boutique stays, Tiger Hill sunrise, and scenic drives."
    },
    {
        "title": "Sikkim Silk Route & High Alpine Lakes",
        "duration": "5 Days • 4 Nights",
        "sector": "East Sikkim, India",
        "elevation": "1,500m - 3,753m",
        "image": "https://images.unsplash.com/photo-1626621341517-bbf3d9990a23?auto=format&fit=crop&w=900&q=80",
        "highlights": [
            "Zuluk zig-zag 32 hairpin loops with Kanchenjunga vistas",
            "Sacred Kupup Elephant Lake & Baba Harbhajan Mandir",
            "Sunrise over Thambi View Point",
            "Historic Silk Route heritage trade hamlet stays"
        ],
        "default_prompt": "Plan an expedition through Sillery Gaon, Zuluk, Nathang Valley, and Reshikhola with local homestays and mountain passes."
    },
    {
        "title": "Meghalaya Living Roots & Cloud Canyons",
        "duration": "5 Days • 4 Nights",
        "sector": "Meghalaya, India",
        "elevation": "1,496m - 180m",
        "image": "https://images.unsplash.com/photo-1605649487212-47bdab064df7?auto=format&fit=crop&w=900&q=80",
        "highlights": [
            "Double Decker Living Root Bridges in Nongriat",
            "Crystal clear Dawki river boat navigation",
            "Nohkalikai waterfalls & Mawsmai cave expeditions",
            "Serene pine hills and café culture in Shillong"
        ],
        "default_prompt": "Plan a lush 5-day adventure across Shillong, Cherrapunji, and Dawki focusing on root bridges, waterfalls, and local Khasi homestays."
    }
]

DEFAULT_FALLBACK_PACKAGES = [
    {
        "title": "Darjeeling & Kalimpong Alpine Retreat",
        "duration": "4 Days • 3 Nights",
        "price_per_head": "₹12,499",
        "stay_type": "Heritage Tea Estate + Boutique View Lodge",
        "transit": "Dedicated Innova / Scorpio",
        "meals": "MAP (Breakfast + Dinner)",
        "features": [
            "Private pickup & drop from Bagdogra Airport (IXB)",
            "3 Nights accommodation in curated premium view rooms",
            "Dedicated mountain sightseeing vehicle including all tolls",
            "Tiger Hill morning pass & permits managed"
        ]
    },
    {
        "title": "East Sikkim Silk Route Homestay Explorer",
        "duration": "5 Days • 4 Nights",
        "price_per_head": "₹14,950",
        "stay_type": "Authentic Mountain View Homestays",
        "transit": "Dedicated Bolero / Scorpio 4x4",
        "meals": "AP (All Meals)",
        "features": [
            "Zuluk, Nathang Valley, and Aritar Lake coverage",
            "Inner Line Permits (ILP) included for all travelers",
            "Home-cooked organic meals",
            "Full transit from Siliguri / NJP"
        ]
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
            highlights_raw = str(row.get("highlights", ""))
            highlights = [h.strip() for h in highlights_raw.split(";") if h.strip()] if highlights_raw.lower() != "nan" else []
            itineraries.append({
                "title": title,
                "duration": str(row.get("duration", "4 Days • 3 Nights")).strip(),
                "sector": str(row.get("sector", "")).strip(),
                "elevation": str(row.get("elevation", "")).strip(),
                "image": str(row.get("image", DEFAULT_CARD_IMG)).strip(),
                "highlights": highlights,
                "default_prompt": str(row.get("default_prompt", f"Plan an authentic {title} tour.")).strip()
            })
        return itineraries if itineraries else DEFAULT_FALLBACK_ITINERARIES
    except Exception:
        return DEFAULT_FALLBACK_ITINERARIES

@st.cache_data(ttl=60)
def load_packages_from_sheet(sheet_id: str) -> List[Dict[str, Any]]:
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet=Packages"
    try:
        df = pd.read_csv(url)
        df.columns = [str(col).strip().lower() for col in df.columns]
        packages = []
        for _, row in df.iterrows():
            title = str(row.get("title", "")).strip()
            if not title or title.lower() == "nan":
                continue
            features_raw = str(row.get("features", ""))
            features = [f.strip() for f in features_raw.split(";") if f.strip()] if features_raw.lower() != "nan" else []
            packages.append({
                "title": title,
                "duration": str(row.get("duration", "")).strip(),
                "price_per_head": str(row.get("price_per_head", "")).strip(),
                "stay_type": str(row.get("stay_type", "")).strip(),
                "transit": str(row.get("transit", "")).strip(),
                "meals": str(row.get("meals", "")).strip(),
                "features": features
            })
        return packages if packages else DEFAULT_FALLBACK_PACKAGES
    except Exception:
        return DEFAULT_FALLBACK_PACKAGES

LIVE_ITINERARIES = load_itineraries_from_sheet(CATALOG_SHEET_ID)
LIVE_PACKAGES = load_packages_from_sheet(CATALOG_SHEET_ID)

# ---------------------------------------------------------------------------
# DYNAMIC ITINERARY RECOMMENDATIONS GENERATOR
# ---------------------------------------------------------------------------
@st.cache_data(ttl=3600)
def fetch_dynamic_recommendations(tour_title: str, sector: str, places_str: str) -> dict:
    prompt = f"""Generate practical, tailored travel tips for this itinerary:
Tour: {tour_title}
Region/Sector: {sector}
Key Destinations: {places_str}

Provide exactly 4 distinct sections in valid JSON:
{{
  "food": ["2-3 specific dishes/drinks authentic to these exact destinations"],
  "photo_spots": ["2 specific iconic viewpoints/moments for these places with timings"],
  "gear": ["2 essential packing/clothing items suited for this exact altitude/terrain"],
  "etiquette": ["2 local cultural, monastery, or environmental etiquette tips"]
}}"""
    try:
        api_key = os.environ.get("GEMINI_API_KEY", "")
        client = genai.Client(api_key=api_key) if api_key else genai.Client()
        response = client.models.generate_content(
            model=PRIMARY_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.3,
                response_mime_type="application/json"
            )
        )
        return json.loads(response.text)
    except Exception:
        return {
            "food": [
                f"Authentic local regional delicacies of {sector}.",
                "Locally brewed beverages and seasonal hot soups."
            ],
            "photo_spots": [
                f"Golden hour viewpoints across {sector} at dawn (05:30 AM).",
                "Scenic river banks and high ridge overlooks during midday breaks."
            ],
            "gear": [
                "Layered woolens or breathable windbreakers suited for local elevation changes.",
                "Sturdy walking shoes with traction for walking trails and cobblestone steps."
            ],
            "etiquette": [
                "Respect local customs and request permission before photographing sacred shrines or villagers.",
                "Follow Leave No Trace principles; keep mountain water bodies and trails pristine."
            ]
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
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 *FINANCIAL SUMMARY*\n"
        f"• Grand Package Fare: ₹{info['grand_total']:,.0f}\n"
        f"• 25% Advance Token Paid: ₹{info['advance_paid']:,.0f}\n"
        f"• Balance Due on Arrival: ₹{info['balance_due']:,.0f}\n"
        f"• Promo Coupon: {info.get('coupon_applied', 'NONE')}\n"
        f"• Bank UTR / Ref: {info['transaction_utr']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ *Status*: Confirmed & Locked\n\n"
        f"Please share our driver contact and hotel check-in vouchers."
    )
    return urllib.parse.quote(message)

# ---------------------------------------------------------------------------
# BOOKING MODAL DIALOG & TOKEN LOCK ENGINE
# ---------------------------------------------------------------------------
@st.dialog("Expedition Reservation & Token Lock", width="large")
def open_package_booking_dialog(itinerary: TourItinerary, matched_stays: list):
    st.markdown(
        f"""<div style="margin-bottom:12px;">
<div style="font-family:'Playfair Display', serif; font-size:1.35rem; font-weight:700; color:#1A3828;">
🌿 {itinerary.tour_title}
</div>
<div style="font-size:13px; color:#557461; font-weight:500;">
{itinerary.duration} • {itinerary.sector} • Handpicked Mountain Stays
</div>
</div>""",
        unsafe_allow_html=True
    )

    tab_specs, tab_payment = st.tabs(["1. Traveler & Circuit Specs", "2. Fare Summary & Token Lock"])

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
            heads = st.number_input("Adult Travelers", min_value=1, max_value=24, value=2, step=1)
        with col_p2:
            rooms = st.number_input("Rooms Required", min_value=1, max_value=12, value=max(1, (heads + 1) // 2), step=1)
        with col_p3:
            cab_choice = st.selectbox(
                "Dedicated Transit Vehicle",
                ["Include Dedicated Cab (Innova/Scorpio)", "Include Bolero 4x4", "Self Transit / Exclude Vehicle"],
                index=0
            )

        col_cpn1, col_cpn2 = st.columns([2.5, 1], gap="small")
        with col_cpn1:
            coupon_input = st.text_input("Promotional Code", placeholder="e.g. ALPINE10, WOND2026", key="dlg_coupon_code")
        with col_cpn2:
            st.markdown("<div style='height:28px;'></div>", unsafe_allow_html=True)
            apply_cpn = st.button("Apply", key="btn_dlg_apply_cpn", use_container_width=True)

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
    quotation = calculate_dynamic_sheet_quotation(
        matched_stays=matched_stays,
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

    with tab_payment:
        discount_row = (
            f"""<div style="display:flex; justify-content:space-between; margin-bottom:6px; font-size:13px; color:#2E5E3F; font-weight:700;">
  <span>Discount ({st.session_state.applied_coupon['code']}):</span>
  <span>- ₹{discount_amount:,.0f}</span>
</div>"""
            if discount_amount > 0
            else ""
        )

        st.markdown(
            f"""<div style="background:#F4F7F4; border:1px solid rgba(26,56,40,0.1); border-radius:18px; padding:16px 20px; margin-bottom:14px;">
<div style="display:flex; justify-content:space-between; margin-bottom:6px; font-size:14px;">
  <span>Base Expedition Package ({heads} Travelers • {rooms} Rooms):</span>
  <b>₹{base_total:,.0f}</b>
</div>
<div style="display:flex; justify-content:space-between; margin-bottom:6px; font-size:13px; color:#557461;">
  <span>Curated Stays & Meal Plans:</span>
  <span>Included</span>
</div>
<div style="display:flex; justify-content:space-between; margin-bottom:6px; font-size:13px; color:#557461;">
  <span>Transit Vehicle:</span>
  <span>{cab_choice.split('(')[0].strip()}</span>
</div>
{discount_row}
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

        booking_ref = f"WAN-{uuid.uuid4().hex[:6].upper()}"
        upi_pay_url = generate_upi_qr_url(
            vpa=UPI_VPA,
            payee_name=UPI_PAYEE_NAME,
            amount=advance_token,
            transaction_ref=booking_ref
        )

        col_qr, col_tx = st.columns([1, 1.4], gap="medium")
        with col_qr:
            st.image(upi_pay_url, caption=f"Scan with GPay / PhonePe / Paytm", width=170)
            st.caption(f"UPI ID: `{UPI_VPA}`")
        with col_tx:
            utr_ref = st.text_input("12-Digit Bank Reference / UTR Number *", placeholder="e.g. 423984029384", key="booking_utr_field")
            st.markdown(
                """<div style="font-size:11px; color:#688574; line-height:1.4; margin-top:-4px;">
✦ Instant lock upon reference submission.<br>
✦ An official booking voucher is immediately transmitted to WhatsApp.
</div>""",
                unsafe_allow_html=True
            )

        if st.button("Confirm Reservation & Dispatch Voucher ➔", type="primary", use_container_width=True):
            if not lead_name.strip() or not lead_phone.strip():
                st.error("Please enter traveler name and WhatsApp contact number.")
            elif not utr_ref.strip() or len(utr_ref.strip()) < 8:
                st.error("Please provide a valid UPI Bank Reference / UTR Number to confirm token payment.")
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
                    "base_total": float(base_total),
                    "discount": float(discount_amount),
                    "grand_total": float(final_grand_total),
                    "advance_paid": float(advance_token),
                    "balance_due": float(balance_payable),
                    "coupon_applied": st.session_state.applied_coupon["code"] if st.session_state.get("applied_coupon") else "NONE",
                    "transaction_utr": utr_ref.strip(),
                    "timestamp": datetime.now(ist_tz).strftime("%Y-%m-%d %H:%M:%S IST")
                }

                try:
                    requests.post(BOOKING_WEBHOOK_URL, json=booking_payload, timeout=3)
                except Exception:
                    pass

                if st.session_state.get("applied_coupon"):
                    try:
                        record_coupon_redemption(st.session_state.applied_coupon["code"], lead_phone.strip())
                    except Exception:
                        pass

                st.session_state.booking_confirmed = booking_payload
                st.rerun()

# ---------------------------------------------------------------------------
# RESPONSIVE CUSTOM CSS
# ---------------------------------------------------------------------------
st.markdown(
    """<style>
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,500;0,600;0,700;1,500;1,600&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

html, body, [data-testid="stAppViewContainer"], section.main, .stApp {
  background-color: #F4F7F4 !important;
  font-family: 'Plus Jakarta Sans', sans-serif !important;
  color: #1A3828 !important;
  scroll-behavior: auto !important;
  scroll-padding-top: 0 !important;
  overflow-anchor: none !important;
}

header[data-testid="stHeader"] {
  display: none !important;
  height: 0 !important;
}

[data-testid="stHeader"] button[kind="header"],
button[data-testid="baseButton-header"],
.stDeployButton {
  display: none !important;
}

.block-container {
  max-width: 1240px !important;
  padding-top: 0.8rem !important;
  margin-top: 0 !important;
  padding-bottom: 3.5rem !important;
  padding-left: 1.2rem !important;
  padding-right: 1.2rem !important;
  margin-left: auto !important;
  margin-right: auto !important;
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
  background-color: transparent !important;
  background-position: center center !important;
  background-repeat: no-repeat !important;
  background-size: cover !important;
  image-rendering: -webkit-optimize-contrast !important;
  image-rendering: crisp-edges !important;
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
  text-shadow: 0 2px 10px rgba(255, 255, 255, 0.7);
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
  text-shadow: 0 1px 8px rgba(255, 255, 255, 0.7);
  margin-bottom: 0px;
}

/* SECTION HEADERS */
.section-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 20px 4px 12px 4px;
}

.section-heading-text {
  font-size: 1.2rem;
  font-weight: 700;
  color: #1A3828;
}

/* INSPIRING DESTINATIONS */
.dest-card-styled {
  position: relative;
  height: 220px;
  width: 100%;
  border-radius: 24px;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.8);
  box-shadow: 0 8px 24px rgba(26, 56, 40, 0.08);
  margin-bottom: 8px;
}

.dest-card-styled img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.dest-scrim-overlay {
  position: absolute;
  bottom: 0; left: 0; right: 0;
  padding: 14px 14px;
  background: linear-gradient(180deg, transparent 0%, rgba(15, 33, 23, 0.85) 75%);
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  color: #FFFFFF;
  text-align: left;
}

.dest-card-title {
  font-family: 'Plus Jakarta Sans', sans-serif;
  font-size: 15px;
  font-weight: 700;
  color: #FFFFFF;
  margin-bottom: 2px;
}

.dest-card-sub {
  font-size: 11px;
  color: #D8E7DC;
}

.dest-arrow-pill {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.35);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: #FFFFFF;
}

/* --------------------------------------------------------------------------
   RESPONSIVE SQUARE ACTION TILES (4 ON DESKTOP, 2 PER ROW ON MOBILE)
   -------------------------------------------------------------------------- */
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
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
  cursor: pointer;
  box-sizing: border-box;
}

.square-action-card-tile:hover {
  transform: translateY(-4px);
  box-shadow: 0 12px 28px rgba(26, 56, 40, 0.1);
  border-color: rgba(36, 78, 55, 0.28);
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
  line-height: 1.25;
}

.square-card-badge-text {
  font-size: 11px;
  color: #557461;
  font-weight: 600;
  margin-top: 4px;
  text-align: center;
}

@media (max-width: 768px) {
  .quick-action-grid-wrap {
    grid-template-columns: repeat(2, 1fr) !important;
    gap: 12px !important;
  }
  .square-action-card-tile {
    border-radius: 20px !important;
    padding: 14px 8px !important;
  }
  .square-card-icon-bubble {
    width: 44px !important;
    height: 44px !important;
    margin-bottom: 8px !important;
  }
  .square-card-icon-bubble img {
    width: 24px !important;
    height: 24px !important;
  }
  .square-card-title-text {
    font-size: 13px !important;
  }
  .square-card-badge-text {
    font-size: 10px !important;
  }
  .hero-illustrated-scene {
    min-height: 230px !important;
    padding: 18px 18px 20px 18px !important;
    background-position: center 82% !important;
  }
  .hero-scene-content { margin-top: 0 !important; }
  .hero-headline-serif { font-size: 2.15rem !important; }
  .editorial-app-bar { flex-direction: column !important; align-items: flex-start !important; gap: 8px !important; }
  .bar-telemetry-pill { width: 100% !important; text-align: center !important; }
}

/* FLOATING CAPSULE CHAT INPUT (ACTIVE IN VIEW 1 - AI CONCIERGE) */
[data-testid="stBottom"] {
  background: transparent !important;
  border: none !important;
  padding-bottom: 12px !important;
}

[data-testid="stBottom"] > div {
  background: transparent !important;
  display: flex !important;
  flex-direction: column !important;
  align-items: center !important;
}

div[data-testid="stChatInput"] {
  max-width: 800px !important; 
  width: 100% !important;
  margin: 0 auto !important;
}

div[data-testid="stChatInput"] > div {
  background: #FFFFFF !important;
  border: 1.5px solid rgba(26, 56, 40, 0.08) !important;
  border-radius: 9999px !important;
  padding: 8px 14px 8px 46px !important;
  position: relative !important;
  box-shadow: 0 10px 30px rgba(26, 56, 40, 0.06) !important;
}

div[data-testid="stChatInput"] > div:focus-within {
  border-color: #244E37 !important;
}

div[data-testid="stChatInput"] textarea {
  color: #1A3828 !important;
  font-size: 14.5px !important;
  padding: 6px 12px 6px 0 !important;
}

div[data-testid="stChatInput"] textarea::placeholder {
  color: #718E7D !important;
  font-weight: 500 !important;
  opacity: 1 !important;
}

div[data-testid="stChatInput"] > div::before {
  content: '🔍';
  position: absolute;
  left: 17px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 15px;
  opacity: 0.65;
}

div[data-testid="stChatInput"] button {
  background-color: #2E593F !important;
  border-radius: 50% !important;
  width: 36px !important;
  height: 36px !important;
  color: #FFFFFF !important;
}

/* EDITORIAL ITINERARY VIEW */
.itin-nav-circle-btn {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: #FFFFFF;
  border: 1px solid rgba(26, 56, 40, 0.08);
  box-shadow: 0 2px 10px rgba(26, 56, 40, 0.04);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  color: #1A3828;
  cursor: pointer;
  text-decoration: none;
}

.itin-header-hero-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
}

.itin-destination-name {
  font-family: 'Playfair Display', Georgia, serif;
  font-size: 1.85rem;
  font-weight: 700;
  color: #1A3828;
  display: flex;
  align-items: center;
  gap: 8px;
  line-height: 1.2;
}

.itin-meta-subline {
  font-size: 13.5px;
  color: #557461;
  font-weight: 500;
  margin: 6px 0 12px 0;
}

.itin-avatar-stack {
  display: flex;
  align-items: center;
}

.itin-avatar-circle {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: 2px solid #FFFFFF;
  margin-left: -8px;
  object-fit: cover;
}

.itin-avatar-circle:first-child {
  margin-left: 0;
}

.itin-avatar-more-pill {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: #EBF3EC;
  border: 2px solid #FFFFFF;
  margin-left: -8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  color: #244E37;
}

.itin-preview-img-card {
  width: 140px;
  height: 100px;
  border-radius: 20px;
  object-fit: cover;
  box-shadow: 0 6px 20px rgba(26, 56, 40, 0.08);
  flex-shrink: 0;
}

/* AI ROUTE OPTIMIZED BOX */
.itin-ai-optimized-box {
  background: #FFFFFF;
  border: 1px solid rgba(26, 56, 40, 0.06);
  border-radius: 24px;
  padding: 18px 20px;
  box-shadow: 0 6px 22px rgba(26, 56, 40, 0.03);
  margin-bottom: 16px;
}

.ai-opt-head-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 16px;
}

.ai-opt-badge-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #244E37;
  font-weight: 700;
  font-size: 14.5px;
}

.ai-opt-subtext {
  font-size: 12px;
  color: #557461;
  margin-top: 4px;
  line-height: 1.4;
}

.ai-route-trajectory-art {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #2E5E3F;
  font-size: 14px;
  padding: 4px 10px;
  background: #F4F7F4;
  border-radius: 12px;
}

.itin-telemetry-metrics-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 14px;
  border-top: 1px solid rgba(26, 56, 40, 0.06);
}

.metric-col-card {
  display: flex;
  align-items: center;
  gap: 10px;
}

.metric-icon-bubble {
  font-size: 18px;
}

.metric-label-small {
  font-size: 11px;
  color: #688574;
  font-weight: 500;
  line-height: 1.1;
}

.metric-value-bold {
  font-size: 15px;
  font-weight: 700;
  color: #1A3828;
}

/* TIMELINE DAY CARDS */
.mockup-timeline-wrap {
  position: relative;
  padding-left: 48px;
  margin-bottom: 20px;
}

.mockup-timeline-dashed-line {
  position: absolute;
  left: 17px;
  top: 36px;
  bottom: 24px;
  width: 2px;
  border-left: 2px dashed rgba(36, 78, 55, 0.28);
}

.mockup-day-entry {
  position: relative;
  margin-bottom: 16px;
}

.mockup-day-circle-tag {
  position: absolute;
  left: -48px;
  top: 16px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.mockup-day-label-txt {
  font-size: 10px;
  font-weight: 600;
  color: #557461;
  text-transform: uppercase;
}

.mockup-day-badge-num {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: #244E37;
  color: #FFFFFF;
  font-size: 14px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 10px rgba(36, 78, 55, 0.2);
}

.mockup-itinerary-card {
  background: #FFFFFF;
  border: 1px solid rgba(26, 56, 40, 0.06);
  border-radius: 22px;
  padding: 16px 18px;
  box-shadow: 0 4px 18px rgba(26, 56, 40, 0.03);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  transition: transform 0.15s ease;
}

.mockup-itinerary-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(26, 56, 40, 0.06);
}

.mockup-card-text-side {
  flex: 1 1 auto;
}

.mockup-card-route-title {
  font-family: 'Playfair Display', Georgia, serif;
  font-size: 16.5px;
  font-weight: 700;
  color: #1A3828;
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.mockup-card-thumb-photo {
  width: 82px;
  height: 82px;
  border-radius: 16px;
  object-fit: cover;
  flex-shrink: 0;
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
  border: 1px solid rgba(26, 56, 40, 0.12) !important;
  color: #244E37 !important;
  font-weight: 600 !important;
  border-radius: 9999px !important;
}

[data-testid="stChatMessage"] {
  background: #FFFFFF !important;
  border: 1px solid rgba(26, 56, 40, 0.06) !important;
  border-radius: 18px !important;
  padding: 14px 18px !important;
  margin-bottom: 12px !important;
  box-shadow: 0 4px 14px rgba(26, 56, 40, 0.03) !important;
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

st.markdown(
    f"""<div class="editorial-app-bar">
<div class="bar-brand-wrap">
<img src="{APP_LOGO_SRC}" class="bar-logo-img" alt="Logo" />
<div>
<div class="bar-title-text">Wondoo <span>Alpine Studio</span></div>
<div class="bar-sub-text">Autonomous Circuit Architect • Curated Mountain Stays • Brochure Studio</div>
</div>
</div>
<div style="display:flex; align-items:center; gap:10px;">
<div class="bar-telemetry-pill">● {period_label}</div>
<div style="background:#244E37; color:#FFFFFF; width:38px; height:38px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:13px;">{user_initial}</div>
</div>
</div>""",
    unsafe_allow_html=True,
)

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

# ===========================================================================
# VIEW 1: DEDICATED AI CONCIERGE CHAT PAGE (CLICKED "AI ITINERARY")
# ===========================================================================
if st.session_state.get("active_view") == "ai_concierge" and not st.session_state.get("itinerary_data"):
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

    if len(st.session_state.messages) > 1:
        c_left, c_center, c_right = st.columns([1, 4, 1])
        with c_center:
            if st.button("✨ Finalize Itinerary & Reveal Curated Stays", type="primary", use_container_width=True):
                with st.spinner("Synthesizing final day-by-day itinerary..."):
                    dialogue_digest = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in st.session_state.messages])
                    extraction_prompt = f"Create an authentic, structured tour itinerary based on this conversation:\n\n{dialogue_digest}"
                    try:
                        plan = generate_itinerary_content(extraction_prompt)
                        st.session_state.itinerary_data = plan
                        st.session_state.active_view = "home"
                        st.rerun()
                    except Exception as e:
                        st.error(f"Generation Error: {e}")

    user_prompt = st.chat_input("Ask Alpine — Where would you like to wander?")
    if user_prompt:
        st.session_state.messages.append({"role": "user", "content": user_prompt})
        with st.chat_message("user", avatar="👤"):
            st.markdown(user_prompt)

        with st.chat_message("assistant", avatar="🌿"):
            random_fact = random.choice(ALPINE_FACTS)
            waiting_banner = st.empty()
            waiting_banner.info(random_fact)

            api_key = os.environ.get("GEMINI_API_KEY", "")
            client = genai.Client(api_key=api_key) if api_key else genai.Client()

            system_instruction = (
                "You are the senior AI Travel Concierge at Wondoo Studio, engaging in an authentic, consultative dialogue.\n\n"
                "CRITICAL FORMATTING & STYLE DIRECTIVES:\n"
                "1. DO NOT GENERATE A DAY-BY-DAY ITINERARY IN THIS CHAT. Keep it conversational in 2 engaging paragraphs.\n"
                "2. MANDATORY CLOSING CALL-TO-ACTION: Prompt them to click the '✨ Finalize Itinerary & Reveal Curated Stays' button right below.\n"
                "Target length: 140 to 190 words."
            )

            contents = [
                types.Content(
                    role="user" if m["role"] == "user" else "model",
                    parts=[types.Part.from_text(text=m["content"])],
                )
                for m in st.session_state.messages
            ]

            response_stream = stream_gemini_with_fallback(client, contents, system_instruction)

            def stream_text_generator():
                first_chunk = True
                for chunk in response_stream:
                    if first_chunk:
                        waiting_banner.empty()
                        first_chunk = False
                    if getattr(chunk, "text", None):
                        yield chunk.text
                    elif getattr(chunk, "candidates", None) and chunk.candidates[0].content:
                        for p in chunk.candidates[0].content.parts:
                            if getattr(p, "text", None):
                                yield p.text

            full_reply = st.write_stream(stream_text_generator())

        st.session_state.messages.append({"role": "assistant", "content": full_reply})
        st.rerun()

# ===========================================================================
# VIEW 2: SMART ROUTE CATALOG (CLICKED "SMART ROUTE")
# ===========================================================================
elif st.session_state.get("active_view") == "smart_route" and not st.session_state.get("itinerary_data"):
    col_back, _ = st.columns([1.5, 4.5])
    with col_back:
        if st.button("← Back to Discover", key="back_to_discover_sr", use_container_width=True):
            st.session_state.active_view = "home"
            st.rerun()

    st.markdown(
        """<div style="margin: 10px 0 20px 0;">
<div style="font-family:'Playfair Display', serif; font-size: 2.1rem; font-weight:700; color:#1A3828; margin-bottom:4px;">Smart Mountain Routes</div>
<div style="font-size:14px; color:#557461;">Directly pulled from our verified Google Sheets route catalog. Select your custom duration to generate.</div>
</div>""",
        unsafe_allow_html=True
    )

    grid_cols = st.columns(2, gap="medium")
    for idx, itin in enumerate(LIVE_ITINERARIES):
        img_url = itin.get("image") if itin.get("image") and str(itin.get("image")).startswith("http") else DEFAULT_CARD_IMG
        with grid_cols[idx % 2]:
            highlights_li = "".join([f"<li style='margin-bottom:4px;'>✦ {h}</li>" for h in itin.get("highlights", [])])
            st.markdown(
                f"""<div style="background:#FFFFFF; border:1px solid rgba(26,56,40,0.08); border-radius:20px; overflow:hidden; box-shadow:0 4px 18px rgba(26,56,40,0.04); margin-bottom:14px;">
<img src="{img_url}" style="width:100%; height:180px; object-fit:cover;" onerror="this.src='{DEFAULT_CARD_IMG}'" />
<div style="padding:16px;">
  <div style="font-size:11px; text-transform:uppercase; color:#2E5E3F; font-weight:700; letter-spacing:0.5px;">{itin['sector']} • {itin['duration']}</div>
  <div style="font-family:'Playfair Display', serif; font-size:18px; font-weight:700; color:#1A3828; margin:4px 0;">{itin['title']}</div>
  <div style="font-size:12.5px; color:#557461; margin-bottom:10px;">Altitude: {itin['elevation']}</div>
  <ul style="list-style:none; padding-left:0; margin:0; font-size:13px; color:#314B3B;">{highlights_li}</ul>
</div>
</div>""",
                unsafe_allow_html=True
            )
            col_pick, col_action = st.columns([1.1, 1.9], gap="small")
            with col_pick:
                custom_days = st.selectbox(
                    "Duration",
                    [3, 4, 5, 6, 7, 8],
                    index=1,
                    format_func=lambda d: f"{d}D / {d-1}N",
                    key=f"sr_picker_{idx}"
                )
            with col_action:
                st.markdown("<div style='height:28px;'></div>", unsafe_allow_html=True)
                if st.button(f"⚡ Generate {custom_days}D Plan", key=f"sr_gen_{idx}", type="primary", use_container_width=True):
                    extraction_prompt = (
                        f"Create an authentic, structured tour itinerary for: {itin['title']}.\n"
                        f"Strict Duration: Exactly {custom_days} Days / {custom_days - 1} Nights.\n"
                        f"Sector: {itin['sector']} ({itin['elevation']}).\n"
                        f"Highlights: {itin['default_prompt']}"
                    )
                    with st.spinner(f"Synthesizing customized {custom_days}D expedition..."):
                        try:
                            plan = generate_itinerary_content(extraction_prompt)
                            st.session_state.itinerary_data = plan
                            st.session_state.active_view = "home"
                            st.rerun()
                        except Exception as e:
                            st.error(f"Generation error: {e}")

# ===========================================================================
# VIEW 3: BUDGET PLAN CATALOG (CLICKED "BUDGET PLAN")
# ===========================================================================
elif st.session_state.get("active_view") == "budget_plan" and not st.session_state.get("itinerary_data"):
    col_back, _ = st.columns([1.5, 4.5])
    with col_back:
        if st.button("← Back to Discover", key="back_to_discover_bp", use_container_width=True):
            st.session_state.active_view = "home"
            st.rerun()

    st.markdown(
        """<div style="margin: 10px 0 20px 0;">
<div style="font-family:'Playfair Display', serif; font-size: 2.1rem; font-weight:700; color:#1A3828; margin-bottom:4px;">Curated Tour Packages</div>
<div style="font-size:14px; color:#557461;">Fixed transparent packages loaded live from your Google Sheets catalog.</div>
</div>""",
        unsafe_allow_html=True
    )

    pkg_cols = st.columns(2, gap="medium")
    for idx, pkg in enumerate(LIVE_PACKAGES):
        with pkg_cols[idx % 2]:
            features_li = "".join([f"<li style='margin-bottom:5px;'>✔ {f}</li>" for f in pkg.get("features", [])])
            st.markdown(
                f"""<div style="background:#FFFFFF; border:1px solid rgba(26,56,40,0.08); border-radius:20px; padding:18px; box-shadow:0 4px 18px rgba(26,56,40,0.04); margin-bottom:14px;">
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
  <div style="display:flex; flex-wrap:wrap; gap:6px; margin-bottom:12px;">
    <span style="background:#E2EDE4; color:#1A3828; padding:3px 9px; border-radius:6px; font-size:11px; font-weight:700;">🏡 {pkg['stay_type']}</span>
    <span style="background:#F4F7F4; color:#2E5E3F; border:1px solid rgba(46,94,63,0.3); padding:3px 9px; border-radius:6px; font-size:11px; font-weight:700;">🚗 {pkg['transit']}</span>
  </div>
  <ul style="list-style:none; padding-left:0; margin:0 0 14px 0; font-size:13px; color:#314B3B;">{features_li}</ul>
</div>""",
                unsafe_allow_html=True
            )
            wa_pkg_text = urllib.parse.quote(f"Hi Wondoo Team, I would like to reserve the package: '{pkg['title']}' ({pkg['duration']}).")
            st.markdown(
                f"""<a href="https://api.whatsapp.com/send?phone={AGENCY_WHATSAPP_NUMBER}&text={wa_pkg_text}" target="_blank" style="
display:block; text-align:center; background:#244E37; color:#FFFFFF; font-size:13px; font-weight:700;
padding:10px; border-radius:9999px; text-decoration:none; margin-top:-6px; margin-bottom:18px;
">💬 Inquire Package via WhatsApp</a>""",
                unsafe_allow_html=True
            )

# ===========================================================================
# VIEW 4: PRIMARY HOME SCREEN (DEFAULT DISCOVERY)
# ===========================================================================
elif not st.session_state.get("itinerary_data"):

    # 1. Hero Illustrated Scene
    hero_markup = f"""<div class="hero-illustrated-scene" style="background-image: url('{HERO_BG_SRC}');">
<div class="hero-scene-content">
<div class="hero-headline-serif">Your Journey,<br><span>Intelligently</span> Planned.</div>
<div class="hero-subline-sans">AI-powered travel planning made effortless. Converse with our Expedition Architect to create tailored high-altitude routes.</div>
</div>
</div>"""
    st.markdown(hero_markup, unsafe_allow_html=True)

    # -----------------------------------------------------------------------
    # DEDICATED INLINE ROUNDED CHAT CAPSULE (BETWEEN HERO AND DESTINATIONS)
    # -----------------------------------------------------------------------
    query_params = st.query_params
    if "q" in query_params and query_params["q"].strip():
        user_q = query_params["q"].strip()
        st.query_params.clear()
        st.session_state.messages.append({"role": "user", "content": user_q})
        st.session_state.active_view = "ai_concierge"
        st.rerun()

    components.html(
        """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@500;600;700&display=swap');
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: transparent;
    font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: flex-start;
    overflow: hidden;
  }
  .pill-wrapper {
    width: 100%;
    max-width: 780px;
    background: #FFFFFF;
    border: 1.5px solid rgba(26, 56, 40, 0.12);
    border-radius: 9999px;
    display: flex;
    align-items: center;
    padding: 6px 8px 6px 20px;
    box-shadow: 0 10px 30px rgba(26, 56, 40, 0.08);
    transition: border-color 0.18s ease, box-shadow 0.18s ease;
  }
  .pill-wrapper:focus-within {
    border-color: #244E37;
    box-shadow: 0 12px 34px rgba(36, 78, 55, 0.15);
  }
  .search-glass {
    font-size: 16px;
    opacity: 0.75;
    margin-right: 12px;
    user-select: none;
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
    color: #6F8977;
    opacity: 1;
  }
  .send-btn {
    background-color: #244E37;
    border: none;
    outline: none;
    border-radius: 50%;
    width: 38px;
    height: 38px;
    min-width: 38px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    box-shadow: 0 4px 12px rgba(36, 78, 55, 0.25);
    transition: transform 0.15s ease, background-color 0.15s ease;
  }
  .send-btn:hover {
    background-color: #1A3828;
    transform: scale(1.05);
  }
  .send-btn svg {
    width: 16px;
    height: 16px;
    fill: #FFFFFF;
  }
  .disclaimer {
    font-size: 11px;
    color: #557461;
    font-weight: 500;
    margin-top: 6px;
    text-align: center;
  }
</style>
</head>
<body>
  <div class="pill-wrapper">
    <div class="search-glass">🔍</div>
    <input type="text" id="alpineInput" placeholder="Ask Alpine — Where would you like to wander?" autocomplete="off" />
    <button class="send-btn" id="sendBtn" title="Send">
      <svg viewBox="0 0 24 24">
        <path d="M5 12h14M12 5l7 7-7 7" stroke="#FFFFFF" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
      </svg>
    </button>
  </div>
  <div class="disclaimer">Alpine Concierge is AI and can make mistakes.</div>

  <script>
    function submitQuery() {
      const input = document.getElementById('alpineInput');
      const val = input.value.trim();
      if (val.length > 0) {
        const parentUrl = new URL(window.parent.location.href);
        parentUrl.searchParams.set('q', val);
        window.parent.location.href = parentUrl.toString();
      }
    }
    document.getElementById('sendBtn').addEventListener('click', submitQuery);
    document.getElementById('alpineInput').addEventListener('keydown', function(e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        submitQuery();
      }
    });
  </script>
</body>
</html>""",
        height=82,
    )

    # 2. Inspiring Destinations Section Header & Clean Cards
    st.markdown(
        """<div class="section-header-row" style="margin-top: 20px;">
<div class="section-heading-text">Inspiring Destinations</div>
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
                extraction_prompt = (
                    f"Create an authentic, structured tour itinerary for: {d['title']}.\n"
                    f"Duration: {d['duration']}.\n"
                    f"Sector: {d['sector']} ({d['elevation']}).\n"
                    f"Highlights: {d['default_prompt']}"
                )
                with st.spinner(f"Synthesizing {d['title']} Expedition..."):
                    plan = generate_itinerary_content(extraction_prompt)
                    st.session_state.itinerary_data = plan
                    st.rerun()

    # -----------------------------------------------------------------------
    # 3. QUICK ACTIONS: RESPONSIVE SQUARE TILES (4 DESKTOP, 2 PER ROW ON MOBILE)
    # -----------------------------------------------------------------------
    if "action" in query_params:
        act = query_params["action"]
        st.query_params.clear()
        if act == "ai":
            st.session_state.active_view = "ai_concierge"
            st.rerun()
        elif act == "route":
            st.session_state.active_view = "smart_route"
            st.rerun()
        elif act == "budget":
            st.session_state.active_view = "budget_plan"
            st.rerun()
        elif act == "guide":
            st.info("📖 High-altitude permit protocols and weather briefings are currently accessible via our AI Concierge!")

    st.markdown(
        """<div class="section-header-row" style="margin-top: 24px;">
<div class="section-heading-text">Quick Actions</div>
<div style="font-size:12.5px; color:#557461; font-weight:600;">Explore Modes</div>
</div>""",
        unsafe_allow_html=True
    )

    square_tiles_html = f"""<div class="quick-action-grid-wrap">
  <a href="?action=ai" target="_self" class="square-action-card-tile">
    <div class="square-card-icon-bubble">
      <img src="{AI_ICON_SRC}" alt="AI Itinerary" />
    </div>
    <div class="square-card-title-text">AI Itinerary</div>
    <div class="square-card-badge-text">Custom Plan</div>
  </a>

  <a href="?action=route" target="_self" class="square-action-card-tile">
    <div class="square-card-icon-bubble">
      <img src="{ROUTE_ICON_SRC}" alt="Smart Route" />
    </div>
    <div class="square-card-title-text">Smart Route</div>
    <div class="square-card-badge-text">Verified Pacing</div>
  </a>

  <a href="?action=budget" target="_self" class="square-action-card-tile">
    <div class="square-card-icon-bubble">
      <img src="{BUDGET_ICON_SRC}" alt="Budget Plan" />
    </div>
    <div class="square-card-title-text">Budget Plan</div>
    <div class="square-card-badge-text">Transparent Fares</div>
  </a>

  <a href="?action=guide" target="_self" class="square-action-card-tile">
    <div class="square-card-icon-bubble">
      <img src="{GUIDE_ICON_SRC}" alt="Travel Guide" />
    </div>
    <div class="square-card-title-text">Travel Guide</div>
    <div class="square-card-badge-text">Passes & Advice</div>
  </a>
</div>"""

    st.markdown(square_tiles_html, unsafe_allow_html=True)

# ===========================================================================
# VIEW 5: STRUCTURED EDITORIAL ITINERARY WORKSPACE WITH 4 TABS
# ===========================================================================
else:
    data: TourItinerary = st.session_state.itinerary_data

    # Resolve stays dynamically using exact sheet headers
    matched_trip_stays = resolve_stays_for_itinerary(data)

    # Calculate Est. Budget dynamically using Google Sheets quotation formula
    quote = calculate_dynamic_sheet_quotation(
        matched_stays=matched_trip_stays,
        total_days=len(data.days),
        num_heads=2,
        num_rooms=1,
        cab_option="Include Dedicated Cab"
    )
    est_total_budget = quote.get("grand_total", len(data.days) * 3500)
    est_total_distance = sum([45 + (d.day_number * 10) for d in data.days])

    # 1. TOP HEADER NAVIGATION BAR
    c_btn_back, c_title_center, c_btn_actions = st.columns([1, 4, 1.2])
    with c_btn_back:
        if st.button("←", key="nav_back_arrow", help="Back to Discover"):
            st.session_state.itinerary_data = None
            st.session_state.booking_confirmed = None
            st.session_state.active_view = "home"
            st.rerun()

    with c_title_center:
        st.markdown(
            """<div style="text-align:center; font-family:'Playfair Display', serif; font-size:1.45rem; font-weight:700; color:#1A3828; margin-top:4px;">
Your Itinerary
</div>""",
            unsafe_allow_html=True
        )

    with c_btn_actions:
        c_book, c_menu = st.columns(2)
        with c_book:
            st.markdown('<div class="itin-nav-circle-btn">🔖</div>', unsafe_allow_html=True)
        with c_menu:
            st.markdown('<div class="itin-nav-circle-btn">⋮</div>', unsafe_allow_html=True)

    # 2. DESTINATION HERO & AVATARS
    primary_spot = data.days[0].stay_location or data.days[0].place_name
    coords = get_coords_for_place(primary_spot)
    weather_data = fetch_live_weather(coords[0], coords[1])

    st.markdown(
        f"""<div class="itin-header-hero-row">
<div>
  <div class="itin-destination-name">
    {data.tour_title} <span style="font-size:16px; cursor:pointer;">✏️</span>
  </div>
  <div class="itin-meta-subline">
    {data.duration} • {data.sector}
  </div>
  <div class="itin-avatar-stack">
    <img src="https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=100&q=80" class="itin-avatar-circle" alt="User 1" />
    <img src="https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?auto=format&fit=crop&w=100&q=80" class="itin-avatar-circle" alt="User 2" />
    <img src="https://images.unsplash.com/photo-1500648767791-00dcc994a43e?auto=format&fit=crop&w=100&q=80" class="itin-avatar-circle" alt="User 3" />
    <div class="itin-avatar-more-pill">+2</div>
  </div>
</div>
<img src="{DEFAULT_CARD_IMG}" class="itin-preview-img-card" alt="Preview" />
</div>""",
        unsafe_allow_html=True
    )

    # 3. AI ROUTE OPTIMIZED TELEMETRY BOX WITH DYNAMIC BUDGET
    st.markdown(
        f"""<div class="itin-ai-optimized-box">
<div class="ai-opt-head-row">
  <div>
    <div class="ai-opt-badge-pill">
      <span style="background:#244E37; color:#FFFFFF; width:18px; height:18px; border-radius:50%; display:inline-flex; align-items:center; justify-content:center; font-size:11px;">✓</span>
      AI Route Optimized
    </div>
    <div class="ai-opt-subtext">
      Best time to visit • Less travel time<br>
      Scenic • Budget friendly
    </div>
  </div>
  <div class="ai-route-trajectory-art">
    📍···~···📍 ›
  </div>
</div>
<div class="itin-telemetry-metrics-bar">
  <div class="metric-col-card">
    <div class="metric-icon-bubble">🏷️</div>
    <div>
      <div class="metric-label-small">Est. Distance</div>
      <div class="metric-value-bold">{est_total_distance} km</div>
    </div>
  </div>
  <div class="metric-col-card">
    <div class="metric-icon-bubble">💼</div>
    <div>
      <div class="metric-label-small">Est. Budget</div>
      <div class="metric-value-bold">₹{est_total_budget:,.0f}</div>
    </div>
  </div>
  <div class="metric-col-card">
    <div class="metric-icon-bubble">🍃</div>
    <div>
      <div class="metric-label-small">Live Weather</div>
      <div class="metric-value-bold">{weather_data['temperature']}</div>
    </div>
  </div>
</div>
</div>""",
        unsafe_allow_html=True
    )

    # 4. SEGMENTED INTERACTIVE 4 TABS
    tab_cols = st.columns(4, gap="small")
    tabs_list = ["Itinerary", "Transport", "Stay", "Recommendations"]

    for idx, tab_name in enumerate(tabs_list):
        with tab_cols[idx]:
            is_active = (st.session_state.itin_tab == tab_name)
            if st.button(
                tab_name,
                key=f"tab_nav_{tab_name.lower()}",
                type="primary" if is_active else "secondary",
                use_container_width=True
            ):
                st.session_state.itin_tab = tab_name
                st.rerun()

    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)

    # 5. FETCH ASYNC WAYPOINT PHOTOS
    with ThreadPoolExecutor(max_workers=min(len(data.days), 6)) as executor:
        photos_results = list(executor.map(
            lambda d: search_key_spot_images(d.place_name, max_results=1), 
            data.days
        ))

    # =======================================================================
    # TAB CONTENT 1: ITINERARY
    # =======================================================================
    if st.session_state.itin_tab == "Itinerary":
        timeline_elements = ['<div class="mockup-timeline-wrap"><div class="mockup-timeline-dashed-line"></div>']
        icons_palette = ["🌱", "🏡", "🏔️", "☕", "🌊", "🛕", "🛶"]

        for idx, day in enumerate(data.days):
            spot_img = photos_results[idx][0]["url"] if photos_results[idx] else DEFAULT_CARD_IMG
            day_icon = icons_palette[idx % len(icons_palette)]
            bullet_tags = " • ".join(day.bullets[:2]) if day.bullets else day.place_name
            stay_tag = f"<div style='font-size:11.5px; color:#557461; margin-top:3px;'>🌙 Stay at: {day.stay_location}</div>" if getattr(day, "stay_location", None) else ""

            timeline_elements.append(
                f"""<div class="mockup-day-entry">
<div class="mockup-day-circle-tag">
  <div class="mockup-day-label-txt">Day</div>
  <div class="mockup-day-badge-num">{day.day_number}</div>
</div>
<div class="mockup-itinerary-card">
  <div class="mockup-card-text-side">
    <div class="mockup-card-route-title">
      <span>{day_icon}</span> {day.route_title} <span style="font-size:13px; color:#688574;">›</span>
    </div>
    <div style="font-size:12px; color:#435E4E; line-height:1.4;">
      • {bullet_tags}
    </div>
    {stay_tag}
  </div>
  <img src="{spot_img}" class="mockup-card-thumb-photo" alt="{day.place_name}" onerror="this.src='{DEFAULT_CARD_IMG}'" />
</div>
</div>"""
            )

        timeline_elements.append('</div>')
        st.markdown("".join(timeline_elements), unsafe_allow_html=True)

        st.markdown(
            """<div class="mockup-add-activity-row">
<span style="font-size:18px;">⊕</span> Add Activity
</div>""",
            unsafe_allow_html=True
        )

    # =======================================================================
    # TAB CONTENT 2: TRANSPORT
    # =======================================================================
    elif st.session_state.itin_tab == "Transport":
        st.markdown(
            """<div style="background:#FFFFFF; border:1px solid rgba(26,56,40,0.06); border-radius:22px; padding:20px; box-shadow:0 4px 18px rgba(26,56,40,0.03); margin-bottom:16px;">
<div style="font-family:'Playfair Display', serif; font-size:1.25rem; font-weight:700; color:#1A3828; margin-bottom:4px;">
🚗 Dedicated Mountain Carrier & Chauffeur
</div>
<div style="font-size:13px; color:#557461; margin-bottom:12px;">
Private SUV (Scorpio / Bolero / Innova Crysta) assigned exclusively for your circuit
</div>
<div style="display:flex; flex-wrap:wrap; gap:8px;">
  <span style="background:#E2EDE4; color:#1A3828; padding:4px 10px; border-radius:8px; font-size:11.5px; font-weight:700;">✔ Point-to-Point Sightseeing</span>
  <span style="background:#E2EDE4; color:#1A3828; padding:4px 10px; border-radius:8px; font-size:11.5px; font-weight:700;">✔ Luggage Carrier Included</span>
  <span style="background:#E2EDE4; color:#1A3828; padding:4px 10px; border-radius:8px; font-size:11.5px; font-weight:700;">✔ Fuel, Driver Food & Night Halts Covered</span>
  <span style="background:#E2EDE4; color:#1A3828; padding:4px 10px; border-radius:8px; font-size:11.5px; font-weight:700;">✔ Inner Line Border Permits Arranged</span>
</div>
</div>""",
            unsafe_allow_html=True
        )

        st.markdown("<div style='font-size:15px; font-weight:700; color:#1A3828; margin: 16px 0 10px 0;'>Transit Route Pacing</div>", unsafe_allow_html=True)
        
        for d in data.days:
            transit_km = 35 + (d.day_number * 10)
            transit_hrs = round(transit_km / 22, 1)
            st.markdown(
                f"""<div style="background:#FFFFFF; border:1px solid rgba(26,56,40,0.06); border-radius:18px; padding:14px 18px; margin-bottom:10px; display:flex; justify-content:space-between; align-items:center;">
<div>
  <div style="font-weight:700; font-size:14px; color:#1A3828;">Day {d.day_number}: Transit to {d.place_name}</div>
  <div style="font-size:12px; color:#557461;">Scenic Hill Route & Sightseeing Loops</div>
</div>
<div style="text-align:right;">
  <div style="font-size:13px; font-weight:700; color:#2E5E3F;">~{transit_km} km • {transit_hrs} hrs</div>
  <div style="font-size:11px; color:#688574;">Avg Speed 22 km/h</div>
</div>
</div>""",
                unsafe_allow_html=True
            )

    # =======================================================================
    # TAB CONTENT 3: STAY (SHOWS ALL OPTIONS PER NIGHT DIRECT FROM SHEET)
    # =======================================================================
    elif st.session_state.itin_tab == "Stay":
        nights_data = resolve_all_stays_for_itinerary(data)
        
        for night_idx, n_info in nights_data.items():
            avail_count = len(n_info["stays"])
            badge_color = "#244E37" if avail_count > 0 else "#688574"
            count_label = f"{avail_count} Curated Properties Available" if avail_count > 0 else "Allocated at Checkout"

            st.markdown(
                f"""<div style="margin: 20px 0 10px 4px; display:flex; align-items:center; justify-content:space-between;">
  <div>
    <span style="background:{badge_color}; color:#FFFFFF; padding:4px 12px; border-radius:9999px; font-size:11.5px; font-weight:700; text-transform:uppercase;">Night {night_idx}</span>
    <span style="font-family:'Playfair Display', serif; font-size:19px; font-weight:700; color:#1A3828; margin-left:10px;">{n_info['town']}</span>
  </div>
  <div style="font-size:12.5px; color:#557461; font-weight:600;">{count_label}</div>
</div>""",
                unsafe_allow_html=True
            )
            
            if n_info["stays"]:
                for s in n_info["stays"]:
                    stay_img = s.get("image", DEFAULT_CARD_IMG)
                    price_val = f"₹{s['price_bracket']}" if s.get('price_bracket') else "₹2,000"
                    
                    st.markdown(
                        f"""<div style="background:#FFFFFF; border:1px solid rgba(26,56,40,0.08); border-radius:20px; padding:16px 18px; margin-bottom:12px; box-shadow:0 4px 16px rgba(26,56,40,0.03); display:flex; gap:16px; align-items:center;">
  <img src="{stay_img}" style="width:115px; height:90px; border-radius:16px; object-fit:cover;" onerror="this.src='{DEFAULT_CARD_IMG}'" />
  <div style="flex:1;">
    <div style="display:flex; justify-content:space-between; align-items:flex-start;">
      <div>
        <div style="font-family:'Playfair Display', serif; font-size:17.5px; font-weight:700; color:#1A3828;">{s['stay_name']}</div>
        <div style="font-size:12.5px; color:#557461; margin:2px 0 6px 0;">
          🏡 <b>{s['property_type']}</b> • ⛰️ {s['altitude']}
        </div>
      </div>
      <div style="text-align:right;">
        <div style="font-size:18px; font-weight:800; color:#244E37;">{price_val}</div>
        <div style="font-size:11px; color:#6B8073; font-weight:600;">{s.get('pricing_type', 'Per Head')}</div>
      </div>
    </div>
    <div style="display:flex; gap:6px; flex-wrap:wrap; margin-top:4px;">
      <span style="background:#E2EDE4; color:#1A3828; padding:3px 8px; border-radius:6px; font-size:11px; font-weight:700;">{s['rating']}</span>
      <span style="background:#E2EDE4; color:#1A3828; padding:3px 8px; border-radius:6px; font-size:11px; font-weight:600;">☕ Mountain View</span>
      <span style="background:#E2EDE4; color:#1A3828; padding:3px 8px; border-radius:6px; font-size:11px; font-weight:600;">🚿 24x7 Hot Water</span>
      <span style="background:#F4F7F4; color:#244E37; border:1px solid rgba(36,78,55,0.2); padding:3px 8px; border-radius:6px; font-size:11px; font-weight:600;">Verified Partner</span>
    </div>
  </div>
</div>""",
                        unsafe_allow_html=True
                    )
            else:
                st.markdown(
                    f"""<div style="background:#FFFFFF; border:1px dashed rgba(26,56,40,0.18); border-radius:18px; padding:14px 18px; margin-bottom:12px; color:#557461; font-size:13px;">
  📍 Verified boutique lodge / homestay in <b>{n_info['town']}</b> allocated automatically at checkout.
</div>""",
                    unsafe_allow_html=True
                )

    # =======================================================================
    # TAB CONTENT 4: RECOMMENDATIONS (DYNAMICALLY GENERATED FOR DESTINATIONS)
    # =======================================================================
    elif st.session_state.itin_tab == "Recommendations":
        places_summary = ", ".join([d.place_name for d in data.days])
        with st.spinner("Curating destination-specific local recommendations..."):
            recs = fetch_dynamic_recommendations(data.tour_title, data.sector, places_summary)

        r1, r2 = st.columns(2, gap="medium")
        with r1:
            food_items = "".join([f"<li>{item}</li>" for item in recs.get("food", [])])
            st.markdown(
                f"""<div style="background:#FFFFFF; border:1px solid rgba(26,56,40,0.06); border-radius:20px; padding:18px; margin-bottom:12px;">
<div style="font-family:'Playfair Display', serif; font-size:16px; font-weight:700; color:#1A3828; margin-bottom:8px;">🍲 Local Cuisine & Food</div>
<ul style="font-size:12.5px; color:#314B3B; line-height:1.6; padding-left:18px; margin:0;">{food_items}</ul>
</div>""",
                unsafe_allow_html=True
            )

            photo_items = "".join([f"<li>{item}</li>" for item in recs.get("photo_spots", [])])
            st.markdown(
                f"""<div style="background:#FFFFFF; border:1px solid rgba(26,56,40,0.06); border-radius:20px; padding:18px; margin-bottom:12px;">
<div style="font-family:'Playfair Display', serif; font-size:16px; font-weight:700; color:#1A3828; margin-bottom:8px;">📷 Golden Hour & Viewpoints</div>
<ul style="font-size:12.5px; color:#314B3B; line-height:1.6; padding-left:18px; margin:0;">{photo_items}</ul>
</div>""",
                unsafe_allow_html=True
            )

        with r2:
            gear_items = "".join([f"<li>{item}</li>" for item in recs.get("gear", [])])
            st.markdown(
                f"""<div style="background:#FFFFFF; border:1px solid rgba(26,56,40,0.06); border-radius:20px; padding:18px; margin-bottom:12px;">
<div style="font-family:'Playfair Display', serif; font-size:16px; font-weight:700; color:#1A3828; margin-bottom:8px;">🎒 Essential Packing & Gear</div>
<ul style="font-size:12.5px; color:#314B3B; line-height:1.6; padding-left:18px; margin:0;">{gear_items}</ul>
</div>""",
                unsafe_allow_html=True
            )

            etiquette_items = "".join([f"<li>{item}</li>" for item in recs.get("etiquette", [])])
            st.markdown(
                f"""<div style="background:#FFFFFF; border:1px solid rgba(26,56,40,0.06); border-radius:20px; padding:18px; margin-bottom:12px;">
<div style="font-family:'Playfair Display', serif; font-size:16px; font-weight:700; color:#1A3828; margin-bottom:8px;">🛕 Local Customs & Etiquette</div>
<ul style="font-size:12.5px; color:#314B3B; line-height:1.6; padding-left:18px; margin:0;">{etiquette_items}</ul>
</div>""",
                unsafe_allow_html=True
            )

    # 6. BOTTOM ACTION DOCK
    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
    deck_c1, deck_c2, deck_c3 = st.columns([3.5, 1, 1], gap="small")
    with deck_c1:
        if st.button("✨ Optimize with AI & Reserve", type="primary", use_container_width=True):
            open_package_booking_dialog(data, matched_trip_stays)
    with deck_c2:
        guest_url = generate_guest_portal_url(data)
        st.markdown(
            f"""<a href="{guest_url}" target="_blank" style="display:flex; align-items:center; justify-content:center; background:#FFFFFF; border:1px solid rgba(26,56,40,0.12); height:44px; border-radius:9999px; font-weight:700; text-decoration:none; font-size:13px; color:#244E37;">
📱 Pass
</a>""",
            unsafe_allow_html=True
        )
    with deck_c3:
        wa_summary = f"🌿 *{data.tour_title}* ({data.duration})\n" + "\n".join([f"📍 *Day {d.day_number}*: {d.route_title}" for d in data.days])
        wa_link = f"https://api.whatsapp.com/send?text={urllib.parse.quote(wa_summary)}"
        st.markdown(
            f"""<a href="{wa_link}" target="_blank" style="display:flex; align-items:center; justify-content:center; background:#FFFFFF; border:1px solid rgba(26,56,40,0.12); height:44px; border-radius:9999px; text-decoration:none; font-size:16px; color:#244E37;">
⚙️
</a>""",
            unsafe_allow_html=True
        )
