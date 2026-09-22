import os
import time
import base64
import asyncio
import urllib.request
import urllib.parse
import json
from typing import List
from PIL import Image
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from playwright.async_api import async_playwright

# ---------------------------------------------------------------------------
# 1. Pydantic Models for Structured Output
# ---------------------------------------------------------------------------
class DaySightseeing(BaseModel):
    day_number: int = Field(description="Day number (e.g. 1, 2, 3)")
    route_name: str = Field(description="Short route/location name (e.g. 'NJP to Kaluk via Melli')")
    attractions: List[str] = Field(description="3 to 5 specific spots/viewpoints visited enroute")

class DayPlan(BaseModel):
    day_number: int = Field(description="Day number (e.g. 1, 2, 3)")
    route_title: str = Field(description="Title in Title Case, e.g. 'Arrival – NJP to Rinchenpong via Jorethang'")
    place_name: str = Field(description="1-3 words in Title Case for photo caption, e.g. 'Rinchenpong'")
    wikipedia_search_term: str = Field(description="Wikipedia search term, e.g. 'Rinchenpong', 'Kangchenjunga'")
    bullets: List[str] = Field(description="5 to 6 concise bullet points (20 to 26 words each) starting with an emoji.")

class TourItinerary(BaseModel):
    tour_title: str
    duration: str
    days: List[DayPlan]
    sightseeing_enroute: List[DaySightseeing] = Field(description="Comprehensive list of all attractions covered across each day.")

# ---------------------------------------------------------------------------
# 2. Dynamic Image Fetcher
# ---------------------------------------------------------------------------
def get_relevant_photo(place_name: str, search_term: str, day_num: int = 1) -> str:
    try:
        query = urllib.parse.quote(search_term.strip())
        url = f"https://en.wikipedia.org/w/api.php?action=query&format=json&prop=pageimages&pithumbsize=1000&generator=search&gsrsearch={query}&gsrlimit=1"
        req = urllib.request.Request(url, headers={"User-Agent": "WondooItineraryBot/1.0"})
        with urllib.request.urlopen(req, timeout=4) as response:
            data = json.loads(response.read().decode())
            pages = data.get("query", {}).get("pages", {})
            for _, page_info in pages.items():
                if "thumbnail" in page_info and "source" in page_info["thumbnail"]:
                    return page_info["thumbnail"]["source"]
    except Exception:
        pass

    fallbacks = [
        "https://images.unsplash.com/photo-1544735716-392fe2489ffa?w=800&q=80",
        "https://images.unsplash.com/photo-1506744038136-46273834b3fb?w=800&q=80",
        "https://images.unsplash.com/photo-1513836279014-a89f7a76ae86?w=800&q=80",
        "https://images.unsplash.com/photo-1448375240586-882707db888b?w=800&q=80",
        "https://images.unsplash.com/photo-1470071459604-3b5ec3a7fe05?w=800&q=80",
    ]
    return fallbacks[(day_num - 1) % len(fallbacks)]

# ---------------------------------------------------------------------------
# 3. HTML Day Template (TRANSPARENT HEADER - NO WHITE BOXES)
# ---------------------------------------------------------------------------
HTML_DAY_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Caveat:wght@700&family=Poppins:wght@400;500;600;700;800;900&display=swap');
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    width: {width}px;
    height: {height}px;
    position: relative;
    overflow: hidden;
    background-image: url('{bg_base64_data}');
    background-repeat: no-repeat;
    background-position: top left;
    background-size: 100% 100%;
    font-family: 'Poppins', sans-serif;
    color: #111;
  }}

  /* HEADER CONTAINER: Completely transparent with no mask or white box */
  .header-slot-box {{
    position: absolute;
    top: 15.6%;
    left: 5%;
    width: 90%;
    height: 9.8%;
    background: transparent;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    gap: 1px;
    z-index: 10;
  }}

  /* Clean bold DAY indicator */
  .day-title {{
    font-family: 'Poppins', sans-serif;
    font-size: 60px;
    font-weight: 900;
    color: #0d0d0d;
    letter-spacing: 0.5px;
    line-height: 0.95;
  }}

  /* Route Title: Natural brush script with no background */
  .route-title {{
    font-family: 'Caveat', cursive;
    font-size: 52px;
    font-weight: 700;
    color: #b45309; /* Warm amber/brown tone for premium contrast */
    line-height: 1.0;
    text-transform: none;
    letter-spacing: 0.2px;
    text-align: center;
    width: 100%;
    white-space: nowrap;
  }}

  /* Left photo inside rounded black frame */
  .photo-slot {{
    position: absolute;
    top: 48.6%;
    left: 0.8%;
    width: 28.5%;
    height: 21.2%;
    border-radius: 46px;
    overflow: hidden;
    z-index: 8;
    background-color: #ddd;
    border: 4px solid #111;
  }}
  .photo-slot img {{
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }}

  /* Caption below the photo */
  .place-name-slot {{
    position: absolute;
    top: 71.0%;
    left: 1%;
    width: 28%;
    height: 5.2%;
    background: transparent;
    display: flex;
    justify-content: center;
    align-items: center;
    font-family: 'Caveat', cursive;
    font-size: 42px;
    font-weight: 700;
    color: #111;
    line-height: 1;
    text-transform: none;
    z-index: 10;
  }}

  /* Itinerary slot bounded between the two horizontal yellow lines */
  .itinerary-slot {{
    position: absolute;
    top: 27.2%;
    left: 31.5%;
    width: 66%;
    height: 56.5%;
    display: flex;
    flex-direction: column;
    justify-content: flex-start;
    overflow: hidden;
    z-index: 10;
  }}
  .bullet-list {{
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }}
  .bullet-list li {{
    font-size: 26px;
    line-height: 1.45;
    color: #1a1a1a;
    font-weight: 500;
    text-align: justify;
    text-justify: inter-word;
  }}
