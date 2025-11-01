import json
import time
import os
import threading

INCIDENT_FILE_PATH = "incidents.json"
CLEANUP_INTERVAL_SECONDS = 10  # 10초마다 확인
EXPIRATION_SECONDS = 60  # 60초(1분) 지난 항목 삭제
file_lock = threading.Lock()


def cleanup_expired_incidents():
    """
    incidents.json 파일을 읽어,
    'timestamp'가 60초 이상 지난 항목을 찾아 삭제합니다.
    """

    # sup.py와 동일한 잠금을 사용하여 파일 충돌 방지
    with file_lock:
        incidents = []
        try:
            if not os.path.exists(INCIDENT_FILE_PATH):
                return  # 파일이 없으면 아무것도 안함

            with open(INCIDENT_FILE_PATH, 'r', encoding='utf-8') as f:
                incidents = json.load(f)
                if not isinstance(incidents, list):
                    return  # 형식이 리스트가 아니면 중단
        except (FileNotFoundError, json.JSONDecodeError):
            return  # 파일이 비었거나 깨졌으면 중단

        current_time = int(time.time())
        valid_incidents = []  # 살아남을 항목
        expired_count = 0  # 삭제될 항목 수

        for inc in incidents:
            timestamp = inc.get("timestamp")

            # 1. timestamp가 있고, (현재시간 - 생성시간) > 60초 이면
            if timestamp and (current_time - timestamp) > EXPIRATION_SECONDS:
                expired_count += 1  # 삭제 대상
            else:
                # 2. timestamp가 없거나 (sup.py가 아닌 다른 스크립트가 추가한 것)
                #    아직 60초가 지나지 않았으면
                valid_incidents.append(inc)  # 유지 대상

        # 3. 삭제된 항목이 1개 이상 있을 때만 파일 다시 쓰기
        if expired_count > 0:
            print(f"[Cleanup] 만료된 {expired_count}개 항목을 '{INCIDENT_FILE_PATH}'에서 제거합니다.")
            try:
                with open(INCIDENT_FILE_PATH, 'w', encoding='utf-8') as f:
                    json.dump(valid_incidents, f, ensure_ascii=False, indent=4)
            except Exception as e:
                print(f"[Cleanup] 파일 쓰기 오류: {e}")


if __name__ == "__main__":
    print("--- 'incidents.json' 임시 항목 정리기 시작 ---")
    print(f"ℹ️ {EXPIRATION_SECONDS}초 이상된 항목을 {CLEANUP_INTERVAL_SECONDS}초마다 확인합니다.")
    print("ℹ️ (Ctrl+C를 눌러 종료)")
    try:
        while True:
            cleanup_expired_incidents()
            time.sleep(CLEANUP_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\n[Cleanup] 정리기를 종료합니다.")