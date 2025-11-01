# camera_handler.py
import cv2

class CameraHandler:
    def __init__(self, source=0):
        # source: 0(웹캠) | 파일 경로 | RTSP/HTTP
        self.cap = cv2.VideoCapture(0 if str(source) == "0" else source)
        if not self.cap.isOpened():
            raise RuntimeError(f"Cannot open source: {source}")

    def read(self):
        ok, frame = self.cap.read()
        if not ok:
            return None
        return frame

    def size(self):
        w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        return w, h

    def release(self):
        if self.cap:
            self.cap.release()