</style>
</head>
<body>
  <div class="header-slot-box">
    <div class="day-title">DAY {day_number}</div>
    <div class="route-title">{route_title}</div>
  </div>

  <div class="photo-slot">
    <img src="{photo_url}" alt="{place_name}">
  </div>
  <div class="place-name-slot">{place_name}</div>

  <div class="itinerary-slot" id="itineraryBox">
    <ul class="bullet-list" id="bulletList">
      {bullet_html}
    </ul>
  </div>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# 4. HTML Sightseeing Page (CLEAN COVER FOR 'GET SPECIAL PROMO')
# ---------------------------------------------------------------------------
HTML_SIGHTSEEING_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Caveat:wght@700&family=Poppins:wght@400;500;600;700;800;900&display=swap');
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    width: {width}px;
    height: {height}px;
    position: relative;
    overflow: hidden;
    background-image: url('{bg_base64_data}');
    background-repeat: no-repeat;
    background-position: top left;
    background-size: 100% 100%;
    font-family: 'Poppins', sans-serif;
    color: #111;
  }}

  /* 
     Elegantly transform the left yellow promo bubble into a branded section badge 
     so 'GET SPECIAL PROMO' is completely replaced rather than clashing.
  */
  .promo-replacement-bubble {{
    position: absolute;
    top: 29.0%;
    left: -2%;
    width: 29%;
    height: 18%;
    background-color: #fde047;
    border-radius: 50%;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    text-align: center;
    z-index: 8;
    box-shadow: 2px 4px 10px rgba(0,0,0,0.06);
  }}
  .promo-replacement-bubble .badge-line1 {{
    font-family: 'Caveat', cursive;
    font-size: 40px;
    font-weight: 700;
    color: #111;
    line-height: 1.0;
  }}
  .promo-replacement-bubble .badge-line2 {{
    font-family: 'Poppins', sans-serif;
    font-size: 30px;
    font-weight: 900;
    color: #0b0b0b;
    line-height: 1.1;
    letter-spacing: 0.5px;
  }}

  /* Erase lower photo frame area smoothly with a matching soft cream patch */
  .mask-lower-photo {{
    position: absolute;
    top: 48.0%;
    left: 0.5%;
    width: 29.5%;
    height: 29.5%;
    background-color: #fff9e6;
    border-radius: 36px;
    z-index: 7;
  }}

  /* Header Container: Transparent, No White Box */
  .header-slot-box {{
    position: absolute;
    top: 15.6%;
    left: 5%;
    width: 90%;
    height: 9.8%;
    background: transparent;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    gap: 1px;
    z-index: 10;
  }}
  .main-title {{
    font-family: 'Poppins', sans-serif;
    font-size: 52px;
    font-weight: 900;
    color: #0b0b0b;
    letter-spacing: 0.5px;
    line-height: 0.95;
  }}
  .sub-title {{
    font-family: 'Caveat', cursive;
    font-size: 46px;
    font-weight: 700;
    color: #b45309;
    line-height: 1.0;
  }}

  /* Content area strictly placed between yellow dividers */
  .sightseeing-container {{
    position: absolute;
    top: 27.2%;
    left: 31.5%;
    width: 66%;
    height: 56.5%;
    display: flex;
    flex-direction: column;
    gap: 14px;
    overflow: hidden;
    z-index: 10;
  }}

  .day-card {{
    background: #ffffff;
    border: 2.5px solid #111;
    border-left: 6px solid #f59e0b;
    border-radius: 14px;
    padding: 10px 14px;
    box-shadow: 2px 4px 0px rgba(0,0,0,0.05);
  }}
  .day-card-header {{
    font-size: 19px;
    font-weight: 800;
    color: #0b0b0b;
    border-bottom: 2px solid #fde047;
    padding-bottom: 3px;
    margin-bottom: 6px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }}
  .day-card-header span {{
    font-family: 'Caveat', cursive;
    font-size: 22px;
    font-weight: 700;
    color: #b45309;
  }}
  .attraction-list {{
    list-style: none;
    display: flex;
    flex-wrap: wrap;
    gap: 6px 12px;
  }}
  .attraction-list li {{
    font-size: 16px;
    line-height: 1.3;
    color: #1e293b;
    font-weight: 500;
  }}
