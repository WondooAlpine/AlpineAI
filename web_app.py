import os
import glob
import json
import uuid
import random
import re
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

from generate_itinerary import (
    generate_itinerary_content,
    render_itinerary_pages,
    TourItinerary,
)
from web_image_fetcher import search_key_spot_images
from stay_matcher import match_stay_for_day, match_all_stays_for_day
from booking_pricing import calculate_dynamic_sheet_quotation, generate_upi_qr_url

# ---------------------------------------------------------------------------
# CONFIGURATION & SECRETS
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Wondoo AI Studio | Alpine 3D Expedition Studio",
    page_icon="🏔️",
    layout="wide",
    initial_sidebar_state="collapsed",
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

# ---------------------------------------------------------------------------
# TIME ZONE: INDIAN STANDARD TIME (IST = UTC + 5:30)
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
                "image": str(row.get("image", "https://images.unsplash.com/photo-1544735716-392fe2489ffa?auto=format&fit=crop&w=900&q=80")).strip(),
                "highlights": highlights,
                "default_prompt": str(row.get("default_prompt", f"Plan an authentic {title} tour.")).strip()
            })
        return itineraries if itineraries else DEFAULT_FALLBACK_ITINERARIES
    except Exception as e:
        st.warning(f"Note: Could not reach 'Itineraries' tab on Google Sheet ({e}). Using local defaults.")
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
    except Exception as e:
        st.warning(f"Note: Could not reach 'Packages' tab on Google Sheet ({e}). Using local defaults.")
        return DEFAULT_FALLBACK_PACKAGES

LIVE_ITINERARIES = load_itineraries_from_sheet(CATALOG_SHEET_ID)
LIVE_PACKAGES = load_packages_from_sheet(CATALOG_SHEET_ID)

