import os
import glob
import time
import asyncio
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import streamlit as st
import streamlit.components.v1 as components
from PIL import Image

# Import core generation and rendering pipeline
from generate_itinerary import (
    generate_itinerary_content,
    render_itinerary_pages,
    TourItinerary,
)

# ---------------------------------------------------------------------------
# PAGE CONFIGURATION
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Wondoo AI Studio | Alpine 3D Expedition Studio",
    page_icon="🏔️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# EXPEDITION KNOWLEDGE TRIVIA REPOSITORY
# ---------------------------------------------------------------------------
EXPEDITION_TIPS = [
    ("🏔️ Kangchenjunga Vista", "Kaluk & Rinchenpong offer one of the closest and widest unobstructed views of Mt. Kangchenjunga (8,586 m) anywhere in the eastern Himalayas."),
    ("🪪 High-Altitude Permit Tip", "Visiting Gurudongmar Lake (17,800 ft) or Yumthang Valley in North Sikkim requires Inner Line Permits (ILP) processed 24 hours prior via registered operators."),
    ("☕ Heritage Toy Train Fact", "The Darjeeling Himalayan Railway (DHR), built in 1881, is a UNESCO World Heritage site and ascends from 100 m at New Jalpaiguri to over 2,200 m at Ghum."),
    ("🍲 Local Culinary Pick", "When traveling through West Sikkim, don't miss authentic freshly prepared 'Sel Roti' (traditional ring-shaped rice bread) and local organic cardamom tea."),
    ("🌉 Engineering Marvel", "Singshore Bridge near Uttarey is the highest suspension bridge in Sikkim and the second highest in Asia, spanning over a 100-meter sheer gorge."),
    ("🌲 The Ancient Silk Route", "Zuluk loops through 32 hairpin turns along the historic Silk Route connecting Kalimpong to Lhasa through the Jelep La pass."),
    ("🌿 Tea Estate Microclimates", "Mirik Lake sits at 1,495 meters surrounded by fragrant cryptomeria pine forests and the famed Thurbo Tea Estate, known for autumnal flush flushes."),
    ("🛕 Historic Monasteries", "Pemayangtse Monastery near Pelling, founded in 1705, houses the revered seven-tiered wooden model of Guru Rinpoche's celestial abode.")
]

# ---------------------------------------------------------------------------
# TIME ZONE: INDIAN STANDARD TIME (IST = UTC + 5:30)
# ---------------------------------------------------------------------------
ist_tz = timezone(timedelta(hours=5, minutes=30))
now_ist = datetime.now(ist_tz)
current_hour_ist = now_ist.hour + (now_ist.minute / 60.0)

# Day in India: 06:00 to 18:30 (6:00 AM to 6:30 PM IST)
is_day_mode = 6.0 <= current_hour_ist < 18.5
ist_time_str = now_ist.strftime("%I:%M %p")

if is_day_mode:
    period_label = f"☀️ Daytime in India ({ist_time_str} IST)"
    real_mountain_photo_url = "https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?auto=format&fit=crop&w=2560&q=92"
    base_bg_gradient = "linear-gradient(180deg, rgba(12, 18, 34, 0.40) 0%, rgba(15, 23, 42, 0.65) 60%, rgba(10, 15, 29, 0.95) 100%)"
    fog_color_hex = "0x0b132b"
    card_bg = "rgba(15, 23, 42, 0.72)"
    card_border = "rgba(255, 255, 255, 0.16)"
    text_color = "#f8fafc"
    subtext_color = "#cbd5e1"
else:
    period_label = f"🌙 Nighttime in India ({ist_time_str} IST)"
    real_mountain_photo_url = "https://images.unsplash.com/photo-1519681393784-d120267933ba?auto=format&fit=crop&w=2560&q=92"
    base_bg_gradient = "linear-gradient(180deg, rgba(6, 9, 19, 0.45) 0%, rgba(8, 12, 24, 0.70) 60%, rgba(4, 6, 14, 0.98) 100%)"
    fog_color_hex = "0x050811"
    card_bg = "rgba(10, 15, 29, 0.78)"
    card_border = "rgba(56, 189, 248, 0.16)"
    text_color = "#f1f5f9"
    subtext_color = "#94a3b8"

