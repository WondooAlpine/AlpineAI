import requests
import streamlit as st
from typing import List, Dict

WIKIMEDIA_ENDPOINT = "https://en.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "WondooAlpineAI/2.0 (expedition.studio@wondoo.internal)"}

FALLBACK_SPOT_PHOTOS = [
    {
        "url": "https://images.unsplash.com/photo-1544735716-392fe2489ffa?auto=format&fit=crop&w=1000&q=80",
        "caption": "Mountain Ridge & Promenade",
        "tag": "Iconic Vista"
    },
    {
        "url": "https://images.unsplash.com/photo-1506744038136-46273834b3fb?auto=format&fit=crop&w=1000&q=80",
        "caption": "Pine Valley Overlook",
        "tag": "Alpine Trail"
    }
]

@st.cache_data(ttl=86400, show_spinner=False)
def search_key_spot_images(spot_name: str, max_results: int = 2) -> List[Dict[str, str]]:
    """
    Finds authentic live web photography specifically matching the day's Key Spot name.
    """
    clean_spot = spot_name.strip()
    if not clean_spot:
        return FALLBACK_SPOT_PHOTOS

    # Sanitize transit strings like "NJP / Bagdogra to Darjeeling" -> "Darjeeling"
    if "/" in clean_spot or " to " in clean_spot.lower():
        parts = clean_spot.replace("/", " ").split()
        clean_spot = parts[-1]

    if "mall" in clean_spot.lower() and "darjeeling" in clean_spot.lower():
        search_query = "Chowrasta Darjeeling"
    else:
        search_query = clean_spot

    try:
        search_params = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": f"{search_query}",
            "gsrlimit": max_results + 3,
            "prop": "pageimages|pageterms",
            "piprop": "thumbnail|original",
            "pithumbsize": 900
        }

        resp = requests.get(WIKIMEDIA_ENDPOINT, params=search_params, headers=HEADERS, timeout=3)
        if resp.status_code == 200:
            pages = resp.json().get("query", {}).get("pages", {})
            photos = []

            for _, info in pages.items():
                img_url = info.get("original", {}).get("source") or info.get("thumbnail", {}).get("source")
                if img_url and not any(ext in img_url.lower() for ext in [".svg", ".ogg", ".pdf"]):
                    title = info.get("title", clean_spot)
                    photos.append({
                        "url": img_url,
                        "caption": title[:38],
                        "tag": "Key Spot Landmark"
                    })
                if len(photos) >= max_results:
                    break

            if photos:
                return photos

    except Exception as e:
        print(f"Error fetching image for key spot '{clean_spot}': {e}")

    return FALLBACK_SPOT_PHOTOS