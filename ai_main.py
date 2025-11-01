import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Optional

import cv2
import websockets

# Path setup
THIS_FILE = Path(__file__).resolve()
SRC_DIR = THIS_FILE.parent if THIS_FILE.parent.name != "core" else THIS_FILE.parent.parent
if SRC_DIR.as_posix() not in sys.path:
    sys.path.append(SRC_DIR.as_posix())

# Module imports
from core.risk_assessor import RiskAssessor
from core.yolo_processor import YOLOProcessor
#
# from communication.websocket_server import WebSocketServer

SHOW = True  # Enable visualization

# Model path resolution
def resolve_model_path(cli_value: Optional[str]) -> str:
#
    candidates = []
    if cli_value:
        p = Path(cli_value)
        candidates.append(p if p.is_absolute() else Path.cwd() / cli_value)

    core_dir = SRC_DIR / "core"
    candidates += [
        core_dir / "yolov8n.pt",
        SRC_DIR / "yolov8n.pt",
        Path.cwd() / "yolov8n.pt",
    ]

    for c in candidates:
        if c.exists():
            print(f"Using YOLO model file: {c}")
            return c.as_posix()

    print("Local model not found, using default yolov8n.pt (auto-download).")
    return "yolov8n.pt"


# Overlay drawing
def draw_overlay(frame, tracks, alerts, fps: float, safe_occ_ratio: float):
#
#
    for det in tracks:
        x1, y1, x2, y2 = map(int, det["bbox"])
        tid = det["id"]
        color = (0, 200, 255)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        # Label: prefer model class + confidence, fallback to ID
        _name = det.get("label") if isinstance(det, dict) else None
        _conf = det.get("conf") if isinstance(det, dict) else None
        _lab = (f"{_name} {(_conf if _conf is not None else 0):.2f}".strip() if _name else f"ID{tid}")
        t_size = cv2.getTextSize(_lab, 0, fontScale=0.7, thickness=2)[0]
        c2 = (x1 + t_size[0], y1 - t_size[1] - 3)
        cv2.rectangle(frame, (x1, y1), c2, color, -1, cv2.LINE_AA)
        cv2.putText(frame, _lab, (x1, max(0, y1 - 2)), 0, 0.7, (255, 255, 255), 1, cv2.LINE_AA)

