# ============================================================
# ODISHA FLOOD RISK & EMERGENCY EVACUATION SYSTEM
# main.py — v13.0
#
# MAIN APPLICATION
#
# CORE SERVICES
#   - Live weather
#   - Flood-risk screening
#   - Elevation
#   - Government shelters
#   - Emergency contacts
#   - Navigation
#
# CITIZEN SERVICES
#   - Registration / OTP
#   - CAPTCHA
#   - Login
#   - Profile
#   - Notification preferences
#   - Location
#   - Citizen alerts
#   - Flood reports
#   - Browser push
#
# ADMIN SERVICES
#   - Authentication
#   - Dashboard
#   - Citizen management
#   - Alert management
#   - Message campaigns
#   - Delivery
#   - Flood reports
#   - Browser push
#
# MESSAGING
#   - Gmail
#   - Twilio SMS
#   - Twilio WhatsApp
#   - Dashboard
#
# IMPORTANT
#   AI-generated emergency content must remain subject
#   to administrator approval before broadcast.
# ============================================================


# ============================================================
# STANDARD LIBRARY
# ============================================================

import math
import os
from typing import Any, Dict, Optional

from datetime import (
    datetime,
    timezone,
)

from pathlib import Path
from typing import Optional

from urllib.parse import quote


# ============================================================
# THIRD PARTY
# ============================================================

import httpx

from dotenv import load_dotenv

from fastapi import (
    FastAPI,
    HTTPException,
    Request,
)

from fastapi.middleware.cors import (
    CORSMiddleware,
)

from fastapi.responses import (
    FileResponse,
)

from fastapi.staticfiles import (
    StaticFiles,
)

from pydantic import (
    BaseModel,
    Field,
)


# ============================================================
# AI / ML FLOOD ENGINE
# ============================================================

try:
    from ai_flood_engine import prediction_dict, model_metadata
except Exception as error:
    prediction_dict = None
    model_metadata = None
    AI_ENGINE_IMPORT_ERROR = str(error)
else:
    AI_ENGINE_IMPORT_ERROR = None

try:
    from multisource import fetch_satellite, fetch_radar, radar_status, satellite_status
except Exception as error:
    fetch_satellite = None
    fetch_radar = None
    radar_status = None
    satellite_status = None
    MULTISOURCE_IMPORT_ERROR = str(error)
else:
    MULTISOURCE_IMPORT_ERROR = None


# ============================================================
# ENVIRONMENT
# ============================================================

BASE_DIR = Path(
    __file__
).resolve().parent

ENV_FILE = (
    BASE_DIR / ".env"
)

load_dotenv(
    ENV_FILE,
    override=True,
)


# ============================================================
# PATHS
# ============================================================

CITIZEN_DIR = (
    BASE_DIR / "citizen"
)

ADMIN_DIR = (
    BASE_DIR / "admin"
)

DATA_DIR = (
    BASE_DIR / "data"
)

PROJECT_INDEX = (
    BASE_DIR.parent / "index.html"
)


CITIZEN_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

ADMIN_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

DATA_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


# ============================================================
# APPLICATION CONFIGURATION
# ============================================================

APP_NAME = os.getenv(
    "EWS_APP_NAME",
    "Odisha Flood Risk & Emergency Evacuation System",
).strip()


APP_VERSION = os.getenv(
    "EWS_APP_VERSION",
    "13.0.0",
).strip()


APP_ENVIRONMENT = os.getenv(
    "EWS_ENVIRONMENT",
    "development",
).strip().lower()


try:

    REQUEST_TIMEOUT = float(
        os.getenv(
            "EWS_REQUEST_TIMEOUT",
            "12",
        )
    )

except ValueError:

    REQUEST_TIMEOUT = 12.0


try:

    OVERPASS_TIMEOUT = float(
        os.getenv(
            "EWS_OVERPASS_TIMEOUT",
            "30",
        )
    )

except ValueError:

    OVERPASS_TIMEOUT = 30.0


USER_AGENT = os.getenv(
    "EWS_USER_AGENT",
    (
        "OdishaFloodEWS/12.7 "
        "(emergency evacuation project)"
    ),
).strip()


# ============================================================
# FASTAPI APPLICATION
# ============================================================

app = FastAPI(

    title=APP_NAME,

    description=(
        "Flood-risk screening, emergency facilities, "
        "citizen reporting, emergency alerts, "
        "message campaigns, browser push notifications "
        "and evacuation support."
    ),

    version=APP_VERSION,

    docs_url="/docs",

    redoc_url="/redoc",
)


# ============================================================
# CORS
# ============================================================

CORS_RAW = os.getenv(
    "EWS_CORS_ORIGINS",
    "*",
).strip()


if CORS_RAW == "*":

    CORS_ORIGINS = ["*"]

    CORS_CREDENTIALS = False

else:

    CORS_ORIGINS = [
        item.strip()
        for item in CORS_RAW.split(",")
        if item.strip()
    ]

    CORS_CREDENTIALS = True


app.add_middleware(

    CORSMiddleware,

    allow_origins=
        CORS_ORIGINS,

    allow_credentials=
        CORS_CREDENTIALS,

    allow_methods=[
        "*"
    ],

    allow_headers=[
        "*"
    ],
)


# ============================================================
# EXTERNAL SERVICES
# ============================================================

OPEN_METEO_URL = (
    "https://api.open-meteo.com/v1/forecast"
)

OPEN_METEO_ELEVATION_URL = (
    "https://api.open-meteo.com/v1/elevation"
)

OVERPASS_SERVERS = (

    "https://overpass-api.de/api/interpreter",

    "https://overpass.kumi.systems/api/interpreter",

)

NOMINATIM_URL = (
    "https://nominatim.openstreetmap.org/search"
)

OSRM_URL = (
    "https://router.project-osrm.org/route/v1/driving"
)

# Optional upstream source feeds. Each endpoint must return JSON with the
# following optional keys: rainfall_24h_mm / rainfall_3h_mm / rainfall_1h_mm.
SATELLITE_FEED_URL = os.getenv("EWS_SATELLITE_FEED_URL", "").strip()
RADAR_FEED_URL = os.getenv("EWS_RADAR_FEED_URL", "").strip()

SOURCE_CACHE: Dict[str, Dict[str, Any]] = {}


# ============================================================
# OFFICIAL EMERGENCY CONTACTS
# ============================================================

