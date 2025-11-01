import time
import google.generativeai as genai
import requests
import math
from dotenv import load_dotenv
import os
import json         # ⭐️ [추가] JSON 파일 수정을 위해
import uuid         # ⭐️ [추가] 랜덤 ID 생성을 위해
import threading    # ⭐️ [추가] 파일 동시 접근을 막기 위해

load_dotenv()

GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')

if not GOOGLE_API_KEY:
    raise ValueError("GOOGLE_API_KEY 환경 변수가 설정되지 않았습니다. .env 파일을 확인하세요.")


GOOGLE_MAPS_KEY = os.getenv('GOOGLE_MAPS_KEY')

if not GOOGLE_MAPS_KEY:
    raise ValueError("GOOGLE_MAPS_KEY 환경 변수가 설정되지 않았습니다. .env 파일을 확인하세요.")


genai.configure(api_key=GOOGLE_API_KEY)  # 제미나이 API 인증

LAT = "37.2972846"  # 임의의 위치 (안산시 부근)
LNG = "126.835436"  # 임의의 위치 (안산시 부근)
RADIUS = 800  # 검색 반경 (미터 단위)

# ⭐️ [추가] JSON 파일 경로 및 파일 접근 잠금
INCIDENT_FILE_PATH = "incidents.json"
file_lock = threading.Lock()

# --- 2. 장소 유형 배열 정의 ---
place_categories = {
    "자동차": ["car_dealer", "car_rental", "car_repair", "car_wash", "electric_vehicle_charging_station", "gas_station",
            "parking", "rest_stop"],
    "비즈니스": ["corporate_office", "farm", "ranch"],
    "문화": ["art_gallery", "art_studio", "auditorium", "cultural_landmark", "historical_place", "monument", "museum",
           "performing_arts_theater", "sculpture"],
    "교육": ["library", "preschool", "primary_school", "secondary_school", "university"],
    "엔터테인먼트": ["amusement_center", "amusement_park", "aquarium", "banquet_hall", "barbecue_area", "botanical_garden",
               "bowling_alley", "casino", "childrens_camp", "comedy_club", "community_center", "concert_hall",
               "convention_center", "cultural_center", "cycling_park", "dance_hall", "dog_park", "event_venue",
               "ferris_wheel", "garden", "hiking_area", "internet_cafe", "karaoke", "marina", "movie_rental",
               "movie_theater", "national_park", "night_club", "observation_deck", "off_roading_area", "opera_house",
               "park", "philharmonic_hall", "picnic_ground", "planetarium", "plaza", "roller_coaster",
               "skateboard_park", "state_park", "tourist_attraction", "video_arcade", "visitor_center", "water_park",
               "wedding_venue", "wildlife_park", "wildlife_refuge", "zoo"],
    "시설": ["public_bath", "public_bathroom", "stable"],
    "금융": ["atm", "bank"],
    "식음료": ["restaurant", "cafe", "fast_food_restaurant", "bar", "convenience_store"],
    "지역": ["locality", "postal_code", "city_hall", "fire_station"],
    "건강": ["hospital", "pharmacy", "doctor", "gym", "drugstore"],
    "주택": ["apartment_building", "condominium_complex"],
    "숙박시설": ["hotel", "hostel", "motel"],
    "자연": ["beach", "park", "lake"],
    "교통": ["airport", "bus_station", "train_station"]
}

# 모델 로드
model = genai.GenerativeModel('gemini-2.5-flash') # 1.5-flash (2.5-flash는 아직 존재하지 않음)


# --- 2.5. 모든 장소 유형을 하나의 리스트로 만들기 ---
def get_all_place_types(categories):
    all_types = set()
    for category_list in categories.values():
        all_types.update(category_list)
    return sorted(list(all_types))


# --- 3. 제미나이 API를 사용하여 사용자 텍스트 분석 ---
def analyze_request_with_gemini(user_input, all_types_list):
    start_time = time.time()
    all_types_string = ", ".join(all_types_list)

    prompt = f"""
    사용자의 요청을 분석하여 다음 Google Places API 유형 목록에서 가장 적절한 **한 가지** 유형을 골라주세요.

    사용자 요청: "{user_input}"

    [유효한 장소 유형 목록]
    {all_types_string}

    응답은 반드시 목록에 있는 유형 **하나만** 포함해야 합니다. (예: "gas_station", "hospital", "park" 등)
    다른 설명이나 문장은 절대 추가하지 마세요.
    """

    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                candidate_count=1,
                temperature=0.1
            )
        )
        end_time = time.time()
        print(f"실행 시간: {end_time - start_time:.2f} 초")

        place_type = response.text.strip().replace("'", "").replace('"', '')
        print(f"제미나이 분석 결과 (장소 유형): {place_type}")

        if place_type not in all_types_list:
            print(f"경고: AI가 유효하지 않은 유형({place_type})을 반환했습니다. 'restaurant'로 대체합니다.")
            return "restaurant"
        return place_type

    except Exception as e:
        print(f"Gemini API 오류 발생: {e}")
        return "restaurant"


