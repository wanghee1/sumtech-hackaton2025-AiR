import asyncio
import json
import websockets
import socket
import argparse
import os
from typing import Optional, Dict

# --- P2P 명령 전송 함수 ---
def send_p2p_command(from_node_id: str, message_content: Dict, target_peer_id: Optional[str] = None):
    """공유 파일에서 명령을 보낼 클라이언트의 포트를 찾아 메시지 전송을 요청합니다."""
    ports_file = "p2p_ports.json"
    if not os.path.exists(ports_file):
        print(f"오류: {ports_file} 파일을 찾을 수 없습니다. P2P 클라이언트가 실행 중인지, 파일이 생성되었는지 확인하세요.")
        return

    try:
        with open(ports_file, "r") as f:
            port_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"오류: {ports_file} 파일을 읽거나 파싱할 수 없습니다: {e}")
        return

    command_port = port_data.get(from_node_id)
    if not command_port:
        print(f"오류: {ports_file}에서 '{from_node_id}'의 명령 포트를 찾을 수 없습니다.")
        return

    target_host = "127.0.0.1" # 명령 수신 포트는 로컬에서만 열림
    command = {
        "content": message_content # 경고 레벨, GPS 좌표가 담긴 딕셔너리
    }
    # target_id가 주어졌을 때만 command에 추가
    if target_peer_id:
        command["target_id"] = target_peer_id

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(json.dumps(command).encode('utf-8'), (target_host, command_port))

            if target_peer_id:
                print(f"🅿️ [{from_node_id}] -> [{target_peer_id}]에게 P2P 명령 전송: {message_content}")
            else:
                print(f"🅿️ [{from_node_id}] -> 그룹 전체에 P2P 방송 명령 전송: {message_content}")
    except Exception as e:
        print(f"P2P 명령 UDP 전송 실패 ({target_host}:{command_port}): {e}")

# --- 웹소켓 수신 및 P2P 전송 로직 ---
async def receive_alerts_and_send_p2p(p2p_sender_id: str, p2p_target_id: Optional[str] = None):
    """웹소켓으로 RISK_ALERT를 받아 level과 gps를 P2P로 전송합니다."""
    # 웹소켓 서버 URI (localhost:8090)
    uri = "ws://localhost:8090"
    retry_delay = 5 # 재시도 간격 (초)

    print(f"--- WebSocket 클라이언트 시작 (P2P 발신자: {p2p_sender_id}) ---")

    while True:
        websocket = None
        try:
            print(f"--- WebSocket 서버 연결 시도: {uri} ---")
            websocket = await asyncio.wait_for(websockets.connect(uri), timeout=10.0)
            print(f"✅ WebSocket 서버에 연결됨: {websocket.remote_address}")

            # 연결 성공 후 메시지 수신 루프
            async for message in websocket:
                print("--- 🔵 WebSocket 메시지 수신! ---")
                try:
                    data = json.loads(message)
                    # 보기 좋게 출력 (디버깅용)
                    print(json.dumps(data, indent=2, ensure_ascii=False))

                    # 1. 메시지 타입이 RISK_ALERT 인지 확인
                    if data.get("type") == "RISK_ALERT":
                        # 2. level 및 gps 값 추출
                        alert_level = data.get("level")
                        gps_data = data.get("gps") # 추가된 GPS 정보 확인

                        if alert_level is not None and gps_data is not None:
                            lat = gps_data.get("latitude")
                            lon = gps_data.get("longitude")

                            if lat is not None and lon is not None:
                                # P2P로 보낼 내용을 딕셔너리로 구성
                                p2p_message_content = {
                                    "alert_level": alert_level,
                                    "latitude": lat,
                                    "longitude": lon
                                }
                                # P2P 명령 전송 함수 호출
                                send_p2p_command(
                                    from_node_id=p2p_sender_id,
                                    message_content=p2p_message_content,
                                    target_peer_id=p2p_target_id
                                )
                            else:
                                print("   (경고: RISK_ALERT의 GPS 정보에 위도/경도가 없습니다.)")
                        else:
                            print("   (경고: RISK_ALERT 메시지에 'level' 또는 'gps' 필드가 없습니다.)")
                    else:
                        print(f"   (정보: '{data.get('type')}' 타입 메시지는 P2P로 전달하지 않습니다.)")

                except json.JSONDecodeError:
                    print(f"(JSON 아님): {message[:100]}...") # 너무 길면 잘라서 출력
                    print("   (정보: JSON 형식이 아니므로 P2P로 전달하지 않습니다.)")
                except Exception as inner_e:
                    print(f"메시지 처리 또는 P2P 전송 중 오류 발생: {inner_e}")

                print("-----------------------------------")

        except asyncio.TimeoutError:
             print(f"❌ WebSocket 연결 시간 초과 ({uri}). {retry_delay}초 후 재시도...")
        except websockets.exceptions.ConnectionClosedOK:
            print("⭕ WebSocket 서버와의 연결이 정상적으로 종료되었습니다. 재연결 시도...")
        except websockets.exceptions.ConnectionClosedError as e:
            print(f"❌ WebSocket 서버와의 연결이 비정상적으로 끊겼습니다: {e.code} {e.reason}. {retry_delay}초 후 재시도...")
        except ConnectionRefusedError:
             print(f"❌ WebSocket 서버({uri})가 실행 중이지 않거나 연결을 거부했습니다. {retry_delay}초 후 재시도...")
        except OSError as e:
             print(f"❌ 네트워크 오류 발생: {e}. {retry_delay}초 후 재시도...")
        except Exception as e:
            print(f"💥 예상치 못한 오류 발생: {type(e).__name__} - {e}")
            import traceback
            traceback.print_exc()
            print(f"{retry_delay}초 후 재시도...")

        finally:
            if websocket and not websocket.closed:
                 try:
                     await websocket.close()
                 except Exception: pass
            await asyncio.sleep(retry_delay)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Receive WebSocket alerts and relay level/gps via P2P command")
    parser.add_argument("--from-id", required=True, help="P2P 명령을 내릴 클라이언트의 Node ID")
    parser.add_argument("--target-id", help="[선택] 귓속말을 보낼 상대방 P2P 클라이언트의 Node ID (없으면 전체 방송)")

    args = parser.parse_args()

    try:
        asyncio.run(receive_alerts_and_send_p2p(args.from_id, args.target_id))
    except KeyboardInterrupt:
        print("\n--- 사용자에 의해 클라이언트 종료됨 ---")