OFFICIAL_EMERGENCY_CONTACTS = {

    "national_emergency": {

        "name":
            "Emergency Response Support System",

        "phone":
            "112",

        "description":
            "Police, fire and emergency assistance",

    },

    "police": {

        "name":
            "Police Emergency",

        "phone":
            "100",

        "description":
            "Police emergency assistance",

    },

    "ambulance": {

        "name":
            "National Ambulance Service",

        "phone":
            "108",

        "description":
            "Emergency ambulance service",

    },

    "ambulance_102": {

        "name":
            "Ambulance / Janani Service",

        "phone":
            "102",

        "description":
            "Ambulance assistance",

    },

    "fire": {

        "name":
            "Fire Emergency",

        "phone":
            "101",

        "description":
            "Fire emergency assistance",

    },

    "state_disaster": {

        "name":
            "Odisha State Emergency Operation Centre",

        "phone":
            "1070",

        "description":
            "State disaster-management assistance",

    },

    "district_emergency": {

        "name":
            "Dhenkanal District Emergency Helpline",

        "phone":
            "06762-220368",

        "description":
            "Dhenkanal district emergency assistance",

    },

    "district_emergency_short": {

        "name":
            "Dhenkanal District Emergency Helpline",

        "phone":
            "1077",

        "description":
            "Dhenkanal district emergency assistance",

    },

}


# ============================================================
# AI / ML MODEL STATUS
# ============================================================

@app.get(
    "/api/v1/disaster/model-status",
    tags=["Flood"],
)
async def disaster_model_status():
    if model_metadata is None:
        return {
            "status": "DEGRADED",
            "model": {
                "ready": False,
                "type": "unavailable",
                "error": AI_ENGINE_IMPORT_ERROR,
            },
        }

    metadata = model_metadata()
    return {
        "status": "SUCCESS",
        **metadata,
    }


# ============================================================
# GOVERNMENT SHELTERS
# ============================================================

GOVERNMENT_SHELTERS = [

    {

        "name":
            "Asurabandha Multipurpose Flood Shelter",

        "block":
            "Bhuban",

        "gp":
            "Bhusal",

        "village":
            "Asurabandha",

        "location":
            (
                "High School, Asurabandha, "
                "Bhuban, Dhenkanal, Odisha"
            ),

    },

    {

        "name":
            "Lahada Multipurpose Flood Shelter",

        "block":
            "Gondia",

        "gp":
            "Kashipur",

        "village":
            "Nahada",

        "location":
            (
                "Anchalika High School, Lahada, "
                "Gondia, Dhenkanal, Odisha"
            ),

    },

    {

        "name":
            "Khandabandha Multipurpose Flood Shelter",

        "block":
            "Gondia",

        "gp":
            "Khandabandha",

        "village":
            "Khandabandha",

        "location":
            (
                "High School, Khandabandha, "
                "Gondia, Dhenkanal, Odisha"
            ),

    },

    {

        "name":
            "Budhibili Multipurpose Flood Shelter",

        "block":
            "Kamakhyanagar",

        "gp":
            "Budhibili",

        "village":
            "Budhibili",

        "location":
            (
                "High School, Budhibili, "
                "Kamakhyanagar, Dhenkanal, Odisha"
            ),

    },

    {

        "name":
            "Kankadahad Multipurpose Flood Shelter",

        "block":
            "Kankadahad",

        "gp":
            "Kankadahad",

        "village":
            "Kankadahad",

        "location":
            (
                "Near High School, Kankadahad, "
                "Dhenkanal, Odisha"
            ),

    },

    {

        "name":
            "Khadagprasad Multipurpose Flood Shelter",

        "block":
            "Odapada",

        "gp":
            "Khadagprasad",

        "village":
            "Khadagprasad",

        "location":
            (
                "Primary School, Khadagprasad, "
                "Odapada, Dhenkanal, Odisha"
            ),

    },

    {

        "name":
            "Kuspanga Multipurpose Flood Shelter",

        "block":
            "Odapada",

        "gp":
            "Kuspanga",

        "village":
            "Kuspanga",

        "location":
            (
                "Side of UP School, Kuspanga, "
                "Odapada, Dhenkanal, Odisha"
            ),

    },

    {

        "name":
            "Panigengutia Multipurpose Flood Shelter",

        "block":
            "Parjang",

        "gp":
            "Rentapat",

        "village":
            "Panigengutia",

        "location":
            (
                "High School, Panigengutia, "
                "Parjang, Dhenkanal, Odisha"
            ),

    },

]


# ============================================================
# REQUEST MODELS
# ============================================================

class UserCoordinates(BaseModel):

    latitude: float = Field(
        ...,
        ge=-90,
        le=90,
    )

    longitude: float = Field(
        ...,
        ge=-180,
        le=180,
    )


# ============================================================
# LOCAL AI PEOPLE'S ASSISTANT
# ============================================================

class AssistantRequest(BaseModel):

    message: str = Field(..., min_length=1, max_length=2000)
    page: str = ""
    language: str = "en"
    context: Dict[str, Any] = Field(default_factory=dict)


def _assistant_language(request: AssistantRequest) -> str:
    value = (request.language or "en").strip().lower()
    if value in {"en", "hi", "or", "bn", "te"}:
        return value
    return "en"


