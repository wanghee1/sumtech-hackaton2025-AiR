import google.generativeai as genai
import os
from dotenv import load_dotenv  # ⭐️ [추가] 1. dotenv 라이브러리 임포트

# ⭐️ [추가] 2. .env 파일에서 환경 변수를 불러옵니다
load_dotenv()

# ⭐️ [수정] 3. 'YOUR_API_KEY' 대신 os.getenv()를 사용해 키를 불러옵니다
API_KEY = os.getenv('GOOGLE_API_KEY')

if not API_KEY:
    raise ValueError("GOOGLE_API_KEY 환경 변수가 설정되지 않았습니다. .env 파일을 확인하세요.")

# 4. API 키로 클라이언트 설정
genai.configure(api_key=API_KEY)

# 5. 사용할 모델 선택
model = genai.GenerativeModel('gemini-2.0-flash')

# 6. 콘텐츠 생성 요청
try:
    response = model.generate_content("한양대 에리카에서 가장 가까운 주유소의 위도,경도 좌표를 알려줘")
    print(response.text)

except Exception as e:
    print(f"API 호출 중 오류가 발생했습니다: {e}")