import subprocess
import time
import sys


# 시작할 명령어 리스트
commands = [
    [sys.executable, "ai_main2.py"],
    [sys.executable, "p2p_client.py", "--id" , "B"],
    [sys.executable, "gps_sender.py", "--id" , "B"],
    [sys.executable, "rec.py", "--from-id", "B"],
]

processes = []

try:
    print("Starting all processes...")
    # 모든 프로세스를 Popen으로 시작 (비동기)
    for cmd in commands:
        proc = subprocess.Popen(cmd)
        processes.append(proc)
        print(f"Started process {proc.pid} ({' '.join(cmd)})")

    # 메인 스크립트가 종료되지 않도록 대기
    # (여기서 모든 프로세스가 실행 중입니다)
    while True:
        time.sleep(1)

except KeyboardInterrupt:
    # Ctrl+C 를 누르면 여기로 옵니다.
    print("\nStopping all processes...")
    for proc in processes:
        proc.terminate()  # 모든 자식 프로세스에 종료 신호 전송

    # 프로세스가 완전히 종료될 때까지 잠시 대기
    for proc in processes:
        proc.wait()

    print("All processes stopped.")