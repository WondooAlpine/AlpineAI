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
# CONFIGURATION & SECRETS
# ---------------------------------------------------------------------------
def get_image_base64(image_path: str) -> str:
    """Reads a local image and converts it into a base64 string for HTML embedding."""
    if os.path.exists(image_path):
        with open(image_path, "rb") as f:
            data = base64.b64encode(f.read()).decode("utf-8")
        ext = os.path.splitext(image_path)[1].replace(".", "").lower()
        mime = "image/svg+xml" if ext == "svg" else f"image/{ext}"
        return f"data:{mime};base64,{data}"
    # Fallback to an empty or default URL if the file isn't found
    return "https://images.unsplash.com/photo-1544735716-392fe2489ffa?auto=format&fit=crop&w=100&q=80"

# Path to your logo file
LOGO_PATH = "assets/logo.png"  # Replace with your actual path
APP_LOGO_SRC = get_image_base64(LOGO_PATH)

st.set_page_config(
    page_title="Wondoo AI Studio | Alpine 3D Expedition Studio",
    page_icon=LOGO_PATH if os.path.exists(LOGO_PATH) else "🏔️",
    layout="wide",
    initial_sidebar_state="expanded",
)

BOOKING_WEBHOOK_URL = os.environ.get(
    "BOOKING_WEBHOOK_URL",
    "https://script.google.com/macros/s/YOUR_APPS_SCRIPT_DEPLOYMENT_ID/exec",
)
AGENCY_WHATSAPP_NUMBER = os.environ.get("AGENCY_WHATSAPP_NUMBER", "919800000000")
UPI_VPA = os.environ.get("UPI_VPA", "wondooexpeditions@oksbi")
UPI_PAYEE_NAME = os.environ.get("UPI_PAYEE_NAME", "Wondoo Alpine Studio")
CATALOG_SHEET_ID = os.environ.get(
    "CATALOG_SHEET_ID",
    "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms",
)

DEFAULT_CARD_IMG = "https://images.unsplash.com/photo-1544735716-392fe2489ffa?auto=format&fit=crop&w=900&q=80"