</style>
</head>
<body>
  <!-- Clean badge that covers 'GET SPECIAL PROMO' gracefully -->
  <div class="promo-replacement-bubble">
    <div class="badge-line1">Enroute</div>
    <div class="badge-line2">SPOTS</div>
  </div>

  <div class="mask-lower-photo"></div>

  <!-- Transparent Header -->
  <div class="header-slot-box">
    <div class="main-title">SIGHTSEEING ENROUTE</div>
    <div class="sub-title">Major Attractions & Key Viewpoints</div>
  </div>

  <!-- Sightseeing Cards aligned safely inside right container -->
  <div class="sightseeing-container" id="sightseeingBox">
    {sightseeing_cards_html}
  </div>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# 5. Gemini Generation
# ---------------------------------------------------------------------------
import time
import os
from google import genai
from google.genai import types
from google.genai.errors import APIError

def generate_itinerary_content(prompt: str) -> TourItinerary:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is not set.")

    client = genai.Client(api_key=api_key)

    system_instruction = (
        "You are an elite high-altitude travel curator and route planner specializing "
        "in the Himalayas (Sikkim, Darjeeling, West Bengal, Ladakh). "
        "Create an authentic, structured, and realistic day-by-day travel plan based strictly "
        "on the user's route request. Output valid JSON matching the TourItinerary schema."
    )

    max_retries = 4
    base_delay = 3

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model="gemini-3.5-flash",  # High throughput, low latency
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    response_schema=TourItinerary,
                    temperature=0.7,
                ),
            )
            
            # Parse response into Pydantic model
            if response.text:
                return TourItinerary.model_validate_json(response.text)
            else:
                raise ValueError("Received empty response text from Gemini.")

        except APIError as e:
            # Handle rate limits (429) or temporary server busyness (503)
            if e.code in [429, 503] or "temporarily busy" in str(e).lower() or "resource exhausted" in str(e).lower():
                if attempt < max_retries - 1:
                    sleep_time = base_delay * (2 ** attempt)
                    time.sleep(sleep_time)
                    continue
            raise RuntimeError(f"Gemini API failure: {e}") from e
        except Exception as e:
            if "temporarily busy" in str(e).lower() or "503" in str(e) or "429" in str(e):
                if attempt < max_retries - 1:
                    time.sleep(base_delay * (2 ** attempt))
                    continue
            raise e

# ---------------------------------------------------------------------------
# 6. Playwright Rendering + PDF Compiler
# ---------------------------------------------------------------------------
def find_file(base_name: str) -> str:
    for ext in [".png", ".jpg", ".jpeg"]:
        candidate = f"{base_name}{ext}"
        if os.path.exists(candidate):
            return candidate
    return ""