# ---------------------------------------------------------------------------
# 1. HARDWARE-ACCELERATED THREE.JS (MOBILE-OPTIMIZED VIEWPORT)
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
    let mountainMesh = null;

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
      mountainMesh = new THREE.Mesh(farGeo, farMat);
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
# 2. RESPONSIVE CSS STYLES & CONTRAST OVERRIDES
# ---------------------------------------------------------------------------
st.markdown(
    """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Space+Grotesk:wght@600;700&display=swap');

  html, body, [data-testid="stAppViewContainer"], .stApp, header[data-testid="stHeader"], footer {
    background-color: transparent !important;
    background: transparent !important;
    font-family: 'Plus Jakarta Sans', sans-serif !important;
    -webkit-tap-highlight-color: transparent;
  }
  header[data-testid="stHeader"] {
    background: transparent !important;
    box-shadow: none !important;
  }

  .block-container {
    max-width: 1300px !important;
    padding-top: 2.4rem !important;
    padding-bottom: 6rem !important;
    padding-left: 1rem !important;
    padding-right: 1rem !important;
    position: relative;
    z-index: 1;
  }

  .hero-container {
    padding: 18px 16px 14px 16px;
    text-align: center;
    border: 1px solid rgba(255, 255, 255, 0.14);
    margin-top: 0.2rem;
    margin-bottom: 16px;
    background: radial-gradient(circle at center, rgba(15, 23, 42, 0.88) 0%, rgba(15, 23, 42, 0.35) 85%, transparent 100%);
    border-radius: 18px;
    backdrop-filter: blur(14px);
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.45);
  }
  .ai-status-pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: rgba(15, 23, 42, 0.95);
    border: 1px solid rgba(245, 158, 11, 0.6);
    color: #fde047;
    padding: 4px 14px;
    border-radius: 9999px;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    margin-bottom: 8px;
  }
  .hero-title {
    font-size: 2.3rem;
    font-weight: 800;
    color: #ffffff;
    letter-spacing: -0.5px;
    margin-bottom: 4px;
  }
  .hero-title span {
    background: linear-gradient(135deg, #ffffff 0%, #fde047 50%, #f59e0b 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }

  /* HIGH-CONTRAST EXPANDER & FILTER BAR */
  [data-testid="stExpander"] {
    background: rgba(15, 23, 42, 0.94) !important;
    border: 1px solid rgba(56, 189, 248, 0.35) !important;
    border-radius: 14px !important;
    margin-bottom: 20px !important;
  }
  [data-testid="stExpander"] summary {
    background: rgba(15, 23, 42, 0.98) !important;
    color: #fde047 !important;
    font-weight: 700 !important;
    border-radius: 14px !important;
  }
  [data-testid="stExpander"] summary svg {
    fill: #fde047 !important;
  }
  [data-testid="stExpander"] div[role="region"] {
    background: transparent !important;
    padding: 12px 14px !important;
  }

  /* ALL FORM & SLIDER LABELS */
  div[data-testid="stWidgetLabel"] label,
  div[data-testid="stWidgetLabel"] p,
  div[data-testid="stWidgetLabel"] span {
    color: #ffffff !important;
    font-weight: 700 !important;
    font-size: 13.5px !important;
  }

  /* SLIDER VALUES & NUMBERS */
  div[data-testid="stSlider"] div[data-testid="stMarkdownContainer"] p,
  div[data-testid="stSlider"] div[data-baseweb="slider"] div {
    color: #fde047 !important;
    font-weight: 700 !important;
  }

  /* SELECTBOX TEXT */
  div[data-baseweb="select"] * {
    color: #0f172a !important;
    font-weight: 600 !important;
  }

  .catalog-card {
    background: rgba(15, 23, 42, 0.90) !important;
    border: 1px solid rgba(56, 189, 248, 0.3) !important;
    border-radius: 18px !important;
    overflow: hidden;
    margin-bottom: 12px;
    box-shadow: 0 12px 35px rgba(0, 0, 0, 0.5) !important;
    backdrop-filter: blur(16px) !important;
  }
  .catalog-img-wrap {
    width: 100%;
    height: 180px;
    overflow: hidden;
    position: relative;
  }
  .catalog-img-wrap img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
  .catalog-badge {
    position: absolute;
    top: 10px;
    left: 10px;
    background: rgba(15, 23, 42, 0.9);
    border: 1px solid rgba(245, 158, 11, 0.6);
    color: #fde047;
    font-size: 11px;
    font-weight: 800;
    padding: 3px 10px;
    border-radius: 6px;
    backdrop-filter: blur(6px);
  }
  .catalog-body {
    padding: 18px 18px 14px 18px;
  }

  .picker-bar {
    background: rgba(15, 23, 42, 0.85);
    border: 1px solid rgba(56, 189, 248, 0.25);
    border-radius: 14px;
    padding: 8px 12px 6px 12px;
    margin-bottom: 24px;
    backdrop-filter: blur(10px);
  }

  [data-testid="stSpinner"],
  div[data-testid="stSpinner"] > div {
    color: #fde047 !important;
    font-size: 15px !important;
    font-weight: 700 !important;
    background: rgba(15, 23, 42, 0.95) !important;
    padding: 12px 24px !important;
    border-radius: 12px !important;
    border: 1px solid rgba(245, 158, 11, 0.7) !important;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.6) !important;
    display: inline-flex !important;
    align-items: center !important;
  }
  [data-testid="stSpinner"] i {
    border-top-color: #f59e0b !important;
  }

  [data-testid="stStatusWidget"] {
    background: rgba(15, 23, 42, 0.95) !important;
    border: 1px solid rgba(56, 189, 248, 0.4) !important;
    color: #f8fafc !important;
    border-radius: 14px !important;
    padding: 12px !important;
  }
  [data-testid="stStatusWidget"] * {
    color: #f8fafc !important;
  }

  [data-testid="stChatMessageContainer"],
  [data-testid="stChatMessageList"] {
    display: flex !important;
    flex-direction: column !important;
    gap: 14px !important;
    max-width: 960px !important;
    margin: 0 auto !important;
  }

  [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]),
  [data-testid="stChatMessage"]:has([aria-label="Chat message from assistant"]) {
    display: flex !important;
    flex-direction: row !important;
    align-self: flex-start !important;
    margin-right: auto !important;
    margin-left: 0 !important;
    max-width: 85% !important;
    background: rgba(15, 23, 42, 0.95) !important;
    border: 1px solid rgba(56, 189, 248, 0.35) !important;
    border-radius: 4px 18px 18px 18px !important;
    padding: 14px 18px !important;
    box-shadow: 0 8px 30px rgba(0, 0, 0, 0.45) !important;
    backdrop-filter: blur(14px) !important;
  }

  [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]),
  [data-testid="stChatMessage"]:has([aria-label="Chat message from user"]) {
    display: flex !important;
    flex-direction: row-reverse !important;
    align-self: flex-end !important;
    margin-left: auto !important;
    margin-right: 0 !important;
    max-width: 78% !important;
    background: linear-gradient(135deg, #1e293b, #334155) !important;
    border: 1px solid rgba(245, 158, 11, 0.55) !important;
    border-radius: 18px 4px 18px 18px !important;
    padding: 12px 16px !important;
    box-shadow: 0 8px 25px rgba(0, 0, 0, 0.45) !important;
    backdrop-filter: blur(14px) !important;
  }

  [data-testid="stChatMessage"] p, 
  [data-testid="stChatMessage"] div,
  [data-testid="stChatMessage"] span {
    color: #f8fafc !important;
    font-size: 14.5px !important;
    line-height: 1.6 !important;
  }
  [data-testid="stChatMessage"] strong {
    color: #fde047 !important;
  }
  [data-testid="stChatMessage"] ul {
    margin: 6px 0 8px 0 !important;
    padding-left: 18px !important;
  }
  [data-testid="stChatMessage"] li {
    color: #e2e8f0 !important;
    margin-bottom: 5px !important;
  }

  .gemini-thinking-banner {
    display: flex;
    align-items: center;
    gap: 10px;
    background: rgba(15, 23, 42, 0.95);
    border: 1px solid rgba(56, 189, 248, 0.45);
    border-radius: 14px;
    padding: 8px 14px;
    margin: 6px 0;
    max-width: 95%;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
    backdrop-filter: blur(12px);
  }
  .gemini-loader {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    flex-shrink: 0;
  }
  .gemini-dot {
    width: 6.5px;
    height: 6.5px;
    border-radius: 50%;
    background-color: #38bdf8;
    animation: geminiPulse 1.4s infinite ease-in-out both;
  }
  .gemini-dot:nth-child(1) { animation-delay: -0.32s; }
  .gemini-dot:nth-child(2) { animation-delay: -0.16s; }
  .gemini-dot:nth-child(3) { animation-delay: 0s; }

  @keyframes geminiPulse {
    0%, 80%, 100% { transform: scale(0.4); opacity: 0.35; background-color: #38bdf8; }
    40% { transform: scale(1.15); opacity: 1; background-color: #fde047; box-shadow: 0 0 10px rgba(253, 224, 71, 0.75); }
  }

  .gemini-thinking-text {
    font-size: 12.5px;
    color: #e2e8f0;
    line-height: 1.4;
  }
  .gemini-thinking-text strong {
    color: #fde047;
  }

  [data-testid="stBottom"] {
    background: linear-gradient(180deg, transparent 0%, rgba(11, 15, 25, 0.95) 30%, #0b0f19 100%) !important;
    padding-top: 0.8rem !important;
    padding-bottom: 0.8rem !important;
  }
  [data-testid="stBottom"] > div {
    background: transparent !important;
  }
  [data-testid="stChatInput"] {
    max-width: 900px !important;
    margin: 0 auto !important;
    background: #0f172a !important;
    background-color: #0f172a !important;
    border: 1.5px solid rgba(245, 158, 11, 0.75) !important;
    border-radius: 14px !important;
    box-shadow: 0 8px 30px rgba(0, 0, 0, 0.65), 0 0 15px rgba(245, 158, 11, 0.2) !important;
  }
  [data-testid="stChatInput"] textarea {
    background: transparent !important;
    color: #ffffff !important;
    -webkit-text-fill-color: #ffffff !important;
    font-size: 14.5px !important;
    caret-color: #fde047 !important;
  }

  .waypoint-card {
    background: rgba(15, 23, 42, 0.88) !important;
    border: 1px solid rgba(255, 255, 255, 0.15) !important;
    border-left: 4px solid #f59e0b !important;
    border-radius: 16px !important;
    padding: 16px !important;
    margin-bottom: 16px !important;
    box-shadow: 0 14px 40px rgba(0, 0, 0, 0.5) !important;
    backdrop-filter: blur(16px) !important;
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
    box-shadow: 0 4px 18px rgba(0, 0, 0, 0.45);
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

  .stay-card {
    background: rgba(15, 23, 42, 0.90) !important;
    border: 1px solid rgba(56, 189, 248, 0.3) !important;
    border-radius: 16px !important;
    overflow: hidden;
    margin-bottom: 16px !important;
    box-shadow: 0 14px 40px rgba(0, 0, 0, 0.5) !important;
    backdrop-filter: blur(16px) !important;
  }
  .stay-img-wrap {
    width: 100%;
    height: 150px;
    overflow: hidden;
    position: relative;
    background-color: #0b1329;
  }
  .stay-img-wrap img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
  .stay-img-badge {
    position: absolute;
    top: 10px;
    left: 10px;
    background: rgba(15, 23, 42, 0.88);
    border: 1px solid rgba(245, 158, 11, 0.6);
    color: #fde047;
    font-size: 10px;
    font-weight: 800;
    text-transform: uppercase;
    padding: 2px 8px;
    border-radius: 6px;
    backdrop-filter: blur(8px);
  }
  .stay-content {
    padding: 14px 16px;
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
  /* FORCE HIGH CONTRAST ON ALL STREAMLIT CAPTIONS */
.stCaption,
[data-testid="stCaptionContainer"],
[data-testid="stCaptionContainer"] p,
[data-testid="stCaptionContainer"] span {
  color: #e2e8f0 !important; /* Crisp light silver-white */
  font-size: 14px !important;
  font-weight: 500 !important;
  opacity: 1 !important;
  text-shadow: 0 1px 4px rgba(0, 0, 0, 0.9) !important;
}
  @media only screen and (max-width: 768px) {
    .block-container {
      padding-top: 1.8rem !important;
      padding-left: 0.6rem !important;
      padding-right: 0.6rem !important;
      padding-bottom: 5.5rem !important;
    }
    .hero-title { font-size: 1.85rem !important; }
    [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) { max-width: 92% !important; }
    [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) { max-width: 88% !important; }
    .day-photo-grid { grid-template-columns: 1fr !important; }
    .day-photo-card { height: 155px !important; }
  }
	
</style>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# 3. STATE INITIALIZATION
# ---------------------------------------------------------------------------
if "active_tab" not in st.session_state:
    st.session_state.active_tab = "Home"

if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": (
                "**Wondoo Alpine Concierge**\n\n"
                "Welcome! Where across our destination circuits are you planning to travel, for how long, and who is joining you?"
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

# ---------------------------------------------------------------------------
# 4. PACKAGE BOOKING & QUOTATION MODAL
# ---------------------------------------------------------------------------
@st.dialog("🎒 Reserve Complete Expedition Package", width="large")
def open_package_booking_dialog(itinerary: TourItinerary, matched_stays: list):
    st.markdown(f"### **{itinerary.tour_title}** ({itinerary.duration})")

    total_days = len(itinerary.days)
    booking_id = f"WND-{uuid.uuid4().hex[:6].upper()}"

    st.markdown("##### **1. Traveler & Logistics Details**")
    c1, c2, c3 = st.columns([1.2, 1, 1])
    with c1:
        lead_name = st.text_input("Lead Traveler Name*", placeholder="e.g. Rahul Sharma")
    with c2:
        phone_num = st.text_input("WhatsApp / Contact Number*", placeholder="e.g. 9876543210")
    with c3:
        email_addr = st.text_input("Confirmation Email", placeholder="e.g. rahul@example.com")

    c_heads, c_rooms, c_pickup = st.columns([1, 1, 1.2])
    with c_heads:
        num_heads = st.number_input("Total Heads", min_value=1, max_value=25, value=2)
    with c_rooms:
        num_rooms = st.number_input("Rooms", min_value=1, max_value=12, value=1)
    with c_pickup:
        pickup_loc = st.selectbox(
            "Pickup & Drop Point",
            [
                "Bagdogra Airport (IXB)", "New Jalpaiguri Stn (NJP)", "Siliguri Junction",
                "Pakyong Airport (PYG)", "Gangtok Stand", "Guwahati Airport (GAU)",
                "Dehradun Airport (DED)", "Chandigarh Airport (IXC)", "Srinagar Airport (SXR)",
                "Cochin Airport (COK)", "Bhubaneswar Airport (BBI)", "Port Blair Airport (IXZ)"
            ]
        )

    cab_option = st.selectbox(
        "Dedicated Sightseeing Cab",
        [
            "Include Dedicated Cab (Innova / Scorpio / Bolero 4x4 / Tempo)",
            "Self-Arranged (No Cab Required)"
        ]
    )

    special_requests = st.text_area(
        "Special Requests (Optional)",
        placeholder="e.g., Mountain/Valley view room, ground floor preference, airport pickup arrival flight number..."
    )

    pricing = calculate_dynamic_sheet_quotation(
        matched_stays=matched_stays,
        total_days=total_days,
        num_heads=int(num_heads),
        num_rooms=int(num_rooms),
        cab_option=cab_option
    )

    st.markdown("<hr style='border-color: rgba(255,255,255,0.1); margin: 15px 0;'>", unsafe_allow_html=True)
    st.markdown("##### **2. Dynamic Fare Breakdown & Quotation**")

    q1, q2, q3, q4 = st.columns(4)
    q1.metric("Est. Total Package", f"₹{pricing['grand_total']:,}")
    q2.metric("Per Head Cost", f"₹{pricing['per_head']:,}")
    q3.metric("25% Advance Token", f"₹{pricing['advance_payable']:,}")
    q4.metric("Duration", f"{total_days}D / {pricing['nights']}N")

    with st.expander("📄 View Itemized Property & Transport Breakdown", expanded=False):
        for item in pricing["stay_breakdown"]:
            st.markdown(
                f"• **Night {item['night']} — {item['hotel']}** "
                f"<span class='plan-tag'>{item['plan']} Plan</span> "
                f"<span class='pricing-tag'>{item['pricing_type']}</span> "
                f"<span style='color:#cbd5e1; font-size:12px;'>({item['plan_desc']})</span>: "
                f"**₹{item['cost']:,}** (`{item['formula']}`)",
                unsafe_allow_html=True
            )
        st.write(f"• **Dedicated Vehicle ({total_days} Days)**: ₹{pricing['cab_cost']:,}")
        st.write(f"• **GST (5% Hospitality)**: ₹{pricing['gst_amount']:,}")
        st.markdown(f"**Guaranteed Total**: **₹{pricing['grand_total']:,}**")

    st.markdown("<hr style='border-color: rgba(255,255,255,0.1); margin: 15px 0;'>", unsafe_allow_html=True)
    st.markdown("##### **3. Lock Dates (Payment & Confirmation)**")

    qr_col, info_col = st.columns([1, 1.6])
    with qr_col:
        qr_url = generate_upi_qr_url(
            vpa=UPI_VPA,
            payee_name=UPI_PAYEE_NAME,
            amount=float(pricing["advance_payable"]),
            booking_id=booking_id
        )
        st.image(qr_url, width=170, caption=f"Ref: {booking_id}")
    with info_col:
        st.markdown(f"""
        - **Payee**: `{UPI_PAYEE_NAME}`
        - **UPI ID**: `{UPI_VPA}`
        - **Booking Ref**: `{booking_id}`
        - **Advance Token Due**: **₹{pricing['advance_payable']:,}**
        """)
        txn_ref = st.text_input("12-digit UPI UTR / Ref # (After scanning)", placeholder="e.g. 427810398412")

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🚀 Confirm & Lock Expedition Booking", type="primary", use_container_width=True):
        if not lead_name.strip() or not phone_num.strip():
            st.error("Please provide both Lead Traveler Name and WhatsApp Number.")
            return

        stays_summary = "; ".join([
            f"Night {s['night']}: {s['hotel']} [{s['plan']} - {s['pricing_type']}]" 
            for s in pricing["stay_breakdown"]
        ])

        payload = {
            "booking_id": booking_id,
            "timestamp": datetime.now(ist_tz).isoformat(),
            "lead_name": lead_name.strip(),
            "phone": phone_num.strip(),
            "email": email_addr.strip(),
            "pickup_location": pickup_loc,
            "circuit": itinerary.tour_title,
            "duration": itinerary.duration,
            "heads": int(num_heads),
            "rooms": int(num_rooms),
            "cab_option": cab_option,
            "grand_total": pricing["grand_total"],
            "advance_payable": pricing["advance_payable"],
            "per_head": pricing["per_head"],
            "transaction_utr": txn_ref.strip() if txn_ref.strip() else "PENDING_VERIFICATION",
            "special_requests": special_requests.strip(),
            "stays_summary": stays_summary
        }

        if "YOUR_APPS_SCRIPT" not in BOOKING_WEBHOOK_URL:
            try:
                requests.post(BOOKING_WEBHOOK_URL, json=payload, timeout=8)
            except Exception as e:
                print(f"Webhook dispatch error: {e}")

        st.session_state.booking_confirmed = payload
        st.rerun()

# ---------------------------------------------------------------------------
# 5. HERO & TOP GLASS NAVIGATION MENU
# ---------------------------------------------------------------------------
st.markdown(
    f"""
<div class="hero-container">
  <div class="ai-status-pill">{period_label}</div>
  <div class="hero-title">Wondoo <span>Alpine Studio</span></div>
  <div style="color: #e2e8f0; font-size: 14px; font-weight: 500;">Tailored Expedition Architect, Stay Matcher & Brochure Engine</div>
</div>
""",
    unsafe_allow_html=True,
)

# Top Navigation Tabs
nav_c1, nav_c2, nav_c3 = st.columns([1, 1, 1])
with nav_c1:
    btn_type_home = "primary" if st.session_state.active_tab == "Home" else "secondary"
    if st.button("🏠 Home (AI Concierge)", type=btn_type_home, use_container_width=True):
        st.session_state.active_tab = "Home"
        st.rerun()

with nav_c2:
    btn_type_itin = "primary" if st.session_state.active_tab == "Itineraries" else "secondary"
    if st.button("🗺️ Signature Itineraries", type=btn_type_itin, use_container_width=True):
        st.session_state.active_tab = "Itineraries"
        st.rerun()

with nav_c3:
    btn_type_pkg = "primary" if st.session_state.active_tab == "Packages" else "secondary"
    if st.button("🎒 Curated Packages", type=btn_type_pkg, use_container_width=True):
        st.session_state.active_tab = "Packages"
        st.rerun()

st.markdown("<hr style='border-color: rgba(255,255,255,0.12); margin: 12px 0 20px 0;'>", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# 6. CONFIRMATION BANNER & WHATSAPP VOUCHER ROUTING
# ---------------------------------------------------------------------------
if st.session_state.get("booking_confirmed"):
    info = st.session_state.booking_confirmed

    wa_dispatch_text = urllib.parse.quote(
        f"🏔️ *Wondoo Alpine Reservation Confirmation*\n\n"
        f"• *Booking ID*: {info['booking_id']}\n"
        f"• *Lead Traveler*: {info['lead_name']}\n"
        f"• *Contact*: {info['phone']}\n"
        f"• *Circuit*: {info['circuit']} ({info['duration']})\n"
        f"• *Pickup*: {info['pickup_location']}\n"
        f"• *Party*: {info['heads']} Heads | {info['rooms']} Rooms\n"
        f"• *Grand Total*: ₹{info['grand_total']:,}\n"
        f"• *Advance Token*: ₹{info['advance_payable']:,}\n"
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
        box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5), 0 0 20px rgba(16, 185, 129, 0.25);
        backdrop-filter: blur(16px);
    ">
      <div style="display: flex; flex-direction: column; gap: 10px;">
        <div style="font-size: 1.15rem; font-weight: 800; color: #34d399;">
          🎉 Reservation #{info['booking_id']} Locked & Confirmed!
        </div>
        <div style="font-size: 14px; color: #f1f5f9; line-height: 1.55;">
          Thank you, <b>{info['lead_name']}</b>. Your expedition request for <b>{info['circuit']}</b> (Est. <b>₹{info['grand_total']:,}</b>) has been logged.<br>
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
# 7. ROUTING BASED ON SELECTED MENU TAB
# ---------------------------------------------------------------------------

# === TAB 2: SIGNATURE ITINERARIES (WITH CUSTOM DAY-COUNT PICKER) ===
if st.session_state.active_tab == "Itineraries":
    hdr_c1, hdr_c2 = st.columns([5, 1])
    with hdr_c1:
        st.markdown("<h3 style='color: #ffffff;'>🗺️ Pre-Defined Signature Itineraries</h3>", unsafe_allow_html=True)
        st.caption("Select your desired duration on any circuit to immediately compile your custom day-by-day plan and matched stays.")
    with hdr_c2:
        if st.button("🔄 Sync Sheet", key="sync_itin_btn", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    grid_cols = st.columns(2, gap="medium")
    for idx, itin in enumerate(LIVE_ITINERARIES):
        with grid_cols[idx % 2]:
            st.markdown(
                f"""
                <div class="catalog-card">
                  <div class="catalog-img-wrap">
                    <img src="{itin['image']}" alt="{itin['title']}" loading="lazy"/>
                    <div class="catalog-badge">📍 {itin['sector']} • Base: {itin['duration']}</div>
                  </div>
                  <div class="catalog-body">
                    <div style="font-size:18px; font-weight:800; color:#ffffff; margin-bottom:4px;">{itin['title']}</div>
                    <div style="font-size:12px; color:#38bdf8; font-weight:600; margin-bottom:10px;">Altitude: {itin['elevation']}</div>
                    <ul style="list-style:none; padding-left:0; margin:0;">
                      {"".join([f"<li style='color:#e2e8f0; font-size:13px; margin-bottom:6px;'>✦ {h}</li>" for h in itin['highlights']])}
                    </ul>
                  </div>
                </div>
                """,
                unsafe_allow_html=True
            )

            # Auto-detect default days from sheet string (e.g., "5 Days / 4 Nights" -> 5)
            match = re.search(r'(\d+)\s*(?:Day|D)', itin['duration'], re.IGNORECASE)
            base_days = int(match.group(1)) if match else 4
            picker_options = [3, 4, 5, 6, 7, 8]
            default_idx = picker_options.index(base_days) if base_days in picker_options else 1

            # Custom Day-Count Picker & Action Row
            st.markdown("<div class='picker-bar'>", unsafe_allow_html=True)
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
                    with st.spinner(f"Synthesizing customized {custom_days}D / {custom_days-1}N expedition for {itin['title']}..."):
                        extraction_prompt = (
                            f"Create an authentic, structured tour itinerary for: {itin['title']}.\n"
                            f"Strict Duration: Exactly {custom_days} Days / {custom_days - 1} Nights.\n"
                            f"Sector & Elevation: {itin['sector']} ({itin['elevation']}).\n"
                            f"Highlights & Route Guidance: {itin['default_prompt']}"
                        )
                        try:
                            plan = generate_itinerary_content(extraction_prompt)
                            st.session_state.itinerary_data = plan
                            st.session_state.active_tab = "Home"
                            st.rerun()
                        except Exception as e:
                            st.error(f"Generation error: {e}")
            st.markdown("</div>", unsafe_allow_html=True)

# === TAB 3: SIGNATURE PACKAGES (WITH FILTER BAR & FIXED DOCKED BUTTONS) ===
elif st.session_state.active_tab == "Packages":
    hdr_p1, hdr_p2 = st.columns([5, 1])
    with hdr_p1:
        st.markdown("<h3 style='color: #ffffff;'>🎒 Handcrafted Expedition Packages</h3>", unsafe_allow_html=True)
        st.markdown(
    "<p style='color: #e2e8f0; font-size: 14px; font-weight: 500; margin-top: -8px; margin-bottom: 16px; text-shadow: 0 1px 3px rgba(0,0,0,0.8);'>"
    "Browse and filter all-inclusive holiday packages with dedicated mountain transit, curated stays, and meals."
    "</p>",
    unsafe_allow_html=True
)
    with hdr_p2:
        if st.button("🔄 Sync Sheet", key="sync_pkg_btn", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    # --- FILTER BAR ---
    with st.expander("🔍 Filter & Sort Packages", expanded=False):
        f_col1, f_col2, f_col3 = st.columns([1.2, 1.4, 1.2])

        def parse_price(val_str: str) -> int:
            clean = re.sub(r"[^\d]", "", str(val_str))
            return int(clean) if clean else 0

        with f_col1:
            st.markdown("<p style='color: #ffffff; font-weight: 700; font-size: 13.5px; margin-bottom: 4px;'>Filter by Duration</p>", unsafe_allow_html=True)
            duration_filter = st.selectbox(
                "Filter by Duration",
                options=["All Durations", "Quick (3–4 Days)", "Signature (5–6 Days)", "Extended (7+ Days)"],
                label_visibility="collapsed",
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
            st.markdown("<p style='color: #ffffff; font-weight: 700; font-size: 13.5px; margin-bottom: 4px;'>Sort By</p>", unsafe_allow_html=True)
            sort_by = st.selectbox(
                "Sort By",
                options=["Default", "Price: Low to High", "Price: High to Low", "Duration: Short to Long"],
                label_visibility="collapsed",
                key="pkg_sort_by"
            )

    # Filtering Logic
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

    # Sorting Logic
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
                    <div class="catalog-card">
                      <div class="catalog-body">
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

        if user_prompt := st.chat_input("E.g., What would be an ideal relaxing getaway in Darjeeling and Kalimpong?"):
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
                    "1. DO NOT GENERATE A DAY-BY-DAY ITINERARY IN THIS CHAT (Strictly NO 'Day 1', 'Day 2', etc.). "
                    "The detailed itinerary will be compiled when the user clicks finalize.\n"
                    "2. KEEP IT CONVERSATIONAL & INFORMATIVE: Discuss route feasibility, highlights, altitude, transit, and boutique stays in natural paragraphs.\n"
                    "3. MANDATORY CLOSING CALL-TO-ACTION: Conclude by asking if this direction matches their preferences, and prompt them to click the finalize button right below.\n"
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

        # -------------------------------------------------------------------
        # LEFT COLUMN: WAYPOINT CARDS (WITH STAY AT / DEPARTURE LABEL)
        # -------------------------------------------------------------------
        with col_itinerary:
            st.markdown(f"<h3 style='color: #ffffff;'>🗺️ {data.tour_title} ({data.duration})</h3>", unsafe_allow_html=True)

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

                # NIGHT HALT STATUS BADGE
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

        # -------------------------------------------------------------------
        # RIGHT COLUMN: MULTI-HOTEL SUB-TABS BASED ON STAY_LOCATION
        # -------------------------------------------------------------------
        with col_stays:
            st.markdown("<h3 style='color: #ffffff;'>🏡 Recommended Stays & Booking</h3>", unsafe_allow_html=True)
            st.caption("Curated lodges matched to each day's night halt location from your live Google Sheet inventory.")

            # Filter only days that have an overnight stay (exclude final departure day)
            stay_days = [d for d in data.days if getattr(d, "stay_location", None)]

            # Safety fallback: if Gemini omitted stay_location for early days, take all except the final day
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

                # Match hotels using the exact stay_location
                try:
                    available_hotels = match_all_stays_for_day(halt_location, day.route_title)
                except Exception:
                    available_hotels = []

                # CASE 1: NO HOTEL IN INVENTORY FOR THIS LOCATION
                if not available_hotels:
                    st.markdown(
                        f"""
                        <div style="
                            background: rgba(15, 23, 42, 0.75);
                            border: 1px dashed rgba(245, 158, 11, 0.5);
                            border-radius: 12px;
                            padding: 14px 16px;
                            margin-bottom: 14px;
                            color: #cbd5e1;
                            font-size: 13px;
                        ">
                            <span style="color: #fde047; font-weight: 700;">⚠️ No registered properties in inventory</span> for <b>{halt_location}</b>.<br>
                            <span style="font-size: 11.5px; color: #94a3b8;">Our concierge team will manually source local boutique stays or homestays upon package request.</span>
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

                # CASE 2: HOTELS AVAILABLE IN INVENTORY (RENDER SUB-TABS)
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

                            img_src = s.get(
                                "image_url",
                                "https://images.unsplash.com/photo-1544735716-392fe2489ffa?auto=format&fit=crop&w=900&q=80",
                            )
                            plan_name = s.get("plan", "EP")
                            p_type = s.get("pricing_type", "Per Room")
                            rate_val = s.get("rate", 0)
                            rate_suffix = "/head" if p_type == "Per Head" else "/room"

                            st.markdown(
                                f"""
                                <div class="stay-card" style="margin-top: 8px;">
                                  <div class="stay-img-wrap">
                                    <img src="{img_src}" alt="{s['stay_name']}" loading="lazy" />
                                    <div class="stay-img-badge">Night {s['night']} • {halt_location}</div>
                                  </div>
                                  <div class="stay-content">
                                    <div style="font-size:16px; font-weight:700; color:#ffffff; margin-bottom:4px;">
                                      {s['stay_name']}
                                      <span class="plan-tag">{plan_name} Plan</span>
                                      <span class="pricing-tag">{p_type}</span>
                                    </div>
                                    <div style="font-size:11.5px; color:#cbd5e1; margin-bottom:8px; display:flex; align-items:center; gap:8px;">
                                      <span style="background:rgba(56,189,248,0.2); color:#38bdf8; padding:2px 8px; border-radius:6px; font-weight:600;">
                                        📍 {s.get('altitude', 'Alpine Elev')}
                                      </span>
                                      <span>{s.get('property_type', 'Retreat')}</span>
                                      <b style="color:#fbbf24;">{s.get('rating', 'N/A')}</b>
                                      <span style="color:#22c55e; font-weight:700; margin-left: auto;">₹{rate_val:,.0f} {rate_suffix}</span>
                                    </div>
                                    <div style="font-size:12.5px; color:#cbd5e1; line-height:1.45; margin-bottom:12px;">
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

            # Book Complete Tour Package Button
            st.markdown("<hr style='border-color: rgba(255,255,255,0.1); margin: 20px 0 16px 0;'>", unsafe_allow_html=True)
            if st.button("🎒 Book Complete Tour Package (Stays + Transit)", type="primary", use_container_width=True):
                open_package_booking_dialog(data, matched_trip_stays)

        # LOWER DOCKED PRODUCTION STUDIO
        st.markdown("<hr style='border-color: rgba(245, 158, 11, 0.25); margin: 30px 0;'>", unsafe_allow_html=True)
        with st.expander("🛠️ Production Studio • Compile High-Res PDF Brochure & WhatsApp Export", expanded=True):
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

                    wa_summary = f"🏔️ *{data.tour_title}* ({data.duration})\n" + "\n".join(
                        [f"📍 *Day {d.day_number}*: {d.route_title}" for d in data.days]
                    )
                    wa_url = f"https://api.whatsapp.com/send?text={urllib.parse.quote(wa_summary)}"
                    st.markdown(
                        f'<a href="{wa_url}" target="_blank" style="display:block; text-align:center; background:#25D366; color:white; padding:10px; border-radius:10px; text-decoration:none; font-weight:700; margin-top:8px;">💬 Dispatch Itinerary to WhatsApp</a>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.info("Click 'Render Flyers & Compile PDF' to initiate brochure export.")

            if st.session_state.generated_files:
                tabs = st.tabs([f"Day {i+1}" if i < len(data.days) else "Sightseeing" for i in range(len(st.session_state.generated_files))])
                for idx, tab in enumerate(tabs):
                    with tab:
                        st.image(st.session_state.generated_files[idx], use_container_width=True)