def _assistant_answer(message: str, language: str, context: Dict[str, Any]) -> str:
    q = message.lower().strip()
    risk = str(context.get("hazard_tier") or "").upper()
    prob = context.get("flood_probability_pct")

    if language == "hi":
        if any(k in q for k in ["112", "emergency", "आपात", "मदद"]):
            return "आपातकाल में 112 पर कॉल करें। बाढ़ के पानी में वाहन न चलाएँ, बिजली के खुले तारों से दूर रहें और स्थानीय सरकारी निर्देशों का पालन करें।"
        if any(k in q for k in ["safe", "safety", "बाढ़", "फ्लड"]):
            return "बाढ़ के दौरान ऊँचे और सुरक्षित स्थान पर जाएँ, आवश्यक दवाएँ व दस्तावेज़ सुरक्षित रखें, और पानी के तेज बहाव को पार न करें।"
        if any(k in q for k in ["kit", "सामान", "आपातकालीन किट"]):
            return "आपातकालीन किट में पीने का पानी, सूखा भोजन, दवाएँ, टॉर्च, पावर बैंक, प्राथमिक उपचार और महत्वपूर्ण दस्तावेज़ रखें।"
        if any(k in q for k in ["risk", "जोखिम", "probability"]):
            extra = f" वर्तमान अनुमान {prob} और स्तर {risk}." if (prob or risk) else ""
            return "रिस्क स्तर मौसम, वर्षा, NWP, सैटेलाइट और अन्य उपलब्ध संकेतकों के संयुक्त मॉडल से आता है।" + extra
        return "मैं ओडिशा Flood EWS का सहायता सहायक हूँ। बाढ़ सुरक्षा, जोखिम, मौसम, डेटा स्रोत या पोर्टल उपयोग के बारे में पूछें।"

    if language == "or":
        if any(k in q for k in ["112", "emergency", "ଜରୁରୀ", "ସହାୟତା"]):
            return "ଜରୁରୀକାଳୀନ ସମୟରେ 112 କୁ ଫୋନ୍ କରନ୍ତୁ। ବନ୍ୟା ପାଣି ମଧ୍ୟରେ ଯାନ ଚଳାନ୍ତୁ ନାହିଁ ଏବଂ ସ୍ଥାନୀୟ ସରକାରୀ ନିର୍ଦ୍ଦେଶ ମାନନ୍ତୁ।"
        if any(k in q for k in ["flood", "ବନ୍ୟା", "ସୁରକ୍ଷା"]):
            return "ବନ୍ୟା ସମୟରେ ଉଚ୍ଚ ଏବଂ ସୁରକ୍ଷିତ ସ୍ଥାନକୁ ଯାଆନ୍ତୁ, ଦ୍ରୁତ ପାଣି ଅଟକାଇ ଅତିକ୍ରମ କରନ୍ତୁ ନାହିଁ ଏବଂ ଅଧିକାରିକ ସତର୍କତା ମାନନ୍ତୁ।"
        if any(k in q for k in ["risk", "ଜୋଖିମ", "ପ୍ରତିଶତ"]):
            extra = f" ବର୍ତ୍ତମାନ ଅନୁମାନ {prob}, ସ୍ତର {risk}." if (prob or risk) else ""
            return "ଜୋଖିମ ଅନୁମାନ ହେଉଛି ପର୍ଯ୍ୟବେକ୍ଷଣ, NWP, ସାଟେଲାଇଟ ଏବଂ ଭୌଗୋଳିକ ତଥ୍ୟର ସଂଯୁକ୍ତ ମଡେଲ ଫଳାଫଳ।" + extra
        return "ମୁଁ ଓଡ଼ିଶା Flood EWS ସହାୟକ। ବନ୍ୟା ସୁରକ୍ଷା, ଜୋଖିମ, ଆବହାବାଣୀ, ଡାଟା ସ୍ରୋତ କିମ୍ବା ପୋର୍ଟାଲ ବିଷୟରେ ପଚାରନ୍ତୁ।"

    if language == "bn":
        if "112" in q or "emergency" in q:
            return "জরুরি অবস্থায় 112-এ কল করুন। বন্যার স্রোত পার হবেন না এবং সরকারি নির্দেশনা মেনে চলুন।"
        if "flood" in q or "safety" in q:
            return "বন্যার সময় উঁচু ও নিরাপদ স্থানে যান, দ্রুত স্রোতের পানি পার হবেন না এবং সরকারি সতর্কতা অনুসরণ করুন।"
        if "risk" in q or "ঝুঁকি" in q:
            return f"বর্তমান মডেল ঝুঁকি স্তর {risk or 'UNKNOWN'} এবং সম্ভাবনা {prob or 'N/A'}।"
        return "আমি Odisha Flood EWS সহায়ক। বন্যা নিরাপত্তা, ঝুঁকি, আবহাওয়া ও ডেটা উৎস সম্পর্কে জিজ্ঞাসা করুন।"

    if language == "te":
        if "112" in q or "emergency" in q:
            return "అత్యవసర సమయంలో 112కు కాల్ చేయండి. వరద ప్రవాహాన్ని దాటవద్దు మరియు అధికారిక సూచనలు పాటించండి."
        if "flood" in q or "safety" in q:
            return "వరద సమయంలో ఎత్తైన సురక్షిత ప్రాంతానికి వెళ్లండి, వేగమైన నీటిని దాటవద్దు మరియు అధికారిక హెచ్చరికలను అనుసరించండి."
        if "risk" in q or "ప్రమాదం" in q:
            return f"ప్రస్తుత మోడల్ రిస్క్ {risk or 'UNKNOWN'}, సంభావ్యత {prob or 'N/A'}."
        return "నేను Odisha Flood EWS సహాయకుడు. వరద భద్రత, రిస్క్, వాతావరణం మరియు డేటా మూలాల గురించి అడగండి."

    # English
    if any(k in q for k in ["112", "emergency", "help"]):
        return "For an emergency, call 112. Move to a safe elevated location, avoid floodwater and downed electrical wires, and follow official Odisha disaster-management instructions."
    if any(k in q for k in ["flood", "safe", "safety"]):
        return "During flooding, move to higher ground, avoid walking or driving through fast-moving water, keep medicines and documents protected, and follow official alerts."
    if any(k in q for k in ["kit", "supplies", "prepared"]):
        return "Keep drinking water, dry food, medicines, first-aid supplies, a torch, power bank, essential documents and emergency contacts in your kit."
    if any(k in q for k in ["risk", "probability", "high risk", "critical"]):
        extra = f" Current portal estimate: {prob}; tier: {risk}." if (prob or risk) else ""
        return "The flood-risk result combines available observations, NWP forecast, satellite precipitation, terrain and other model features. It is an informational assessment, not an official evacuation order." + extra
    if any(k in q for k in ["satellite", "gpm", "imerg"]):
        return "The system currently uses NASA GPM IMERG daily precipitation as a satellite rainfall input when the local NetCDF data are available."
    if any(k in q for k in ["radar", "rainviewer"]):
        return "RainViewer radar is available for live radar visualization and metadata. The system does not invent numeric radar rainfall from image colours."
    if any(k in q for k in ["source", "dataset", "data"]):
        return "The portal combines live observational weather, NWP-compatible forecast data, NASA GPM IMERG satellite rainfall, radar metadata, terrain and model features."
    return "I’m the Odisha Flood EWS People's Assistant. Ask me about flood safety, risk interpretation, weather, satellite/radar data, datasets, emergency services, or how to use this portal."


@app.post("/api/v1/ai/assistant")
async def ai_people_assistant(request: AssistantRequest):
    language = _assistant_language(request)
    answer = _assistant_answer(request.message, language, request.context)
    return {
        "status": "SUCCESS",
        "answer": answer,
        "language": language,
        "assistant": "Odisha Flood EWS People's Assistant",
        "mode": "local_safety_assistant",
        "note": "Informational assistance only. It does not issue official evacuation orders.",
    }


# ============================================================
# HELPERS
# ============================================================

def now_iso() -> str:

    return datetime.now(
        timezone.utc
    ).isoformat()


