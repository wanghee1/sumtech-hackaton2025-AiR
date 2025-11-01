import argparse
import asyncio
import base64
import io
import json
import sys
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
import websockets
import logging

THIS_FILE = Path(__file__).resolve()
SRC_DIR = THIS_FILE.parent if THIS_FILE.parent.name != "core" else THIS_FILE.parent.parent
if SRC_DIR.as_posix() not in sys.path:
    sys.path.append(SRC_DIR.as_posix())

# Simple file logger for system-level risk events and gated alerts
logging.basicConfig(
    filename=str((SRC_DIR / "hazard.log")) ,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

from core.yolo_processor import YOLOProcessor
from core.risk_assessor import RiskAssessor


# -------------- Utility helpers --------------
def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def make_safety_zone(w: int, h: int,
                     width_ratio: float = 0.40,
                     height_ratio: float = 0.35,
                     bottom_margin_ratio: float = 0.05) -> List[int]:
    sw = int(w * width_ratio)
    sh = int(h * height_ratio)
    cx = w // 2
    bottom = h - int(h * bottom_margin_ratio)
    x1 = int(cx - sw // 2)
    x2 = int(cx + sw // 2)
    y2 = bottom
    y1 = max(0, y2 - sh)
    return [x1, y1, x2, y2]


def bbox_area_xyxy(b: List[float]) -> float:
    x1, y1, x2, y2 = b
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def bbox_center(b: List[float]) -> Tuple[float, float]:
    x1, y1, x2, y2 = b
    return (0.5 * (x1 + x2), 0.5 * (y1 + y2))


def point_in_rect(pt: Tuple[float, float], rect: List[int]) -> bool:
    x, y = pt
    x1, y1, x2, y2 = rect
    return (x1 <= x <= x2) and (y1 <= y <= y2)


def crop_to_base64(frame: np.ndarray, bbox: List[float], max_side: int = 256) -> str:
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = [int(clamp(v, 0, w if i % 2 == 0 else h)) for i, v in enumerate(bbox)]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    if x2 <= x1 or y2 <= y1:
        return ""
    crop = frame[y1:y2, x1:x2]
    ch, cw = crop.shape[:2]
    scale = min(1.0, max_side / max(ch, cw)) if max(ch, cw) > 0 else 1.0
    if scale < 1.0:
        crop = cv2.resize(crop, (int(cw * scale), int(ch * scale)))
    ok, buf = cv2.imencode('.jpg', crop, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    if not ok:
        return ""
    return base64.b64encode(buf.tobytes()).decode('ascii')


# -------------- Send/Dump helpers --------------
async def ws_send_safe(ws, payload: Dict):
    if ws is None:
        return
    try:
        await ws.send(json.dumps(payload, ensure_ascii=False))
    except Exception as e:
        print(f"[WARN] WebSocket send failed: {e}")


def dump_jsonl(path: Path, obj: Dict):
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[WARN] Dump to file failed: {e}")


# -------------- Track state and detectors --------------
@dataclass
class TrackState:
    id: int
    first_seen_ts: float
    centers: deque
    heights: deque
    areas: deque
    in_danger_zone: bool = False
    accident_frames: int = 0


class HazardDetector:
    """
    Improved hazard logic for:
    - Accident detection: stable detection of 'Accident' class for N frames.
    - Sudden pop-in: new track appears away from borders, or very low TTC based on height growth rate.
    """

    # Parameters (tunable)
    EDGE_MARGIN_RATIO = 0.07  # births near edges ignored
    ACCIDENT_MIN_FRAMES = 3   # consistent frames before accident alert
    TTC_THRESH_SEC = 1.0      # alert if time-to-contact below this
    SMOOTH_WIN = 5

    def __init__(self, frame_w: int, frame_h: int, dz_width_ratio: float = 0.40, dz_height_ratio: float = 0.35, dz_bottom_margin_ratio: float = 0.05):
        self.w = frame_w
        self.h = frame_h
        self.tracks: Dict[int, TrackState] = {}
        self.danger_rect = make_safety_zone(frame_w, frame_h, width_ratio=dz_width_ratio, height_ratio=dz_height_ratio, bottom_margin_ratio=dz_bottom_margin_ratio)

    def ensure(self, tid: int) -> TrackState:
        if tid not in self.tracks:
            self.tracks[tid] = TrackState(
                id=tid,
                first_seen_ts=time.time(),
                centers=deque(maxlen=self.SMOOTH_WIN),
                heights=deque(maxlen=self.SMOOTH_WIN),
                areas=deque(maxlen=self.SMOOTH_WIN),
            )
        return self.tracks[tid]

    def _near_edge(self, c: Tuple[float, float]) -> bool:
        x, y = c
        mx, my = self.w * self.EDGE_MARGIN_RATIO, self.h * self.EDGE_MARGIN_RATIO
        return x <= mx or x >= (self.w - mx) or y <= my or y >= (self.h - my)

    def _estimate_ttc(self, heights: deque, fps: float) -> Optional[float]:
        # Use relative growth rate of height: dh/dt / h ~ approach rate
        if len(heights) < 2 or fps <= 1e-6:
            return None
        h_now, h_prev = float(heights[-1]), float(heights[-2])
        if h_now <= 1e-6 or h_prev <= 1e-6:
            return None
        rel_growth_per_frame = (h_now - h_prev) / h_prev
        rel_growth_per_sec = rel_growth_per_frame * fps
        if rel_growth_per_sec <= 1e-6:
            return None
        return 1.0 / rel_growth_per_sec

    def assess(self, frame: np.ndarray, tracks: List[Dict], fps: float) -> List[Dict]:
        alerts = []
        for d in tracks:
            tid = int(d["id"])
            bbox = d["bbox"]
            label = d.get("label")
            conf = d.get("conf", 0.0)
            x1, y1, x2, y2 = bbox
            h = max(1.0, y2 - y1)
            a = bbox_area_xyxy(bbox)
            c = bbox_center(bbox)

            st = self.ensure(tid)
            st.centers.append(c)
            st.heights.append(h)
            st.areas.append(a)

            # Accident: stable 'Accident' label
            if label is not None and str(label).lower() == "accident" and conf >= 0.4:
                st.accident_frames += 1
                if st.accident_frames >= self.ACCIDENT_MIN_FRAMES:
                    alerts.append({
                        "type": "accident",
                        "track_id": tid,
                        "label": label,
                        "conf": conf,
                        "bbox": bbox,
                        "reason": f"Accident detected for {st.accident_frames} frames",
                        "image": crop_to_base64(frame, bbox)
                    })
            else:
                st.accident_frames = 0

            # Sudden pop-in: new track that is not near edges on first frames
            if len(st.centers) == 1 and not self._near_edge(c):
                alerts.append({
                    "type": "pop_in",
                    "track_id": tid,
                    "label": label,
                    "conf": conf,
                    "bbox": bbox,
                    "reason": "New object appeared away from frame edges",
                    "image": crop_to_base64(frame, bbox)
                })

            # TTC-based approach alert inside danger zone
            if point_in_rect(c, self.danger_rect):
                st.in_danger_zone = True
                ttc = self._estimate_ttc(st.heights, fps)
                if ttc is not None and ttc <= self.TTC_THRESH_SEC:
                    alerts.append({
                        "type": "approach",
                        "track_id": tid,
                        "label": label,
                        "conf": conf,
                        "bbox": bbox,
                        "reason": f"Estimated TTC {ttc:.2f}s inside danger zone",
                        "ttc": ttc,
                        "image": crop_to_base64(frame, bbox)
                    })
        return alerts


# -------------- Visualization --------------
def draw_overlay(frame: np.ndarray, tracks: List[Dict], alerts: List[Dict], fps: float, danger_rect: List[int], conf: float, send_image: bool):
    # Map alerts by track for coloring and extra info (e.g., TTC)
    by_tid: Dict[int, List[Dict]] = {}
    for a in alerts:
        by_tid.setdefault(int(a.get("track_id", -1)), []).append(a)

    # Color priority by alert type
    def color_for_alerts(a_list: List[Dict]) -> Tuple[int, int, int]:
        types = {a.get("type") for a in a_list}
        if "accident" in types:
            return (0, 0, 255)      # red
        if "approach" in types:
            return (0, 165, 255)    # orange
        if "pop_in" in types:
            return (255, 0, 255)    # magenta
        return (0, 200, 255)        # cyan (default)

    # Draw tracked boxes with labels and TTC if available
    for d in tracks:
        x1, y1, x2, y2 = map(int, d["bbox"])
        tid = int(d["id"])
        label = d.get("label")
        conf_v = d.get("conf")
        a_list = by_tid.get(tid, [])
        color = color_for_alerts(a_list) if a_list else (0, 200, 255)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

        text = f"{label} {conf_v:.2f}" if label else f"ID{tid}"
        t_size = cv2.getTextSize(text, 0, fontScale=0.7, thickness=2)[0]
        c2 = (x1 + t_size[0], y1 - t_size[1] - 3)
        cv2.rectangle(frame, (x1, y1), c2, color, -1, cv2.LINE_AA)
        cv2.putText(frame, text, (x1, max(0, y1 - 2)), 0, 0.7, (255, 255, 255), 1, cv2.LINE_AA)

        # If TTC alert exists for this track, annotate near box bottom
        ttc_vals = [a.get("ttc") for a in a_list if a.get("type") == "approach" and a.get("ttc") is not None]
        if ttc_vals:
            ttc_text = f"TTC {min(ttc_vals):.2f}s"
            cv2.putText(frame, ttc_text, (x1, min(frame.shape[0]-5, y2 + 18)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

    # Danger zone
    dx1, dy1, dx2, dy2 = map(int, danger_rect)
    cv2.rectangle(frame, (dx1, dy1), (dx2, dy2), (60, 220, 60), 2)
    cv2.putText(frame, "Danger zone", (dx1, max(0, dy1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (60, 220, 60), 2)

    # Status panel (top-left)
    h, w = frame.shape[:2]
    panel_w, panel_h = 460, 140
    overlay = frame.copy()
    cv2.rectangle(overlay, (8, 8), (8 + panel_w, 8 + panel_h), (30, 30, 30), -1)
    frame_alpha = 0.35
    cv2.addWeighted(overlay, frame_alpha, frame, 1 - frame_alpha, 0, frame)

    total_alerts = len(alerts)
    acc_cnt = sum(1 for a in alerts if a.get("type") == "accident")
    app_cnt = sum(1 for a in alerts if a.get("type") == "approach")
    pop_cnt = sum(1 for a in alerts if a.get("type") == "pop_in")
    lines = [
        f"FPS: {fps:.1f} | Tracks: {len(tracks)} | Alerts: {total_alerts}",
        f"accident: {acc_cnt}  approach: {app_cnt}  pop_in: {pop_cnt}",
        f"conf: {conf:.2f}  send_image: {bool(send_image)}",
        "Recent alerts:",
    ]
    y = 30
    for ln in lines:
        cv2.putText(frame, ln, (16, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (240, 240, 240), 2)
        y += 22
    # Show up to 3 recent alerts
    for a in alerts[-3:]:
        msg = f"[{a.get('type')}] T{a.get('track_id')} - {a.get('reason')}"
        cv2.putText(frame, msg, (16, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 180, 255), 2)
        y += 20


# -------------- Main async loop --------------
async def run(args):
    model_path = args.model or "yolov8n.pt"
    yolo = YOLOProcessor(model_path, conf_thres=args.conf)

    # Use model names for accident detection if available; optional accident model could be added later
    CLASS_NAMES = getattr(yolo.model, "names", None)
    if isinstance(CLASS_NAMES, dict):
        CLASS_NAMES = [CLASS_NAMES[i] for i in sorted(CLASS_NAMES.keys())]

    server_uri = f"ws://{args.ws_host}:{args.ws_port}"
    print(f"AI client will connect to central server: {server_uri}")

    # Try to connect to WebSocket, but continue detection even if it fails
    websocket = None
    try:
        websocket = await websockets.connect(server_uri)
        print("Connected to central server.")
    except Exception as e:
        print(f"[WARN] Could not connect to server ({server_uri}): {e}. Continuing without sending.")

    def to_tracks(result):
        tracks = []
        boxes = result.boxes
        if boxes is None or len(boxes) == 0:
            return tracks
        xyxy = boxes.xyxy.cpu().numpy()
        ids = boxes.id.cpu().numpy() if boxes.id is not None else None
        cls = boxes.cls.cpu().numpy() if boxes.cls is not None else None
        conf = boxes.conf.cpu().numpy() if boxes.conf is not None else None
        for i, bb in enumerate(xyxy):
            det_id = int(ids[i]) if ids is not None else i
            det_conf = float(conf[i]) if conf is not None else 0.0
            det_cls = int(cls[i]) if cls is not None else None
            det_label = None
            if det_cls is not None and CLASS_NAMES is not None:
                if isinstance(CLASS_NAMES, list) and 0 <= det_cls < len(CLASS_NAMES):
                    det_label = str(CLASS_NAMES[det_cls])
            if det_conf < float(args.conf):
                continue
            tracks.append({
                "id": det_id,
                "bbox": [float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3])],
                "cls": det_cls,
                "label": det_label,
                "conf": det_conf,
            })
        return tracks

    last_t = time.time()
    last_sys_log = 0.0
    printed_dz = False

    # System risk assessor (levels WARN1/WARN2/WARN3). Gate actions on level >= 2.
    sys_assessor = None

    def max_risk_level(risk):
        if not risk or not risk.get('alerts'):
            return 0
        lv_map = {'WARN1': 1, 'WARN2': 2, 'WARN3': 3}
        return max(lv_map.get(str(a.get('level')), 0) for a in risk.get('alerts', []))

    try:
        # First frame to initialize detector with frame size
        stream = yolo.track_stream(source=args.source)
        detector: Optional[HazardDetector] = None
        for result in stream:
            frame = result.orig_img
            if frame is None:
                await asyncio.sleep(0)
                continue
            h, w = frame.shape[:2]
            if detector is None:
                detector = HazardDetector(w, h, args.dz_width, args.dz_height, args.dz_bottom)
            if sys_assessor is None:
                sys_assessor = RiskAssessor()
                sys_assessor.set_frame_size(w, h)
            tracks = to_tracks(result)
            fps = 1.0 / max(1e-6, time.time() - last_t)
            last_t = time.time()

            alerts = detector.assess(frame, tracks, fps)

            # System risk evaluation and gating (level >= 2)
            sys_risk = sys_assessor.assess(tracks) if sys_assessor is not None else None
            risk_level = max_risk_level(sys_risk)
            risk2plus = risk_level >= getattr(args, 'gate_level', 2)

            # Optional console heartbeat about current system risk
            if getattr(args, 'log_system_risk', False) and (time.time() - last_sys_log) > 1.0:
                try:
                    compact = [
                        {"level": a.get("level"), "track_id": a.get("track_id"), "reason": a.get("reason")}
                        for a in (sys_risk.get("alerts", []) if isinstance(sys_risk, dict) else [])
                    ]
                except Exception:
                    compact = []
                print(json.dumps({"system_risk_level": risk_level, "alerts": compact}, ensure_ascii=False))
                last_sys_log = time.time()
            if risk2plus:
                # Log compact system risk info
                try:
                    compact = [
                        {"level": a.get("level"), "track_id": a.get("track_id"), "reason": a.get("reason")}
                        for a in (sys_risk.get("alerts", []) if isinstance(sys_risk, dict) else [])
                    ]
                    logging.info("system_risk_gte2 alerts=%s", json.dumps(compact, ensure_ascii=False))
                except Exception:
                    pass
                # Send alerts with optional image crops if connected
                for a in alerts:
                    payload = {
                        "type": "RISK_ALERT",
                        "ts": time.time(),
                        "subtype": a.get("type"),
                        "track_id": a.get("track_id"),
                        "label": a.get("label"),
                        "conf": a.get("conf"),
                        "reason": a.get("reason"),
                        "bbox": a.get("bbox"),
                        "ttc": a.get("ttc"),
                        "image": a.get("image") if args.send_image else None,
                    }
                    print(json.dumps({k: v for k, v in payload.items() if v is not None}, ensure_ascii=False))
                    try:
                        logging.info("hazard_alert_gte2 %s", json.dumps(payload, ensure_ascii=False))
                    except Exception:
                        pass
                    if websocket is not None:
                        await websocket.send(json.dumps(payload, ensure_ascii=False))

            if args.show:
                draw_overlay(frame, tracks, alerts, fps, detector.danger_rect, args.conf, args.send_image)
                cv2.imshow("AI Main3 - Hazard Monitor", frame)
                if cv2.waitKey(1) & 0xFF == 27:
                    break
            await asyncio.sleep(0)

    except Exception as e:
        print(f"[INFO] Track stream failed, switching to fallback camera: {e}")
        cap = cv2.VideoCapture(0, cv2.CAP_AVFOUNDATION)
        if not cap.isOpened():
            raise SystemExit("Fallback camera failed to open")
        detector: Optional[HazardDetector] = None
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            h, w = frame.shape[:2]
            if detector is None:
                detector = HazardDetector(w, h, args.dz_width, args.dz_height, args.dz_bottom)
            if sys_assessor is None:
                sys_assessor = RiskAssessor()
                sys_assessor.set_frame_size(w, h)
            # Single-frame run for fallback
            result = yolo.model.track(
                source=frame, conf=yolo.conf_thres,
                tracker="bytetrack.yaml", stream=False, verbose=False, persist=True
            )[0]
            tracks = to_tracks(result)
            fps = 1.0 / max(1e-6, time.time() - last_t)
            last_t = time.time()
            alerts = detector.assess(frame, tracks, fps)
            sys_risk = sys_assessor.assess(tracks) if sys_assessor is not None else None
            risk_level = max_risk_level(sys_risk)
            risk2plus = risk_level >= getattr(args, 'gate_level', 2)
            if getattr(args, 'log_system_risk', False) and (time.time() - last_sys_log) > 1.0:
                try:
                    compact = [
                        {"level": a.get("level"), "track_id": a.get("track_id"), "reason": a.get("reason")}
                        for a in (sys_risk.get("alerts", []) if isinstance(sys_risk, dict) else [])
                    ]
                except Exception:
                    compact = []
                print(json.dumps({"system_risk_level": risk_level, "alerts": compact}, ensure_ascii=False))
                last_sys_log = time.time()
            if risk2plus:
                try:
                    compact = [
                        {"level": a.get("level"), "track_id": a.get("track_id"), "reason": a.get("reason")}
                        for a in (sys_risk.get("alerts", []) if isinstance(sys_risk, dict) else [])
                    ]
                    logging.info("system_risk_gte2 alerts=%s", json.dumps(compact, ensure_ascii=False))
                except Exception:
                    pass
                for a in alerts:
                    payload = {
                        "type": "RISK_ALERT",
                        "ts": time.time(),
                        "subtype": a.get("type"),
                        "track_id": a.get("track_id"),
                        "label": a.get("label"),
                        "conf": a.get("conf"),
                        "reason": a.get("reason"),
                        "bbox": a.get("bbox"),
                        "ttc": a.get("ttc"),
                        "image": a.get("image") if args.send_image else None,
                    }
                    print(json.dumps({k: v for k, v in payload.items() if v is not None}, ensure_ascii=False))
                    try:
                        logging.info("hazard_alert_gte2 %s", json.dumps(payload, ensure_ascii=False))
                    except Exception:
                        pass
                    if websocket is not None:
                        await websocket.send(json.dumps(payload, ensure_ascii=False))
            if args.show:
                draw_overlay(frame, tracks, alerts, fps, detector.danger_rect, args.conf, args.send_image)
                cv2.imshow("AI Main3 - Hazard Monitor (Fallback)", frame)
                if cv2.waitKey(1) & 0xFF == 27:
                    break
            await asyncio.sleep(0)
        cap.release()
    if websocket is not None:
        try:
            await websocket.close()
        except Exception:
            pass
    cv2.destroyAllWindows()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", type=str, default="./yolov8n.pt", help="YOLO model path or name")
    ap.add_argument("--source", type=str, default="2", help="Camera index or file path")
    ap.add_argument("--conf", type=float, default=0.25, help="Confidence threshold")
    ap.add_argument("--ws_host", type=str, default="localhost")
    ap.add_argument("--ws_port", type=int, default=8090)
    ap.add_argument("--show", default=True, action="store_true", help="Show visualization window")
    ap.add_argument("--send_image", action="store_true", help="Attach cropped object image (base64) to alerts")
    ap.add_argument("--gate_level", type=int, default=2, help="Minimum system risk level (2=WARN2) to emit alerts and log")
    ap.add_argument("--log_system_risk", default=True, action="store_true", help="Print system risk level/alerts once per second")
    ap.add_argument("--dump", default=True, action="store_true", help="Dump each emitted alert to a JSONL file")
    ap.add_argument("--dump_path", type=str, default="hazard_dump.jsonl", help="Path to JSONL dump file")
    args = ap.parse_args()

    asyncio.run(run(args))