# --- 4. 두 지점 간 거리 계산 (Haversine 공식) ---
def calculate_distance(lat1, lon1, lat2, lon2):
    """
    두 개의 위도, 경도 좌표 사이의 거리를 미터(m) 단위로 반환합니다.
    """
    R = 6371000  # 지구 반지름 (미터)
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2.0) ** 2 + \
        math.cos(phi1) * math.cos(phi2) * \
        math.sin(delta_lambda / 2.0) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    distance = R * c
    return distance


# ⭐️ --- [추가] 5. 찾은 장소를 incidents.json에 추가하는 함수 ---
def add_temporary_incident(place_name, lat, lng):
    """
    찾은 장소를 incidents.json에 요청하신 양식으로 추가합니다.
    (cleanup.py가 삭제할 수 있도록 timestamp를 포함합니다.)
    """
    new_incident = {
        "id": str(uuid.uuid4()),  # "random?": 고유 ID 생성
        "type": 0,
        "title": place_name,      # "가게 이름": 찾은 장소 이름
        "latitude": lat,
        "longitude": lng,
        "color_type": 0,
        "timestamp": int(time.time()) # ⭐️ 1분 뒤 삭제를 위한 현재 시간
    }

    # ⭐️ 파일 잠금을 사용하여 안전하게 읽고 쓰기
    with file_lock:
        incidents = []
        try:
            # 1. 기존 파일 읽기
            if os.path.exists(INCIDENT_FILE_PATH):
                with open(INCIDENT_FILE_PATH, 'r', encoding='utf-8') as f:
                    incidents = json.load(f)
                    if not isinstance(incidents, list): # 혹시 파일이 깨졌으면
                        incidents = []
        except (FileNotFoundError, json.JSONDecodeError):
            incidents = [] # 파일이 없거나 비어있으면 새 리스트로 시작

        # 2. 새 항목 추가
        incidents.append(new_incident)

        # 3. 전체 리스트 다시 쓰기
        try:
            with open(INCIDENT_FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump(incidents, f, ensure_ascii=False, indent=4)
            print(f"[+] '{place_name}'을(를) '{INCIDENT_FILE_PATH}'에 추가했습니다.")
        except Exception as e:
            print(f"[!] '{INCIDENT_FILE_PATH}' 파일 쓰기 오류: {e}")


# --- 6. (수정) Google Places API 요청 및 가장 가까운 곳 찾기 ---
def search_nearby_places(place_type):
    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {
        'location': f"{LAT},{LNG}",
        'radius': RADIUS,
        'type': place_type,
        'key': GOOGLE_MAPS_KEY,
        'language': 'ko'
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        if data['status'] == 'OK':
            results = data.get('results', [])

            if not results:
                print(f"--- '{place_type}' 검색 결과 ---")
                print(f"{RADIUS}m 이내에 검색 결과가 없습니다.")
                return

            user_lat = float(LAT)
            user_lng = float(LNG)

            closest_place = None
            min_distance = float('inf')

            for place in results:
                place_lat = place['geometry']['location']['lat']
                place_lng = place['geometry']['location']['lng']
                distance = calculate_distance(user_lat, user_lng, place_lat, place_lng)

                if distance < min_distance:
                    min_distance = distance
                    closest_place = place

            print(f"--- '{LAT}, {LNG}' 근처 {RADIUS}m 이내 *가장 가까운* '{place_type}' ---")
            if closest_place:
                name = closest_place['name']
                location = closest_place['geometry']['location']
                lat = location['lat']
                lng = location['lng']

                print(f"이름: {name}")
                print(f"  GPS: {lat}, {lng}")
                print(f"  거리: {min_distance:.2f} m")

                # ⭐️ --- [수정된 부분] --- ⭐️
                # 찾은 장소를 incidents.json에 추가
                add_temporary_incident(name, lat, lng)
                # ⭐️ --- [수정 끝] --- ⭐️

        else:
            print(f"API 오류 또는 검색 결과 없음: ({data['status']})")
            if 'error_message' in data:
                print(f"오류 메시지: {data['error_message']}")

    except requests.exceptions.RequestException as e:
        print(f"API 요청 오류: {e}")
    except Exception as e:
        print(f"알 수 없는 오류 발생: {e}")


# --- 7. 메인 함수 ---
def main():
    all_types = get_all_place_types(place_categories)
    user_input = input("어떤 장소를 찾고 싶으신가요?: ")

    if user_input:
        place_type = analyze_request_with_gemini(user_input, all_types)
        if place_type:
            search_nearby_places(place_type)


if __name__ == "__main__":
    main()