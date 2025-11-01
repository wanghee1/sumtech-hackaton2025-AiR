
import requests
import math
import os
import speech_recognition as sr
from gtts import gTTS
from playsound import playsound
import json                      

import config                   
from stt import start_stt        
from support import analyze_with_gemini  

# --- 1. 음성 답변(TTS) 함수 ---
def speak(text):
    try:
        print(f"[음성 답변] {text}")
        tts = gTTS(text=text, lang='ko')
        tts_file = "response.mp3"
        tts.save(tts_file)
        playsound(tts_file)
        os.remove(tts_file) # 재생 후 파일 삭제
    except Exception as e:
        print(f"[TTS 오류] {e}")

# --- 2. 장소 유형 정의 ---
place_categories = {
    # (내용 동일 - 생략)
    "자동차": ["car_dealer", "car_rental", "car_repair", "car_wash", "electric_vehicle_charging_station", "gas_station", "parking", "rest_stop"],
    "비즈니스": ["corporate_office", "farm", "ranch"],
    "문화": ["art_gallery", "art_studio", "auditorium", "cultural_landmark", "historical_place", "monument", "museum", "performing_arts_theater", "sculpture"],
    "교육": ["library", "preschool", "primary_school", "secondary_school", "university"],
    "엔터테인먼트": ["amusement_center", "amusement_park", "aquarium", "banquet_hall", "barbecue_area", "botanical_garden", "bowling_alley", "casino", "childrens_camp", "comedy_club", "community_center", "concert_hall", "convention_center", "cultural_center", "cycling_park", "dance_hall", "dog_park", "event_venue", "ferris_wheel", "garden", "hiking_area", "internet_cafe", "karaoke", "marina", "movie_rental", "movie_theater", "national_park", "night_club", "observation_deck", "off_roading_area", "opera_house", "park", "philharmonic_hall", "picnic_ground", "planetarium", "plaza", "roller_coaster", "skateboard_park", "state_park", "tourist_attraction", "video_arcade", "visitor_center", "water_park", "wedding_venue", "wildlife_park", "wildlife_refuge", "zoo"],
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

# --- 3. 장소 검색 관련 함수들 (기존 map_search.py) ---
def get_all_place_types():
    all_types = set()
    for category_list in place_categories.values():
        all_types.update(category_list)
    return sorted(list(all_types))

def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1 = math.radians(lat1); phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1); delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def search_nearby_places(place_type):
    params = {
        'location': f"{config.LAT},{config.LNG}",
        'radius': config.RADIUS,
        'type': place_type,
        'key': config.PLACES_API_KEY, 
        'language': 'ko'
    }
    try:
        response = requests.get(url="https://maps.googleapis.com/maps/api/place/nearbysearch/json", params=params)
        response.raise_for_status()
        data = response.json()

        if data['status'] == 'OK':
            results = data.get('results', [])
            if not results:
                speak(f"{config.RADIUS}미터 이내에 {place_type} 장소를 찾지 못했어요.")
                return
            
            user_lat = float(config.LAT); user_lng = float(config.LNG)
            
            # [수정] 1. 모든 장소의 거리를 계산하여 리스트에 저장
            places_with_distance = []
            for place in results:
                place_lat = place['geometry']['location']['lat']
                place_lng = place['geometry']['location']['lng']
                distance = calculate_distance(user_lat, user_lng, place_lat, place_lng)
                places_with_distance.append({
                    'name': place['name'],
                    'lat': place_lat,
                    'lng': place_lng,
                    'distance': distance
                })
            
            # [수정] 2. 거리 기준으로 오름차순 정렬
            places_with_distance.sort(key=lambda x: x['distance'])

            # [수정] 3. 가장 가까운 5개 선택
            top_5_places = places_with_distance[:5]

            # [수정] 4. JSON 형식으로 변환할 리스트 준비
            json_output = []
            print(f"--- 근처 *가장 가까운* '{place_type}' 5곳 ---")

            for i, place in enumerate(top_5_places):
                # 4-A. 요청하신 JSON 형식대로 데이터 생성
                place_data = {
                    "id": f"{place_type}_{i + 1}", # 예: "gas_station_1"
                    "type": 0,
                    "title": place['name'],
                    "latitude": place['lat'],
                    "longitude": place['lng'],
                    "color_type": 0
                }
                json_output.append(place_data)
                
                # 4-B. 터미널에도 출력 (사용자 확인용)
                print(f"  {i+1}. {place['name']} (거리: {place['distance']:.0f}m)")

            # [수정] 5. 'incident.json' 파일로 저장
            with open('incident.json', 'w', encoding='utf-8') as f:
                json.dump(json_output, f, ensure_ascii=False, indent=4)
            
            print(f"\n'{place_type}' 5곳의 정보를 'incident.json' 파일로 저장했습니다.")
            
            # [수정] 6. 요청대로 마지막 음성 안내 제거
            # speak(f"가장 가까운 곳은 {name}이며, 약 {distance_str} 거리에 있어요.")
            
        else:
            # (오류 처리 부분은 기존과 동일)
            print(f"[Google] API가 'OK'가 아닌 상태를 반환했습니다: {data['status']}")
            if 'error_message' in data:
                print(f"[Google] 오류 메시지: {data['error_message']}")
            speak("장소 검색 중 오류가 발생했어요.")
            
    except requests.exceptions.RequestException as e:
        print(f"[Google] API 요청 오류: {e}")
        speak("구글 지도 서비스에 연결하지 못했어요.")

# --- 4. [핵심] "헤이 구글"이 감지된 *후*에 실행될 함수 ---
def handle_command():
    speak("네, 말씀하세요.")
    
    r = sr.Recognizer()
    user_input = ""
    all_types_list = get_all_place_types()

    with sr.Microphone() as source:
        r.adjust_for_ambient_noise(source, duration=0.5)
        try:
            audio = r.listen(source, timeout=5, phrase_time_limit=5)
            print("[명령 인식 중...]")
            user_input = r.recognize_google(audio, language='ko-KR')
            print(f"[사용자 명령] {user_input}")
        except sr.WaitTimeoutError:
            speak("시간이 초과되었어요. 다시 불러주세요."); return
        except sr.UnknownValueError:
            speak("무슨 말씀인지 잘 모르겠어요. 다시 불러주세요."); return
        except sr.RequestError as e:
            speak("음성 인식 서비스에 연결할 수 없어요."); return
    
    if user_input:
        try:
            place_type = analyze_with_gemini(user_input, all_types_list)
            
            if place_type:
                search_nearby_places(place_type)
        except Exception as e:
            print(f"[처리 오류] {e}")
            speak("명령을 처리하는 중 오류가 발생했어요.")

def main():
    print("===== 음성 인식 장소 검색기 (Main: map_search.py) =====")
    speak("음성 인식 장소 검색기를 시작합니다.")
    
    start_stt(on_wake_word_detected_callback=handle_command)
    
    print("프로그램이 종료되었습니다.")

if __name__ == "__main__":
    main()