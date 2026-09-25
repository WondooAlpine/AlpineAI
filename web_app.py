import os
import glob
import json
import urllib.parse
import requests
from datetime import datetime, timezone, timedelta
import streamlit as st
import streamlit.components.v1 as components
from google import genai
from google.genai import types

from generate_itinerary import (
    generate_itinerary_content,
    render_itinerary_pages,
    TourItinerary,
)
from stay_matcher import match_stay_for_day

# ---------------------------------------------------------------------------
# CONFIGURATION
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
# 2. STREAMLIT STYLING (DARK FROSTED CONTROLS & COMPACT SPACING)
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
    max-width: 1400px !important;
    padding-top: 1.2rem !important;
    padding-bottom: 3rem !important;
    position: relative;
    z-index: 1;
  }

  /* Chat Bubbles */
  [data-testid="stChatMessage"] {
    background: rgba(15, 23, 42, 0.88) !important;
    border: 1px solid rgba(56, 189, 248, 0.35) !important;
    border-radius: 18px !important;
    padding: 16px 20px !important;
    margin-bottom: 12px !important;
    box-shadow: 0 10px 35px rgba(0, 0, 0, 0.55) !important;
    backdrop-filter: blur(16px) !important;
  }
  [data-testid="stChatMessage"] p, [data-testid="stChatMessage"] span, [data-testid="stChatMessage"] div {
    color: #f8fafc !important;
    font-size: 15.5px !important;
    line-height: 1.65 !important;
  }

  /* Chat Input Bar */
  [data-testid="stBottom"] {
    background: transparent !important;
    padding-top: 0rem !important;
    padding-bottom: 1.2rem !important;
  }
  [data-testid="stBottom"] > div {
    background: transparent !important;
    padding: 0 !important;
  }
  [data-testid="stChatInput"],
  [data-testid="stChatInput"] > div,
  [data-testid="stChatInput"] div[data-baseweb="base-input"],
  [data-testid="stChatInput"] div[data-baseweb="input"] {
    background-color: rgba(15, 23, 42, 0.92) !important;
    background: rgba(15, 23, 42, 0.92) !important;
    border: 1.5px solid rgba(245, 158, 11, 0.7) !important;
    border-radius: 16px !important;
    box-shadow: 0 8px 30px rgba(0, 0, 0, 0.65), 0 0 15px rgba(245, 158, 11, 0.15) !important;
    backdrop-filter: blur(16px) !important;
  }
  [data-testid="stChatInput"] textarea {
    background: transparent !important;
    color: #ffffff !important;
    font-size: 15px !important;
    caret-color: #fde047 !important;
  }
  [data-testid="stChatInput"] textarea::placeholder {
    color: #94a3b8 !important;
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

  /* Hero Section */
  .hero-container {
    padding: 22px 0 16px 0;
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

  /* Waypoint Card */
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

  /* Stay Cards with Photography */
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

  /* Production Expander */
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
                "Namaste! I am your **Wondoo Alpine AI Concierge**.\n\n"
                "Tell me where you want to travel (e.g. Sikkim, Darjeeling, Kalimpong, or Ladakh), "
                "how many days, and your preferred travel pace."
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
# 4. PACKAGE BOOKING MODAL (AUTO-CLOSE + LEAD DISPATCH)
# ---------------------------------------------------------------------------
@st.dialog("🎒 Reserve Complete Himalayan Expedition Package")
def open_package_booking_dialog(itinerary: TourItinerary, matched_stays: list):
    st.markdown(f"#### **{itinerary.tour_title}** ({itinerary.duration})")
    st.caption(
        "Provide your group details below. Our concierge team logs your request in our master inventory sheet and prepares your confirmation."
    )

    with st.form("package_booking_form"):
        col_name, col_phone = st.columns(2)
        with col_name:
            lead_name = st.text_input("Lead Traveler Name*", placeholder="e.g. Rahul Sharma")
        with col_phone:
            phone_num = st.text_input("WhatsApp / Contact Number*", placeholder="e.g. +91 98765 43210")

        col_heads, col_rooms = st.columns(2)
        with col_heads:
            num_heads = st.number_input(
                "Total Number of Heads (Adults + Kids)", min_value=1, max_value=35, value=2
            )
        with col_rooms:
            num_rooms = st.number_input("Rooms Required", min_value=1, max_value=15, value=1)

        col_food, col_cab = st.columns(2)
        with col_food:
            meal_plan = st.selectbox(
                "Meal Plan Preference",
                [
                    "With Fooding (MAP - Breakfast + Dinner included)",
                    "All Meals (AP - Breakfast + Lunch + Dinner)",
                    "Without Fooding (EP - Room Only / Ala Carte on-site)",
                ],
            )
        with col_cab:
            cab_option = st.selectbox(
                "Mountain Transit & Sightseeing Cab",
                [
                    "Include Dedicated Cab (Innova / Scorpio / Bolero 4x4)",
                    "Self-Arranged (I will manage my own transit)",
                ],
            )

        special_requests = st.text_area(
            "Special Requests (Optional)",
            placeholder="e.g., Room with Kangchenjunga view, ground-floor for seniors, pickup from Bagdogra (IXB)...",
        )

        submitted = st.form_submit_button(
            "🚀 Submit Reservation Request", type="primary", use_container_width=True
        )

        if submitted:
            if not lead_name.strip() or not phone_num.strip():
                st.error("Please provide both Lead Traveler Name and Contact Number.")
            else:
                stays_summary = "; ".join(
                    [
                        f"Day {s['day']}: {s['stay_name']} ({s.get('property_type', 'Lodge')})"
                        for s in matched_stays
                    ]
                )

                payload = {
                    "lead_name": lead_name.strip(),
                    "phone": phone_num.strip(),
                    "circuit": itinerary.tour_title,
                    "duration": itinerary.duration,
                    "heads": int(num_heads),
                    "rooms": int(num_rooms),
                    "meal_plan": meal_plan,
                    "cab_option": cab_option,
                    "special_requests": special_requests.strip(),
                    "stays_summary": stays_summary,
                }

                if "YOUR_APPS_SCRIPT" not in BOOKING_WEBHOOK_URL:
                    try:
                        requests.post(BOOKING_WEBHOOK_URL, json=payload, timeout=8)
                    except Exception as e:
                        print(f"Webhook dispatch error: {e}")

                # Save confirmation state & close modal by rerunning
                st.session_state.booking_confirmed = {
                    "lead_name": lead_name.strip(),
                    "phone": phone_num.strip(),
                    "circuit": itinerary.tour_title,
                    "duration": itinerary.duration,
                }
                st.rerun()

# ---------------------------------------------------------------------------
# HERO SECTION
# ---------------------------------------------------------------------------
st.markdown(
    f"""
<div class="hero-container">
  <div class="ai-status-pill">{period_label}</div>
  <div class="hero-title">Wondoo <span>Alpine Studio</span></div>
  <div style="color: #cbd5e1; font-size: 15px;">Conversational Himalayan Expedition Architect, Stay Matcher & Brochure Engine</div>
</div>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# BOOKING CONFIRMATION BANNER (DISPLAYS ONCE MODAL AUTO-CLOSES)
# ---------------------------------------------------------------------------
if st.session_state.get("booking_confirmed"):
    info = st.session_state.booking_confirmed
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
            🎉 Reservation Request Received!
          </div>
          <div style="font-size: 15px; color: #f1f5f9; line-height: 1.6;">
            Thank you, <b>{info['lead_name']}</b>. Your booking request for <b>{info['circuit']} ({info['duration']})</b> has been recorded in our reservation database.<br>
            <span style="color: #fde047; font-weight: 700;">Our dedicated representative will contact you shortly on {info['phone']}</span> to verify stay availability and confirm your expedition voucher.
          </div>
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
# MAIN WORKSPACE (CONVERSATION INITIAL -> DUAL WORKSPACE FINAL)
# ---------------------------------------------------------------------------
if not st.session_state.itinerary_data:
    st.markdown("<h3 style='color: #ffffff; margin-bottom: 12px;'>💬 Live Expedition Dialogue</h3>", unsafe_allow_html=True)

    for msg in st.session_state.messages:
        avatar = "🏔️" if msg["role"] == "assistant" else "👤"
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])

    if user_prompt := st.chat_input("E.g., Plan 4 days in West Sikkim with great views and relaxing village walks..."):
        st.session_state.messages.append({"role": "user", "content": user_prompt})
        with st.chat_message("user", avatar="👤"):
            st.markdown(user_prompt)

        with st.chat_message("assistant", avatar="🏔️"):
            with st.spinner("Analyzing Himalayan passes, topography, and routes..."):
                raw_key = os.environ.get("GEMINI_API_KEY", "").strip().strip("'").strip('"')

                if not raw_key:
                    st.error("Missing GEMINI_API_KEY. Please set an environment variable with a key starting with 'AIzaSy'.")
                    st.stop()

                client = genai.Client(api_key=raw_key, http_options={"api_version": "v1beta"})

                system_instruction = (
                    "You are the master AI Travel Concierge at Wondoo Alpine Studio specializing in the Himalayas. "
                    "Engage warmly, discuss mountain road travel times, and altitude pacing. "
                    "When the user is satisfied, prompt them to click '✨ Finalize Itinerary & Reveal Curated Stays'."
                )

                contents = [
                    types.Content(
                        role="user" if m["role"] == "user" else "model",
                        parts=[types.Part.from_text(text=m["content"])],
                    )
                    for m in st.session_state.messages
                ]

                response = client.models.generate_content(
                    model="gemini-3.5-flash",
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.7,
                    ),
                )

                reply_text = response.text or "I am refining your route parameters."
                st.markdown(reply_text)
                st.session_state.messages.append({"role": "assistant", "content": reply_text})

    if len(st.session_state.messages) > 1:
        st.markdown("<br>", unsafe_allow_html=True)
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

        for day in data.days:
            bullet_items = "".join([f"<li style='color:#f8fafc; margin-bottom:8px;'>✦ {b}</li>" for b in day.bullets])
            st.markdown(
                f"""
            <div class="waypoint-card">
              <div style="font-size:18px; font-weight:700; color:#ffffff; margin-bottom:8px;">
                <span class="day-tag">DAY {day.day_number}</span> {day.route_title}
              </div>
              <div style="color:#94a3b8; font-size:13px; margin-bottom:12px;">
                📍 Key Spot: <b style="color:#fde047;">{day.place_name}</b>
              </div>
              <ul style="list-style:none; padding-left:0; margin:0;">
                {bullet_items}
              </ul>
            </div>
            """,
                unsafe_allow_html=True,
            )

    with col_stays:
        st.markdown("<h3 style='color: #ffffff;'>🏡 Recommended Stays & Booking</h3>", unsafe_allow_html=True)
        st.caption("Curated lodges matched to each day's route elevations.")

        matched_trip_stays = []
        for day in data.days:
            stay_dict = match_stay_for_day(day.place_name, day.route_title)
            stay_dict["day"] = day.day_number
            stay_dict["day_place"] = day.place_name
            matched_trip_stays.append(stay_dict)

        if st.button("🎒 Book Complete Tour Package (Stays + Food + Cab)", type="primary", use_container_width=True):
            open_package_booking_dialog(data, matched_trip_stays)

        st.markdown("<hr style='border-color: rgba(255,255,255,0.1); margin: 16px 0;'>", unsafe_allow_html=True)

        for s in matched_trip_stays:
            img_src = s.get(
                "image_url",
                "https://images.unsplash.com/photo-1544735716-392fe2489ffa?auto=format&fit=crop&w=900&q=80",
            )
            st.markdown(
                f"""
            <div class="stay-card">
              <div class="stay-img-wrap">
                <img src="{img_src}" alt="{s['stay_name']}" loading="lazy" />
                <div class="stay-img-badge">Day {s['day']} Night • {s['day_place']}</div>
              </div>
              <div class="stay-content">
                <div style="font-size:17px; font-weight:700; color:#ffffff; margin-bottom:4px;">
                  {s['stay_name']}
                </div>
                <div style="font-size:12px; color:#cbd5e1; margin-bottom:8px; display:flex; align-items:center; gap:8px;">
                  <span style="background:rgba(56,189,248,0.2); color:#38bdf8; padding:2px 8px; border-radius:6px; font-weight:600;">
                    📍 {s.get('altitude', 'Alpine Elev')}
                  </span>
                  <span>{s.get('property_type', 'Retreat')}</span>
                  <b style="color:#fbbf24;">{s.get('rating', '4.8 ★')}</b>
                  <span style="color:#94a3b8;">({s.get('price_bracket', '₹₹₹')})</span>
                </div>
                <div style="font-size:13px; color:#94a3b8; line-height:1.45; margin-bottom:12px;">
                  {s.get('vibe', '')}
                </div>
              </div>
            </div>
            """,
                unsafe_allow_html=True,
            )

            single_stay_inquiry = urllib.parse.quote(
                f"Hi, I would like to reserve only Day {s['day']} Stay at {s['stay_name']} ({s['day_place']}) for circuit {data.tour_title}."
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