def validate_odisha_coordinates(

    latitude: float,

    longitude: float,

) -> bool:

    return (

        17.5 <= latitude <= 22.7

        and

        81.3 <= longitude <= 87.6

    )


def haversine_km(

    lat1: float,

    lon1: float,

    lat2: float,

    lon2: float,

) -> float:

    radius = 6371.0088


    p1 = math.radians(
        lat1
    )

    p2 = math.radians(
        lat2
    )


    dlat = math.radians(
        lat2 - lat1
    )

    dlon = math.radians(
        lon2 - lon1
    )


    a = (

        math.sin(
            dlat / 2
        ) ** 2

        +

        math.cos(p1)
        *
        math.cos(p2)
        *
        math.sin(
            dlon / 2
        ) ** 2

    )


    a = max(
        0.0,
        min(
            1.0,
            a,
        ),
    )


    return (

        radius
        *
        2
        *
        math.atan2(
            math.sqrt(a),
            math.sqrt(
                1 - a
            ),
        )

    )


def google_navigation_url(

    latitude: float,

    longitude: float,

) -> str:

    destination = quote(
        f"{latitude},{longitude}"
    )


    return (

        "https://www.google.com/maps/dir/"
        "?api=1"
        f"&destination={destination}"
        "&travelmode=driving"
        "&dir_action=navigate"

    )


def google_place_url(

    name: str,

    latitude: float,

    longitude: float,

) -> str:

    query = quote(
        f"{name}, {latitude}, {longitude}"
    )


    return (

        "https://www.google.com/maps/search/"
        "?api=1"
        f"&query={query}"

    )


# ============================================================
# WEATHER
# ============================================================

async def fetch_live_weather(

    latitude: float,

    longitude: float,

) -> dict:

    params = {

        "latitude":
            latitude,

        "longitude":
            longitude,

        "current":
            (
                "temperature_2m,"
                "relative_humidity_2m,"
                "precipitation,"
                "rain,"
                "showers,"
                "weather_code,"
                "wind_speed_10m"
            ),

        "hourly":
            (
                "precipitation,"
                "rain,"
                "showers,"
                "temperature_2m,"
                "relative_humidity_2m"
            ),

        "forecast_days":
            2,

        "past_days":
            1,

        "timezone":
            "Asia/Kolkata",

    }


    async with httpx.AsyncClient(

        timeout=REQUEST_TIMEOUT,

        headers={
            "User-Agent":
                USER_AGENT
        },

    ) as client:

        response = await client.get(

            OPEN_METEO_URL,

            params=params,

        )


        response.raise_for_status()


        data = response.json()


    current = (
        data.get(
            "current"
        )
        or
        {}
    )


    hourly = (
        data.get(
            "hourly"
        )
        or
        {}
    )


    times = (
        hourly.get(
            "time"
        )
        or
        []
    )


    precipitation = [

        float(
            value
            or
            0
        )

        for value in (

            hourly.get(
                "precipitation"
            )
            or
            []

        )

    ]


    current_time = (
        current.get(
            "time"
        )
    )


    try:

        current_index = times.index(
            current_time
        )

    except (
        ValueError,
        TypeError,
    ):

        current_index = (
            len(
                precipitation
            )
            - 1
        )


    current_index = max(
        0,
        current_index,
    )


    rainfall_6h = sum(

        precipitation[
            max(
                0,
                current_index - 5,
            ):
            current_index + 1
        ]

    )


    rainfall_24h = sum(

        precipitation[
            max(
                0,
                current_index - 23,
            ):
            current_index + 1
        ]

    )


    trend = precipitation[

        max(
            0,
            current_index - 11,
        ):
        current_index + 1

    ]


    return {

        "temperature_c":
            round(
                float(
                    current.get(
                        "temperature_2m",
                        0,
                    )
                    or
                    0
                ),
                2,
            ),

        "humidity_pct":
            round(
                float(
                    current.get(
                        "relative_humidity_2m",
                        0,
                    )
                    or
                    0
                ),
                2,
            ),

        "wind_speed_kmh":
            round(
                float(
                    current.get(
                        "wind_speed_10m",
                        0,
                    )
                    or
                    0
                ),
                2,
            ),

        "weather_code":
            current.get(
                "weather_code"
            ),

        "precipitation_current_mm":
            round(
                float(
                    current.get(
                        "precipitation",
                        0,
                    )
                    or
                    0
                ),
                2,
            ),

        "rain_current_mm":
            round(
                float(
                    current.get(
                        "rain",
                        0,
                    )
                    or
                    0
                ),
                2,
            ),

        "showers_current_mm":
            round(
                float(
                    current.get(
                        "showers",
                        0,
                    )
                    or
                    0
                ),
                2,
            ),

        "rainfall_6h_mm":
            round(
                rainfall_6h,
                2,
            ),

        "rainfall_24h_mm":
            round(
                rainfall_24h,
                2,
            ),

        "hourly_precipitation":
            [
                round(
                    value,
                    2,
                )
                for value in trend
            ],

        "provider":
            "Open-Meteo",

        "live":
            True,

    }


# ============================================================
# ELEVATION
# ============================================================

async def fetch_elevation(

    latitude: float,

    longitude: float,

) -> Optional[float]:

    try:

        async with httpx.AsyncClient(

            timeout=REQUEST_TIMEOUT,

            headers={
                "User-Agent":
                    USER_AGENT
            },

        ) as client:

            response = await client.get(

                OPEN_METEO_ELEVATION_URL,

                params={

                    "latitude":
                        latitude,

                    "longitude":
                        longitude,

                },

            )


            response.raise_for_status()


            data = response.json()


        elevations = (
            data.get(
                "elevation"
            )
            or
            []
        )


        if not elevations:

            return None


        return float(
            elevations[0]
        )


    except Exception as error:

        print(
            "[ELEVATION WARNING]",
            error,
        )

        return None


# ============================================================
# FLOOD RISK
# ============================================================

