import socket
import json
import time
import requests
import threading

# --- 설정 ---
APP_SERVER_URL = "http://127.0.0.1:8070"  # app.py 서버 주소
LISTENER_PORT = 9999  # gps_sender.py 방송 포트
UPDATE_INTERVAL_SEC = 1  # 갱신 주기 (10초)
DEFAULT_RADIUS_KM = 10  # incidents.json에 저장할 기본 반경 (km)

# --- 전역 변수 ---
# gps_sender.py의 초기 위치로 시작
latest_gps = {"lat": 37.296143, "lon": 126.840495}
gps_lock = threading.Lock()

def udp_listener_thread():
    """UDP 9999 포트에서 GPS 방송을 수신하여 latest_gps를 갱신하는 스레드"""
    global latest_gps

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # ⭐️ [중요] tts.py와 포트를 공유하기 위한 옵션
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        s.bind(("", LISTENER_PORT))
    except OSError as e:
        print(f"[UPDATER] 오류: {LISTENER_PORT} 포트 바인딩 실패. {e}")
        print(" -> tts.py가 이 옵션 없이 이미 실행 중일 수 있습니다.")
        return

    print(f"[UPDATER] UDP 리스너 시작 (포트 {LISTENER_PORT})...")

    while True:
        try:
            data, _ = s.recvfrom(1024)
            gps_data = json.loads(data.decode('utf-8'))
            lat = float(gps_data.get("latitude"))
            lon = float(gps_data.get("longitude"))

            with gps_lock:
                latest_gps['lat'] = lat
                latest_gps['lon'] = lon

            # (디버깅용) print(f"[UPDATER] GPS 수신: {lat}, {lon}")
        except Exception:
            pass  # 파싱 오류 등 무시


def main_updater_loop():
    """10초마다 app.py의 /api/nearby를 호출하여 incident.json을 갱신"""
    global latest_gps

    print(f"[UPDATER] {UPDATE_INTERVAL_SEC}초마다 '{APP_SERVER_URL}/api/nearby'를 호출합니다.")

    while True:
        # 1. 10초 대기
        time.sleep(UPDATE_INTERVAL_SEC)

        # 2. 현재 GPS 좌표 읽기
        with gps_lock:
            current_lat = latest_gps['lat']
            current_lon = latest_gps['lon']

        if current_lat is None or current_lon is None:
            print(f"[UPDATER] 아직 GPS 신호를 받지 못했습니다. 대기합니다...")
            continue

        # 3. app.py 서버에 /api/nearby 호출 (파일 쓰기 트리거)
        try:
            url = f"{APP_SERVER_URL}/api/nearby"
            params = {
                "latitude": current_lat,
                "longitude": current_lon,
                "radius": DEFAULT_RADIUS_KM  # 갱신할 반경
            }

            response = requests.get(url, params=params, timeout=5)
            response.raise_for_status()

            # app.py의 /api/nearby는 JSON 메시지를 반환함
            result_msg = response.json().get("message", "OK")
            print(f"[{time.strftime('%H:%M:%S')}] [UPDATER] 갱신 성공: {result_msg}")

        except requests.RequestException as e:
            print(f"[{time.strftime('%H:%M:%S')}] [UPDATER] app.py 호출 실패: {e}")


if __name__ == "__main__":
    # 1. UDP 수신 스레드 시작
    listener = threading.Thread(target=udp_listener_thread, daemon=True)
    listener.start()

    # 2. 메인 루프 (HTTP 호출) 시작
    try:
        main_updater_loop()
    except KeyboardInterrupt:
        print("[UPDATER] 종료합니다.")