# ---------------------------------------------------------------------------
# GUEST PORTAL (ONE-CLICK SHAREABLE PASS INSPECTOR)
# ---------------------------------------------------------------------------
def check_and_render_guest_portal():
    params = st.query_params
    if params.get("portal") == "true" and "data" in params:
        try:
            encoded = params.get("data")
            raw_bytes = zlib.decompress(base64.urlsafe_b64decode(encoded))
            summary = json.loads(raw_bytes.decode("utf-8"))

            st.markdown(
                """
                <style>
                  @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800&display=swap');
                  html, body, [data-testid="stAppViewContainer"] {
                    background: #0b1329 !important;
                    font-family: 'Plus Jakarta Sans', sans-serif !important;
                    color: #f8fafc !important;
                  }
                  .guest-card {
                    background: rgba(15, 23, 42, 0.94);
                    border: 1px solid rgba(56, 189, 248, 0.35);
                    border-radius: 14px;
                    padding: 18px;
                    margin-bottom: 16px;
                  }
                </style>
                """,
                unsafe_allow_html=True
            )

            st.markdown(f"# 🏔️ {summary['t']}")
            st.caption(f"📍 {summary['s']} • ⏱️ {summary['d']} • Wondoo Digital Itinerary Pass")
            st.markdown("<hr style='border-color: rgba(255,255,255,0.15); margin: 12px 0 20px 0;'>", unsafe_allow_html=True)

            for d in summary.get("days", []):
                halt_info = (
                    f"<span style='color:#34d399; font-weight:700;'>🌙 Stay at: {d['h']}</span>"
                    if d.get("h")
                    else "<span style='color:#94a3b8;'>🛫 Departure / Drop-off</span>"
                )
                bullets_html = "".join([f"<li style='color:#e2e8f0; margin-bottom:6px;'>✦ {b}</li>" for b in d.get("b", [])])
                st.markdown(
                    f"""
                    <div class="guest-card">
                      <div style="font-size:18px; font-weight:800; color:#ffffff; margin-bottom:4px;">
                        Day {d['n']}: {d['r']}
                      </div>
                      <div style="font-size:13px; color:#38bdf8; margin-bottom:8px;">
                        📍 Key Spot: <b>{d['p']}</b> &nbsp;|&nbsp; {halt_info}
                      </div>
                      <ul style="list-style:none; padding-left:0; margin:0;">{bullets_html}</ul>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

            wa_chat_text = urllib.parse.quote(f"Hi Wondoo Team, I am viewing my guest itinerary pass for '{summary['t']}'.")
            st.markdown(
                f"""
                <a href="https://api.whatsapp.com/send?phone={AGENCY_WHATSAPP_NUMBER}&text={wa_chat_text}" target="_blank" style="
                    display:block; text-align:center; background:#25D366; color:white; padding:12px;
                    border-radius:12px; font-weight:700; text-decoration:none; margin-top:20px;
                ">
                    💬 Connect with Tour Concierge on WhatsApp
                </a>
                """,
                unsafe_allow_html=True
            )
            st.stop()
        except Exception:
            st.error("Invalid, corrupted, or expired digital guest itinerary link.")
            st.stop()

check_and_render_guest_portal()

# ---------------------------------------------------------------------------
# TIME ZONE & AMBIENCE (IST = UTC + 5:30)
# ---------------------------------------------------------------------------
ist_tz = timezone(timedelta(hours=5, minutes=30))
now_ist = datetime.now(ist_tz)
current_hour_ist = now_ist.hour + (now_ist.minute / 60.0)

is_day_mode = 6.0 <= current_hour_ist < 18.5
ist_time_str = now_ist.strftime("%I:%M %p")

if is_day_mode:
    period_label = f"☀️ Daytime in India ({ist_time_str} IST)"
    real_mountain_photo_url = "https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?auto=format&fit=crop&w=2560&q=92"
    fog_color_hex = "0x0b132b"
else:
    period_label = f"🌙 Nighttime in India ({ist_time_str} IST)"
    real_mountain_photo_url = "https://images.unsplash.com/photo-1519681393784-d120267933ba?auto=format&fit=crop&w=2560&q=92"
    fog_color_hex = "0x050811"

ALPINE_FACTS = [
    "🏔️ **Tiger Hill Sunrise**: Morning sunlight illuminates Mt. Everest and Mt. Kanchenjunga simultaneously before valleys catch dawn.",
    "🍵 **Darjeeling First Flush**: Harvested from mid-March to May across steep slope elevations, producing a prized light floral muscatel cup.",
    "🚗 **Mountain Pacing**: Hill drives across Sikkim, Himachal, and Uttarakhand average 20–25 km/h due to winding hairpin bends.",
    "🪪 **Protected Area Permits**: High-altitude frontiers like Nathula, Tsomgo, and Tawang require registered permits arranged 24h prior.",
    "🌴 **Kerala Backwaters**: Vembanad Lake connects over 900 km of palm-fringed lagoons, best navigated on traditional Kettuvallam houseboats.",
    "🏝️ **Andaman Horizons**: Radhanagar Beach on Havelock Island features shallow turquoise reefs ranked among Asia's cleanest shorelines.",
    "🛕 **Odisha Heritage**: Konark's 13th-century Sun Temple is engineered as a colossal 24-wheel stone chariot aligned with the sun's trajectory."
]

# ---------------------------------------------------------------------------
# FLEET CATALOG
# ---------------------------------------------------------------------------
FLEET_CATALOG = {
    "hatchback": {
        "name": "WagonR / Dzire (Compact)",
        "capacity": "Max 3-4 Pax",
        "per_day_rate": 2400,
        "terrain": "Paved Highways / Low Altitude"
    },
    "suv": {
        "name": "Innova Crysta / Scorpio (Premium SUV)",
        "capacity": "Max 6 Pax",
        "per_day_rate": 4200,
        "terrain": "All Mountain Terrains / Family Comfort"
    },
    "4x4": {
        "name": "Bolero 4x4 / Thar Expedition Spec",
        "capacity": "Max 5 Pax",
        "per_day_rate": 4800,
        "terrain": "Silk Route / Zuluk / Sandakphu Rough Track"
    },
    "tempo": {
        "name": "Force Urbania / Luxury Tempo Traveller",
        "capacity": "Max 12-16 Pax",
        "per_day_rate": 7500,
        "terrain": "Large Group Scenic Touring"
    }
}

# ---------------------------------------------------------------------------
# WEATHER INSIGHT HELPER
# ---------------------------------------------------------------------------
COORDINATES_DB = {
    "bagdogra": (26.6812, 88.3286),
    "siliguri": (26.7271, 88.3953),
    "njp": (26.6853, 88.4414),
    "darjeeling": (27.0410, 88.2663),
    "tiger hill": (27.0149, 88.2861),
    "ghoom": (27.0112, 88.2562),
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
    0: ("☀️ Clear Sky", "Optimal sunrise visibility"),
    1: ("🌤️ Mainly Clear", "Mild sunshine"),
    2: ("⛅ Partly Cloudy", "Scattered ridge mist"),
    3: ("☁️ Overcast", "Low cloud base"),
    45: ("🌫️ Dense Fog", "Early morning hill mist"),
    61: ("🌧️ Light Rain", "Carry water-resistant jackets"),
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
        return {
            "temperature": f"{temp}°C",
            "desc": desc,
            "advisory": advisory
        }
    except Exception:
        return {
            "temperature": "14°C",
            "desc": "⛅ Alpine Air",
            "advisory": "Woolen layers recommended for mornings"
        }

# ---------------------------------------------------------------------------
# SERIALIZATION & STORY EXPORT
# ---------------------------------------------------------------------------
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

def create_story_card(day_number: int, route_title: str, stay_location: str, image_url: str, output_path: str):
    width, height = 1080, 1920
    img = Image.new("RGB", (width, height), color=(11, 19, 43))
    draw = ImageDraw.Draw(img)

    if image_url:
        try:
            res = requests.get(image_url, timeout=5)
            photo = Image.open(BytesIO(res.content)).convert("RGB")
            photo = photo.resize((1080, 1000))
            img.paste(photo, (0, 0))
        except Exception:
            pass

    draw.rectangle([0, 950, 1080, 1920], fill=(15, 23, 42))
    draw.rectangle([80, 1040, 340, 1110], fill=(245, 158, 11))
    draw.text((100, 1060), f"DAY {day_number} EXPEDITION", fill=(11, 15, 25))

    draw.text((80, 1160), route_title[:45], fill=(255, 255, 255))
    halt_text = f"NIGHT HALT: {stay_location.upper()}" if stay_location else "DEPARTURE / TRANSFER"
    draw.text((80, 1260), halt_text, fill=(56, 189, 248))
    draw.text((80, 1780), "WONDOO ALPINE STUDIO • CURATED EXPEDITIONS", fill=(148, 163, 184))

    img.save(output_path, quality=95)
    return output_path

# ---------------------------------------------------------------------------
# DYNAMIC GOOGLE SHEET LOADERS
# ---------------------------------------------------------------------------
DEFAULT_FALLBACK_ITINERARIES = [
    {
        "title": "Classic Darjeeling & Misty Kalimpong",
        "duration": "4 Days / 3 Nights",
        "sector": "West Bengal (Eastern Himalayas)",
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
        "duration": "5 Days / 4 Nights",
        "sector": "East Sikkim Border Circuit",
        "elevation": "1,500m - 3,753m",
        "image": "https://images.unsplash.com/photo-1626621341517-bbf3d9990a23?auto=format&fit=crop&w=900&q=80",
        "highlights": [
            "Zuluk zig-zag 32 hairpin loops with Kanchenjunga vistas",
            "Sacred Kupup Elephant Lake & Baba Harbhajan Mandir",
            "Sunrise over Thambi View Point",
            "Historic Silk Route heritage trade hamlet stays"
        ],
        "default_prompt": "Plan an expedition through Sillery Gaon, Zuluk, Nathang Valley, and Reshikhola with local homestays and mountain passes."
    }
]

DEFAULT_FALLBACK_PACKAGES = [
    {
        "title": "Darjeeling & Kalimpong Alpine Retreat",
        "duration": "4 Days / 3 Nights",
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
        "duration": "5 Days / 4 Nights",
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
    url = f"https://docs.google.com/spreadsheets/d/1fbDtDmXR2QS15V3oY6dAIW64gcqMui3vTMrndxsOYVQ/gviz/tq?tqx=out:csv&sheet=Itineraries"
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
                "duration": str(row.get("duration", "4 Days / 3 Nights")).strip(),
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
    url = f"https://docs.google.com/spreadsheets/d/1fbDtDmXR2QS15V3oY6dAIW64gcqMui3vTMrndxsOYVQ/gviz/tq?tqx=out:csv&sheet=Packages"
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
# HARDWARE-ACCELERATED THREE.JS BACKGROUND
# ---------------------------------------------------------------------------
components.html(
    f"""
<script>
(function() {{
  const parentDoc = window.parent.document;
  const existingCanvas = parentDoc.getElementById('threejs-mountain-canvas');
  if (existingCanvas) existingCanvas.remove();

  const canvas = parentDoc.createElement('canvas');
  canvas.id = 'threejs-mountain-canvas';
  canvas.style.position = 'fixed';
  canvas.style.top = '0';
  canvas.style.left = '0';
  canvas.style.width = '100vw';
  canvas.style.height = '100vh';
  canvas.style.zIndex = '0';
  canvas.style.pointerEvents = 'none';
  parentDoc.body.prepend(canvas);

  const script = parentDoc.createElement('script');
  script.src = 'https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js';
  script.onload = () => {{
    const THREE = window.parent.THREE;
    const isMobile = window.parent.innerWidth <= 768;
    const scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2({fog_color_hex}, isMobile ? 0.0008 : 0.0006);

    const camera = new THREE.PerspectiveCamera(60, window.parent.innerWidth / window.parent.innerHeight, 1, 4000);
    camera.position.set(0, 30, 600);

    const renderer = new THREE.WebGLRenderer({{ canvas: canvas, alpha: true, antialias: !isMobile }});
    renderer.setSize(window.parent.innerWidth, window.parent.innerHeight);
    renderer.setPixelRatio(Math.min(window.parent.devicePixelRatio, isMobile ? 1.5 : 2));

    function getFrustumSizeAtDistance(distance) {{
      const vFov = (camera.fov * Math.PI) / 180;
      const height = 2 * Math.tan(vFov / 2) * distance;
      const width = height * camera.aspect;
      return {{ width, height }};
    }}

    const textureLoader = new THREE.TextureLoader();
    textureLoader.setCrossOrigin('anonymous');

    textureLoader.load('{real_mountain_photo_url}', (texture) => {{
      texture.minFilter = THREE.LinearFilter;
      texture.generateMipmaps = false;
      const fDist = 950;
      const fSize = getFrustumSizeAtDistance(camera.position.z + fDist);
      const farGeo = new THREE.PlaneGeometry(fSize.width * 1.35, fSize.height * 1.35);
      const farMat = new THREE.MeshBasicMaterial({{
        map: texture,
        transparent: true,
        opacity: 0.98,
        depthWrite: false
      }});
      const mountainMesh = new THREE.Mesh(farGeo, farMat);
      mountainMesh.position.set(0, 80, -fDist);
      scene.add(mountainMesh);
    }});

    const flakeCount = isMobile ? 600 : 1200;
    const flakeGeo = new THREE.BufferGeometry();
    const snowPositions = new Float32Array(flakeCount * 3);
    const snowData = [];

    for (let i = 0; i < flakeCount; i++) {{
      snowPositions[i * 3] = (Math.random() - 0.5) * 2600;
      snowPositions[i * 3 + 1] = Math.random() * 1600 - 800;
      snowPositions[i * 3 + 2] = (Math.random() - 0.5) * 1800;

      snowData.push({{
        speedY: Math.random() * 1.8 + 0.8,
        swaySpeed: Math.random() * 0.02 + 0.01,
        swayOffset: Math.random() * Math.PI * 2,
        windInfluence: Math.random() * 0.7 + 0.3
      }});
    }}
    flakeGeo.setAttribute('position', new THREE.BufferAttribute(snowPositions, 3));

    const snowCanvas = parentDoc.createElement('canvas');
    snowCanvas.width = 32;
    snowCanvas.height = 32;
    const ctx = snowCanvas.getContext('2d');
    const grad = ctx.createRadialGradient(16, 16, 0, 16, 16, 16);
    grad.addColorStop(0, 'rgba(255, 255, 255, 1)');
    grad.addColorStop(0.35, 'rgba(224, 242, 254, 0.75)');
    grad.addColorStop(0.7, 'rgba(186, 230, 253, 0.25)');
    grad.addColorStop(1, 'rgba(0, 0, 0, 0)');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, 32, 32);

    const snowTexture = new THREE.CanvasTexture(snowCanvas);
    const snowMaterial = new THREE.PointsMaterial({{
      size: isMobile ? 6 : 7.5,
      map: snowTexture,
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false
    }});

    const snowSystem = new THREE.Points(flakeGeo, snowMaterial);
    scene.add(snowSystem);

    let mouseX = 0, mouseY = 0;
    let targetCameraX = 0, targetCameraY = 30;
    let scrollOffset = 0;

    if (!isMobile) {{
      window.parent.addEventListener('mousemove', (e) => {{
        const halfW = window.parent.innerWidth / 2;
        const halfH = window.parent.innerHeight / 2;
        mouseX = (e.clientX - halfW) * 0.35;
        mouseY = (e.clientY - halfH) * 0.2;
      }});
    }}

    window.parent.addEventListener('scroll', () => {{
      const scrollPos = window.parent.pageYOffset || window.parent.document.documentElement.scrollTop;
      scrollOffset = scrollPos * (isMobile ? 0.25 : 0.42);
    }});

    function animate() {{
      window.parent.requestAnimationFrame(animate);
      targetCameraX += (mouseX - targetCameraX) * 0.04;
      targetCameraY += (30 - mouseY - targetCameraY) * 0.04;
      camera.position.x = targetCameraX;
      camera.position.y = targetCameraY;
      camera.position.z = 600 - (scrollOffset % 700);
      camera.lookAt(0, 30, -750);

      const posAttr = flakeGeo.attributes.position;
      for (let i = 0; i < flakeCount; i++) {{
        let y = posAttr.getY(i) - snowData[i].speedY;
        let x = posAttr.getX(i);
        if (y < -800) {{
          y = 800;
          x = (Math.random() - 0.5) * 2600;
        }}
        posAttr.setY(i, y);
        posAttr.setX(i, x);
      }}
      posAttr.needsUpdate = true;
      renderer.render(scene, camera);
    }}
    animate();
  }};
  parentDoc.head.appendChild(script);
}})();
</script>
""",
    height=0,
)

# ---------------------------------------------------------------------------
# HARDENED HIGH-CONTRAST CSS
# ---------------------------------------------------------------------------
st.markdown(
    """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;600;700&display=swap');

  html, body, [data-testid="stAppViewContainer"], .stApp {
    background-color: transparent !important;
    background: transparent !important;
    font-family: 'Plus Jakarta Sans', sans-serif !important;
    color: #f8fafc !important;
  }

  header[data-testid="stHeader"] {
    background: transparent !important;
    box-shadow: none !important;
    height: 2.2rem !important;
  }

  /* Hide Deploy button */
  [data-testid="stHeader"] button[kind="header"],
  button[data-testid="baseButton-header"],
  .stDeployButton {
    display: none !important;
  }

  .block-container {
    max-width: 1300px !important;
    padding-top: 0.6rem !important;
    padding-bottom: 7rem !important;
    padding-left: 1rem !important;
    padding-right: 1rem !important;
    position: relative;
    z-index: 1;
  }

  /* ----------------------------------------------------
     MODERN FROSTED GLASS CAPSULE COMMAND BAR
     ---------------------------------------------------- */
  .modern-app-bar {
    position: relative;
    background: rgba(13, 19, 33, 0.75) !important;
    border: 1px solid rgba(255, 255, 255, 0.12) !important;
    border-top: 1px solid rgba(255, 255, 255, 0.22) !important;
    border-radius: 16px !important;
    padding: 12px 20px !important;
    margin-bottom: 14px !important;
    backdrop-filter: blur(24px) saturate(180%) !important;
    -webkit-backdrop-filter: blur(24px) saturate(180%) !important;
    box-shadow: 0 10px 32px 0 rgba(0, 0, 0, 0.42), inset 0 1px 0 0 rgba(255, 255, 255, 0.1) !important;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
  }

  .bar-left {
    display: flex;
    align-items: center;
    gap: 14px;
  }

  .brand-logo-icon {
    width: 38px;
    height: 38px;
    border-radius: 10px;
    background: linear-gradient(135deg, rgba(56, 189, 248, 0.25) 0%, rgba(245, 158, 11, 0.2) 100%);
    border: 1px solid rgba(56, 189, 248, 0.4);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 18px;
    box-shadow: 0 0 16px rgba(56, 189, 248, 0.2);
  }

  .brand-text-wrap {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .brand-title {
    font-family: 'Space Grotesk', 'Plus Jakarta Sans', sans-serif !important;
    font-size: 1.35rem !important;
    font-weight: 800 !important;
    color: #ffffff !important;
    letter-spacing: -0.4px !important;
    line-height: 1.1 !important;
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .brand-title span {
    background: linear-gradient(135deg, #38bdf8 0%, #fde047 60%, #f59e0b 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }

  .brand-sub {
    color: #94a3b8;
    font-size: 11.5px;
    font-weight: 500;
    letter-spacing: 0.2px;
  }

  .bar-right-telemetry {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .status-pill-modern {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    background: rgba(15, 23, 42, 0.65);
    border: 1px solid rgba(56, 189, 248, 0.25);
    padding: 5px 12px;
    border-radius: 9999px;
    font-size: 11px;
    font-weight: 600;
    color: #e2e8f0;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
  }

  .pulse-dot-green {
    width: 6.5px;
    height: 6.5px;
    border-radius: 50%;
    background: #34d399;
    box-shadow: 0 0 8px #34d399;
    animation: statusPulse 2s infinite ease-in-out;
  }

  @keyframes statusPulse {
    0%, 100% { opacity: 0.7; transform: scale(0.95); }
    50% { opacity: 1; transform: scale(1.25); box-shadow: 0 0 12px #34d399; }
  }

  .chip-tag-modern {
    background: rgba(245, 158, 11, 0.12);
    border: 1px solid rgba(245, 158, 11, 0.35);
    color: #fde047;
    font-size: 10.5px;
    font-weight: 700;
    padding: 4px 9px;
    border-radius: 7px;
    letter-spacing: 0.4px;
    text-transform: uppercase;
  }

  /* ----------------------------------------------------
     GEMINI-STYLE SIDEBAR
     ---------------------------------------------------- */
  [data-testid="stSidebar"] {
    background: #13171f !important;
    border-right: 1px solid rgba(255, 255, 255, 0.08) !important;
  }
  [data-testid="stSidebar"] [data-testid="stSidebarNav"] {
    display: none !important;
  }
  [data-testid="stSidebar"] .block-container {
    padding: 1rem 0.6rem 1.2rem 0.6rem !important;
    max-width: 100% !important;
  }

  .gemini-sidebar-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 4px 8px 16px 8px;
  }
  .gemini-brand-logo {
    display: flex;
    align-items: center;
    gap: 8px;
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1.15rem;
    font-weight: 700;
    color: #f8fafc;
    letter-spacing: -0.3px;
  }

  [data-testid="stSidebar"] .stButton > button {
    background: transparent !important;
    border: none !important;
    color: #e2e8f0 !important;
    font-weight: 500 !important;
    font-size: 13.5px !important;
    text-align: left !important;
    display: flex !important;
    justify-content: flex-start !important;
    align-items: center !important;
    border-radius: 9999px !important;
    padding: 8px 14px !important;
    box-shadow: none !important;
    height: 38px !important;
    min-height: 38px !important;
    width: 100% !important;
    transition: background-color 0.15s ease !important;
  }
  [data-testid="stSidebar"] .stButton > button div,
  [data-testid="stSidebar"] .stButton > button p {
    text-align: left !important;
    justify-content: flex-start !important;
    width: 100% !important;
    display: flex !important;
    align-items: center !important;
  }
  [data-testid="stSidebar"] .stButton > button:hover {
    background: rgba(255, 255, 255, 0.08) !important;
    color: #ffffff !important;
  }
  [data-testid="stSidebar"] .stButton > button[kind="primary"] {
    background: rgba(255, 255, 255, 0.12) !important;
    color: #ffffff !important;
    font-weight: 600 !important;
  }

  .gemini-section-title {
    color: #94a3b8;
    font-size: 11.5px;
    font-weight: 600;
    letter-spacing: 0.4px;
    padding: 12px 10px 4px 10px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    text-transform: uppercase;
  }

  .gemini-bottom-dock {
    border-top: 1px solid rgba(255, 255, 255, 0.08);
    padding-top: 10px;
    margin-top: 20px;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .gemini-profile-pill {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 6px 8px;
    border-radius: 10px;
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.06);
    flex-grow: 1;
    margin-right: 6px;
  }
  .gemini-avatar {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    background: linear-gradient(135deg, #0284c7, #0369a1);
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 800;
    color: #fff;
    font-size: 13px;
  }

  /* ----------------------------------------------------
     CHAT MESSAGES
     ---------------------------------------------------- */
  [data-testid="stChatMessage"] {
    background: rgba(15, 23, 42, 0.94) !important;
    border: 1px solid rgba(56, 189, 248, 0.35) !important;
    border-radius: 16px !important;
    padding: 16px 20px !important;
    margin-bottom: 12px !important;
    backdrop-filter: blur(14px) !important;
    box-shadow: 0 8px 30px rgba(0, 0, 0, 0.5) !important;
  }
  [data-testid="stChatMessage"] * {
    color: #f8fafc !important;
    font-size: 14.5px !important;
    line-height: 1.6 !important;
  }
  [data-testid="stChatMessage"] strong, [data-testid="stChatMessage"] b {
    color: #fde047 !important;
  }

  /* ----------------------------------------------------
     CLEAN FLOATING PILL CHAT INPUT DOCK
     ---------------------------------------------------- */
  [data-testid="stBottom"] {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    padding-bottom: 12px !important;
  }
  [data-testid="stBottom"] > div {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    display: flex !important;
    flex-direction: column !important;
    align-items: center !important;
  }

  /* Clear default border from stChatInput */
  div[data-testid="stChatInput"] {
    border: none !important;
    background: transparent !important;
    box-shadow: none !important;
    padding: 0 !important;
    max-width: 820px !important;
    width: 100% !important;
    margin: 0 auto !important;
  }

  /* Capsule Pill styling */
  div[data-testid="stChatInput"] > div {
    background: rgba(22, 27, 38, 0.94) !important;
    border: 1px solid rgba(255, 255, 255, 0.16) !important;
    border-radius: 9999px !important;
    padding: 6px 14px 6px 46px !important;
    position: relative !important;
    box-shadow: 0 10px 32px rgba(0, 0, 0, 0.45) !important;
    backdrop-filter: blur(20px) !important;
    -webkit-backdrop-filter: blur(20px) !important;
    transition: all 0.2s ease !important;
  }

  div[data-testid="stChatInput"] > div:focus-within {
    border-color: rgba(255, 255, 255, 0.36) !important;
    box-shadow: 0 12px 38px rgba(0, 0, 0, 0.6) !important;
  }

  /* Textarea */
  div[data-testid="stChatInput"] textarea {
    color: #ffffff !important;
    -webkit-text-fill-color: #ffffff !important;
    font-size: 15px !important;
    background: transparent !important;
    border: none !important;
    outline: none !important;
    box-shadow: none !important;
    padding: 7px 36px 7px 0 !important;
  }
  div[data-testid="stChatInput"] textarea::placeholder {
    color: #94a3b8 !important;
    font-size: 14.5px !important;
  }

  /* Left '+' glyph */
  div[data-testid="stChatInput"] > div::before {
    content: '+';
    position: absolute;
    left: 18px;
    top: 50%;
    transform: translateY(-50%);
    font-size: 20px;
    font-weight: 300;
    color: #94a3b8;
    pointer-events: none;
    line-height: 1;
  }

  /* Right mic glyph */
  div[data-testid="stChatInput"] > div::after {
    content: '🎙';
    position: absolute;
    right: 54px;
    top: 50%;
    transform: translateY(-50%);
    font-size: 14px;
    color: #94a3b8;
    opacity: 0.65;
    pointer-events: none;
  }

  /* Periwinkle Send Button */
  div[data-testid="stChatInput"] button {
    background-color: #a5b4fc !important;
    border-radius: 50% !important;
    width: 34px !important;
    height: 34px !important;
    min-height: 34px !important;
    border: none !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    color: #1e1b4b !important;
    margin-right: 2px !important;
    transition: transform 0.15s ease !important;
  }
  div[data-testid="stChatInput"] button svg {
    fill: #1e1b4b !important;
  }
  div[data-testid="stChatInput"] button:hover {
    background-color: #c7d2fe !important;
    transform: scale(1.05) !important;
  }

  /* Disclaimer docked neatly below */
  .chat-bottom-disclaimer {
    text-align: center;
    color: #94a3b8;
    font-size: 11.5px;
    font-weight: 400;
    margin-top: 6px;
    letter-spacing: 0.2px;
    user-select: none;
  }

  /* CARDS & GENERAL STYLING */
  .waypoint-card {
    background: rgba(15, 23, 42, 0.94) !important;
    border: 1px solid rgba(56, 189, 248, 0.35) !important;
    border-left: 4px solid #f59e0b !important;
    border-radius: 16px !important;
    padding: 16px !important;
    margin-bottom: 16px !important;
    box-shadow: 0 12px 35px rgba(0, 0, 0, 0.6) !important;
  }
  .day-tag {
    background: #f59e0b;
    color: #0b0f19 !important;
    font-weight: 900;
    font-size: 11px;
    padding: 3px 8px;
    border-radius: 5px;
    margin-right: 8px;
  }
  .day-photo-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 8px;
    margin: 10px 0 12px 0;
  }
  .day-photo-card {
    position: relative;
    border-radius: 10px;
    overflow: hidden;
    height: 140px;
    border: 1px solid rgba(255, 255, 255, 0.16);
    background: #0b1329;
  }
  .day-photo-card img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
  .photo-tag-pill {
    position: absolute;
    top: 6px;
    left: 6px;
    background: rgba(15, 23, 42, 0.88);
    border: 1px solid rgba(245, 158, 11, 0.6);
    color: #fde047;
    font-size: 9.5px;
    font-weight: 700;
    padding: 2px 6px;
    border-radius: 5px;
  }
  .photo-overlay {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    background: linear-gradient(180deg, transparent 0%, rgba(15, 23, 42, 0.95) 90%);
    padding: 5px 8px;
    color: #f1f5f9;
    font-size: 10.5px;
    font-weight: 600;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .plan-tag {
    background: #1e293b;
    border: 1px solid #38bdf8;
    border-radius: 4px;
    padding: 2px 6px;
    font-size: 10.5px;
    color: #38bdf8;
    font-weight: 700;
    margin-left: 4px;
  }
  .pricing-tag {
    background: #14532d;
    border: 1px solid #22c55e;
    border-radius: 4px;
    padding: 2px 6px;
    font-size: 10.5px;
    color: #86efac;
    font-weight: 700;
    margin-left: 4px;
  }
  /* ----------------------------------------------------
     RESPONSIVE MOBILE 2-ROW HEADER (<= 768px)
     ---------------------------------------------------- */
  @media (max-width: 768px) {
    /* 1. Expand the container to comfortably fit 2 rows */
    .modern-app-bar {
      padding: 10px 14px !important;
      display: flex !important;
      flex-wrap: wrap !important;
      align-items: center !important;
      justify-content: space-between !important;
      gap: 6px 10px !important;
      height: auto !important;
      min-height: 72px !important;
    }

    /* Left title lock */
    .bar-left {
      display: flex !important;
      align-items: center !important;
      gap: 8px !important;
      flex: 1 1 auto !important;
      min-width: 0 !important;
    }

    .brand-logo-icon {
      width: 28px !important;
      height: 28px !important;
      min-width: 28px !important;
      border-radius: 6px !important;
    }

    .brand-logo-icon img {
      height: 24px !important;
      width: auto !important;
    }

    .brand-text-wrap {
      display: contents !important; /* Lets title stay on row 1 and subtitle break to row 2 */
    }

    .brand-title {
      font-size: 1rem !important;
      white-space: nowrap !important;
      line-height: 1.1 !important;
      margin: 0 !important;
    }

    /* Right Telemetry stays locked to the top-right */
    .bar-right-telemetry {
      display: flex !important;
      align-items: center !important;
      flex: 0 0 auto !important;
      margin-left: auto !important;
    }

    .status-pill-modern {
      padding: 3px 8px !important;
      font-size: 9.5px !important;
      white-space: nowrap !important;
    }

    .chip-tag-modern {
      display: none !important;
    }

    /* 2. Subtitle: Drop onto its own full-width row with elegant separator */
    .brand-sub {
      display: block !important;
      width: 100% !important;
      flex-basis: 100% !important;
      order: 3 !important;
      font-size: 10px !important;
      font-weight: 500 !important;
      color: #94a3b8 !important;
      line-height: 1.35 !important;
      letter-spacing: 0.1px !important;
      margin-top: 4px !important;
      padding-top: 5px !important;
      border-top: 1px solid rgba(255, 255, 255, 0.08) !important;
      white-space: normal !important;
      text-align: left !important;
    }

    /* 3. Input Capsule Bar */
    div[data-testid="stChatInput"] {
      width: 100% !important;
      max-width: 95% !important;
    }

    div[data-testid="stChatInput"] > div {
      padding: 4px 8px 4px 38px !important;
    }

    div[data-testid="stChatInput"] > div::before {
      left: 14px !important;
      font-size: 18px !important;
    }

    div[data-testid="stChatInput"] > div::after {
      display: none !important;
    }

    div[data-testid="stChatInput"] textarea {
      font-size: 13.5px !important;
      padding: 6px 12px 6px 0 !important;
    }

    div[data-testid="stChatInput"] button {
      width: 32px !important;
      height: 32px !important;
      min-height: 32px !important;
    }

    .chat-bottom-disclaimer {
      font-size: 10.5px !important;
      margin-top: 6px !important;
      margin-bottom: 8px !important;
    }
  }
</style>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# STATE INITIALIZATION
# ---------------------------------------------------------------------------
if "active_tab" not in st.session_state:
    st.session_state.active_tab = "Home"

if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": (
                "**Wondoo Alpine Concierge**\n\n"
                "Welcome! Where across our destination circuits (West Bengal, Sikkim, Northeast, Uttarakhand, Himachal, Kashmir, Odisha, Kerala, or Andaman) are you planning to travel, for how long, and who is joining you?"
            ),
        }
    ]

if "itinerary_data" not in st.session_state:
    st.session_state.itinerary_data = None
if "generated_files" not in st.session_state:
    st.session_state.generated_files = None
if "pdf_path" not in st.session_state:
    st.session_state.pdf_path = None
if "booking_confirmed" not in st.session_state:
    st.session_state.booking_confirmed = None

# AUTHENTICATION & WALLET STATE
if "user" not in st.session_state:
    st.session_state.user = None
if "applied_coupon" not in st.session_state:
    st.session_state.applied_coupon = None
if "use_wallet" not in st.session_state:
    st.session_state.use_wallet = False

# ---------------------------------------------------------------------------
# LOGIN & SIGNUP DIALOG
# ---------------------------------------------------------------------------
@st.dialog("🔑 Sign In to Wondoo Alpine Club")
def open_login_dialog():
    st.markdown("##### Unlock Exclusive Member Pricing & Alpine Wallet")
    st.caption("New travelers instantly receive **₹2,500 Welcome Credits** in their Alpine Wallet.")
    
    name = st.text_input("Full Name*", placeholder="e.g. Rahul Sharma")
    email = st.text_input("Email Address*", placeholder="e.g. rahul@example.com")
    phone = st.text_input("WhatsApp Number*", placeholder="e.g. 9876543210")
    
    if st.button("Continue to Expedition Account", type="primary", use_container_width=True):
        if not name.strip() or not email.strip() or not phone.strip():
            st.error("Please fill in your name, email, and WhatsApp number.")
            return
        
        st.session_state.user = {
            "name": name.strip(),
            "email": email.strip().lower(),
            "phone": phone.strip(),
            "wallet_balance": 2500.0,
            "member_tier": "Alpine Explorer",
            "logged_in": True
        }
        st.success(f"Welcome, {name}! ₹2,500 credited to your Alpine Wallet.")
        st.rerun()

# ---------------------------------------------------------------------------
# MODAL WITH FLEET SELECTOR & COUPON / WALLET ENGINE
# ---------------------------------------------------------------------------
@st.dialog("🎒 Reserve Complete Expedition Package", width="large")
def open_package_booking_dialog(itinerary: TourItinerary, matched_stays: list):
    if not st.session_state.get("user"):
        st.warning("🔒 Please sign in to book and apply discount coupons.")
        open_login_dialog()
        return

    user = st.session_state.user
    total_days = len(itinerary.days)
    booking_id = f"WND-{uuid.uuid4().hex[:6].upper()}"

    st.markdown(f"### **{itinerary.tour_title}** ({itinerary.duration})")

    c1, c2, c3 = st.columns([1.2, 1, 1])
    with c1:
        lead_name = st.text_input("Lead Traveler Name*", value=user.get("name", ""))
    with c2:
        phone_num = st.text_input("WhatsApp Number*", value=user.get("phone", ""))
    with c3:
        email_addr = st.text_input("Email Address*", value=user.get("email", ""), disabled=True)

    c_heads, c_rooms, c_pickup = st.columns([1, 1, 1.2])
    with c_heads:
        num_heads = st.number_input("Total Heads", min_value=1, max_value=25, value=2)
    with c_rooms:
        num_rooms = st.number_input("Rooms", min_value=1, max_value=12, value=1)
    with c_pickup:
        pickup_loc = st.selectbox(
            "Pickup & Drop Point",
            ["Bagdogra Airport (IXB)", "New Jalpaiguri Stn (NJP)", "Siliguri Junction", "Gangtok Stand"]
        )

    pricing = calculate_dynamic_sheet_quotation(
        matched_stays=matched_stays,
        total_days=total_days,
        num_heads=int(num_heads),
        num_rooms=int(num_rooms),
        cab_option="Include Dedicated Cab"
    )
    base_grand_total = pricing["grand_total"]

    st.markdown("<hr style='border-color: rgba(255,255,255,0.1); margin: 15px 0;'>", unsafe_allow_html=True)
    st.markdown("##### **2. Discounts & Alpine Wallet**")

    col_coupon, col_wallet = st.columns([1.2, 1])

    with col_coupon:
        st.markdown("<div style='font-size:13px; font-weight:700; color:#38bdf8;'>🎟️ Apply Promo Coupon (Max 1)</div>", unsafe_allow_html=True)
        
        if st.session_state.get("applied_coupon"):
            cur_cpn = st.session_state.applied_coupon
            st.markdown(
                f"""
                <div style="background: rgba(34, 197, 94, 0.15); border: 1px solid #22c55e; border-radius: 8px; padding: 8px 12px; margin-bottom: 6px;">
                  <span style="color: #4ade80; font-weight: 700;">✔ Code '{cur_cpn['code']}' Active</span> 
                  <span style="color: #ffffff; font-size: 13px;">(-₹{cur_cpn['discount']:,.0f})</span>
                </div>
                """,
                unsafe_allow_html=True
            )
            if st.button("Remove Coupon", key="remove_coupon_btn"):
                st.session_state.applied_coupon = None
                st.rerun()
        else:
            c_in, c_btn = st.columns([2, 1])
            with c_in:
                coupon_code_input = st.text_input("Coupon Code", placeholder="e.g. WONDOO10", label_visibility="collapsed")
            with c_btn:
                if st.button("Apply", use_container_width=True):
                    is_valid, msg, discount = validate_coupon_for_user(
                        code=coupon_code_input,
                        grand_total=base_grand_total,
                        user_email=user["email"]
                    )
                    if is_valid:
                        st.session_state.applied_coupon = {
                            "code": coupon_code_input.strip().upper(),
                            "discount": discount
                        }
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

    with col_wallet:
        st.markdown(f"<div style='font-size:13px; font-weight:700; color:#fde047;'>🎒 Alpine Wallet (Balance: ₹{user.get('wallet_balance', 0):,.0f})</div>", unsafe_allow_html=True)
        use_wallet = st.checkbox("Redeem Wallet Credits (Up to ₹2,000)", value=st.session_state.get("use_wallet", False))
        st.session_state.use_wallet = use_wallet

    coupon_discount = st.session_state.applied_coupon["discount"] if st.session_state.get("applied_coupon") else 0.0
    wallet_deduction = min(float(user.get("wallet_balance", 0)), 2000.0) if use_wallet else 0.0

    final_total = max(base_grand_total - coupon_discount - wallet_deduction, 0.0)
    advance_payable = int(final_total * 0.25)
    per_head_final = int(final_total / max(int(num_heads), 1))

    st.markdown("<hr style='border-color: rgba(255,255,255,0.1); margin: 15px 0;'>", unsafe_allow_html=True)
    st.markdown("##### **3. Final Payable Fare**")

    q1, q2, q3, q4 = st.columns(4)
    q1.metric("Final Package", f"₹{final_total:,.0f}", delta=f"-₹{coupon_discount + wallet_deduction:,.0f}" if (coupon_discount or wallet_deduction) else None)
    q2.metric("Per Head", f"₹{per_head_final:,.0f}")
    q3.metric("25% Advance Token", f"₹{advance_payable:,.0f}")
    q4.metric("Total Saved", f"₹{coupon_discount + wallet_deduction:,.0f}")

    qr_url = generate_upi_qr_url(
        vpa=UPI_VPA,
        payee_name=UPI_PAYEE_NAME,
        amount=float(advance_payable),
        booking_id=booking_id
    )
    col_qr, col_info = st.columns([1, 1.6])
    with col_qr:
        st.image(qr_url, width=170, caption=f"Ref: {booking_id}")
    with col_info:
        st.markdown(f"""
        - **Payee**: `{UPI_PAYEE_NAME}`
        - **UPI ID**: `{UPI_VPA}`
        - **Advance Token Due**: **₹{advance_payable:,.0f}**
        """)
        txn_ref = st.text_input("12-digit UPI UTR / Ref #", placeholder="e.g. 427810398412")

    if st.button("🚀 Confirm & Lock Expedition Booking", type="primary", use_container_width=True):
        if not lead_name.strip() or not phone_num.strip():
            st.error("Please provide both Lead Traveler Name and WhatsApp Number.")
            return

        applied_code = "NONE"
        if st.session_state.get("applied_coupon"):
            applied_code = st.session_state.applied_coupon["code"]
            record_coupon_redemption(applied_code, user["email"])

        if use_wallet:
            st.session_state.user["wallet_balance"] -= wallet_deduction

        payload = {
            "booking_id": booking_id,
            "user_email": user["email"],
            "lead_name": lead_name.strip(),
            "phone": phone_num.strip(),
            "circuit": itinerary.tour_title,
            "duration": itinerary.duration,
            "grand_total": final_total,
            "coupon_applied": applied_code,
            "coupon_discount": coupon_discount,
            "wallet_redeemed": wallet_deduction,
            "advance_paid": advance_payable,
            "transaction_utr": txn_ref.strip() if txn_ref.strip() else "PENDING_VERIFICATION"
        }

        st.session_state.applied_coupon = None
        st.session_state.booking_confirmed = payload
        st.rerun()

# ---------------------------------------------------------------------------
# GEMINI-STYLE LEFT SIDE PANEL (MONOCHROME & LEFT-ALIGNED)
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown(
        f"""
        <div class="gemini-sidebar-header">
          <div class="gemini-brand-logo">
            <img src="{APP_LOGO_SRC}" alt="Logo" style="height: 26px; width: auto; object-fit: contain; border-radius: 4px;" />
            <span>Wondoo Alpine</span>
          </div>
          <span style="color: #94a3b8; font-size: 13px;">▯</span>
        </div>
        """,
        unsafe_allow_html=True
    )

    if st.button("＋   New expedition", key="side_new_chat", use_container_width=True):
        st.session_state.itinerary_data = None
        st.session_state.messages = [
            {
                "role": "assistant",
                "content": (
                    "**Wondoo Alpine Concierge**\n\n"
                    "Welcome! Where across our destination circuits (West Bengal, Sikkim, Northeast, Uttarakhand, Himachal, Kashmir, Odisha, Kerala, or Andaman) are you planning to travel, for how long, and who is joining you?"
                ),
            }
        ]
        st.session_state.active_tab = "Home"
        st.rerun()

    nav_btn_home = "primary" if st.session_state.active_tab == "Home" else "secondary"
    if st.button("🗨   Concierge Terminal", key="side_home", type=nav_btn_home, use_container_width=True):
        st.session_state.active_tab = "Home"
        st.rerun()

    nav_btn_itin = "primary" if st.session_state.active_tab == "Itineraries" else "secondary"
    if st.button("⚲   Signature Circuits", key="side_itin", type=nav_btn_itin, use_container_width=True):
        st.session_state.active_tab = "Itineraries"
        st.rerun()

    nav_btn_pkg = "primary" if st.session_state.active_tab == "Packages" else "secondary"
    if st.button("⌸   Curated Packages", key="side_pkg", type=nav_btn_pkg, use_container_width=True):
        st.session_state.active_tab = "Packages"
        st.rerun()

    st.markdown("<hr style='border-color: rgba(255,255,255,0.06); margin: 8px 0;'>", unsafe_allow_html=True)

    st.markdown('<div class="gemini-section-title"><span>Featured Circuits</span><span>✦</span></div>', unsafe_allow_html=True)
    for idx, item in enumerate(LIVE_ITINERARIES[:3]):
        short_name = (item["title"][:22] + "...") if len(item["title"]) > 22 else item["title"]
        if st.button(f"▲   {short_name}", key=f"side_feat_{idx}", use_container_width=True):
            extraction_prompt = (
                f"Create an authentic, structured tour itinerary for: {item['title']}.\n"
                f"Duration: {item['duration']}.\n"
                f"Sector: {item['sector']} ({item['elevation']}).\n"
                f"Highlights: {item['default_prompt']}"
            )
            with st.spinner("Synthesizing circuit..."):
                try:
                    plan = generate_itinerary_content(extraction_prompt)
                    st.session_state.itinerary_data = plan
                    st.session_state.active_tab = "Home"
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")

    st.markdown(
        """
        <div class="gemini-section-title">
          <span>Recent Expeditions</span>
          <span style="color:#64748b; font-size:10px;">▼</span>
        </div>
        """,
        unsafe_allow_html=True
    )

    if st.session_state.itinerary_data:
        active_title = st.session_state.itinerary_data.tour_title
        short_title = (active_title[:23] + "...") if len(active_title) > 23 else active_title
        st.button(f"◷   {short_title}", key="side_curr_trip", type="primary", use_container_width=True)
    else:
        st.markdown("<div style='color: #64748b; font-size: 12px; padding: 6px 12px;'>No recent expedition</div>", unsafe_allow_html=True)

    st.markdown("<div style='height: 35px;'></div>", unsafe_allow_html=True)
    if st.session_state.get("user"):
        u = st.session_state.user
        initials = u["name"][0].upper() if u.get("name") else "W"
        st.markdown(
            f"""
            <div class="gemini-bottom-dock">
              <div class="gemini-profile-pill">
                <div class="gemini-avatar">{initials}</div>
                <div>
                  <div style="font-size: 13px; font-weight: 700; color: #fff;">{u['name']}</div>
                  <div style="font-size: 11px; color: #34d399; font-weight: 600;">₹{u['wallet_balance']:,.0f} Wallet</div>
                </div>
              </div>
            </div>
            """,
            unsafe_allow_html=True
        )
        if st.button("⎋   Log out", key="side_logout_btn", use_container_width=True):
            st.session_state.user = None
            st.session_state.applied_coupon = None
            st.session_state.use_wallet = False
            st.rerun()
    else:
        st.markdown(
            """
            <div class="gemini-bottom-dock">
              <div class="gemini-profile-pill">
                <div class="gemini-avatar" style="background: #1e293b; color: #f8fafc;">W</div>
                <div>
                  <div style="font-size: 12.5px; font-weight: 700; color: #fff;">Wondoo Pro</div>
                  <div style="font-size: 10.5px; color: #94a3b8;">₹2,500 Bonus Ready</div>
                </div>
              </div>
            </div>
            """,
            unsafe_allow_html=True
        )
        if st.button("⚿   Sign in", key="side_login_btn", use_container_width=True):
            open_login_dialog()

# ---------------------------------------------------------------------------
# MODERN FROSTED GLASS BAR WITH LIVE TELEMETRY
# ---------------------------------------------------------------------------
st.markdown(
    f"""
    <div class="modern-app-bar">
      <div class="bar-left">
        <div class="brand-logo-icon" style="background: transparent; border: none; box-shadow: none;">
          <img src="{APP_LOGO_SRC}" alt="Wondoo Logo" style="height: 38px; width: auto; object-fit: contain;" />
        </div>
        <div class="brand-text-wrap">
          <div class="brand-title">Wondoo <span>Alpine Studio</span></div>
          <div class="brand-sub">Autonomous Circuit Architect • Curated Mountain Stays • Brochure Studio</div>
        </div>
      </div>
      <div class="bar-right-telemetry">
        <div class="status-pill-modern">
          <div class="pulse-dot-green"></div>
          <span>{period_label}</span>
        </div>
        <div class="chip-tag-modern">v2.5 AI Active</div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown("<hr style='border-color: rgba(56, 189, 248, 0.15); margin: 4px 0 14px 0;'>", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# CONFIRMATION BANNER
# ---------------------------------------------------------------------------
if st.session_state.get("booking_confirmed"):
    info = st.session_state.booking_confirmed
    wa_dispatch_text = urllib.parse.quote(
        f"🏔️ *Wondoo Alpine Reservation Confirmation*\n\n"
        f"• *Booking ID*: {info['booking_id']}\n"
        f"• *Lead Traveler*: {info['lead_name']}\n"
        f"• *Contact*: {info['phone']}\n"
        f"• *Circuit*: {info['circuit']} ({info['duration']})\n"
        f"• *Grand Total*: ₹{info['grand_total']:,}\n"
        f"• *Advance Token*: ₹{info['advance_paid']:,}\n"
        f"• *Coupon*: {info.get('coupon_applied', 'NONE')}\n"
        f"• *UTR Ref*: {info['transaction_utr']}\n\n"
        f"Please share our expedition check-in voucher and driver assignment."
    )
    wa_direct_url = f"https://api.whatsapp.com/send?phone={AGENCY_WHATSAPP_NUMBER}&text={wa_dispatch_text}"

    st.markdown(
        f"""
        <div style="
            background: rgba(15, 23, 42, 0.94);
            border: 1.5px solid #10b981;
            border-radius: 16px;
            padding: 16px 20px;
            margin-bottom: 20px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
        ">
          <div style="display: flex; flex-direction: column; gap: 10px;">
            <div style="font-size: 1.15rem; font-weight: 800; color: #34d399;">
              🎉 Reservation #{info['booking_id']} Locked & Confirmed!
            </div>
            <div style="font-size: 14px; color: #f1f5f9; line-height: 1.55;">
              Thank you, <b>{info['lead_name']}</b>. Your request for <b>{info['circuit']}</b> (Est. <b>₹{info['grand_total']:,}</b>) is logged.<br>
              Advance Ref: <code style="color: #fde047;">{info['transaction_utr']}</code>
            </div>
            <div>
              <a href="{wa_direct_url}" target="_blank" style="
                  display: inline-block;
                  background: #25D366; 
                  color: white; 
                  text-decoration: none; 
                  padding: 9px 18px; 
                  border-radius: 10px; 
                  font-weight: 700; 
                  font-size: 13.5px;
              ">
                  💬 Send Booking Summary to WhatsApp
              </a>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("✕ Dismiss Notification", key="dismiss_booking_banner"):
        st.session_state.booking_confirmed = None
        st.rerun()

# ---------------------------------------------------------------------------
# ROUTING
# ---------------------------------------------------------------------------

# === TAB 2: SIGNATURE ITINERARIES ===
if st.session_state.active_tab == "Itineraries":
    hdr_c1, hdr_c2 = st.columns([5, 1])
    with hdr_c1:
        st.markdown("<h3 style='color: #ffffff;'>🗺️ Pre-Defined Signature Itineraries</h3>", unsafe_allow_html=True)
        st.markdown(
            "<p style='color: #cbd5e1; font-size: 13.5px; margin-top:-6px; margin-bottom:14px;'>"
            "Select your desired duration on any circuit to immediately compile your custom day-by-day plan and matched stays."
            "</p>",
            unsafe_allow_html=True
        )
    with hdr_c2:
        if st.button("🔄 Sync Sheet", key="sync_itin_btn", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    grid_cols = st.columns(2, gap="medium")
    for idx, itin in enumerate(LIVE_ITINERARIES):
        img_url = itin.get("image") if itin.get("image") and str(itin.get("image")).startswith("http") else DEFAULT_CARD_IMG
        with grid_cols[idx % 2]:
            st.markdown(
                f"""
                <div style="
                    background: rgba(15, 23, 42, 0.94);
                    border: 1px solid rgba(56, 189, 248, 0.35);
                    border-radius: 18px;
                    overflow: hidden;
                    margin-bottom: 10px;
                    box-shadow: 0 14px 40px rgba(0,0,0,0.6);
                ">
                  <div style="width: 100%; height: 180px; position: relative; background: #0b1329;">
                    <img src="{img_url}" alt="{itin['title']}" style="width: 100%; height: 100%; object-fit: cover; display: block;" onerror="this.src='{DEFAULT_CARD_IMG}'" />
                    <div style="position: absolute; top: 10px; left: 10px; background: rgba(15,23,42,0.92); border: 1px solid rgba(245,158,11,0.6); color: #fde047; font-size: 11px; font-weight: 800; padding: 3px 10px; border-radius: 6px;">
                      📍 {itin['sector']} • Base: {itin['duration']}
                    </div>
                  </div>
                  <div style="padding: 16px 18px;">
                    <div style="font-size: 18px; font-weight: 800; color: #ffffff; margin-bottom: 4px;">{itin['title']}</div>
                    <div style="font-size: 12px; color: #38bdf8; font-weight: 600; margin-bottom: 10px;">Altitude: {itin['elevation']}</div>
                    <ul style="list-style: none; padding-left: 0; margin: 0;">
                      {"".join([f"<li style='color:#e2e8f0; font-size:13px; margin-bottom:6px;'>✦ {h}</li>" for h in itin['highlights']])}
                    </ul>
                  </div>
                </div>
                """,
                unsafe_allow_html=True
            )

            match = re.search(r'(\d+)\s*(?:Day|D)', itin['duration'], re.IGNORECASE)
            base_days = int(match.group(1)) if match else 4
            picker_options = [3, 4, 5, 6, 7, 8]
            default_idx = picker_options.index(base_days) if base_days in picker_options else 1

            col_pick, col_action = st.columns([1.1, 1.9], gap="small")
            with col_pick:
                custom_days = st.selectbox(
                    "Duration",
                    options=picker_options,
                    index=default_idx,
                    format_func=lambda d: f"{d}D / {d-1}N",
                    key=f"picker_{idx}"
                )
            with col_action:
                st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
                if st.button(
                    f"⚡ Generate {custom_days}D Plan & Stays",
                    key=f"gen_custom_itin_{idx}",
                    type="primary",
                    use_container_width=True
                ):
                    with st.spinner(f"Synthesizing customized {custom_days}D expedition for {itin['title']}..."):
                        extraction_prompt = (
                            f"Create an authentic, structured tour itinerary for: {itin['title']}.\n"
                            f"Strict Duration: Exactly {custom_days} Days / {custom_days - 1} Nights.\n"
                            f"Sector & Elevation: {itin['sector']} ({itin['elevation']}).\n"
                            f"Highlights: {itin['default_prompt']}"
                        )
                        try:
                            plan = generate_itinerary_content(extraction_prompt)
                            st.session_state.itinerary_data = plan
                            st.session_state.active_tab = "Home"
                            st.rerun()
                        except Exception as e:
                            st.error(f"Generation error: {e}")

# === TAB 3: SIGNATURE PACKAGES ===
elif st.session_state.active_tab == "Packages":
    hdr_p1, hdr_p2 = st.columns([5, 1])
    with hdr_p1:
        st.markdown("<h3 style='color: #ffffff;'>🎒 Handcrafted Expedition Packages</h3>", unsafe_allow_html=True)
        st.markdown(
            "<p style='color: #cbd5e1; font-size: 14px; font-weight: 500; margin-top: -6px; margin-bottom: 14px;'>"
            "Browse and filter all-inclusive holiday packages with dedicated mountain transit, curated stays, and meals."
            "</p>",
            unsafe_allow_html=True
        )
    with hdr_p2:
        if st.button("🔄 Sync Sheet", key="sync_pkg_btn", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    def parse_price(val_str: str) -> int:
        clean = re.sub(r"[^\d]", "", str(val_str))
        return int(clean) if clean else 0

    with st.expander("🔍 Filter & Sort Packages", expanded=False):
        f_col1, f_col2, f_col3 = st.columns([1.2, 1.4, 1.2])

        with f_col1:
            duration_filter = st.selectbox(
                "Filter by Duration",
                options=["All Durations", "Quick (3–4 Days)", "Signature (5–6 Days)", "Extended (7+ Days)"],
                key="pkg_filter_dur"
            )

        with f_col2:
            max_found_price = max([parse_price(p["price_per_head"]) for p in LIVE_PACKAGES] + [25000])
            budget_limit = st.slider(
                "Max Budget (Per Head)",
                min_value=8000,
                max_value=max(max_found_price, 30000),
                value=max(max_found_price, 30000),
                step=1000,
                format="₹%d",
                key="pkg_filter_price"
            )

        with f_col3:
            sort_by = st.selectbox(
                "Sort By",
                options=["Default", "Price: Low to High", "Price: High to Low", "Duration: Short to Long"],
                key="pkg_sort_by"
            )

    filtered_packages = []
    for pkg in LIVE_PACKAGES:
        price_num = parse_price(pkg["price_per_head"])
        match = re.search(r"(\d+)\s*(?:Day|D)", pkg["duration"], re.IGNORECASE)
        days = int(match.group(1)) if match else 4

        duration_match = True
        if duration_filter == "Quick (3–4 Days)" and not (3 <= days <= 4):
            duration_match = False
        elif duration_filter == "Signature (5–6 Days)" and not (5 <= days <= 6):
            duration_match = False
        elif duration_filter == "Extended (7+ Days)" and days < 7:
            duration_match = False

        budget_match = price_num <= budget_limit if price_num > 0 else True

        if duration_match and budget_match:
            pkg_copy = dict(pkg)
            pkg_copy["_parsed_price"] = price_num
            pkg_copy["_parsed_days"] = days
            filtered_packages.append(pkg_copy)

    if sort_by == "Price: Low to High":
        filtered_packages.sort(key=lambda x: x["_parsed_price"])
    elif sort_by == "Price: High to Low":
        filtered_packages.sort(key=lambda x: x["_parsed_price"], reverse=True)
    elif sort_by == "Duration: Short to Long":
        filtered_packages.sort(key=lambda x: x["_parsed_days"])

    if not filtered_packages:
        st.info("No packages match your selected filter criteria. Try adjusting your duration or budget limit.")
    else:
        pkg_cols = st.columns(2, gap="medium")
        for idx, pkg in enumerate(filtered_packages):
            with pkg_cols[idx % 2]:
                st.markdown(
                    f"""
                    <div style="
                        background: rgba(15, 23, 42, 0.94);
                        border: 1px solid rgba(56, 189, 248, 0.35);
                        border-radius: 18px;
                        overflow: hidden;
                        margin-bottom: 12px;
                        box-shadow: 0 14px 40px rgba(0, 0, 0, 0.6);
                    ">
                      <div style="padding: 18px;">
                        <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:8px;">
                          <div>
                            <div style="font-size:18px; font-weight:800; color:#ffffff;">{pkg['title']}</div>
                            <div style="font-size:12.5px; color:#94a3b8; font-weight:600;">{pkg['duration']}</div>
                          </div>
                          <div style="text-align:right;">
                            <div style="font-size:20px; font-weight:800; color:#22c55e;">{pkg['price_per_head']}</div>
                            <div style="font-size:11px; color:#cbd5e1;">per head</div>
                          </div>
                        </div>
                        <div style="display:flex; flex-wrap:wrap; gap:6px; margin-bottom:12px;">
                          <span class="plan-tag">🏡 {pkg['stay_type']}</span>
                          <span class="pricing-tag">🚗 {pkg['transit']}</span>
                          <span class="plan-tag">🍽️ {pkg['meals']}</span>
                        </div>
                        <ul style="list-style:none; padding-left:0; margin:0 0 16px 0;">
                          {"".join([f"<li style='color:#e2e8f0; font-size:13px; margin-bottom:6px;'>✔ {f}</li>" for f in pkg['features']])}
                        </ul>
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

                wa_pkg_text = urllib.parse.quote(
                    f"Hi Wondoo Team, I would like to reserve or customize the package: '{pkg['title']}' ({pkg['duration']} at {pkg['price_per_head']}/head)."
                )
                wa_pkg_link = f"https://api.whatsapp.com/send?phone={AGENCY_WHATSAPP_NUMBER}&text={wa_pkg_text}"
                st.markdown(
                    f"""
                    <a href="{wa_pkg_link}" target="_blank" style="
                        display: block;
                        text-align: center;
                        background: #25D366; 
                        color: white; 
                        text-decoration: none; 
                        font-size: 13.5px; 
                        font-weight: 700; 
                        padding: 10px; 
                        border-radius: 12px; 
                        margin-top: -6px; 
                        margin-bottom: 24px;
                    ">
                        💬 Inquire Package via WhatsApp
                    </a>
                    """,
                    unsafe_allow_html=True
                )

# === TAB 1: HOME (CONVERSATIONAL LIVE CHAT & ITINERARY WORKSPACE) ===
else:
    if not st.session_state.itinerary_data:
        for msg in st.session_state.messages:
            role = msg["role"]
            avatar = "👤" if role == "user" else "🏔️"
            with st.chat_message(role, avatar=avatar):
                st.markdown(msg["content"])

        if len(st.session_state.messages) > 1:
            c_left, c_center, c_right = st.columns([1, 2.5, 1])
            with c_center:
                if st.button("✨ Finalize Itinerary & Reveal Curated Stays", type="primary", use_container_width=True):
                    with st.spinner("Synthesizing final day-by-day itinerary..."):
                        dialogue_digest = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in st.session_state.messages])
                        extraction_prompt = f"Create an authentic, structured tour itinerary based on this conversation:\n\n{dialogue_digest}"
                        try:
                            plan = generate_itinerary_content(extraction_prompt)
                            st.session_state.itinerary_data = plan
                            st.rerun()
                        except Exception as e:
                            st.error(f"Generation error: {e}")

        # Floating Pill Chat Input
        user_prompt = st.chat_input("Ask Alpine...")

        # Inject disclaimer directly beneath the capsule input
        components.html(
            """
            <script>
            (function() {
                const parentDoc = window.parent.document;
                const bottomContainer = parentDoc.querySelector('[data-testid="stBottom"] > div');
                if (bottomContainer) {
                    let disclaimer = parentDoc.getElementById('alpine-custom-disclaimer');
                    if (!disclaimer) {
                        disclaimer = parentDoc.createElement('div');
                        disclaimer.id = 'alpine-custom-disclaimer';
                        disclaimer.className = 'chat-bottom-disclaimer';
                        disclaimer.innerText = 'Alpine is AI and can make mistakes.';
                        bottomContainer.appendChild(disclaimer);
                    }
                }
            })();
            </script>
            """,
            height=0,
            width=0,
        )

        if user_prompt:
            st.session_state.messages.append({"role": "user", "content": user_prompt})
            with st.chat_message("user", avatar="👤"):
                st.markdown(user_prompt)

            with st.chat_message("assistant", avatar="🏔️"):
                random_fact = random.choice(ALPINE_FACTS)
                waiting_banner = st.empty()
                waiting_banner.markdown(
                    f"""
                    <div class="gemini-thinking-banner">
                        <div class="gemini-loader">
                            <div class="gemini-dot"></div>
                            <div class="gemini-dot"></div>
                            <div class="gemini-dot"></div>
                        </div>
                        <div class="gemini-thinking-text">
                            {random_fact}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

                api_key = os.environ.get("GEMINI_API_KEY", "")
                client = genai.Client(api_key=api_key) if api_key else genai.Client()

                system_instruction = (
                    "You are the senior AI Travel Concierge at Wondoo Studio, engaging in a friendly, knowledgeable, and consultative dialogue.\n\n"
                    "OFFICIAL OPERATING FOOTPRINT:\n"
                    "• Eastern Himalayas & Hills: West Bengal (Darjeeling, Kalimpong, Dooars, Sandakphu), Sikkim (Gangtok, Pelling, North Sikkim).\n"
                    "• Northeast India: Assam (Kaziranga, Guwahati, Majuli), Meghalaya (Shillong, Cherrapunji, Dawki), Arunachal Pradesh (Tawang, Ziro, Dirang).\n"
                    "• North Himalayas: Uttarakhand, Himachal Pradesh, Jammu & Kashmir (including Ladakh circuits).\n"
                    "• Heritage & Coastal Escapes: Odisha (Bhubaneswar, Puri, Konark, Chilika), Kerala (Munnar, Alleppey, Wayanad, Kochi).\n"
                    "• Island Expeditions: Andaman & Nicobar Islands (Port Blair, Havelock, Neil Island).\n\n"
                    "CRITICAL FORMATTING & STYLE DIRECTIVES:\n"
                    "1. DO NOT GENERATE A DAY-BY-DAY ITINERARY IN THIS CHAT. Keep it conversational in 2-3 engaging paragraphs.\n"
                    "2. MANDATORY CLOSING CALL-TO-ACTION: Prompt them to click the '✨ Finalize Itinerary & Reveal Curated Stays' button right below.\n"
                    "Target length: 140 to 200 words."
                )

                contents = [
                    types.Content(
                        role="user" if m["role"] == "user" else "model",
                        parts=[types.Part.from_text(text=m["content"])],
                    )
                    for m in st.session_state.messages
                ]

                response_stream = client.models.generate_content_stream(
                    model="gemini-3.5-flash",
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.35,
                        max_output_tokens=2048,
                    ),
                )

                def stream_text_generator():
                    first_chunk = True
                    for chunk in response_stream:
                        if first_chunk:
                            waiting_banner.empty()
                            first_chunk = False

                        if getattr(chunk, "text", None):
                            yield chunk.text
                        elif getattr(chunk, "candidates", None) and chunk.candidates[0].content:
                            parts = chunk.candidates[0].content.parts
                            for p in parts:
                                if getattr(p, "text", None):
                                    yield p.text

                full_reply = st.write_stream(stream_text_generator())

            st.session_state.messages.append({"role": "assistant", "content": full_reply})
            st.rerun()

    else:
        data: TourItinerary = st.session_state.itinerary_data

        col_btn1, col_btn2 = st.columns([4, 1])
        with col_btn2:
            if st.button("🔄 Restart Consultation", use_container_width=True):
                st.session_state.itinerary_data = None
                st.session_state.generated_files = None
                st.session_state.pdf_path = None
                st.session_state.booking_confirmed = None
                st.rerun()

        col_itinerary, col_stays = st.columns([1.12, 0.88], gap="large")

        with col_itinerary:
            st.markdown(f"<h3 style='color: #ffffff;'>🗺️ {data.tour_title} ({data.duration})</h3>", unsafe_allow_html=True)

            primary_spot = data.days[0].stay_location or data.days[0].place_name
            coords = get_coords_for_place(primary_spot)
            weather_data = fetch_live_weather(coords[0], coords[1])
            st.markdown(
                f"""
                <div style="
                    background: rgba(15,23,42,0.88); 
                    border: 1px solid rgba(56,189,248,0.35); 
                    border-radius: 12px; 
                    padding: 10px 14px; 
                    margin-bottom: 16px; 
                    display: flex; 
                    justify-content: space-between; 
                    align-items: center;
                ">
                  <div>
                    <div style="font-size: 11px; text-transform: uppercase; color: #38bdf8; font-weight: 700;">Live Altitude Weather • {primary_spot}</div>
                    <div style="font-size: 13.5px; color: #f8fafc; font-weight: 600;">{weather_data['desc']} — <span style="color:#fde047;">{weather_data['temperature']}</span></div>
                  </div>
                  <div style="font-size: 11.5px; color: #cbd5e1; text-align: right;">💡 {weather_data['advisory']}</div>
                </div>
                """,
                unsafe_allow_html=True
            )

            with ThreadPoolExecutor(max_workers=min(len(data.days), 6)) as executor:
                photos_results = list(executor.map(
                    lambda d: search_key_spot_images(d.place_name, max_results=2), 
                    data.days
                ))

            all_day_cards_html = []

            for idx, day in enumerate(data.days):
                bullet_items = "".join([f"<li style='color:#f8fafc; margin-bottom:8px;'>✦ {b}</li>" for b in day.bullets])
                spot_photos = photos_results[idx]

                photo_cards = "".join([
                    f'<div class="day-photo-card">'
                    f'<img src="{p["url"]}" alt="{p["caption"]}" loading="lazy" />'
                    f'<div class="photo-tag-pill">📍 {day.place_name}</div>'
                    f'<div class="photo-overlay">📸 {p["caption"]}</div>'
                    f'</div>'
                    for p in spot_photos
                ])

                if getattr(day, "stay_location", None):
                    night_stay_html = (
                        f"<div style='color:#34d399; font-size:13px; font-weight:700; margin-bottom:10px; display:flex; align-items:center; gap:6px;'>"
                        f"🌙 Night Halt: <span style='color:#fde047; text-decoration: underline;'>Stay at {day.stay_location}</span>"
                        f"</div>"
                    )
                else:
                    night_stay_html = (
                        f"<div style='color:#94a3b8; font-size:13px; font-weight:600; margin-bottom:10px; display:flex; align-items:center; gap:6px;'>"
                        f"🛫 Departure / Drop-off (No overnight stay)"
                        f"</div>"
                    )

                single_card = (
                    f'<div class="waypoint-card">'
                    f'<div style="font-size:17px; font-weight:700; color:#ffffff; margin-bottom:4px;">'
                    f'<span class="day-tag">DAY {day.day_number}</span> {day.route_title}'
                    f'</div>'
                    f'<div style="color:#cbd5e1; font-size:13px; margin-bottom:4px;">'
                    f'📍 Key Spot: <b style="color:#38bdf8;">{day.place_name}</b>'
                    f'</div>'
                    f'{night_stay_html}'
                    f'<div class="day-photo-grid">{photo_cards}</div>'
                    f'<div style="font-size:12px; font-weight:700; color:#38bdf8; text-transform:uppercase; margin: 10px 0 6px 0; letter-spacing:0.5px;">'
                    f'Route Highlights & Activities'
                    f'</div>'
                    f'<ul style="list-style:none; padding-left:0; margin:0;">{bullet_items}</ul>'
                    f'</div>'
                )
                all_day_cards_html.append(single_card)

            combined_itinerary_html = "\n".join(all_day_cards_html)
            st.markdown(combined_itinerary_html, unsafe_allow_html=True)

        with col_stays:
            st.markdown("<h3 style='color: #ffffff;'>🏡 Recommended Stays & Booking</h3>", unsafe_allow_html=True)
            st.caption("Curated lodges matched to each day's night halt location from your live Google Sheet inventory.")

            stay_days = [d for d in data.days if getattr(d, "stay_location", None)]
            if not stay_days and len(data.days) > 1:
                stay_days = data.days[:-1]

            matched_trip_stays = []

            for night_idx, day in enumerate(stay_days, start=1):
                halt_location = getattr(day, "stay_location", None) or day.place_name

                st.markdown(
                    f"<div style='margin-top: 14px; margin-bottom: 6px; font-weight: 800; color: #fde047; font-size: 15px;'>"
                    f"🌙 Night {night_idx} • Stay at {halt_location}"
                    f"</div>",
                    unsafe_allow_html=True
                )

                try:
                    available_hotels = match_all_stays_for_day(halt_location)
                except Exception:
                    available_hotels = []

                if not available_hotels:
                    st.markdown(
                        f"""
                        <div style="
                            background: rgba(15, 23, 42, 0.85);
                            border: 1px dashed rgba(245, 158, 11, 0.5);
                            border-radius: 12px;
                            padding: 14px 16px;
                            margin-bottom: 14px;
                            color: #cbd5e1;
                            font-size: 13px;
                        ">
                            <span style="color: #fde047; font-weight: 700;">⚠️ No registered properties in inventory</span> for <b>{halt_location}</b>.<br>
                            <span style="font-size: 11.5px; color: #94a3b8;">Our concierge team will manually source local boutique stays upon request.</span>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
                    matched_trip_stays.append({
                        "stay_name": f"Custom Sourced ({halt_location})",
                        "night": night_idx,
                        "day": day.day_number,
                        "day_place": halt_location,
                        "plan": "On Request",
                        "pricing_type": "Per Room",
                        "rate": 0.0,
                        "property_type": "Custom Arrangement"
                    })
                else:
                    tab_labels = [
                        f"🏡 {h.get('stay_name', 'Stay')} (₹{h.get('rate', 0):,.0f})"
                        for h in available_hotels
                    ]
                    hotel_tabs = st.tabs(tab_labels)
                    selected_for_this_night = available_hotels[0]

                    for t_idx, tab in enumerate(hotel_tabs):
                        with tab:
                            s = available_hotels[t_idx]
                            s["night"] = night_idx
                            s["day"] = day.day_number
                            s["day_place"] = halt_location

                            img_src = s.get("image_url") if s.get("image_url") and str(s.get("image_url")).startswith("http") else DEFAULT_CARD_IMG
                            plan_name = s.get("plan", "EP")
                            p_type = s.get("pricing_type", "Per Room")
                            rate_val = s.get("rate", 0)
                            rate_suffix = "/head" if p_type == "Per Head" else "/room"

                            st.markdown(
                                f"""
                                <div style="
                                    background: rgba(15, 23, 42, 0.94);
                                    border: 1px solid rgba(56, 189, 248, 0.35);
                                    border-radius: 16px;
                                    overflow: hidden;
                                    margin-top: 8px;
                                    margin-bottom: 12px;
                                    box-shadow: 0 12px 30px rgba(0,0,0,0.6);
                                ">
                                  <div style="width: 100%; height: 160px; position: relative; background: #0b1329;">
                                    <img src="{img_src}" alt="{s['stay_name']}" style="width: 100%; height: 100%; object-fit: cover; display: block;" onerror="this.src='{DEFAULT_CARD_IMG}'" />
                                    <div style="position: absolute; top: 10px; left: 10px; background: rgba(15, 23, 42, 0.88); border: 1px solid rgba(245, 158, 11, 0.6); color: #fde047; font-size: 10px; font-weight: 800; text-transform: uppercase; padding: 2px 8px; border-radius: 6px;">
                                      Night {s['night']} • {halt_location}
                                    </div>
                                  </div>
                                  <div style="padding: 14px 16px;">
                                    <div style="font-size: 16px; font-weight: 700; color: #ffffff; margin-bottom: 4px;">
                                      {s['stay_name']}
                                      <span class="plan-tag">{plan_name} Plan</span>
                                      <span class="pricing-tag">{p_type}</span>
                                    </div>
                                    <div style="font-size: 11.5px; color: #cbd5e1; margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
                                      <span style="background: rgba(56,189,248,0.2); color: #38bdf8; padding: 2px 8px; border-radius: 6px; font-weight: 600;">
                                        📍 {s.get('altitude', 'Alpine Elev')}
                                      </span>
                                      <span>{s.get('property_type', 'Retreat')}</span>
                                      <b style="color: #fbbf24;">{s.get('rating', '4.8 ★')}</b>
                                      <span style="color: #22c55e; font-weight: 700; margin-left: auto;">₹{rate_val:,.0f} {rate_suffix}</span>
                                    </div>
                                    <div style="font-size: 12.5px; color: #cbd5e1; line-height: 1.45; margin-bottom: 12px;">
                                      {s.get('vibe', '')}
                                    </div>
                                  </div>
                                </div>
                                """,
                                unsafe_allow_html=True,
                            )

                            single_stay_inquiry = urllib.parse.quote(
                                f"Hi, I would like to reserve Night {s['night']} Stay at {s['stay_name']} ({halt_location}) on {plan_name} plan for circuit {data.tour_title}."
                            )
                            wa_stay_link = f"https://api.whatsapp.com/send?phone={AGENCY_WHATSAPP_NUMBER}&text={single_stay_inquiry}"
                            st.markdown(
                                f"""
                                <a href="{wa_stay_link}" target="_blank" style="
                                    display: block;
                                    text-align: center;
                                    background: rgba(15, 23, 42, 0.85);
                                    border: 1px solid rgba(56, 189, 248, 0.4);
                                    color: #38bdf8;
                                    text-decoration: none;
                                    font-size: 13px;
                                    font-weight: 600;
                                    padding: 7px;
                                    border-radius: 10px;
                                    margin-top: -6px;
                                    margin-bottom: 12px;
                                ">
                                    🛎️ Inquire Only for {s['stay_name']}
                                </a>
                                """,
                                unsafe_allow_html=True,
                            )

                    matched_trip_stays.append(selected_for_this_night)

            st.markdown("<hr style='border-color: rgba(255,255,255,0.1); margin: 20px 0 16px 0;'>", unsafe_allow_html=True)
            if st.button("🎒 Book Complete Tour Package (Stays + Transit)", type="primary", use_container_width=True):
                open_package_booking_dialog(data, matched_trip_stays)

        # -------------------------------------------------------------------
        # PRODUCTION STUDIO
        # -------------------------------------------------------------------
        st.markdown("<hr style='border-color: rgba(245, 158, 11, 0.25); margin: 30px 0;'>", unsafe_allow_html=True)
        with st.expander("🛠️ Production Studio • Compile Brochures, 9:16 Reels & Digital Passes", expanded=True):
            prod_col1, prod_col2 = st.columns([1, 1], gap="medium")

            with prod_col1:
                if st.button("🚀 Render Flyers & Compile PDF", type="primary", use_container_width=True):
                    output_dir = os.path.join("web_output", f"session_{abs(hash(data.tour_title))}")
                    os.makedirs(output_dir, exist_ok=True)

                    with st.status("Executing Playwright rendering pipeline...", expanded=True) as status:
                        st.write("• Fetching authentic destination imagery...")
                        st.write("• Rendering high-resolution typography on template canvas...")
                        asyncio.run(render_itinerary_pages(data, template_path="template_bg.png", output_dir=output_dir))

                        day_images = sorted(glob.glob(os.path.join(output_dir, "Day_*.jpg")))
                        sightseeing_img = os.path.join(output_dir, "Sightseeing_Enroute.jpg")
                        pdf_files = glob.glob(os.path.join(output_dir, "*.pdf"))

                        st.session_state.generated_files = day_images + ([sightseeing_img] if os.path.exists(sightseeing_img) else [])
                        if pdf_files:
                            st.session_state.pdf_path = pdf_files[0]
                        status.update(label="Export Complete!", state="complete", expanded=False)

                if st.button("📸 Export 9:16 Story Cards (Instagram / WhatsApp Status)", use_container_width=True):
                    story_dir = os.path.join("web_output", f"story_{abs(hash(data.tour_title))}")
                    os.makedirs(story_dir, exist_ok=True)
                    generated_stories = []
                    for d in data.days:
                        out_f = os.path.join(story_dir, f"Story_Day_{d.day_number}.jpg")
                        photo_url = DEFAULT_CARD_IMG
                        card_path = create_story_card(
                            day_number=d.day_number,
                            route_title=d.route_title,
                            stay_location=getattr(d, "stay_location", ""),
                            image_url=photo_url,
                            output_path=out_f
                        )
                        generated_stories.append(card_path)
                    st.success(f"Generated {len(generated_stories)} vertical 9:16 Story cards in `{story_dir}`!")

            with prod_col2:
                if st.session_state.pdf_path and os.path.exists(st.session_state.pdf_path):
                    with open(st.session_state.pdf_path, "rb") as f:
                        st.download_button(
                            label="📥 Download Merged PDF Brochure",
                            data=f.read(),
                            file_name=os.path.basename(st.session_state.pdf_path),
                            mime="application/pdf",
                            use_container_width=True,
                        )

                guest_link_suffix = generate_guest_portal_url(data)
                full_guest_url = f"{guest_link_suffix}"

                st.markdown(
                    f"""
                    <div style="background: rgba(15,23,42,0.8); border: 1px solid rgba(56,189,248,0.3); border-radius:10px; padding:10px; margin-top:8px;">
                      <div style="font-size:12px; font-weight:700; color:#fde047; margin-bottom:4px;">📱 Client Web Pass (No PDF Required)</div>
                      <a href="{full_guest_url}" target="_blank" style="color:#38bdf8; font-size:12.5px; font-weight:600; text-decoration:none;">
                        🔗 Open Live Digital Guest Pass
                      </a>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

                wa_summary = f"🏔️ *{data.tour_title}* ({data.duration})\n" + "\n".join(
                    [f"📍 *Day {d.day_number}*: {d.route_title}" for d in data.days]
                )
                wa_url = f"https://api.whatsapp.com/send?text={urllib.parse.quote(wa_summary)}"
                st.markdown(
                    f'<a href="{wa_url}" target="_blank" style="display:block; text-align:center; background:#25D366; color:white; padding:10px; border-radius:10px; text-decoration:none; font-weight:700; margin-top:10px;">💬 Dispatch Itinerary to WhatsApp</a>',
                    unsafe_allow_html=True,
                )

            if st.session_state.generated_files:
                tabs = st.tabs([f"Day {i+1}" if i < len(data.days) else "Sightseeing" for i in range(len(st.session_state.generated_files))])
                for idx, tab in enumerate(tabs):
                    with tab:
                        st.image(st.session_state.generated_files[idx], use_container_width=True)