def calculate_risk(

    rainfall_6h: float,

    rainfall_24h: float,

    elevation: Optional[float],

    humidity: float,

) -> dict:

    elevation = (

        30.0

        if elevation is None

        else elevation

    )


    rain_score = min(

        rainfall_24h / 200.0,

        1.0,

    )


    short_rain_score = min(

        rainfall_6h / 100.0,

        1.0,

    )


    elevation_score = max(

        0.0,

        min(

            (
                30.0
                -
                elevation
            )
            /
            30.0,

            1.0,

        ),

    )


    humidity_score = max(

        0.0,

        min(

            (
                humidity
                -
                60.0
            )
            /
            40.0,

            1.0,

        ),

    )


    risk_index = (

        rain_score
        *
        0.50

        +

        short_rain_score
        *
        0.25

        +

        elevation_score
        *
        0.15

        +

        humidity_score
        *
        0.10

    )


    probability = round(

        max(
            0.0,
            min(
                risk_index,
                1.0,
            ),
        )
        *
        100,

        2,

    )


    if probability >= 70:

        tier = "CRITICAL"

        directive = (

            "Critical flood-risk indicators detected. "
            "Follow official disaster-management instructions "
            "and evacuate if authorities order evacuation."

        )


    elif probability >= 35:

        tier = "HIGH RISK"

        directive = (

            "Elevated flood-risk indicators detected. "
            "Monitor official warnings and prepare for evacuation."

        )


    else:

        tier = "NORMAL"

        directive = (

            "No elevated risk detected by this screening model. "
            "Continue monitoring official warnings."

        )


    return {

        "flood_probability_pct":
            probability,

        "hazard_tier":
            tier,

        "operational_directive":
            directive,

        "model_type":
            "Transparent screening index",

        "calibrated":
            False,

    }


# ============================================================
# HEALTH
# ============================================================

@app.get(
    "/health",
    tags=["System"],
)
async def health():

    return {

        "status":
            "OK",

        "service":
            APP_NAME,

        "version":
            APP_VERSION,

        "environment":
            APP_ENVIRONMENT,

        "timestamp":
            now_iso(),

    }


# ============================================================
# SYSTEM INFO
# ============================================================

@app.get(
    "/api/v1/system/info",
    tags=["System"],
)
async def system_info():

    return {

        "status":
            "SUCCESS",

        "service":
            APP_NAME,

        "version":
            APP_VERSION,

        "environment":
            APP_ENVIRONMENT,

        "citizen_portal":
            "/citizen/",

        "admin_portal":
            "/admin/",

        "documentation":
            "/docs",

        "timestamp":
            now_iso(),

    }


# ============================================================
# PUSH PUBLIC KEY
# ============================================================

@app.get(
    "/api/v1/system/push-public-key",
    tags=["System"],
)
async def push_public_key():

    try:

        from push import (
            VAPID_PUBLIC_KEY,
        )

    except Exception as error:

        raise HTTPException(

            status_code=503,

            detail=(
                "Push service is unavailable."
            ),

        ) from error


    if not VAPID_PUBLIC_KEY:

        raise HTTPException(

            status_code=503,

            detail=(
                "Web Push is not configured. "
                "Set EWS_VAPID_PUBLIC_KEY in .env."
            ),

        )


    return {

        "status":
            "SUCCESS",

        "public_key":
            VAPID_PUBLIC_KEY,

    }


# ============================================================
# SYSTEM STATUS
# ============================================================

@app.get(
    "/api/v1/system/status",
    tags=["System"],
)
async def system_status():

    services = {

        "api":
            True,

        "database":
            True,

        "gmail":
            False,

        "twilio_sms":
            False,

        "twilio_whatsapp":
            False,

        "web_push":
            False,

        "turnstile":
            False,

    }


    # --------------------------------------------------------
    # Email / SMS / WhatsApp
    # --------------------------------------------------------

    try:

        from users import (

            email_available,

            sms_available,

            whatsapp_available,

        )


        services["gmail"] = bool(
            email_available()
        )


        services["twilio_sms"] = bool(
            sms_available()
        )


        services["twilio_whatsapp"] = bool(
            whatsapp_available()
        )


    except Exception as error:

        print(
            "[SYSTEM STATUS] Messaging:",
            error,
        )


    # --------------------------------------------------------
    # Web Push
    # --------------------------------------------------------

    try:

        from push import (
            push_configured,
        )


        services["web_push"] = bool(
            push_configured()
        )


    except Exception as error:

        print(
            "[SYSTEM STATUS] Push:",
            error,
        )


    # --------------------------------------------------------
    # CAPTCHA
    # --------------------------------------------------------

    try:

        from captcha import (
            turnstile_fully_configured,
        )


        services["turnstile"] = bool(
            turnstile_fully_configured()
        )


    except Exception as error:

        print(
            "[SYSTEM STATUS] CAPTCHA:",
            error,
        )


    return {

        "status":
            "SUCCESS",

        "service":
            APP_NAME,

        "version":
            APP_VERSION,

        "environment":
            APP_ENVIRONMENT,

        "services":
            services,

        "timestamp":
            now_iso(),

    }


async def fetch_optional_source(url: str, latitude: float, longitude: float) -> Dict[str, Any]:

    if not url:
        return {}

    try:
        async with httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            response = await client.get(
                url,
                params={"latitude": latitude, "longitude": longitude},
            )
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                return payload
    except Exception as error:
        print("[SOURCE FEED WARNING]", url, error)
    return {}


async def fetch_nwp_precipitation(latitude: float, longitude: float) -> Dict[str, Any]:
    # Open-Meteo forecast is used here as the NWP/forecast input. The exact
    # numerical weather model can be controlled with EWS_NWP_MODEL.
    model = os.getenv("EWS_NWP_MODEL", "best_match").strip() or "best_match"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": "precipitation",
        "forecast_days": 2,
        "timezone": "Asia/Kolkata",
        "models": model,
    }
    try:
        async with httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            response = await client.get(OPEN_METEO_URL, params=params)
            response.raise_for_status()
            data = response.json()
        hourly = data.get("hourly") or {}
        values = [float(v or 0) for v in (hourly.get("precipitation") or [])]
        return {
            "rainfall_3h_mm": round(sum(values[:3]), 2),
            "rainfall_24h_mm": round(sum(values[:24]), 2),
            "available": bool(values),
            "model": model,
        }
    except Exception as error:
        print("[NWP WARNING]", error)
        return {"available": False, "model": model}


# ============================================================
# FLOOD PREDICTION
# ============================================================

@app.get(
    "/api/v1/disaster/source-status",
    tags=["Flood"],
)
async def disaster_source_status():
    """Report health and numeric-input readiness for all flood inputs."""
    sat = await satellite_status() if satellite_status is not None else {
        "available": False,
        "provider": None,
        "numeric_rainfall_available": False,
        "error": MULTISOURCE_IMPORT_ERROR,
    }
    rad = await radar_status() if radar_status is not None else {
        "available": False,
        "provider": None,
        "numeric_rainfall_available": False,
        "error": MULTISOURCE_IMPORT_ERROR,
    }

    return {
        "status": "SUCCESS",
        "sources": {
            "observational_weather": {
                "available": True,
                "provider": "Open-Meteo live weather feed",
            },
            "nwp": {
                "available": True,
                "provider": "Open-Meteo forecast/NWP-compatible input",
                "model": os.getenv("EWS_NWP_MODEL", "best_match"),
            },
            "satellite": sat,
            "radar": rad,
        },
        "model": model_metadata() if model_metadata is not None else {"ready": False},
        "statement": "AI/ML-Based Integrated heavy rainfall Early Warning and Inundation Prediction System using Satellite, Radar, observational Weather and numerical weather prediction model data.",
        "integration_note": (
            "Satellite/radar are counted as ML inputs only when numeric rainfall "
            "values are actually available. RainViewer map metadata alone is not "
            "converted to rainfall mm."
        ),
    }


