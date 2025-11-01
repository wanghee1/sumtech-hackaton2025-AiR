import asyncio
import json
import websockets
from typing import Set, Dict, Optional

class WebSocketServer:
    def __init__(self, host="0.0.0.0", port=8090):
        self.host = host
        self.port = port
        self.connected: Set[websockets.WebSocketServerProtocol] = set()
        self.pinpoints: Dict[str, str] = {} # Key: pin_id, Value: full message string
        self.latest_gps_data: Optional[Dict] = None # Stores {"latitude": float, "longitude": float}

    async def _handler(self, websocket: websockets.WebSocketServerProtocol):
        self.connected.add(websocket)
        remote_ip = websocket.remote_address[0] if websocket.remote_address else "Unknown IP"
        print(f"🔗 클라이언트 연결: {remote_ip} (총 {len(self.connected)}명)")

        # 연결 시 최근 핀포인트 전송 (기존 로직 유지)
        for pin_msg in self.pinpoints.values():
            try:
                await websocket.send(pin_msg)
            except websockets.exceptions.ConnectionClosed:
                break # 이미 끊겼으면 더 이상 보낼 필요 없음

        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    msg_type = data.get("type")
                    if not msg_type:
                        print(f"⚠️ 메시지에 'type' 필드 없음: {message[:100]}")
                        continue
                except json.JSONDecodeError as e:
                    print(f"⚠️ JSON 파싱 오류: {e}; raw={message[:120]}")
                    continue
                except Exception as e:
                    print(f"⚠️ 메시지 처리 중 예외 발생: {type(e).__name__} - {e}")
                    continue

                print(f"Received '{msg_type}' from {remote_ip}")

                # GPS 위치 업데이트 처리
                if msg_type == "GPS_POSITION_UPDATE":
                    gps_payload = data.get("payload")
                    if gps_payload and "latitude" in gps_payload and "longitude" in gps_payload:
                        self.latest_gps_data = {
                            "latitude": gps_payload["latitude"],
                            "longitude": gps_payload["longitude"]
                        }
                        # GPS 업데이트는 다른 클라이언트에게 중계하지 않음
                    continue # 다음 메시지 대기

                # 핀포인트 추가/삭제 처리 (최근 상태 저장)
                elif msg_type == "ADD_PINPOINT":
                    pin_id = data.get("payload", {}).get("id")
                    if pin_id:
                        self.pinpoints[pin_id] = message # 전체 메시지 문자열 저장
                elif msg_type == "REMOVE_PINPOINT":
                     pin_id = data.get("payload", {}).get("id")
                     if pin_id in self.pinpoints:
                         del self.pinpoints[pin_id]

                # RISK_ALERT 또는 기타 메시지 처리
                message_to_broadcast = data # 기본적으로 원본 메시지 사용

                if msg_type == "RISK_ALERT" and self.latest_gps_data:
                    # RISK_ALERT 메시지에 'gps' 필드로 최신 GPS 정보 추가
                    message_to_broadcast["gps"] = self.latest_gps_data
                    print(f"    -> RISK_ALERT에 GPS 정보 추가: {self.latest_gps_data}")

                # 수정된 메시지를 JSON 문자열로 변환하여 브로드캐스트
                modified_message_str = json.dumps(message_to_broadcast, ensure_ascii=False)
                await self.broadcast(modified_message_str, exclude=websocket)

        except websockets.exceptions.ConnectionClosedError as e:
            print(f"🔌 클라이언트({remote_ip}) 비정상 연결 종료: {e.code} {e.reason}")
        except websockets.exceptions.ConnectionClosedOK:
            print(f"🔌 클라이언트({remote_ip}) 정상 연결 종료됨")
        except Exception as e:
            print(f"💥 핸들러에서 예상치 못한 오류 발생 ({remote_ip}): {type(e).__name__} - {e}")
        finally:
            self.connected.discard(websocket)
            print(f"🔗 클라이언트 연결 해제: {remote_ip} (총 {len(self.connected)}명)")

    async def broadcast(self, message: str, exclude: Optional[websockets.WebSocketServerProtocol] = None):
        """ 모든 연결된 클라이언트에게 메시지를 전송합니다 (exclude 제외) """
        if not self.connected:
            return

        # 메시지 전송 작업 목록 생성
        tasks = [ws.send(message) for ws in self.connected if ws != exclude]
        if not tasks:
            return

        # 모든 작업 실행, 실패한 연결 처리
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 전송 실패한 연결 정리
        failed_connections = set()
        targets = [ws for ws in self.connected if ws != exclude]
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                failed_ws = targets[i]
                remote_ip = failed_ws.remote_address[0] if failed_ws.remote_address else "Unknown"
                print(f"🧼 브로드캐스트 실패 및 연결 정리: {remote_ip} ({type(result).__name__})")
                failed_connections.add(failed_ws)

        # 실패한 연결 제거
        self.connected -= failed_connections

    async def start(self):
        """ 웹소켓 서버를 시작하고 계속 실행합니다 """
        try:
            async with websockets.serve(self._handler, self.host, self.port):
                print(f"🚀 WebSocket 서버 listening on ws://{self.host}:{self.port}")
                await asyncio.Future()  # 영원히 실행
        except OSError as e:
            print(f"🚨 서버 시작 실패 (포트 {self.port} 사용 중?): {e}")
        except Exception as e:
            print(f"🚨 서버 시작 중 예상치 못한 오류: {type(e).__name__} - {e}")

if __name__ == "__main__":
    try:
        asyncio.run(WebSocketServer().start())
    except KeyboardInterrupt:
        print("\n🛑 서버 종료됨.")