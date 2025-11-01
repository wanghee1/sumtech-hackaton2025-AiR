import os
from google.cloud import aiplatform
import pyttsx3
import requests
import math

# Google Cloud 인증 설정 (서비스 계정 키 경로 설정)
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "C:/Users/gmldn/Desktop/School_hs/2025_SUMTECH+HACKATON/your-service-account-key.json"  # 실제 경로로 수정

# Google Cloud 프로젝트 및 위치 설정
project_id = "YOUR_PROJECT_ID"  # Google Cloud 프로젝트 ID
location = "us-central1"  # 예시로 us-central1 사용
endpoint_id = "YOUR_ENDPOINT_ID"  # 실제 엔드포인트 ID 사용

# Vertex AI 클라이언트 설정
aiplatform.init(project=project_id, location=location)

# 엔드포인트에서 예측 실행
endpoint = aiplatform.Endpoint(f"projects/{project_id}/locations/{location}/endpoints/{endpoint_id}")

# pyttsx3 (음성 출력)
tts = pyttsx3.init()

def speak(text):
    tts.say(text)
    tts.runAndWait()

# 5. **위도와 경도를 사용하여 두 지점 간의 거리 계산**
def haversine(lat1, lon1, lat2, lon2):
    R = 6371  # 지구 반경 (킬로미터)
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    distance = R * c  # 킬로미터 단위
    return distance

# 6. Google Places API로 주변 장소 검색하기
def get_nearby_places(user_lat, user_lon, place_type="store"):
    API_KEY = "YOUR_GOOGLE_API_KEY"  # 실제 Google API Key로 변경
    url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={user_lat},{user_lon}&radius=1000&type={place_type}&keyword={place_type}&key={API_KEY}"
    
    response = requests.get(url)
    data = response.json()

    places = []
    if data["status"] == "OK":
        for result in data["results"]:
            name = result.get("name")
            address = result.get("vicinity")
            places.append(f"{name} - {address}")
    else:
        places.append("주변에 찾을 수 있는 장소가 없습니다.")
    
    return places

# 7. 질문을 받아서 제미나이 AI로 답변을 받는 함수
def ask_question(user_lat, user_lon):
    question = input("질문을 입력해주세요: ")  # 터미널에서 질문 받기
    print(f"질문: {question}")

    # 제미나이 API로 질문에 대한 답변 얻기
    response = endpoint.predict(instances=[{"content": question}])
    answer = response.predictions[0]["content"]

    print(f"답변: {answer}")
    speak(answer)  # 음성 출력 (나중에 사용)

# 메인 루프 (실행)
def main():
    user_lat = 37.7750  # 예시 사용자 위치 (위도)
    user_lon = 127.0740  # 예시 사용자 위치 (경도)
    
    while True:
        ask_question(user_lat, user_lon)  # 질문을 받는다
        time.sleep(1)  # 대기 후 다시 루프

if __name__ == "__main__":
    main()
