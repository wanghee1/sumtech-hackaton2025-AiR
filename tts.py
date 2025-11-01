import argparse, time, json, requests, math, sys
import pyttsx3
import re
import socket
# ⭐️ multiprocessing을 사용합니다.
from multiprocessing import Queue, Process

# --- [TTS 임포트용 함수] ---
_imported_engine = None

def _get_imported_engine():
    global _imported_engine
    if _imported_engine is None:
        try:
            _imported_engine = pyttsx3.init()
            _imported_engine.setProperty("rate", 160)
        except Exception as e:
            print(f"[TTS] 임포트용 엔진 초기화 실패: {e}", file=sys.stderr)
            return None
    return _imported_engine


def speak(text_to_say: str):
    try:
        engine = _get_imported_engine()
        if engine:
            engine.say(text_to_say)
            engine.runAndWait()
        else:
            print(f"[TTS.speak] 엔진이 없어 말할 수 없음: {text_to_say}", file=sys.stderr)
    except Exception as e:
        print(f"[TTS.speak] 말하기 오류: {e}", file=sys.stderr)


# --- [임포트용 끝] ---


# --- [메인 스크립트용 함수] ---

def lane_to_korean(lane_text: str) -> str:
    if not lane_text:
        return ""
    lane_text = str(lane_text)
    num_map = {"1": "일", "2": "이", "3": "삼", "4": "사", "5": "오"}
    for num, kor in num_map.items():
        lane_text = lane_text.replace(num + "차로", kor + "차로")
    return lane_text


def build_sentence(inc):
    # 1. 거리 문구 생성
    dist_m = int(round((inc.get("distance_km") or 0) * 1000))
    if dist_m < 30:
        dist_phrase = "바로 앞"
    elif dist_m < 100:
        dist_phrase = f"{dist_m}미터 앞"
    elif dist_m < 1000:
        dist_phrase = f"{(dist_m // 10) * 10}미터 앞"
    else:
        km = inc.get("distance_km") or 0
        dist_phrase = f"{km:.1f}킬로미터 앞"

    # 2. 차로 문구 생성
    raw_lane = (inc.get("lane") or "").strip()
    lane = lane_to_korean(raw_lane)
    lane_phrase = f"{lane}에서 " if lane else ""

    # 3. app.py가 보낸 typeCd와 title을 기반으로 상황별 문장 생성
    type_cd = str(inc.get("typeCd", ""))
    title = (inc.get("title") or "").strip()

    if type_cd == "2":  # 공사
        return f"{dist_phrase} {lane_phrase}공사 구간입니다. {title}."
    if type_cd == "5":  # 통제
        return f"{dist_phrase} {lane_phrase}통행이 통제되고 있습니다. {title}."
    if type_cd == "1":  # 사고
        if "고장" in title:
            return f"{dist_phrase} {lane_phrase}고장 차량이 있습니다. {title}."
        return f"{dist_phrase} {lane_phrase}{title} 사고가 발생했습니다."
    return f"{dist_phrase} {lane_phrase}{title} 돌발 상황이 발생했습니다."


def fetch_nearby(server, userid=None, lat=None, lon=None, radius=5.0, k=5, timeout=8):
    base = server.rstrip("/") + "/api/tts_nearby"
    if userid:
        url = f"{base}?userid={userid}&radius={radius}&k={k}"
    else:
        url = f"{base}?lat={lat}&lon={lon}&radius={radius}&k={k}"
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()


def tts_worker(tts_queue, args):
    """
    Queue에서 문장을 꺼내 TTS로 재생하는 전용 프로세스
    """
    print("[TTS_WORKER] TTS 전용 프로세스 시작.")
    try:
        # TTS 엔진은 반드시 이 프로세스 *안에서* 초기화해야 합니다.
        engine = pyttsx3.init()
        if args.voice is not None:
            selected = None
            for v in engine.getProperty("voices"):
                if args.voice in (v.id, getattr(v, "name", "")):
                    selected = v.id
                    break
            if selected:
                engine.setProperty("voice", selected)
            else:
                print(f"[WARN] voice '{args.voice}' 미발견. 기본 음성 사용.")
        if args.rate is not None:
            engine.setProperty("rate", int(args.rate))
        else:
            engine.setProperty("rate", 160)
        if args.volume is not None:
            engine.setProperty("volume", max(0.0, min(1.0, float(args.volume))))
    except Exception as e:
        print(f"[TTS_WORKER] TTS 엔진 초기화 실패: {e}")
        return

    while True:
        try:
            sentence = tts_queue.get()
            if sentence is None:
                break
            print(f"[TTS_WORKER] 🔊 재생 시작: {sentence}")
            engine.say(sentence)
            engine.runAndWait()
            print(f"[TTS_WORKER] 🛑 재생 완료.")
        except Exception as e:
            print(f"[TTS_WORKER] 재생 중 오류: {e}")


