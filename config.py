
import os
from dotenv import load_dotenv

load_dotenv()

GENAI_API_KEY = os.getenv('GENAI_API_KEY')
if not GENAI_API_KEY:
    raise ValueError("GENAI_API_KEY가 .env 파일에 없습니다.")

PLACES_API_KEY = os.getenv('PLACES_API_KEY')
if not PLACES_API_KEY:
    raise ValueError("PLACES_API_KEY가 .env 파일에 없습니다.")

PICOVOICE_ACCESS_KEY = os.getenv('PICO_KEY')
if not PICOVOICE_ACCESS_KEY:
    raise ValueError("PICO_KEY가 .env 파일에 없습니다.")

LAT = "37.2972846"
LNG = "126.835436"
RADIUS = 800