@app.get("/api/v1/disaster/prediction-method", tags=["Flood"])
async def prediction_method():
    return {
        "status": "SUCCESS",
        "flood_probability": "prototype Random Forest ML inference",
        "inundation_depth": "prototype hydrologic surrogate estimate",
        "lead_time": "prototype hydrologic surrogate estimate",
        "radar": "RainViewer radar context/visualization; numeric radar QPE accepted when a quantitative feed is configured",
        "scientific_note": "Prototype outputs are not calibrated hydraulic forecasts and should not be treated as operational government warnings."
    }


@app.post(
    "/api/v1/disaster/predict-live-location",
    tags=["Flood"],
)
async def predict_live_location(

    coords: UserCoordinates,

):

    latitude = coords.latitude

    longitude = coords.longitude


    if not validate_odisha_coordinates(

        latitude,

        longitude,

    ):

        raise HTTPException(

            status_code=400,

            detail=(
                "Coordinates are outside the "
                "approximate Odisha area."
            ),

        )


    try:

        weather = await fetch_live_weather(

            latitude,

            longitude,

        )


    except Exception as error:

        print(
            "[WEATHER ERROR]",
            error,
        )


        raise HTTPException(

            status_code=503,

            detail=(
                "Live weather service is "
                "temporarily unavailable."
            ),

        )


    elevation = await fetch_elevation(

        latitude,

        longitude,

    )


    # Multi-source feature assembly. Observational weather and NWP are live.
    # Satellite/radar adapters return numeric precipitation only when a real
    # source provides it; no fake values are injected into the ML vector.
    if fetch_satellite is not None:
        satellite = await fetch_satellite(latitude, longitude)
    else:
        satellite = {"available": False, "numeric": False, "rainfall_24h_mm": 0.0}
    if fetch_radar is not None:
        radar = await fetch_radar(latitude, longitude)
    else:
        radar = {"available": False, "numeric": False, "rainfall_1h_mm": 0.0, "rainfall_3h_mm": 0.0}
    nwp = await fetch_nwp_precipitation(latitude, longitude)

    ai_inputs = {
        "rainfall_obs_1h_mm": weather.get("precipitation_current_mm", 0.0),
        "rainfall_obs_6h_mm": weather.get("rainfall_6h_mm", 0.0),
        "rainfall_obs_24h_mm": weather.get("rainfall_24h_mm", 0.0),
        "rainfall_satellite_24h_mm": satellite.get("rainfall_24h_mm", satellite.get("rainfall_satellite_24h_mm", 0.0)),
        "rainfall_radar_1h_mm": radar.get("rainfall_1h_mm", radar.get("rainfall_radar_1h_mm", 0.0)),
        "rainfall_radar_3h_mm": radar.get("rainfall_3h_mm", radar.get("rainfall_radar_3h_mm", 0.0)),
        "nwp_rain_3h_mm": nwp.get("rainfall_3h_mm", 0.0),
        "nwp_rain_24h_mm": nwp.get("rainfall_24h_mm", 0.0),
        "temperature_c": weather.get("temperature_c", 0.0),
        "humidity_pct": weather.get("humidity_pct", 0.0),
        "wind_speed_kmh": weather.get("wind_speed_kmh", 0.0),
        "elevation_m": elevation if elevation is not None else 30.0,
        "slope_deg": 0.0,
        "soil_moisture_pct": 0.0,
        "distance_to_river_m": 1000.0,
        "observed_water_level_cm": 0.0,
        "previous_flood_flag": 0.0,
        "observational_weather_available": True,
        "satellite_available": bool(satellite.get("numeric") or satellite.get("numeric_rainfall_available")),
        "radar_available": bool(radar.get("numeric") or radar.get("numeric_rainfall_available")),
        "nwp_available": bool(nwp.get("available")),
    }

    if prediction_dict is not None:
        prediction = prediction_dict(ai_inputs)
    else:
        prediction = {
            "rainfall_early_warning": "AI engine unavailable",
            "flood_probability_pct": None,
            "hazard_tier": "UNKNOWN",
            "inundation_probability_pct": None,
            "predicted_inundation_depth_m": None,
            "lead_time_hours": None,
            "model_type": "unavailable",
            "model_version": "unavailable",
            "model_ready": False,
            "sources": {
                "observational_weather": True,
                "satellite": False,
                "radar": False,
                "nwp": False,
            },
            "feature_count": 0,
            "explanation": {
                "source_count": 1,
                "disclaimer": "AI flood engine import failed.",
                "error": AI_ENGINE_IMPORT_ERROR,
            },
        }

    # Keep legacy analytics fields for the existing frontend/admin code.
    risk = calculate_risk(
        rainfall_6h=weather["rainfall_6h_mm"],
        rainfall_24h=weather["rainfall_24h_mm"],
        elevation=elevation,
        humidity=weather["humidity_pct"],
    )


    return {

        "status":
            "SUCCESS",

        "location":
            {

                "latitude":
                    latitude,

                "longitude":
                    longitude,

            },

        "spatial_parameters":
            {

                "resolved_latitude":
                    latitude,

                "resolved_longitude":
                    longitude,

                "rainfall_current_mm":
                    weather[
                        "precipitation_current_mm"
                    ],

                "rainfall_6h_mm":
                    weather[
                        "rainfall_6h_mm"
                    ],

                "rainfall_24h_mm":
                    weather[
                        "rainfall_24h_mm"
                    ],

                "topographical_elevation_m":
                    round(

                        (
                            elevation
                            if elevation is not None
                            else 30.0
                        ),

                        2,

                    ),

            },

        "weather":
            {

                "temperature_c":
                    weather[
                        "temperature_c"
                    ],

                "humidity_pct":
                    weather[
                        "humidity_pct"
                    ],

                "wind_speed_kmh":
                    weather[
                        "wind_speed_kmh"
                    ],

                "weather_code":
                    weather[
                        "weather_code"
                    ],

            },

        "prediction":
            prediction,

        "ai_prediction":
            prediction,

        "analytics":
            {

                **risk,

                "hourly_precipitation_trend":
                    weather[
                        "hourly_precipitation"
                    ],

            },

        "data_source":
            {

                "provider":
                    weather[
                        "provider"
                    ],

                "live":
                    weather[
                        "live"
                    ],

                "retrieved_at":
                    now_iso(),

                "official_imd":
                    False,

                "prediction_engine":
                    prediction.get("model_type"),

                "source_fusion":
                    prediction.get("sources"),

                "note":
                    (
                        "Open-Meteo provides weather data. "
                        "It is not an official IMD observation."
                    ),

            },

    }


