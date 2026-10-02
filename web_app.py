import os
import glob
import json
import uuid
import random
import asyncio
import textwrap
import urllib.parse
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List

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
from stay_matcher import match_stay_for_day
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

# Curated Expedition & Regional Knowledge Nuggets for Live Waiting State
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
# 1. HARDWARE-ACCELERATED THREE.JS (EDGE-TO-EDGE PROJECTION)
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
    const scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2({fog_color_hex}, 0.0006);

    const camera = new THREE.PerspectiveCamera(60, window.parent.innerWidth / window.parent.innerHeight, 1, 4000);
    camera.position.set(0, 30, 600);

    const renderer = new THREE.WebGLRenderer({{ canvas: canvas, alpha: true, antialias: true }});
    renderer.setSize(window.parent.innerWidth, window.parent.innerHeight);
    renderer.setPixelRatio(Math.min(window.parent.devicePixelRatio, 2));

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

    const flakeCount = 1200;
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
      size: 7.5,
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

    window.parent.addEventListener('mousemove', (e) => {{
      const halfW = window.parent.innerWidth / 2;
      const halfH = window.parent.innerHeight / 2;
      mouseX = (e.clientX - halfW) * 0.35;
      mouseY = (e.clientY - halfH) * 0.2;
    }});

    window.parent.addEventListener('scroll', () => {{
      const scrollPos = window.parent.pageYOffset || window.parent.document.documentElement.scrollTop;
      scrollOffset = scrollPos * 0.42;
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
# 2. STREAMLIT DUAL-SIDE CHAT & HIGH-CONTRAST CSS
# ---------------------------------------------------------------------------
st.markdown(
    """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Space+Grotesk:wght@600;700&display=swap');

  html, body, [data-testid="stAppViewContainer"], .stApp, header[data-testid="stHeader"], footer {
    background-color: transparent !important;
    background: transparent !important;
    font-family: 'Plus Jakarta Sans', sans-serif !important;
  }
  header[data-testid="stHeader"] {
    background: transparent !important;
    box-shadow: none !important;
  }

  .block-container {
    max-width: 1300px !important;
    padding-top: 1rem !important;
    padding-bottom: 6.5rem !important;
    position: relative;
    z-index: 1;
  }

  /* HIGH-CONTRAST SPINNER & STATUS TEXT OVERRIDES */
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

  /* CHAT CONTAINER LAYOUT */
  [data-testid="stChatMessageContainer"],
  [data-testid="stChatMessageList"] {
    display: flex !important;
    flex-direction: column !important;
    gap: 16px !important;
    max-width: 960px !important;
    margin: 0 auto !important;
  }

  /* 1. ASSISTANT MESSAGE: LEFT-ALIGNED */
  [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]),
  [data-testid="stChatMessage"]:has([aria-label="Chat message from assistant"]) {
    display: flex !important;
    flex-direction: row !important;
    align-self: flex-start !important;
    margin-right: auto !important;
    margin-left: 0 !important;
    max-width: 84% !important;
    background: rgba(15, 23, 42, 0.95) !important;
    border: 1px solid rgba(56, 189, 248, 0.35) !important;
    border-radius: 4px 18px 18px 18px !important;
    padding: 16px 20px !important;
    box-shadow: 0 8px 30px rgba(0, 0, 0, 0.45) !important;
    backdrop-filter: blur(14px) !important;
  }

  /* 2. USER MESSAGE: RIGHT-ALIGNED (AVATAR ON RIGHT) */
  [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]),
  [data-testid="stChatMessage"]:has([aria-label="Chat message from user"]) {
    display: flex !important;
    flex-direction: row-reverse !important;
    align-self: flex-end !important;
    margin-left: auto !important;
    margin-right: 0 !important;
    max-width: 76% !important;
    background: linear-gradient(135deg, #1e293b, #334155) !important;
    border: 1px solid rgba(245, 158, 11, 0.55) !important;
    border-radius: 18px 4px 18px 18px !important;
    padding: 14px 18px !important;
    box-shadow: 0 8px 25px rgba(0, 0, 0, 0.45) !important;
    backdrop-filter: blur(14px) !important;
  }

  /* Chat Typography */
  [data-testid="stChatMessage"] p, 
  [data-testid="stChatMessage"] div,
  [data-testid="stChatMessage"] span {
    color: #f8fafc !important;
    font-size: 15px !important;
    line-height: 1.65 !important;
  }
  [data-testid="stChatMessage"] strong {
    color: #fde047 !important;
  }
  [data-testid="stChatMessage"] ul {
    margin: 8px 0 10px 0 !important;
    padding-left: 22px !important;
  }
  [data-testid="stChatMessage"] li {
    color: #e2e8f0 !important;
    margin-bottom: 6px !important;
  }

  /* GEMINI 3-DOT PULSING ANIMATION & KNOWLEDGE BANNER */
  .gemini-thinking-banner {
    display: flex;
    align-items: center;
    gap: 12px;
    background: rgba(15, 23, 42, 0.95);
    border: 1px solid rgba(56, 189, 248, 0.45);
    border-radius: 14px;
    padding: 10px 16px;
    margin: 6px 0 10px 0;
    max-width: 90%;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
    backdrop-filter: blur(12px);
  }
  .gemini-loader {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    flex-shrink: 0;
  }
  .gemini-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background-color: #38bdf8;
    animation: geminiPulse 1.4s infinite ease-in-out both;
  }
  .gemini-dot:nth-child(1) { animation-delay: -0.32s; }
  .gemini-dot:nth-child(2) { animation-delay: -0.16s; }
  .gemini-dot:nth-child(3) { animation-delay: 0s; }

  @keyframes geminiPulse {
    0%, 80%, 100% {
      transform: scale(0.4);
      opacity: 0.35;
      background-color: #38bdf8;
    }
    40% {
      transform: scale(1.15);
      opacity: 1;
      background-color: #fde047;
      box-shadow: 0 0 10px rgba(253, 224, 71, 0.75);
    }
  }

  .gemini-thinking-text {
    font-size: 13.5px;
    color: #e2e8f0;
    line-height: 1.45;
  }
  .gemini-thinking-text strong {
    color: #fde047;
  }

  /* General Form, Input & Modal Labels Contrast */
  label[data-testid="stWidgetLabel"] p {
    color: #f8fafc !important;
    font-weight: 700 !important;
    font-size: 14px !important;
  }
  .stCaption, [data-testid="stCaptionContainer"] {
    color: #94a3b8 !important;
    font-size: 13.5px !important;
  }

  /* Pinned Bottom Input Bar */
  [data-testid="stBottom"] {
    background: linear-gradient(180deg, transparent 0%, rgba(11, 15, 25, 0.95) 40%, #0b0f19 100%) !important;
    padding-top: 1.2rem !important;
    padding-bottom: 1.2rem !important;
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
    border-radius: 16px !important;
    box-shadow: 0 8px 30px rgba(0, 0, 0, 0.65), 0 0 15px rgba(245, 158, 11, 0.2) !important;
  }
  [data-testid="stChatInput"] > div,
  [data-testid="stChatInput"] div[data-baseweb="base-input"],
  [data-testid="stChatInput"] div[data-baseweb="input"] {
    background: #0f172a !important;
    background-color: #0f172a !important;
    border: none !important;
  }
  [data-testid="stChatInput"] textarea {
    background: transparent !important;
    background-color: transparent !important;
    color: #ffffff !important;
    -webkit-text-fill-color: #ffffff !important;
    font-size: 15px !important;
    caret-color: #fde047 !important;
  }
  [data-testid="stChatInput"] textarea::placeholder {
    color: #94a3b8 !important;
    -webkit-text-fill-color: #94a3b8 !important;
    opacity: 0.9 !important;
  }
  [data-testid="stChatInput"] button {
    background: linear-gradient(135deg, #f59e0b, #d97706) !important;
    border-radius: 10px !important;
    border: none !important;
    color: #0b0f19 !important;
  }
  [data-testid="stChatInput"] button svg {
    fill: #0b0f19 !important;
  }

  /* Hero Banner */
  .hero-container {
    padding: 20px 0 14px 0;
    text-align: center;
    border-bottom: 1px solid rgba(255, 255, 255, 0.12);
    margin-bottom: 20px;
    background: radial-gradient(circle at center, rgba(15, 23, 42, 0.82) 0%, rgba(15, 23, 42, 0.2) 80%, transparent 100%);
    border-radius: 20px;
    backdrop-filter: blur(14px);
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.4);
  }
  .ai-status-pill {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    background: rgba(15, 23, 42, 0.95);
    border: 1px solid rgba(245, 158, 11, 0.6);
    color: #fde047;
    padding: 5px 18px;
    border-radius: 9999px;
    font-size: 12px;
    font-weight: 700;
    text-transform: uppercase;
    margin-bottom: 10px;
  }
  .hero-title {
    font-size: 2.8rem;
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

  /* Cards & Components */
  .waypoint-card {
    background: rgba(15, 23, 42, 0.88) !important;
    border: 1px solid rgba(255, 255, 255, 0.15) !important;
    border-left: 5px solid #f59e0b !important;
    border-radius: 18px !important;
    padding: 20px !important;
    margin-bottom: 18px !important;
    box-shadow: 0 14px 40px rgba(0, 0, 0, 0.5) !important;
    backdrop-filter: blur(16px) !important;
  }
  .day-tag {
    background: #f59e0b;
    color: #0b0f19 !important;
    font-weight: 900;
    font-size: 12px;
    padding: 4px 10px;
    border-radius: 6px;
    margin-right: 10px;
  }
  .day-photo-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 10px;
    margin: 10px 0 14px 0;
  }
  .day-photo-card {
    position: relative;
    border-radius: 12px;
    overflow: hidden;
    height: 155px;
    border: 1px solid rgba(255, 255, 255, 0.16);
    background: #0b1329;
    box-shadow: 0 4px 18px rgba(0, 0, 0, 0.45);
  }
  .day-photo-card img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
    transition: transform 0.3s ease;
  }
  .day-photo-card:hover img {
    transform: scale(1.05);
  }
  .photo-tag-pill {
    position: absolute;
    top: 8px;
    left: 8px;
    background: rgba(15, 23, 42, 0.88);
    border: 1px solid rgba(245, 158, 11, 0.6);
    color: #fde047;
    font-size: 10px;
    font-weight: 700;
    padding: 3px 8px;
    border-radius: 6px;
    backdrop-filter: blur(6px);
  }
  .photo-overlay {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    background: linear-gradient(180deg, transparent 0%, rgba(15, 23, 42, 0.95) 90%);
    padding: 6px 10px;
    color: #f1f5f9;
    font-size: 11px;
    font-weight: 600;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .stay-card {
    background: rgba(15, 23, 42, 0.90) !important;
    border: 1px solid rgba(56, 189, 248, 0.3) !important;
    border-radius: 20px !important;
    overflow: hidden;
    margin-bottom: 20px !important;
    box-shadow: 0 14px 40px rgba(0, 0, 0, 0.5) !important;
    backdrop-filter: blur(16px) !important;
  }
  .stay-img-wrap {
    width: 100%;
    height: 165px;
    overflow: hidden;
    position: relative;
    background-color: #0b1329;
  }
  .stay-img-wrap img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }
  .stay-img-badge {
    position: absolute;
    top: 12px;
    left: 12px;
    background: rgba(15, 23, 42, 0.88);
    border: 1px solid rgba(245, 158, 11, 0.6);
    color: #fde047;
    font-size: 11px;
    font-weight: 800;
    text-transform: uppercase;
    padding: 3px 10px;
    border-radius: 8px;
    backdrop-filter: blur(8px);
  }
  .stay-content {
    padding: 16px 18px;
  }

  .plan-tag {
    background: #1e293b;
    border: 1px solid #38bdf8;
    border-radius: 4px;
    padding: 2px 7px;
    font-size: 11px;
    color: #38bdf8;
    font-weight: 700;
    margin-left: 4px;
  }
  .pricing-tag {
    background: #14532d;
    border: 1px solid #22c55e;
    border-radius: 4px;
    padding: 2px 7px;
    font-size: 11px;
    color: #86efac;
    font-weight: 700;
    margin-left: 4px;
  }

  [data-testid="stExpander"] summary {
    background: rgba(15, 23, 42, 0.95) !important;
    border: 1px solid rgba(245, 158, 11, 0.6) !important;
    color: #ffffff !important;
    font-weight: 700 !important;
    border-radius: 14px !important;
  }
  [data-testid="stExpander"] div[role="region"] {
    background: rgba(11, 19, 43, 0.92) !important;
    border: 1px solid rgba(255, 255, 255, 0.12) !important;
    border-radius: 0 0 14px 14px !important;
  }
</style>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# 3. STATE INITIALIZATION
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# 4. PACKAGE BOOKING & QUOTATION MODAL
# ---------------------------------------------------------------------------
@st.dialog("🎒 Reserve Complete Expedition Package", width="large")
def open_package_booking_dialog(itinerary: TourItinerary, matched_stays: list):
    st.markdown(f"### **{itinerary.tour_title}** ({itinerary.duration})")

    total_days = len(itinerary.days)
    total_nights = len(matched_stays)
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
        st.image(qr_url, width=180, caption=f"Ref: {booking_id}")
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
# 5. HERO SECTION
# ---------------------------------------------------------------------------
st.markdown(
    f"""
<div class="hero-container">
  <div class="ai-status-pill">{period_label}</div>
  <div class="hero-title">Wondoo <span>Alpine Studio</span></div>
  <div style="color: #e2e8f0; font-size: 15px; font-weight: 500;">Conversational Expedition Architect, Stay Matcher & Brochure Engine</div>
</div>
""",
    unsafe_allow_html=True,
)

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
        border-radius: 18px;
        padding: 20px 24px;
        margin-bottom: 22px;
        box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5), 0 0 20px rgba(16, 185, 129, 0.25);
        backdrop-filter: blur(16px);
    ">
      <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: 16px;">
        <div>
          <div style="font-size: 1.25rem; font-weight: 800; color: #34d399; margin-bottom: 6px;">
            🎉 Reservation #{info['booking_id']} Locked & Confirmed!
          </div>
          <div style="font-size: 15px; color: #f1f5f9; line-height: 1.6; margin-bottom: 12px;">
            Thank you, <b>{info['lead_name']}</b>. Your expedition request for <b>{info['circuit']}</b> (Est. <b>₹{info['grand_total']:,}</b>) has been logged.<br>
            Advance Ref: <code style="color: #fde047;">{info['transaction_utr']}</code>
          </div>
          <a href="{wa_direct_url}" target="_blank" style="
              display: inline-block;
              background: #25D366; 
              color: white; 
              text-decoration: none; 
              padding: 9px 18px; 
              border-radius: 10px; 
              font-weight: 700;
              font-size: 14px;
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
# 7. MAIN WORKSPACE (CONVERSATIONAL LIVE CHAT)
# ---------------------------------------------------------------------------
if not st.session_state.itinerary_data:
    # 1. Render all past messages using native chat components
    for msg in st.session_state.messages:
        role = msg["role"]
        avatar = "👤" if role == "user" else "🏔️"
        with st.chat_message(role, avatar=avatar):
            st.markdown(msg["content"])

    # 2. Finalize Button appears once consultation starts
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

    # 3. Live User Input & Dual-Banner Streaming Generation
    if user_prompt := st.chat_input("E.g., What would be an ideal relaxing getaway in Darjeeling and Kalimpong?"):
        # Display user message immediately on the right
        st.session_state.messages.append({"role": "user", "content": user_prompt})
        with st.chat_message("user", avatar="👤"):
            st.markdown(user_prompt)

        # Assistant Stream Generation on the left
        with st.chat_message("assistant", avatar="🏔️"):
            # Combined 3-Dot Loader + Alpine Knowledge Banner
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

            client = genai.Client(api_key=raw_key, http_options={"api_version": "v1beta"})

            # Conversational prompt without Day 1 / Day 2 items
            system_instruction = (
                "You are the senior AI Travel Concierge at Wondoo Studio, engaging in a friendly, knowledgeable, and consultative dialogue.\n\n"

                "OFFICIAL OPERATING FOOTPRINT (Only plan trips within these destinations):\n"
                "• Eastern Himalayas & Hills: West Bengal (Darjeeling, Kalimpong, Dooars, Sandakphu), Sikkim (Gangtok, Pelling, North Sikkim).\n"
                "• Northeast India: Assam (Kaziranga, Guwahati, Majuli), Meghalaya (Shillong, Cherrapunji, Dawki), Arunachal Pradesh (Tawang, Ziro, Dirang).\n"
                "• North Himalayas: Uttarakhand, Himachal Pradesh, Jammu & Kashmir (including Ladakh circuits).\n"
                "• Heritage & Coastal Escapes: Odisha (Bhubaneswar, Puri, Konark, Chilika), Kerala (Munnar, Alleppey, Wayanad, Kochi).\n"
                "• Island Expeditions: Andaman & Nicobar Islands (Port Blair, Havelock, Neil Island).\n\n"

                "CRITICAL FORMATTING & STYLE DIRECTIVES:\n"
                "1. DO NOT GENERATE A DAY-BY-DAY ITINERARY IN THIS CHAT (Strictly NO 'Day 1', 'Day 2', 'Day 3', or chronological daily schedules). "
                "The detailed day-by-day itinerary will be compiled later by the app's itinerary engine when the user clicks the finalize button.\n"
                "2. KEEP IT CONVERSATIONAL & INFORMATIVE: Speak like an experienced, warm travel planner. Discuss route feasibility, key highlights, "
                "altitude & weather conditions, transit experience, scenic highlights, or local recommendations in natural, engaging paragraphs.\n"
                "3. MANDATORY CLOSING CALL-TO-ACTION (Every response must end with this exact thought):\n"
                "   Conclude by warmly asking if this direction matches their preferences, and tell them that once they are happy with the plan, "
                "they can click the '✨ Finalize Itinerary & Reveal Curated Stays' button right below to generate the complete day-by-day itinerary and view matched properties.\n\n"

                "GUARDRAIL RULES:\n"
                "- Out-of-Scope Regions: Politely explain that Wondoo Studio operates across our specified circuits and suggest an equivalent escape within our portfolio.\n"
                "- Rushed/Impossible Circuits: Gently highlight terrain or transit realities and offer a better, well-paced alternative.\n"
                "- Off-Topic/Unusual Queries: Politely answer in 1 sentence and guide them back to holiday planning.\n\n"

                "TONE & LENGTH:\n"
                "- Warm, professional, inviting, and inspiring.\n"
                "- Target length: 140 to 200 words. Never trail off."
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
                    # Clear BOTH dots and knowledge banner as soon as token 1 arrives
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

            single_card = (
                f'<div class="waypoint-card">'
                f'<div style="font-size:18px; font-weight:700; color:#ffffff; margin-bottom:4px;">'
                f'<span class="day-tag">DAY {day.day_number}</span> {day.route_title}'
                f'</div>'
                f'<div style="color:#cbd5e1; font-size:13.5px; margin-bottom:10px;">'
                f'📍 Key Spot: <b style="color:#fde047;">{day.place_name}</b>'
                f'</div>'
                f'<div class="day-photo-grid">{photo_cards}</div>'
                f'<div style="font-size:12.5px; font-weight:700; color:#38bdf8; text-transform:uppercase; margin: 12px 0 6px 0; letter-spacing:0.5px;">'
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
        st.caption("Curated lodges matched to each day's route from your live Google Sheet inventory.")

        # Determine actual nights: N Days = N - 1 Nights (last day is drop-off / departure)
        total_days = len(data.days)
        stay_days = data.days[:-1] if total_days > 1 else data.days

        matched_trip_stays = []
        for night_idx, day in enumerate(stay_days, start=1):
            stay_dict = match_stay_for_day(day.place_name, day.route_title)
            stay_dict["night"] = night_idx
            stay_dict["day"] = day.day_number
            stay_dict["day_place"] = day.place_name
            matched_trip_stays.append(stay_dict)

        if st.button("🎒 Book Complete Tour Package (Stays + Transit)", type="primary", use_container_width=True):
            open_package_booking_dialog(data, matched_trip_stays)

        st.markdown("<hr style='border-color: rgba(255,255,255,0.1); margin: 16px 0;'>", unsafe_allow_html=True)

        for s in matched_trip_stays:
            img_src = s.get(
                "image_url",
                "https://images.unsplash.com/photo-1544735716-392fe2489ffa?auto=format&fit=crop&w=900&q=80",
            )
            plan_name = s.get("plan", "EP")
            p_type = s.get("pricing_type", "Per Room")
            rate_val = s.get("rate", 1500)
            rate_suffix = "/head" if p_type == "Per Head" else "/room"

            st.markdown(
                f"""
            <div class="stay-card">
              <div class="stay-img-wrap">
                <img src="{img_src}" alt="{s['stay_name']}" loading="lazy" />
                <div class="stay-img-badge">Night {s['night']} • {s['day_place']}</div>
              </div>
              <div class="stay-content">
                <div style="font-size:17px; font-weight:700; color:#ffffff; margin-bottom:4px;">
                  {s['stay_name']}
                  <span class="plan-tag">{plan_name} Plan</span>
                  <span class="pricing-tag">{p_type}</span>
                </div>
                <div style="font-size:12px; color:#cbd5e1; margin-bottom:8px; display:flex; align-items:center; gap:8px;">
                  <span style="background:rgba(56,189,248,0.2); color:#38bdf8; padding:2px 8px; border-radius:6px; font-weight:600;">
                    📍 {s.get('altitude', 'Alpine Elev')}
                  </span>
                  <span>{s.get('property_type', 'Retreat')}</span>
                  <b style="color:#fbbf24;">{s.get('rating', '4.8 ★')}</b>
                  <span style="color:#22c55e; font-weight:700; margin-left: auto;">₹{rate_val:,.0f} {rate_suffix}</span>
                </div>
                <div style="font-size:13px; color:#cbd5e1; line-height:1.45; margin-bottom:12px;">
                  {s.get('vibe', '')}
                </div>
              </div>
            </div>
            """,
                unsafe_allow_html=True,
            )

            single_stay_inquiry = urllib.parse.quote(
                f"Hi, I would like to reserve Night {s['night']} Stay at {s['stay_name']} ({s['day_place']}) on {plan_name} plan for circuit {data.tour_title}."
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
                margin-top: -12px;
                margin-bottom: 20px;
            ">
                🛎️ Inquire Only for {s['stay_name']}
            </a>
            """,
                unsafe_allow_html=True,
            )

    # ---------------------------------------------------------------------------
    # LOWER DOCKED PRODUCTION STUDIO
    # ---------------------------------------------------------------------------
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
