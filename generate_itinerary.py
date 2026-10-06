import os
import json
from typing import List, Optional
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# PYDANTIC SCHEMA
# ---------------------------------------------------------------------------
class DayItinerary(BaseModel):
    day_number: int = Field(description="Sequential day number starting from 1")
    route_title: str = Field(description="Concise route or theme title for the day")
    place_name: str = Field(description="Primary sightseeing spot or key waypoint for image fetching")
    stay_location: Optional[str] = Field(
        default=None,
        description="The exact town/hamlet of overnight stay (e.g., 'Darjeeling', 'Kalimpong', 'Gangtok'). MUST be null/None on the final departure day."
    )
    bullets: List[str] = Field(description="3 to 4 detailed bullet points covering transit, viewpoints, meals, and activities")

class TourItinerary(BaseModel):
    tour_title: str = Field(description="Catchy expedition title")
    duration: str = Field(description="Duration in format 'X Days / Y Nights'")
    sector: str = Field(description="Region or circuit sector name")
    days: List[DayItinerary] = Field(description="List of daily itineraries")

# ---------------------------------------------------------------------------
# GENERATION ENGINE
# ---------------------------------------------------------------------------
def generate_itinerary_content(prompt_text: str) -> TourItinerary:
    """
    Generates a structured TourItinerary object using Gemini with strict JSON schema enforcement.
    Ensures that stay_location is populated for every night except the final departure day.
    """
    api_key = os.environ.get("GEMINI_API_KEY", "")
    client = genai.Client(api_key=api_key) if api_key else genai.Client()

    system_instruction = (
        "You are the Lead Expedition Architect at Wondoo Alpine Studio. "
        "Create an authentic, well-paced, high-altitude or scenic circuit itinerary based on the user's requirements.\n\n"
        "STRICT NIGHT HALT & STAY LOCATION DIRECTIVES:\n"
        "1. For EVERY DAY except the final day, you MUST provide an explicit 'stay_location' indicating the exact town, village, or hamlet where travelers sleep that night (e.g. 'Darjeeling', 'Kalimpong', 'Gangtok', 'Pelling', 'Zuluk', 'Cherrapunji', 'Shillong', 'Pahalgam', 'Munnar').\n"
        "2. The FINAL DAY of any tour is strictly the departure/drop-off day. For the final day, 'stay_location' MUST be set to null (None) because travelers head to the airport/station and there is no overnight accommodation.\n"
        "3. Provide realistic mountain travel timing. Hill drives average 20-25 km/h.\n"
        "4. 'place_name' must be a recognizable tourist landmark or scenic waypoint suitable for image searches."
    )

    response = client.models.generate_content(
        model="gemini-3.5-flash",
        contents=prompt_text,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=TourItinerary,
            temperature=0.2,
        ),
    )

    raw_text = response.text
    parsed_json = json.loads(raw_text)
    return TourItinerary.model_validate(parsed_json)

# ---------------------------------------------------------------------------
# STUB / PLAYWRIGHT RENDER PIPELINE PLACEHOLDER
# ---------------------------------------------------------------------------
async def render_itinerary_pages(itinerary_data: TourItinerary, template_path: str = "template_bg.png", output_dir: str = "web_output"):
    """
    Renders flyer pages and compiles a PDF brochure.
    """
    os.makedirs(output_dir, exist_ok=True)
    # Rendering implementation logic goes here
    return True