# ============================================================
# GOVERNMENT SHELTERS
# ============================================================

@app.get(
    "/api/v1/citizen/government-shelters",
    tags=["Emergency"],
)
async def government_shelters(

    latitude: float,

    longitude: float,

):

    if not validate_odisha_coordinates(

        latitude,

        longitude,

    ):

        raise HTTPException(

            status_code=400,

            detail=(
                "Coordinates are outside Odisha."
            ),

        )


    shelters = []


    for index, shelter in enumerate(

        GOVERNMENT_SHELTERS,

        start=1,

    ):

        shelters.append(

            {

                **shelter,

                "id":
                    f"SHELTER-{index:03d}",

                "type":
                    (
                        "Government Multipurpose "
                        "Flood Shelter"
                    ),

                "emergency_phone":
                    "1077",

                "source":
                    (
                        "Government of Odisha / "
                        "Dhenkanal District Disaster "
                        "Management Plan"
                    ),

                "verified_by_authority":
                    True,

                "operational_status":
                    "Not confirmed live",

            }

        )


    return {

        "status":
            "SUCCESS",

        "location":
            {

                "latitude":
                    latitude,

                "longitude":
                    longitude,

            },

        "count":
            len(shelters),

        "shelters":
            shelters,

    }


# ============================================================
# EMERGENCY CONTACTS
# ============================================================

@app.get(
    "/api/v1/citizen/emergency-contacts",
    tags=["Emergency"],
)
async def emergency_contacts():

    return {

        "status":
            "SUCCESS",

        "contacts":
            OFFICIAL_EMERGENCY_CONTACTS,

    }


# ============================================================
# NAVIGATION
# ============================================================

@app.get(
    "/api/v1/navigation",
    tags=["Navigation"],
)
async def navigation(

    latitude: float,

    longitude: float,

):

    if not validate_odisha_coordinates(

        latitude,

        longitude,

    ):

        raise HTTPException(

            status_code=400,

            detail=(
                "Coordinates are outside Odisha."
            ),

        )


    return {

        "status":
            "SUCCESS",

        "provider":
            "Google Maps",

        "navigation_url":
            google_navigation_url(

                latitude,

                longitude,

            ),

    }


# ============================================================
# USERS ROUTER
# ============================================================

try:

    from users import (
        router as users_router,
    )


    app.include_router(
        users_router
    )


    print(
        "[OK] users.py router loaded"
    )


except Exception as error:

    print(
        "[FATAL] users.py failed:",
        error,
    )

    raise


# ============================================================
# ADMIN ROUTER
# ============================================================

try:

    from admin import (
        router as admin_router,
    )


    app.include_router(
        admin_router
    )


    print(
        "[OK] admin.py router loaded"
    )


except Exception as error:

    print(
        "[FATAL] admin.py failed:",
        error,
    )

    raise


# ============================================================
# REPORTS ROUTER
# ============================================================

try:

    import reports


    reports_router = getattr(

        reports,

        "router",

        None,

    )


    reports_citizen_router = getattr(

        reports,

        "citizen_router",

        None,

    )


    reports_admin_router = getattr(

        reports,

        "admin_router",

        None,

    )


    if reports_router is not None:

        app.include_router(
            reports_router
        )


        print(
            "[OK] reports.py router loaded"
        )


    else:

        if reports_citizen_router is not None:

            app.include_router(
                reports_citizen_router
            )


            print(
                "[OK] reports citizen router loaded"
            )


        if reports_admin_router is not None:

            app.include_router(
                reports_admin_router
            )


            print(
                "[OK] reports admin router loaded"
            )


        if (

            reports_citizen_router is None

            and

            reports_admin_router is None

        ):

            print(
                "[WARNING] reports.py has no recognized router."
            )


except Exception as error:

    print(
        "[FATAL] reports.py failed:",
        error,
    )

    raise


# ============================================================
# PUSH ROUTER
# ============================================================

try:

    import push


    push_router = getattr(

        push,

        "router",

        None,

    )


    push_citizen_router = getattr(

        push,

        "citizen_router",

        None,

    )


    push_admin_router = getattr(

        push,

        "admin_router",

        None,

    )


    if push_router is not None:

        app.include_router(
            push_router
        )


        print(
            "[OK] push.py main router loaded"
        )


    else:

        if push_citizen_router is not None:

            app.include_router(
                push_citizen_router
            )


            print(
                "[OK] push citizen router loaded"
            )


        if push_admin_router is not None:

            app.include_router(
                push_admin_router
            )


            print(
                "[OK] push admin router loaded"
            )


        if (

            push_citizen_router is None

            and

            push_admin_router is None

        ):

            print(
                "[WARNING] push.py has no recognized router."
            )


except Exception as error:

    print(
        "[FATAL] push.py failed:",
        error,
    )

    raise


# ============================================================
# CAPTCHA ROUTER
# ============================================================

try:

    import captcha


    captcha_router = getattr(

        captcha,

        "router",

        None,

    )


    if captcha_router is not None:

        app.include_router(
            captcha_router
        )


        print(
            "[OK] captcha.py router loaded"
        )

    else:

        print(
            "[INFO] captcha.py exposes helpers only."
        )


except ImportError:

    print(
        "[INFO] captcha.py router not available."
    )


except Exception as error:

    print(
        "[WARNING] captcha.py:",
        error,
    )


# ============================================================
# PORTAL ROUTES
# ============================================================

@app.get(
    "/citizen/",
    include_in_schema=False,
)
async def citizen_home():

    file_path = (

        CITIZEN_DIR
        /
        "citizen.html"

    )


    if not file_path.exists():

        raise HTTPException(

            status_code=404,

            detail=(
                "Citizen portal not found."
            ),

        )


    return FileResponse(
        file_path
    )


@app.get(
    "/admin/",
    include_in_schema=False,
)
async def admin_home():

    file_path = (

        ADMIN_DIR
        /
        "admin.html"

    )


    if not file_path.exists():

        raise HTTPException(

            status_code=404,

            detail=(
                "Admin portal not found."
            ),

        )


    return FileResponse(
        file_path
    )