def main():
    ap = argparse.ArgumentParser(description="Listen for UDP GPS, poll /api/nearby, and speak incidents via TTS.")
    ap.add_argument("--server", default="http://127.0.0.1:8070", help="메인 서버(app.py) URL")
    ap.add_argument("--radius", type=float, default=0.5, help="반경 km (예: 0.03 = 30m)")
    ap.add_argument("--k", type=int, default=10, help="최대 N건")
    ap.add_argument("--cooldown", type=float, default=300.0, help="같은 사건 재알림 쿨다운(초)")
    ap.add_argument("--voice", default=None, help="TTS 음성 id(선택)")
    ap.add_argument("--rate", type=int, default=None, help="TTS 말하기 속도(기본 유지)")
    ap.add_argument("--volume", type=float, default=None, help="TTS 볼륨 0.0~1.0")
    args = ap.parse_args()

    tts_queue = Queue()
    worker_process = Process(target=tts_worker, args=(tts_queue, args), daemon=True)
    worker_process.start()

    # --- 1. UDP 소켓 설정 ---
    listener_port = 9999
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("", listener_port))
    except OSError as e:
        print(f"오류: {listener_port} 포트 바인딩 실패. {e}")
        print("다른 스크립트가 이미 이 포트를 사용 중인지 확인하세요.")
        sys.exit(1)

    print(f"--- 실시간 TTS 알림 서비스 시작 ---")
    print(f"UDP 포트 {listener_port}에서 GPS 브로드캐스트 수신 대기 중...")
    print(f"수신된 GPS로 {args.server} 서버에 {args.radius}km 반경 요청을 보냅니다.")
    print(f"알림 쿨다운: {args.cooldown}초")

    last_spoken_at = {}

    # --- 3. 메인 리스너 루프 ---
    try:
        while True:
            # 3-A. GPS 데이터 수신
            try:
                udp_data, addr = s.recvfrom(1024)
                gps_data = json.loads(udp_data.decode('utf-8'))
                user_lat = float(gps_data.get("latitude"))
                user_lon = float(gps_data.get("longitude"))
            except json.JSONDecodeError:
                print(f"[{time.strftime('%H:%M:%S')}] 수신한 GPS 데이터가 JSON 형식이 아닙니다.")
                continue
            except Exception as e:
                print(f"[{time.strftime('%H:%M:%S')}] UDP 수신 오류: {e}")
                continue

            # 3-B. app.py 서버에 데이터 요청
            try:
                data = fetch_nearby(args.server,
                                    lat=user_lat, lon=user_lon,
                                    radius=args.radius, k=args.k, timeout=2.0)
                incidents = data.get("incidents") or []
                now = time.time()

                # ⭐️ --- [수정된 3-C 로직] --- ⭐️
                # "아직 알리지 않은" 가장 가까운 1건만 찾아서 알리고,
                # 나머지는 다음 GPS 수신 시 알림

                # incidents 리스트는 app.py가 이미 거리순으로 정렬해서 줌
                for inc in incidents:
                    inc_id = inc.get("id") or f"{inc.get('lat')}_{inc.get('lon')}"
                    last = last_spoken_at.get(inc_id, 0)

                    if now - last < args.cooldown:
                        # ⭐️ 이미 알렸거나 쿨다운 중이면 건너뛰기
                        continue

                        # ⭐️ 쿨다운이 지난 첫 번째 항목(가장 가까운 항목)을 찾음
                    sentence = build_sentence(inc)
                    print(
                        f"\n[{time.strftime('%H:%M:%S')}] GPS ({user_lat:.5f}, {user_lon:.5f}) -> {args.radius}km 이내 신규 감지!")
                    print(f"[MAIN] ➡️ TTS 큐에 추가: {sentence}")

                    tts_queue.put(sentence)  # ⭐️ 큐에 1건만 추가
                    last_spoken_at[inc_id] = now  # ⭐️ 알렸다고 기록

                    # ⭐️ 1건만 알리기 위해 for 루프를 탈출
                    break
                # ⭐️ --- [수정 끝] --- ⭐️

            except requests.RequestException as e:
                print(f"[{time.strftime('%H:%M:%S')}] HTTP 오류: {args.server} 호출 실패: {e}")
            except Exception as e:
                print(f"[{time.strftime('%H:%M:%S')}] 메인 루프 오류: {e}")

    except KeyboardInterrupt:
        print("\n[TTS] stopped.")
    finally:
        s.close()
        if worker_process:
            worker_process.terminate()  # 프로세스 종료


if __name__ == "__main__":
    # ⭐️ [중요] multiprocessing을 사용할 경우 Windows에서 필요
    main()