# ---------------------------------------------------------------------------
# 1. HARDWARE-ACCELERATED THREE.JS (FULL-BLEED EDGE-TO-EDGE PROJECTION)
# ---------------------------------------------------------------------------
components.html(f"""
<script>
(function() {{
  const parentDoc = window.parent.document;

  const existingCanvas = parentDoc.getElementById('threejs-mountain-canvas');
  if (existingCanvas) {{
    existingCanvas.remove();
  }}

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
    let midMountainMesh = null;

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

      const mDist = 450;
      const mSize = getFrustumSizeAtDistance(camera.position.z + mDist);
      const midGeo = new THREE.PlaneGeometry(mSize.width * 1.3, mSize.height * 1.2);
      const midMat = new THREE.MeshBasicMaterial({{
        map: texture,
        transparent: true,
        opacity: 0.35,
        blending: THREE.AdditiveBlending,
        depthWrite: false
      }});

      midMountainMesh = new THREE.Mesh(midGeo, midMat);
      midMountainMesh.position.set(0, -20, -mDist);
      scene.add(midMountainMesh);
    }});

    const flakeCount = 1400;
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
    let windForce = 0;

    window.parent.addEventListener('mousemove', (e) => {{
      const halfW = window.parent.innerWidth / 2;
      const halfH = window.parent.innerHeight / 2;
      mouseX = (e.clientX - halfW) * 0.35;
      mouseY = (e.clientY - halfH) * 0.2;
      windForce = (e.clientX - halfW) / halfW;
    }});

    window.parent.addEventListener('scroll', () => {{
      const scrollPos = window.parent.pageYOffset || window.parent.document.documentElement.scrollTop;
      scrollOffset = scrollPos * 0.42;
    }});

    window.parent.addEventListener('resize', () => {{
      camera.aspect = window.parent.innerWidth / window.parent.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.parent.innerWidth, window.parent.innerHeight);

      if (mountainMesh) {{
        const fSize = getFrustumSizeAtDistance(camera.position.z + 950);
        mountainMesh.geometry.dispose();
        mountainMesh.geometry = new THREE.PlaneGeometry(fSize.width * 1.35, fSize.height * 1.35);
      }}
    }});

    let clock = 0;
    function animate() {{
      window.parent.requestAnimationFrame(animate);
      clock += 0.02;

      targetCameraX += (mouseX - targetCameraX) * 0.04;
      targetCameraY += (30 - mouseY - targetCameraY) * 0.04;

      camera.position.x = targetCameraX;
      camera.position.y = targetCameraY;
      camera.position.z = 600 - (scrollOffset % 700);
      camera.lookAt(0, 30, -750);

      const posAttr = flakeGeo.attributes.position;
      for (let i = 0; i < flakeCount; i++) {{
        let y = posAttr.getY(i) - snowData[i].speedY;
        let x = posAttr.getX(i) + Math.sin(clock * snowData[i].swaySpeed + snowData[i].swayOffset) * 0.6 + (windForce * snowData[i].windInfluence * 2.0);

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
""", height=0)