#
    if alerts:
        y = 28
        for a in alerts:
            msg = f'[{a["level"]}] T{a["track_id"]} - {a["reason"]}'
            cv2.putText(frame, msg, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            y += 26

#
    cv2.putText(frame, f"{fps:.1f} FPS", (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

#
    h, w = frame.shape[:2]
    frame_area = w * h
    thr_area = frame_area * safe_occ_ratio
    side = int(max(20, thr_area ** 0.5))
    cx = w // 2
    y2 = h - 20
    x1 = max(5, cx - side // 2)
    y1 = max(5, y2 - side)
    cv2.rectangle(frame, (x1, y1), (x1 + side, y2), (50, 220, 50), 2)
    cv2.putText(frame, f"Safety threshold (~{int(safe_occ_ratio * 100)}%)",
                (x1, y1 - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (50, 220, 50), 2)

#
    for det in tracks:
        bx1, by1, bx2, by2 = map(int, det["bbox"])
        occ = ((bx2 - bx1) * (by2 - by1)) / frame_area if frame_area > 0 else 0.0
        bar_h = int((by2 - by1) * min(1.0, occ / safe_occ_ratio))
        bar_x = bx1 - 8
        bar_y = by2 - bar_h
        color = (0, 0, 255) if occ >= safe_occ_ratio else (0, 255, 255)
        cv2.rectangle(frame, (bar_x, by1), (bar_x + 6, by2), (50, 50, 50), -1)
        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + 6, by2), color, -1)
        cv2.putText(frame, f"{int(occ*100)}%", (bar_x - 38, by2 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

async def run(args):
    """
    Connect to the central WebSocket server and stream detections.
    Sends RISK_ALERT messages when risk events are detected.
    """
    # ws_server = WebSocketServer(args.ws_host, args.ws_port)
    # asyncio.create_task(ws_server.start())

    model_path = resolve_model_path(args.model)
    yolo = YOLOProcessor(model_path, conf_thres=args.conf)
    assessor = RiskAssessor()

    # Model class names (for labeling and optional filtering)
    CLASS_NAMES = getattr(yolo.model, "names", None)

    # Optional class filter similar to traffic_accident YOLO_Video.py
    allowed_classes = None
    if getattr(args, "classes", ""):
        try:
            allowed_classes = {c.strip().lower() for c in args.classes.split(",") if c.strip()}
        except Exception:
            allowed_classes = None
    elif isinstance(CLASS_NAMES, (list, dict)):
        values = CLASS_NAMES.values() if isinstance(CLASS_NAMES, dict) else CLASS_NAMES
        if any(str(v).lower() == "accident" for v in values):
            allowed_classes = {"accident"}
            print("[info] 'Accident' class detected. Filtering to 'Accident'. Use --classes to override.")

    server_uri = f"ws://{args.ws_host}:{args.ws_port}"
    print(f"AI client will connect to central server: {server_uri}")

    def results_to_tracks_v2(result):
        """Enhanced conversion with confidence + class-name filtering."""
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

            if det_conf < float(args.conf):
                continue

            det_label = None
            if det_cls is not None and CLASS_NAMES is not None:
                if isinstance(CLASS_NAMES, dict):
                    det_label = str(CLASS_NAMES.get(det_cls, det_cls))
                elif isinstance(CLASS_NAMES, list) and 0 <= det_cls < len(CLASS_NAMES):
                    det_label = str(CLASS_NAMES[det_cls])

            if allowed_classes is not None and det_label is not None and det_label.lower() not in allowed_classes:
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
    try:
        async with websockets.connect(server_uri) as websocket:
            print("Connected to central server.")
            try:
                results = yolo.track_stream(source=args.source)
                for result in results:
                    frame = result.orig_img
                    if frame is None:
                        await asyncio.sleep(0)
                        continue

                    if assessor._frame_w is None:
                        h, w = frame.shape[:2]
                        assessor.set_frame_size(w, h)

                    tracks = results_to_tracks_v2(result)
                    risk = assessor.assess(tracks)
                    alerts = risk["alerts"] if risk else []

                    for a in alerts:
                        payload = {
                            "type": "RISK_ALERT",
                            "ts": time.time(),
                            "level": a["level"],
                            "track_id": a["track_id"],
                            "reason": a["reason"],
                            "bbox": a["bbox"],
                        }
                        print(json.dumps(payload, ensure_ascii=False))
                        await websocket.send(json.dumps(payload, ensure_ascii=False))

                    if SHOW:
                        fps = 1.0 / max(1e-6, time.time() - last_t)
                        last_t = time.time()
                        safe_ratio = getattr(RiskAssessor, "SAFE_OCCUPANCY_FOR_WARN1", 0.08)
                        draw_overlay(frame, tracks, alerts, fps, safe_ratio)
                        cv2.imshow("V2V Risk Monitor", frame)
                        if cv2.waitKey(1) & 0xFF == 27:
                            break

                    await asyncio.sleep(0)

            except Exception as e:
                print(f"[INFO] LoadStreams failed, switching to fallback camera: {e}")
                cap = cv2.VideoCapture(0, cv2.CAP_AVFOUNDATION)
                if not cap.isOpened():
                    raise SystemExit("Fallback camera failed to open")

                while True:
                    ret, frame = cap.read()
                    if not ret:
                        break

                    if assessor._frame_w is None:
                        h, w = frame.shape[:2]
                        assessor.set_frame_size(w, h)

                    result = yolo.model.track(
                        source=frame, conf=yolo.conf_thres,
                        tracker="bytetrack.yaml", stream=False, verbose=False, persist=True
                    )[0]

                    tracks = results_to_tracks_v2(result)
                    risk = assessor.assess(tracks)
                    alerts = risk["alerts"] if risk else []

                    for a in alerts:
                        payload = {
                            "type": "RISK_ALERT",
                            "ts": time.time(),
                            "level": a["level"],
                            "track_id": a["track_id"],
                            "reason": a["reason"],
                            "bbox": a["bbox"],
                        }
                        print(json.dumps(payload, ensure_ascii=False))
                        await websocket.send(json.dumps(payload, ensure_ascii=False))

                    if SHOW:
                        fps = 1.0 / max(1e-6, time.time() - last_t)
                        last_t = time.time()
                        safe_ratio = getattr(RiskAssessor, "SAFE_OCCUPANCY_FOR_WARN1", 0.08)
                        draw_overlay(frame, tracks, alerts, fps, safe_ratio)
                        cv2.imshow("V2V Risk Monitor (Fallback)", frame)
                        if cv2.waitKey(1) & 0xFF == 27:
                            break

                    await asyncio.sleep(0)
                cap.release()
    except Exception as e:
        print(f"AI client could not connect to central server: {e}")
        print(f"Ensure websocket_server.py is running at {server_uri}")

    cv2.destroyAllWindows()

# Entry point
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", type=str, default=None, help="YOLO model path or name")
    ap.add_argument("--source", type=str, default="0", help="Camera index or file path")
    ap.add_argument("--conf", type=float, default=0.25, help="confidence threshold")
    ap.add_argument("--classes", type=str, default="", help="Comma-separated class names to keep (e.g., 'Accident,car')")    # ?????? [??��] ??��??��???? ??��????�� �ּ� (0.0.0.0 -> localhost)
    ap.add_argument("--ws_host", type=str, default="localhost")
    ap.add_argument("--ws_port", type=int, default=8090)
    args = ap.parse_args()

    asyncio.run(run(args))