async def render_itinerary_pages(
    itinerary: TourItinerary,
    template_path: str = "template_bg.png",
    output_dir: str = "output_itinerary"
):
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Template '{template_path}' not found! Place template_bg.png in this directory.")

    with Image.open(template_path) as img:
        img_width, img_height = img.size

    print(f"📐 Template Resolution: {img_width}x{img_height}px")

    with open(template_path, "rb") as f:
        bg_base64_data = f"data:image/png;base64,{base64.b64encode(f.read()).decode('utf-8')}"

    os.makedirs(output_dir, exist_ok=True)
    day_image_paths = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
    headless=True,
    args=[
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
    ]
)
        page = await browser.new_page(viewport={"width": img_width, "height": img_height})

        # 1. Render Day pages
        for day in itinerary.days:
            bullet_html = "".join([f"<li>{b}</li>" for b in day.bullets])
            photo_url = get_relevant_photo(day.place_name, day.wikipedia_search_term, day.day_number)

            rendered_html = HTML_DAY_TEMPLATE.format(
                width=img_width,
                height=img_height,
                bg_base64_data=bg_base64_data,
                day_number=day.day_number,
                route_title=day.route_title,
                photo_url=photo_url,
                place_name=day.place_name,
                bullet_html=bullet_html,
            )

            await page.set_content(rendered_html, wait_until="networkidle")

            await page.evaluate("""() => {
                const routeElem = document.querySelector('.route-title');
                if (routeElem) {
                    let routeSize = 52;
                    while (routeElem.scrollWidth > routeElem.clientWidth && routeSize > 32) {
                        routeSize -= 1;
                        routeElem.style.fontSize = routeSize + 'px';
                    }
                }
                const box = document.getElementById('itineraryBox');
                const list = document.getElementById('bulletList');
                if (box && list) {
                    let fontSize = 26;
                    while (list.scrollHeight > box.clientHeight && fontSize > 18) {
                        fontSize -= 0.5;
                        const items = list.getElementsByTagName('li');
                        for (let item of items) {
                            item.style.fontSize = fontSize + 'px';
                            item.style.lineHeight = '1.38';
                        }
                    }
                }
            }""")

            day_file = os.path.join(output_dir, f"Day_{day.day_number}.jpg")
            await page.screenshot(path=day_file, type="jpeg", quality=95)
            day_image_paths.append(day_file)

        # 2. Render Sightseeing Summary (Safe right-aligned container)
        cards_html_list = []
        for item in itinerary.sightseeing_enroute:
            attractions_li = "".join([f"<li>📍 {att}</li>" for att in item.attractions])
            card = f"""
            <div class="day-card">
              <div class="day-card-header">
                <div>DAY {item.day_number}</div>
                <span>{item.route_name}</span>
              </div>
              <ul class="attraction-list">
                {attractions_li}
              </ul>
            </div>
            """
            cards_html_list.append(card)

        sightseeing_html = HTML_SIGHTSEEING_TEMPLATE.format(
            width=img_width,
            height=img_height,
            bg_base64_data=bg_base64_data,
            sightseeing_cards_html="".join(cards_html_list)
        )
        await page.set_content(sightseeing_html, wait_until="networkidle")
        sightseeing_file = os.path.join(output_dir, "Sightseeing_Enroute.jpg")
        await page.screenshot(path=sightseeing_file, type="jpeg", quality=95)

        await browser.close()

    # 3. Assemble and Merge PDF
    final_page_paths = []
    front_cover_path = find_file("cover_front")
    back_cover_path = find_file("cover_back")

    if front_cover_path:
        final_page_paths.append(front_cover_path)

    final_page_paths.extend(day_image_paths)
    final_page_paths.append(sightseeing_file)

    if back_cover_path:
        final_page_paths.append(back_cover_path)

    if final_page_paths:
        clean_title = "".join(c for c in itinerary.tour_title if c.isalnum() or c in (" ", "_")).strip().replace(" ", "_")
        pdf_path = os.path.join(output_dir, f"{clean_title}_Itinerary.pdf")

        pil_images = []
        for img_path in final_page_paths:
            im = Image.open(img_path).convert("RGB")
            if im.size != (img_width, img_height):
                im = im.resize((img_width, img_height), Image.Resampling.LANCZOS)
            pil_images.append(im)

        pil_images[0].save(
            pdf_path,
            save_all=True,
            append_images=pil_images[1:],
            resolution=150.0,
            quality=95,
            subsampling=0
        )
        print(f"📕 Merged PDF created at: {pdf_path}")

# ---------------------------------------------------------------------------
# 7. Main Execution
# ---------------------------------------------------------------------------
async def main():
    tour_prompt = input("Enter tour details (e.g. 'Darjeeling 4N/5D' or 'Kaluk 3N/4D'): ")
    if not tour_prompt.strip():
        tour_prompt = "Kaluk & Rinchenpong 3N/4D Tour"

    data = generate_itinerary_content(tour_prompt)
    print(f"✨ Plan created: {data.tour_title} ({data.duration})")

    print("\n🎨 Rendering flyers, sightseeing page, and compiling with covers...")
    await render_itinerary_pages(data, template_path="template_bg.png")
    print("\n🎉 Completed! Check the 'output_itinerary' folder.")

if __name__ == "__main__":
    asyncio.run(main())
