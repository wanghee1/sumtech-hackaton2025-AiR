
import pvporcupine
import pyaudio
import struct
import config 

# --- 1. map_search.py가 호출할 함수 ---
def start_stt(on_wake_word_detected_callback):
    """
    호출어('Hey Google') 감지를 시작하는 메인 루프 함수.
    
    Args:
        on_wake_word_detected_callback (function): 
            호출어가 감지되었을 때 실행할 함수 (map_search.py가 전달)
    """
    porcupine = None
    pa = None
    audio_stream = None

    try:
        keyword_path = pvporcupine.KEYWORD_PATHS['hey google']
        
        porcupine = pvporcupine.create(
        access_key=config.PICOVOICE_ACCESS_KEY,
        keyword_paths=[keyword_path],
        sensitivities=[0.7]
    )
        print("웨이크 워드 엔진('Hey Google')이 준비되었습니다.")

        # [마이크 스트림 열기]
        pa = pyaudio.PyAudio()
        audio_stream = pa.open(
            rate=porcupine.sample_rate,
            channels=1,
            format=pyaudio.paInt16,
            input=True,
            frames_per_buffer=porcupine.frame_length
        )
        
        print("\n🎧 'Hey Google'이라고 말하면 감지합니다... (종료: Ctrl+C)")

        while True:
            pcm = audio_stream.read(porcupine.frame_length)
            pcm = struct.unpack_from("h" * porcupine.frame_length, pcm)
            
            keyword_index = porcupine.process(pcm)
            
            if keyword_index >= 0:
                print(f"---  웨이크 워드 감지! ('Hey Google') ---")
            
                on_wake_word_detected_callback()
                
                print("\n 다시 'Hey Google'을 감지합니다...")

    except pvporcupine.PorcupineError as e:
        print(f"Porcupine 초기화 오류: {e}")
    except IOError as e:
        print(f"오디오 스트림 열기 오류: {e}")
    except KeyboardInterrupt:
        print("\n프로그램을 종료합니다.")
    finally:
        # [자원 정리]
        if porcupine: porcupine.delete()
        if audio_stream: audio_stream.close()
        if pa: pa.terminate()