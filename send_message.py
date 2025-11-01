import socket
import json
import argparse

def send_p2p_command(from_node_id: str, message: str, target_peer_id: str = None):
    """공유 파일에서 명령을 보낼 클라이언트의 포트를 찾아 메시지 전송을 요청합니다."""

    try:
        with open("p2p_ports.json", "r") as f:
            port_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print("오류: p2p_ports.json 파일을 찾을 수 없습니다. P2P 클라이언트가 실행 중인지 확인하세요.")
        return

    command_port = port_data.get(from_node_id)
    if not command_port:
        print(f"오류: 실행 중인 클라이언트 목록에서 '{from_node_id}'를 찾을 수 없습니다.")
        return

    target_host = "127.0.0.1"
    command = {
        "content": message
    }
    # target_id가 주어졌을 때만 command에 추가
    if target_peer_id:
        command["target_id"] = target_peer_id

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(json.dumps(command).encode(), (target_host, command_port))

        if target_peer_id:
            print(f"✅ 클라이언트 [{from_node_id}]를 통해 [{target_peer_id}]에게 귓속말 명령 완료!")
        else:
            print(f"✅ 클라이언트 [{from_node_id}]를 통해 그룹 전체에 방송 명령 완료!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Send P2P Message via IPC")
    parser.add_argument("--from-id", required=True, help="The Node ID of the client that will send the message")
    parser.add_argument("--message", required=True, help="The content of the message")
    # target-id를 선택사항으로 변경
    parser.add_argument("--target-id", help="[Optional] Node ID of the peer to send a direct message to")

    args = parser.parse_args()

    send_p2p_command(args.from_id, args.message, args.target_id)