# ============================================================
# STATIC FILES
# ============================================================

app.mount(

    "/citizen",

    StaticFiles(

        directory=str(
            CITIZEN_DIR
        ),

        html=True,

    ),

    name="citizen",

)


app.mount(

    "/admin",

    StaticFiles(

        directory=str(
            ADMIN_DIR
        ),

        html=True,

    ),

    name="admin",

)


# ============================================================
# ROOT WEBSITE
# ============================================================

@app.get(
    "/",
    include_in_schema=False,
)
async def project_home():

    if PROJECT_INDEX.exists():

        return FileResponse(
            PROJECT_INDEX
        )


    return {

        "service":
            APP_NAME,

        "version":
            APP_VERSION,

        "status":
            "online",

        "citizen":
            "/citizen/",

        "admin":
            "/admin/",

        "docs":
            "/docs",

    }


# ============================================================
# REQUEST LOGGER
# ============================================================

@app.middleware(
    "http"
)
async def request_logger(

    request: Request,

    call_next,

):

    start = datetime.now(
        timezone.utc
    )


    try:

        response = await call_next(
            request
        )


    except Exception:

        elapsed = (

            datetime.now(
                timezone.utc
            )
            -
            start

        ).total_seconds()


        print(

            "[API ERROR]",

            request.method,

            request.url.path,

            f"({elapsed:.3f}s)",

        )


        raise


    elapsed = (

        datetime.now(
            timezone.utc
        )
        -
        start

    ).total_seconds()


    print(

        "[API]",

        request.method,

        request.url.path,

        "->",

        response.status_code,

        f"({elapsed:.3f}s)",

    )


    return response


# ============================================================
# STARTUP
# ============================================================

@app.on_event(
    "startup"
)
async def application_startup():

    print()

    print(
        "=========================================================="
    )

    print(
        " ODISHA FLOOD RISK & EMERGENCY EVACUATION SYSTEM"
    )

    print(
        "=========================================================="
    )

    print(
        f"Version     : {APP_VERSION}"
    )

    print(
        f"Environment : {APP_ENVIRONMENT}"
    )

    print(
        f"Citizen     : http://127.0.0.1:8000/citizen/"
    )

    print(
        f"Admin       : http://127.0.0.1:8000/admin/"
    )

    print(
        f"Docs        : http://127.0.0.1:8000/docs"
    )

    print(
        "----------------------------------------------------------"
    )


    # --------------------------------------------------------
    # Citizen DB
    # --------------------------------------------------------

    try:

        from users import (
            init_db,
        )


        init_db()


        print(
            "[OK] Citizen database initialized"
        )


    except Exception as error:

        print(
            "[FAIL] Citizen database:",
            error,
        )

        raise


    # --------------------------------------------------------
    # Admin DB
    # --------------------------------------------------------

    try:

        from admin import (
            init_admin_tables,
        )


        init_admin_tables()


        print(
            "[OK] Admin database initialized"
        )


    except Exception as error:

        print(
            "[FAIL] Admin database:",
            error,
        )

        raise


    # --------------------------------------------------------
    # Flood Reports DB
    # --------------------------------------------------------

    try:

        import reports


        initialize_reports = getattr(

            reports,

            "init_reports_table",

            None,

        )


        if initialize_reports is not None:

            initialize_reports()


        print(
            "[OK] Flood reports initialized"
        )


    except Exception as error:

        print(
            "[FAIL] Flood reports:",
            error,
        )

        raise


    # --------------------------------------------------------
    # Push DB
    # --------------------------------------------------------

    try:

        import push


        initialize_push = getattr(

            push,

            "init_push_table",

            None,

        )


        if initialize_push is not None:

            initialize_push()


        print(
            "[OK] Push subscriptions initialized"
        )


    except Exception as error:

        print(
            "[FAIL] Push subscriptions:",
            error,
        )

        raise


    # --------------------------------------------------------
    # Messaging status
    # --------------------------------------------------------

    try:

        from users import (

            email_available,

            sms_available,

            whatsapp_available,

        )


        print(
            "----------------------------------------------------------"
        )


        print(

            "Gmail SMTP  :",

            (

                "READY"

                if email_available()

                else

                "NOT CONFIGURED"

            ),

        )


        print(

            "Twilio SMS  :",

            (

                "READY"

                if sms_available()

                else

                "NOT CONFIGURED"

            ),

        )


        print(

            "WhatsApp    :",

            (

                "READY"

                if whatsapp_available()

                else

                "NOT CONFIGURED"

            ),

        )


    except Exception as error:

        print(

            "[CONFIG WARNING] Messaging:",

            error,

        )


    # --------------------------------------------------------
    # Push status
    # --------------------------------------------------------

    try:

        from push import (
            push_configured,
        )


        print(

            "Web Push    :",

            (

                "READY"

                if push_configured()

                else

                "NOT CONFIGURED"

            ),

        )


    except Exception:

        print(
            "Web Push    : NOT CONFIGURED"
        )


    # --------------------------------------------------------
    # CAPTCHA status
    # --------------------------------------------------------

    try:

        from captcha import (
            turnstile_fully_configured,
        )


        print(

            "Turnstile   :",

            (

                "READY"

                if turnstile_fully_configured()

                else

                "NOT CONFIGURED"

            ),

        )


    except Exception:

        print(
            "Turnstile   : NOT CONFIGURED"
        )


    print(
        "----------------------------------------------------------"
    )


    print(
        "API         : READY"
    )

    print(
        "Citizen     : READY"
    )

    print(
        "Admin       : READY"
    )

    print(
        "Reports     : READY"
    )

    print(
        "Push        : READY"
    )


    print(
        "=========================================================="
    )

    print()


# ============================================================
# SHUTDOWN
# ============================================================

@app.on_event(
    "shutdown"
)
async def application_shutdown():

    print(
        "[SHUTDOWN] Odisha Flood EWS stopped."
    )


# ============================================================
# DIRECT EXECUTION
# ============================================================

if __name__ == "__main__":

    import uvicorn


    server_host = os.getenv(

        "EWS_HOST",

        "127.0.0.1",

    ).strip()


    try:

        server_port = int(

            os.getenv(

                "EWS_PORT",

                "8000",

            )

        )


    except ValueError:

        server_port = 8000


    uvicorn.run(

        "main:app",

        host=server_host,

        port=server_port,

        reload=(

            APP_ENVIRONMENT
            ==
            "development"

        ),

    )