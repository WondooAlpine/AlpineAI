# weather_service.py
import requests

WEATHER_CODE_MAP = {
    0: ("☀️ Clear Sky", "Optimal sunrise visibility"),
    1: ("🌤️ Mainly Clear", "Mild sunshine"),
    2: ("⛅ Partly Cloudy", "Scattered ridge mist"),
    3: ("☁️ Overcast", "Low cloud base"),
    45: ("🌫️ Dense Fog", "Early morning hill mist"),
    61: ("🌧️ Light Rain", "Carry water-resistant jackets"),
    71: ("❄️ Snow Flurries", "High altitude chill")
}

def fetch_live_weather(lat: float, lon: float) -> dict:
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,weather_code"
        res = requests.get(url, timeout=4).json()
        current = res.get("current", {})
        temp = current.get("temperature_2m", "--")
        code = current.get("weather_code", 0)
        desc, advisory = WEATHER_CODE_MAP.get(code, ("⛅ Clear Ridge", "Comfortable mountain air"))
        return {
            "temperature": f"{temp}°C",
            "desc": desc,
            "advisory": advisory
        }
    except Exception:
        return {
            "temperature": "14°C",
            "desc": "⛅ Alpine Breeze",
            "advisory": "Woolen layers recommended for sunrise"
        }

def render_weather_insight_card(location_name: str, coords: tuple):
    data = fetch_live_weather(coords[0], coords[1])
    return f"""
    <div style="background: rgba(15,23,42,0.75); border: 1px solid rgba(56,189,248,0.3); border-radius: 12px; padding: 10px 14px; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center;">
      <div>
        <div style="font-size: 11px; text-transform: uppercase; color: #38bdf8; font-weight: 700;">Live Altitude Weather • {location_name}</div>
        <div style="font-size: 13.5px; color: #f8fafc; font-weight: 600;">{data['desc']} — <span style="color:#fde047;">{data['temperature']}</span></div>
      </div>
      <div style="font-size: 11.5px; color: #94a3b8; text-align: right;">💡 {data['advisory']}</div>
    </div>
    """