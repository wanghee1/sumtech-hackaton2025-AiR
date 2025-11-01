import google.generativeai as genai
import config 

# --- 1. 모델 설정 (파일 로드 시 1회 실행) ---
genai.configure(api_key=config.GENAI_API_KEY)
try:
    model = genai.GenerativeModel('gemini-2.0-flash')
except Exception:
    model = genai.GenerativeModel('gemini-1.5-flash-latest')

# --- 2. map_search.py가 호출할 함수 ---
def analyze_with_gemini(user_input, all_types_list):
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
            generation_config=genai.types.GenerationConfig(candidate_count=1, temperature=0.1)
        )
        place_type = response.text.strip().replace("'", "").replace('"', '')
        print(f"[Gemini] 분석된 장소 유형: {place_type}")

        if place_type not in all_types_list:
            print(f"[Gemini] 경고: AI가 유효하지 않은 유형({place_type})을 반환했습니다. 'restaurant'로 대체합니다.")
            return "restaurant"
        return place_type
    except Exception as e:
        print(f"[Gemini] API 오류 발생: {e}")
        return "restaurant"