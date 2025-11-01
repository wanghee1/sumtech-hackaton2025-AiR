import socket
import json
import argparse
import time
import random
import requests

# --- 설정 ---
GPS_SERVICE_DATA_ENDPOINT = "http://localhost:8000/data"  # gps_service.py의 /data 엔드포인트
LISTENER_BROADCAST_PORT = 9999  # ⭐️ (추가) TTS 청취자용 브로드캐스트 포트


def send_gps_via_udp(target_node_id: str, lat: float, lon: float):
    """(기존) p2p_client.py의 명령 포트로 GPS 데이터를 UDP 전송합니다."""
    try:
        with open("p2p_ports.json", "r") as f:
            port_data = json.load(f)
    except Exception as e:
        return False

    command_port = port_data.get(target_node_id)
    if not command_port:
        return False

    command = {"gps": {"latitude": lat, "longitude": lon}}
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(json.dumps(command).encode('utf-8'), ("127.0.0.1", command_port))
        return True
    except Exception as e:
        return False


def send_gps_via_http(lat: float, lon: float):
    """(기존) gps_service.py의 /data 엔드포인트로 GPS 데이터를 HTTP POST 전송합니다."""
    payload = {
        "payload": [
            {"name": "location", "values": {"latitude": lat, "longitude": lon}}
        ]
    }
    headers = {'Content-Type': 'application/json'}
    try:
        response = requests.post(GPS_SERVICE_DATA_ENDPOINT, headers=headers, data=json.dumps(payload), timeout=0.5)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        return False

def send_gps_to_listeners(lat: float, lon: float):
    """
    모든 TTS 청취자(proximity_tts_service.py)에게 GPS 데이터를 브로드캐스트합니다.
    """
    try:
        # 브로드캐스트 소켓 생성
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # 브로드캐스트 옵션 활성화
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

            # 보낼 데이터 (간단한 JSON)
            data = {"latitude": lat, "longitude": lon}

            # '<broadcast>' 주소는 네트워크의 모든 기기를 의미합니다.
            s.sendto(json.dumps(data).encode('utf-8'), ("<broadcast>", LISTENER_BROADCAST_PORT))
        return True
    except Exception as e:
        print(f"UDP 브로드캐스트 전송 실패: {e}")
        return False


# ⭐️ --- [추가 끝] ---


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Send GPS Data to P2P Client (UDP) and GPS Service (HTTP)")
    parser.add_argument("--id", required=True, help="Node ID of the target P2P client")
    args = parser.parse_args()

    lat, lon = 37.295332,126.8391226
    print(f"--- 가상 GPS 데이터 전송 시작 ({args.id} 대상) ---")
    print(f"HTTP Target: gps_service.py ({GPS_SERVICE_DATA_ENDPOINT})")
    print(f"UDP Target (P2P): p2p_client.py ({args.id})")
    print(f"UDP Target (TTS): ALL Listeners (Port {LISTENER_BROADCAST_PORT})")  # ⭐️ (추가)

    while True:
        # 가상 위치 업데이트 (예시: 약간의 무작위 이동)
        # 1. p2p_client.py로 UDP 전송
        udp_success = send_gps_via_udp(args.id, lat, lon)

        # 2. gps_service.py로 HTTP 전송
        http_success = send_gps_via_http(lat, lon)

        # 3. ⭐️ (추가) TTS 청취자들에게 UDP 브로드캐스트 전송
        broadcast_success = send_gps_to_listeners(lat, lon)

        status_udp = "OK" if udp_success else "FAIL"
        status_http = "OK" if http_success else "FAIL"
        status_bcast = "OK" if broadcast_success else "FAIL"  # ⭐️ (추가)

        # ⭐️ (수정) 출력 형식 변경
        print(f"GPS ({lat:.5f}, {lon:.5f}) -> HTTP:[{status_http}] | P2P:[{status_udp}] | TTS:[{status_bcast}]")

        time.sleep(0.5)