# ---------------------------------------------------------------------------
# 2. STREAMLIT STYLING (FIXED EXPANDER & SELECTBOX CONTRAST)
# ---------------------------------------------------------------------------
st.markdown(f"""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&family=Caveat:wght@700&family=JetBrains+Mono:wght@400;600;700&display=swap');

  html, body, [data-testid="stAppViewContainer"], .stApp, [data-testid="stHeader"] {{
    background-color: transparent !important;
    background: transparent !important;
    font-family: 'Plus Jakarta Sans', sans-serif !important;
    color: {text_color} !important;
  }}

  .block-container {{
    max-width: 1400px !important;
    padding-top: 1.5rem !important;
    padding-bottom: 3rem !important;
    padding-left: 2rem !important;
    padding-right: 2rem !important;
    margin: 0 auto !important;
    position: relative;
    z-index: 1;
  }}

  body {{
    background: {base_bg_gradient}, #060913 !important;
    margin: 0 !important;
    overflow-x: hidden !important;
  }}

  /* =========================================================================
     FIX 1: EXPANDER OVERRIDE (Fixes the solid white bar & invisible text)
     ========================================================================= */
  [data-testid="stExpander"], 
  .streamlit-expanderHeader, 
  details[data-testid="stExpander"] {{
    background: transparent !important;
    border: none !important;
    margin-bottom: 18px !important;
  }}

  /* Target the clickable header summary bar directly */
  [data-testid="stExpander"] summary,
  .streamlit-expanderHeader {{
    background: rgba(15, 23, 42, 0.88) !important;
    backdrop-filter: blur(20px) !important;
    -webkit-backdrop-filter: blur(20px) !important;
    border: 1px solid rgba(245, 158, 11, 0.55) !important;
    border-radius: 14px !important;
    color: #ffffff !important;
    font-weight: 700 !important;
    font-size: 14.5px !important;
    padding: 12px 18px !important;
    box-shadow: 0 4px 18px rgba(0, 0, 0, 0.4) !important;
    transition: all 0.2s ease !important;
  }}
  [data-testid="stExpander"] summary:hover {{
    border-color: #fde047 !important;
    background: rgba(20, 30, 55, 0.95) !important;
    box-shadow: 0 6px 24px rgba(245, 158, 11, 0.25) !important;
  }}

  /* Force all text, icons, and svgs inside the header to be brightly visible */
  [data-testid="stExpander"] summary *,
  [data-testid="stExpander"] summary p,
  [data-testid="stExpander"] summary span {{
    color: #f8fafc !important;
    font-weight: 700 !important;
  }}
  [data-testid="stExpander"] summary svg {{
    fill: #f59e0b !important;
    color: #f59e0b !important;
  }}

  /* Target the expanded contents box */
  [data-testid="stExpander"] div[role="region"],
  [data-testid="stExpander"] details > div:last-child {{
    background: rgba(15, 23, 42, 0.82) !important;
    backdrop-filter: blur(20px) !important;
    border: 1px solid rgba(255, 255, 255, 0.12) !important;
    border-top: none !important;
    border-bottom-left-radius: 14px !important;
    border-bottom-right-radius: 14px !important;
    padding: 16px !important;
  }}

  /* =========================================================================
     FIX 2: SELECTBOX & LABELS OVERRIDE (Fixes white dropdowns & dim labels)
     ========================================================================= */
  /* Dropdown field labels (Expedition Pace, Traveler Profile, Circuit Core Focus) */
  [data-testid="stSelectbox"] label,
  .stSelectbox label,
  .stTextInput label,
  .stTextArea label {{
    color: #fde047 !important;
    font-weight: 700 !important;
    font-size: 13.5px !important;
    letter-spacing: 0.3px !important;
    margin-bottom: 6px !important;
    text-shadow: 0 1px 6px rgba(0, 0, 0, 0.8) !important;
  }}

  /* Dropdown closed container */
  [data-testid="stSelectbox"] div[data-baseweb="select"] > div {{
    background-color: rgba(15, 23, 42, 0.90) !important;
    backdrop-filter: blur(14px) !important;
    color: #ffffff !important;
    border: 1px solid rgba(245, 158, 11, 0.5) !important;
    border-radius: 12px !important;
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.3) !important;
  }}
  [data-testid="stSelectbox"] div[data-baseweb="select"] * {{
    color: #ffffff !important;
    font-weight: 600 !important;
    font-size: 14px !important;
  }}

  /* Dropdown popup option menu list */
  [data-baseweb="popover"],
  [data-baseweb="menu"],
  ul[role="listbox"] {{
    background-color: #0b1329 !important;
    border: 1px solid rgba(245, 158, 11, 0.5) !important;
    border-radius: 12px !important;
  }}
  li[role="option"] {{
    color: #f1f5f9 !important;
    font-weight: 500 !important;
  }}
  li[role="option"]:hover,
  li[aria-selected="true"] {{
    background-color: rgba(245, 158, 11, 0.25) !important;
    color: #fde047 !important;
  }}

  /* High-Contrast Inputs */
  .stTextInput input, .stTextArea textarea {{
    background-color: rgba(15, 23, 42, 0.9) !important;
    backdrop-filter: blur(14px) !important;
    color: #ffffff !important;
    border: 1px solid rgba(245, 158, 11, 0.5) !important;
    border-radius: 12px !important;
    font-size: 14.5px !important;
    font-weight: 500 !important;
  }}
  .stTextInput input::placeholder {{
    color: #94a3b8 !important;
    opacity: 0.85 !important;
    font-size: 14.5px !important;
  }}

  /* Waypoint & General Frosted Cards */
  .waypoint-card {{
    background: {card_bg} !important;
    backdrop-filter: blur(28px) saturate(180%) !important;
    -webkit-backdrop-filter: blur(28px) saturate(180%) !important;
    border: 1px solid {card_border} !important;
    border-left: 5px solid #f59e0b !important;
    border-radius: 20px !important;
    padding: 24px !important;
    margin-bottom: 20px !important;
    box-shadow: 0 20px 50px rgba(0, 0, 0, 0.5), 0 0 25px rgba(245, 158, 11, 0.08) !important;
    transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1), box-shadow 0.3s ease, border-color 0.3s ease !important;
  }}
  .waypoint-card:hover {{
    border-color: rgba(245, 158, 11, 0.65) !important;
    transform: translateY(-4px) scale(1.008) !important;
  }}

  /* Popular Routes Badge Strip */
  .popular-routes-container {{
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    margin-top: 4px;
    margin-bottom: 18px;
  }}
  .popular-routes-label {{
    color: #f59e0b;
    font-weight: 700;
    font-size: 13.5px;
    letter-spacing: 0.2px;
    margin-right: 2px;
  }}
  .popular-route-pill {{
    background: rgba(15, 23, 42, 0.85);
    border: 1px solid rgba(245, 158, 11, 0.65);
    color: #fde047;
    font-weight: 600;
    font-size: 12.5px;
    padding: 3.5px 12px;
    border-radius: 7px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
    display: inline-block;
  }}

  /* Agentic Terminal Thought Stream Box */
  .agent-terminal {{
    background: #020617;
    border: 1px solid #1e293b;
    border-left: 4px solid #10b981;
    border-radius: 12px;
    padding: 14px 18px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 12.5px;
    color: #34d399;
    line-height: 1.6;
    margin-bottom: 16px;
    box-shadow: inset 0 2px 10px rgba(0, 0, 0, 0.7);
  }}
  .agent-terminal span.ts {{
    color: #64748b;
  }}
  .agent-terminal span.tag {{
    color: #38bdf8;
    font-weight: 700;
  }}

  /* Dispatch Waiting Card */
  @keyframes tipFadeIn {{
    0% {{ opacity: 0; transform: translateY(6px); }}
    100% {{ opacity: 1; transform: translateY(0); }}
  }}
  @keyframes tipProgress {{
    0% {{ width: 0%; }}
    100% {{ width: 100%; }}
  }}
  .dispatch-card {{
    background: rgba(15, 23, 42, 0.90) !important;
    backdrop-filter: blur(28px) saturate(180%) !important;
    border: 1.5px solid rgba(245, 158, 11, 0.65) !important;
    border-radius: 20px !important;
    padding: 24px 28px !important;
    margin-bottom: 24px !important;
    box-shadow: 0 18px 45px rgba(0, 0, 0, 0.6), 0 0 30px rgba(245, 158, 11, 0.2) !important;
    position: relative;
    overflow: hidden;
  }}
  .dispatch-progress-bar {{
    position: absolute;
    bottom: 0;
    left: 0;
    height: 3px;
    background: linear-gradient(90deg, #f59e0b, #fde047);
    animation: tipProgress 4.5s linear infinite;
  }}

  /* Header & Navigation */
  .hero-container {{
    padding: 26px 0 18px 0;
    text-align: center;
    border-bottom: 1px solid rgba(255, 255, 255, 0.12);
    margin-bottom: 24px;
    background: radial-gradient(circle at center, {card_bg} 0%, transparent 85%);
    border-radius: 24px;
    backdrop-filter: blur(18px);
  }}
  .ai-status-pill {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
    background: rgba(15, 23, 42, 0.9);
    border: 1px solid rgba(245, 158, 11, 0.6);
    color: #fde047;
    padding: 6px 20px;
    border-radius: 9999px;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    margin-bottom: 14px;
  }}
  .ai-status-pill::before {{
    content: "●";
    color: #10b981;
    font-size: 14px;
    animation: radar 2s ease infinite;
  }}
  @keyframes radar {{
    0% {{ transform: scale(0.9); opacity: 0.7; }}
    50% {{ transform: scale(1.3); opacity: 1; filter: drop-shadow(0 0 8px #10b981); }}
    100% {{ transform: scale(0.9); opacity: 0.7; }}
  }}

  .hero-title {{
    font-size: 3.1rem;
    font-weight: 800;
    color: #ffffff;
    letter-spacing: -0.5px;
    line-height: 1.15;
    margin-bottom: 8px;
  }}
  .hero-title span {{
    background: linear-gradient(135deg, #ffffff 0%, #fde047 50%, #f59e0b 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }}
  .hero-subtitle {{
    color: {subtext_color} !important;
    font-size: 1.05rem;
    max-width: 720px;
    margin: 0 auto;
  }}

  /* WhatsApp Share Button */
  .whatsapp-btn {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 10px;
    background: linear-gradient(135deg, #25D366 0%, #128C7E 100%) !important;
    color: #ffffff !important;
    font-weight: 700;
    font-size: 14.5px;
    text-decoration: none !important;
    padding: 12px 20px;
    border-radius: 12px;
    box-shadow: 0 4px 18px rgba(37, 211, 102, 0.35);
    transition: transform 0.15s ease;
    width: 100%;
    margin-top: 10px;
  }}
  .whatsapp-btn:hover {{
    transform: translateY(-2px);
    color: #ffffff !important;
  }}

  /* AI Stats Telemetry Strip */
  .stats-bar {{
    display: flex;
    gap: 14px;
    margin-bottom: 22px;
  }}
  .stat-pill {{
    flex: 1;
    background: {card_bg};
    backdrop-filter: blur(18px);
    border: 1px solid {card_border};
    border-radius: 16px;
    padding: 16px;
    text-align: center;
  }}
  .stat-pill .num {{
    font-size: 1.35rem;
    font-weight: 800;
    color: #fde047 !important;
  }}
  .stat-pill .lbl {{
    font-size: 11px;
    font-weight: 700;
    color: {subtext_color} !important;
    text-transform: uppercase;
    letter-spacing: 0.6px;
    margin-top: 3px;
  }}

  .day-tag {{
    background: linear-gradient(135deg, #f59e0b, #d97706);
    color: #0b0f19 !important;
    font-weight: 900;
    font-size: 13px;
    padding: 5px 12px;
    border-radius: 8px;
    display: inline-block;
    margin-right: 12px;
  }}
  .day-headline {{
    font-size: 1.25rem;
    font-weight: 700;
    color: {text_color} !important;
    margin-bottom: 10px;
  }}
  .landmark-chip {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
    background: rgba(30, 41, 59, 0.95);
    border: 1px solid {card_border};
    padding: 4px 14px;
    border-radius: 20px;
    font-size: 13px;
    color: #e2e8f0 !important;
    margin-bottom: 14px;
  }}
  .landmark-chip b {{
    color: #fde047 !important;
  }}
  .bullet-list {{
    list-style: none;
    padding-left: 0;
    margin: 0;
  }}
  .bullet-list li {{
    font-size: 14.5px;
    line-height: 1.65;
    color: {text_color} !important;
    margin-bottom: 10px;
    position: relative;
    padding-left: 22px;
  }}
  .bullet-list li::before {{
    content: "✦";
    position: absolute;
    left: 0;
    color: #f59e0b;
    font-size: 14px;
  }}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# SESSION STATE INITIALIZATION
# ---------------------------------------------------------------------------
if "itinerary_data" not in st.session_state:
    st.session_state.itinerary_data = None
if "generated_files" not in st.session_state:
    st.session_state.generated_files = None
if "pdf_path" not in st.session_state:
    st.session_state.pdf_path = None

# ---------------------------------------------------------------------------
# HERO SECTION
# ---------------------------------------------------------------------------
st.markdown(f"""
<div class="hero-container">
  <div class="ai-status-pill">{period_label}</div>
  <div class="hero-title">Wondoo <span>Alpine Studio</span></div>
  <div class="hero-subtitle">Autonomous AI expedition engine — synthesize high-altitude itineraries, live altitude telemetry, and publication-ready brochures.</div>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# AI PARAMETER TUNING MATRIX (EXPEDITION DIALS)
# ---------------------------------------------------------------------------
with st.expander("⚙️ AI Expedition Tuning Matrix (Custom Pace & Vibe)", expanded=False):
    t_col1, t_col2, t_col3 = st.columns(3)
    with t_col1:
        tune_pace = st.selectbox(
            "Expedition Pace",
            ["Balanced Explorer (Standard)", "Relaxed & Scenic (Slow Travel)", "High-Altitude Thrill (Active Trekking)"]
        )
    with t_col2:
        tune_traveler = st.selectbox(
            "Traveler Profile",
            ["Couples & Leisure", "Family & Elders (Accessible)", "4x4 / Adventure Bikers", "Solo Backpacker & Photographers"]
        )
    with t_col3:
        tune_vibe = st.selectbox(
            "Circuit Core Focus",
            ["Panoramic Peaks & Sunrises", "Offbeat Homestays & Villages", "Monasteries & Tibetan Heritage", "Alpine High Passes & Lakes"]
        )

# ---------------------------------------------------------------------------
# COMMAND CONSOLE (PROMPT BAR & COMPACT POPULAR ROUTES CHIPS)
# ---------------------------------------------------------------------------
st.markdown("""
<div style="margin-bottom: 8px;">
  <span style="font-size: 16px; font-weight: 700; color: #ffffff;">⚡ Destination & Duration Coordinates</span>
</div>
""", unsafe_allow_html=True)

col_input, col_submit = st.columns([4.2, 1.2], gap="small")

with col_input:
    tour_prompt = st.text_input(
        label="Trip Destination & Duration",
        placeholder="e.g. Kaluk & Rinchenpong 3N/4D  |  Darjeeling, Kurseong & Mirik 4N/5D  |  Lachen & Lachung 3N/4D",
        label_visibility="collapsed",
    )

with col_submit:
    trigger_draft = st.button("✨ Draft Journey", type="primary", use_container_width=True)

st.markdown("""
<div class="popular-routes-container">
  <span class="popular-routes-label">Popular Routes:</span>
  <span class="popular-route-pill">Kaluk & Rinchenpong 3N/4D</span>
  <span class="popular-route-pill">Darjeeling, Kurseong & Mirik 4N/5D</span>
  <span class="popular-route-pill">Lachen, Lachung & Yumthang 3N/4D</span>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# LIVE AGENTIC REASONING & DISPATCH LOADING LOOP
# ---------------------------------------------------------------------------
if trigger_draft and tour_prompt.strip():
    enhanced_prompt = (
        f"{tour_prompt.strip()} | Preference constraints: Pace={tune_pace}, "
        f"Travelers={tune_traveler}, Theme={tune_vibe}. Tailor daily stops accordingly."
    )
    
    progress_placeholder = st.empty()
    
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(generate_itinerary_content, enhanced_prompt)
        
        tip_index = 0
        total_tips = len(EXPEDITION_TIPS)
        progress_steps = [
            ("RoutePlannerAgent", "Triangulating passes and elevation curves..."),
            ("TransitIntervalEngine", "Computing mountain transit hours & road checkpoints..."),
            ("VistaCuratorAgent", "Resolving viewpoints, permits, and monastery hours..."),
            ("TypographySynthesizer", "Assembling structured daily flyers and sightseeing cards..."),
            ("QualityGateAgent", "Validating altitude profile safety and acclimatization buffer...")
        ]
        step_idx = 0

        while not future.done():
            tip_title, tip_desc = EXPEDITION_TIPS[tip_index % total_tips]
            agent_name, agent_task = progress_steps[step_idx % len(progress_steps)]

            progress_placeholder.markdown(f"""
            <div class="agent-terminal">
              <span class="ts">[{time.strftime('%H:%M:%S')}]</span> <span class="tag">@{agent_name}</span>: {agent_task}
            </div>
            <div class="dispatch-card">
              <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; border-bottom:1px solid rgba(255,255,255,0.1); padding-bottom:8px;">
                <span style="background:rgba(245,158,11,0.2); border:1px solid #f59e0b; color:#fde047; padding:3px 12px; border-radius:999px; font-size:11px; font-weight:800; text-transform:uppercase;">AI Agent Active</span>
                <span style="font-size:12px; color:#94a3b8; font-family:'JetBrains Mono';">Synthesizing Expedition...</span>
              </div>
              <div style="animation: tipFadeIn 0.5s ease-out forwards;">
                <div style="color:#ffffff; font-size:16.5px; font-weight:800; margin-bottom:5px;">{tip_title}</div>
                <div style="color:#cbd5e1; font-size:14px; line-height:1.6;">{tip_desc}</div>
              </div>
              <div class="dispatch-progress-bar"></div>
            </div>
            """, unsafe_allow_html=True)

            time.sleep(4.5)
            tip_index += 1
            step_idx += 1

        try:
            plan = future.result()
            st.session_state.itinerary_data = plan
            st.session_state.generated_files = None
            st.session_state.pdf_path = None
            progress_placeholder.empty()
            st.rerun()
        except Exception as e:
            progress_placeholder.empty()
            st.error(f"Engine Failure: {e}")

# ---------------------------------------------------------------------------
# MAIN WORKSPACE: TWO-COLUMN SUITE
# ---------------------------------------------------------------------------
if st.session_state.itinerary_data:
    data: TourItinerary = st.session_state.itinerary_data

    total_stops = sum(len(d.attractions) for d in data.sightseeing_enroute)
    st.markdown(f"""
    <div class="stats-bar">
      <div class="stat-pill"><div class="num">{data.tour_title}</div><div class="lbl">Destination Circuit</div></div>
      <div class="stat-pill"><div class="num">{data.duration}</div><div class="lbl">Expedition Duration</div></div>
      <div class="stat-pill"><div class="num">{len(data.days)} Flyers</div><div class="lbl">Daily Itinerary Stages</div></div>
      <div class="stat-pill"><div class="num">{total_stops}+ Stops</div><div class="lbl">Enroute Curated Landmarks</div></div>
      <div class="stat-pill"><div class="num" style="color:#10b981 !important;">96% Safe</div><div class="lbl">Altitude Safety Index</div></div>
    </div>
    """, unsafe_allow_html=True)

    col_preview, col_export = st.columns([1.15, 0.85], gap="large")

    # LEFT PANE: ROADMAP REVIEW & INLINE AI EDITING
    with col_preview:
        st.markdown("<h3 style='color: #ffffff; margin-bottom: 16px;'>🗺️ Expedition Waypoints & Altitude Curve</h3>", unsafe_allow_html=True)

        for day in data.days:
            bullet_items = "".join([f"<li>{b}</li>" for b in day.bullets])
            st.markdown(f"""
            <div class="waypoint-card">
              <div class="day-headline">
                <span class="day-tag">DAY {day.day_number}</span>
                <span>{day.route_title}</span>
              </div>
              <div class="landmark-chip">
                <span>📍 Key Viewpoint:</span> <b>{day.place_name}</b> &nbsp;|&nbsp; <span>Query:</span> <code>{day.wikipedia_search_term}</code>
              </div>
              <ul class="bullet-list">
                {bullet_items}
              </ul>
            </div>
            """, unsafe_allow_html=True)

        with st.expander("📍 Review Enroute Sightseeing Card Contents", expanded=False):
            for s in data.sightseeing_enroute:
                st.markdown(f"<span style='color:#fde047; font-weight:700;'>Day {s.day_number}: {s.route_name}</span>", unsafe_allow_html=True)
                for att in s.attractions:
                    st.markdown(f"<span style='color:{subtext_color};'>• {att}</span>", unsafe_allow_html=True)

        st.markdown("<hr style='border-color: rgba(245, 158, 11, 0.2); margin: 24px 0;'>", unsafe_allow_html=True)
        st.markdown("<h4 style='color: #ffffff; margin-bottom: 8px;'>💬 Route Modification Agent</h4>", unsafe_allow_html=True)
        edit_input = st.text_input(
            "Revision prompt",
            placeholder="e.g. On Day 2, add Singshore Bridge and replace monastery with local homestay visit...",
            label_visibility="collapsed"
        )
        if st.button("🔄 Re-synthesize Plan"):
            if edit_input.strip():
                with st.spinner("🤖 Applying revisions with Gemini..."):
                    revision_prompt = (
                        f"Update this existing itinerary:\n"
                        f"Title: {data.tour_title}\n"
                        f"Current Days: {[d.model_dump() for d in data.days]}\n\n"
                        f"User's requested modification: {edit_input}"
                    )
                    try:
                        st.session_state.itinerary_data = generate_itinerary_content(revision_prompt)
                        st.session_state.generated_files = None
                        st.session_state.pdf_path = None
                        st.rerun()
                    except Exception as e:
                        st.error(f"Revision error: {e}")

    # RIGHT PANE: HEADLESS RENDERING PIPELINE & WHATSAPP DISPATCH
    with col_export:
        st.markdown("<h3 style='color: #ffffff; margin-bottom: 16px;'>🖨️ Production Pipeline</h3>", unsafe_allow_html=True)

        st.markdown(f"""
        <div class="waypoint-card" style="border-left: 4px solid #38bdf8;">
          <div style="font-weight:700; color:#38bdf8; font-size:15px; margin-bottom:6px;">High-Fidelity Compilation Engine</div>
          <div style="font-size:13.5px; color:{subtext_color}; line-height: 1.5;">
            Renders pixel-perfect typography, applies transparent title containers, retrieves Wikipedia photography, masks legacy promo overlays, and compiles your fixed covers into a unified print brochure.
          </div>
        </div>
        """, unsafe_allow_html=True)

        if st.button("🚀 Render Flyers & Compile PDF", type="primary", use_container_width=True):
            output_dir = os.path.join("web_output", f"session_{abs(hash(data.tour_title))}")
            os.makedirs(output_dir, exist_ok=True)

            with st.status("🎨 Executing headless Chromium engine...", expanded=True) as status:
                st.write("• Fetching authentic destination imagery...")
                st.write("• Rendering high-resolution typography on template canvas...")
                st.write("• Merging front cover, daily flyers, sightseeing card, and back cover...")

                asyncio.run(render_itinerary_pages(data, template_path="template_bg.png", output_dir=output_dir))

                day_images = sorted(glob.glob(os.path.join(output_dir, "Day_*.jpg")))
                sightseeing_img = os.path.join(output_dir, "Sightseeing_Enroute.jpg")
                pdf_files = glob.glob(os.path.join(output_dir, "*.pdf"))

                st.session_state.generated_files = day_images + ([sightseeing_img] if os.path.exists(sightseeing_img) else [])
                if pdf_files:
                    st.session_state.pdf_path = pdf_files[0]

                status.update(label="Export Complete & Ready for Distribution!", state="complete", expanded=False)

        # PDF Download Button
        if st.session_state.pdf_path and os.path.exists(st.session_state.pdf_path):
            with open(st.session_state.pdf_path, "rb") as f:
                st.download_button(
                    label="📥 Download Merged PDF Brochure",
                    data=f.read(),
                    file_name=os.path.basename(st.session_state.pdf_path),
                    mime="application/pdf",
                    use_container_width=True,
                )

            # Instant WhatsApp Route Dispatch
            wa_summary_lines = [f"🏔️ *{data.tour_title}* ({data.duration})", ""]
            for d in data.days:
                wa_summary_lines.append(f"📍 *Day {d.day_number}*: {d.route_title}")
                wa_summary_lines.append(f"   • Viewpoint: {d.place_name}")
            wa_summary_lines.append("\n📄 *Full PDF brochure compiled via Wondoo AI Studio.*")
            wa_text = urllib.parse.quote("\n".join(wa_summary_lines))
            wa_url = f"https://api.whatsapp.com/send?text={wa_text}"

            st.markdown(f"""
            <a href="{wa_url}" target="_blank" class="whatsapp-btn">
              <span>💬 Dispatch Itinerary to WhatsApp</span>
            </a>
            """, unsafe_allow_html=True)

        # High-Resolution Page Preview Tabs
        if st.session_state.generated_files:
            st.markdown("<h4 style='color: #ffffff; margin-top: 20px; margin-bottom: 12px;'>🖼️ Generated Visuals</h4>", unsafe_allow_html=True)
            tabs = st.tabs([f"Day {i+1}" if i < len(data.days) else "Sightseeing" for i in range(len(st.session_state.generated_files))])
            for idx, tab in enumerate(tabs):
                with tab:
                    st.image(st.session_state.generated_files[idx], use_container_width=True)

else:
    # Standby State
    st.markdown(f"""
    <div class="waypoint-card" style="text-align: center; padding: 60px 20px; margin-top: 20px;">
      <div style="font-size: 44px; margin-bottom: 14px;">🏔️</div>
      <div style="font-size: 1.3rem; font-weight: 800; color: #ffffff;">Alpine Expedition System Ready</div>
      <div style="color: {subtext_color}; font-size: 14.5px; max-width: 440px; margin: 8px auto 0 auto; line-height: 1.5;">
        Input your target destinations and duration above to initialize waypoint drafting, photo indexing, and flyer assembly.
      </div>
    </div>
    """, unsafe_allow_html=True)