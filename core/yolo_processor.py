# src/core/yolo_processor.py
from ultralytics import YOLO

class YOLOProcessor:
    """
    YOLO + ByteTrack 기반 실시간 추적기
    - 높은 라벨 정확도 (YOLOv8/v11)
    - 안정적인 추적 ID (ByteTrack)
    - 실시간 처리용 stream=True
    """
    def __init__(self, model_path: str, conf_thres: float = 0.25, tracker_type: str = "bytetrack.yaml"):
        self.model = YOLO(model_path)
        self.conf_thres = conf_thres
        self.tracker_type = tracker_type

    def track_stream(self, source=0):
        """
        실시간 추적 스트림 (제너레이터)
        - yield: result (ultralytics.engine.results.Results)
        """
        return self.model.track(
            source=source,
            conf=self.conf_thres,
            tracker=self.tracker_type,
            stream=True,
            verbose=False,
            persist=True  # 동일 ID 유지
        )

    def detect_once(self, frame):
        """
        단일 프레임 예측 (일회성)
        """
        return self.model.predict(frame, conf=self.conf_thres, verbose=False)[0]