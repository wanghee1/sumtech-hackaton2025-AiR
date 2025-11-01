import pvporcupine
import pyaudio
import struct
import os
from dotenv import load_dotenv

# --- 1. 설정 및 키 로딩 ---
load_dotenv()

PICOVOICE_ACCESS_KEY = os.getenv('PICO_KEY')
if not PICOVOICE_ACCESS_KEY:
    raise ValueError("PICOVOICE_ACCESS_KEY가 .env 파일에 없습니다. Picovoice Console에서 발급받으세요.")

try:
    # ⭐️ "헤이 구글"은 무료로 내장된 키워드입니다.
    keyword_path = pvporcupine.KEYWORD_PATHS['hey google']

    porcupine = pvporcupine.create(
        access_key=PICOVOICE_ACCESS_KEY,
        keyword_paths=[keyword_path]
    )
    print("✅ 웨이크 워드 엔진('Hey Google')이 준비되었습니다.")

except pvporcupine.PorcupineError as e:
    print(f"Porcupine 초기화 오류: {e}")
    print("AccessKey가 올바른지 확인하세요.")
    exit()

# --- 2. 오디오 스트림 설정 ---
pa = pyaudio.PyAudio()

try:
    audio_stream = pa.open(
        rate=porcupine.sample_rate,
        channels=1,
        format=pyaudio.paInt16,
        input=True,
        frames_per_buffer=porcupine.frame_length
    )
    print("\n🎧 'Hey Google'이라고 말하면 감지합니다...")

except IOError as e:
    print(f"오디오 스트림 열기 오류: {e}")
    print("마이크가 연결되어 있는지, 권한이 있는지 확인하세요.")
    pa.terminate()
    exit()

# --- 3. 실시간 감지 루프 ---
try:
    while True:
        # 3-A. 오디오 스트림에서 데이터 읽기
        pcm = audio_stream.read(porcupine.frame_length)
        pcm = struct.unpack_from("h" * porcupine.frame_length, pcm)

        # 3-B. Porcupine 엔진으로 웨이크 워드 감지
        keyword_index = porcupine.process(pcm)

        if keyword_index >= 0:
            # ⭐️ 웨이크 워드 감지 성공!
            print(f"--- ❗️ 웨이크 워드 감지! ('Hey Google') ---")

except KeyboardInterrupt:
    print("\n프로그램을 종료합니다.")
finally:
    # 리소스 정리
    if 'porcupine' in locals() and porcupine:
        porcupine.delete()
    if 'audio_stream' in locals() and audio_stream:
        audio_stream.stop_stream()
        audio_stream.close()
    if 'pa' in locals() and pa:
        pa.terminate()