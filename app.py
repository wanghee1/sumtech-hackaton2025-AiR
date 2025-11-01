import os
import re
import math
import time
import json
import xml.etree.ElementTree as ET
from typing import Dict, Any, List
from typing import Optional, Tuple
from flask import Flask, jsonify, request
from flask_cors import CORS
from dash import Dash, dcc, html
from dash.dependencies import Input, Output
import plotly.graph_objects as go

# ───────────── 설정 ─────────────
DATA_FILE_PATH = "result.txt"
FILE_CACHE_TTL = int(os.getenv("FILE_CACHE_TTL", "15"))
DEFAULT_RADIUS_KM = float(os.getenv("DEFAULT_RADIUS_KM", "3"))
DEFAULT_TOPK = int(os.getenv("DEFAULT_TOPK", "5"))
ROAD_ACCIDENTS_FILE = "incidents.json"

# ───────────── 앱 초기화 ─────────────
app = Flask(__name__)
CORS(app)
app.config['JSON_AS_ASCII'] = False  # ⭐️ 한글 인코딩(`\uXXXX`) 방지

USER_POS: Dict[str, Dict[str, Any]] = {}
last_gps_position = {"latitude": None, "longitude": None}
_last_file_read_ts = 0.0
_all_file_items: List[Dict[str, Any]] = []


# ───────────── 유틸 ─────────────
def _to_float(x) -> Optional[float]:
    try:
        if x is None: return None
        v = float(str(x).strip())
        return v if math.isfinite(v) else None
    except Exception:
        return None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(min(1, math.sqrt(a)))


def map_incident_type_to_level_and_color(incident_type: str) -> Tuple[int, int]:
    if incident_type == "1":
        return (1, 1)  # 사고
    elif incident_type == "2":
        return (2, 2)  # 공사
    elif incident_type == "3":
        return (3, 3)  # 행사
    elif incident_type == "4":
        return (4, 0)  # 기상
    elif incident_type == "5":
        return (2, 2)  # 통제
    elif incident_type == "6":
        return (1, 1)  # 재난
    else:
        return (7, 0)  # 기타


# ───────────── 데이터 수집 함수 ─────────────
# ⭐️ [수정 1/3] force_refresh 파라미터 추가
def get_all_accidents_from_file(force_refresh: bool = False) -> List[Dict[str, Any]]:
    global _last_file_read_ts, _all_file_items
    now = time.time()

    # 1. ⭐️ [수정 2/3] 캐시 확인 시 force_refresh 조건 추가
    if not force_refresh and _all_file_items and (now - _last_file_read_ts) < FILE_CACHE_TTL:
        return _all_file_items

    # ⭐️ 캐시를 사용하지 않거나 만료되었다면 파일 읽기
    if force_refresh:
        print(f"[LOCAL] Forcing cache refresh for TTS...")
    else:
        print(f"[LOCAL] Reading XML data from file: {DATA_FILE_PATH}")

    items: List[Dict[str, Any]] = []

    try:
        # 2. ⭐️ [변경] 파일을 읽고 XML로 파싱합니다.
        with open(DATA_FILE_PATH, 'r', encoding='utf-8') as f:
            content = f.read()
        root = ET.fromstring(content)

        def gt(node, *names):
            for n in names:
                v = node.findtext(n)
                if v is not None and str(v).strip() != "": return str(v).strip()
            return ""

        # 3. XML 파싱
        for it in root.findall(".//record"):
            lat_val = _to_float(gt(it, "locationDataY"))
            lon_val = _to_float(gt(it, "locationDataX"))
            if lat_val is None or lon_val is None: continue

            _id = gt(it, "incidentId")
            title = gt(it, "incidentTitle")
            itype = gt(it, "incidenteTypeCd")

            level, color = map_incident_type_to_level_and_color(itype)

            try:
                itype_int = int(itype)
            except (ValueError, TypeError):
                itype_int = 7  # 파싱 실패 시 '기타'로 처리

            items.append({
                "id": _id,
                "type": itype_int,
                "title": title,
                "latitude": lat_val,
                "longitude": lon_val,
                "color_type": color
            })

        _all_file_items, _last_file_read_ts = items, now
        print(f"[LOCAL] Loaded {len(_all_file_items)} items from file.")
        return _all_file_items

    except FileNotFoundError:
        print(f"[LOCAL] Error: Data file not found at '{DATA_FILE_PATH}'")
    except ET.ParseError as e:  # ⭐️ [변경] XML 파싱 오류를 잡습니다.
        print(f"[LOCAL] Error: Failed to parse XML from '{DATA_FILE_PATH}'. Error: {e}")
        print(" -> result.txt 파일이 순수한 <result>...</result> 형식이 맞는지 확인하세요.")
    except Exception as e:
        print(f"[LOCAL] Error reading file: {e}")

    _all_file_items, _last_file_read_ts = [], now  # 오류 시 캐시 비우기
    return []  # ⭐️ 오류 시 빈 리스트 반환


# ───────────── ⭐️ [수정된] Flask 라우팅 ─────────────

@app.route("/data", methods=["POST"])
def receive_data():
    """ (Dash보드용) GPS 데이터를 받아서 최신 위치 저장 """
    global last_gps_position
    try:
        payload = json.loads(request.data).get('payload', [])
        for d in payload:
            if d.get("name") == "location":
                values = d.get("values", {})
                lat, lon = values.get('latitude'), values.get('longitude')
                if lat is not None and lon is not None:
                    last_gps_position = {"latitude": lat, "longitude": lon}
    except Exception:
        pass
    return "success"


@app.route("/api/nearby", methods=["GET"])
def api_nearby():
    """
    [수정] 특정 좌표 반경 내 사고 데이터를 'incident.json' 파일로 *저장*만 합니다.
    (이 엔드포인트는 기존 15초 캐시를 계속 사용합니다.)
    """
    user_lat = float(request.args.get("latitude", 37.6155))
    user_lon = float(request.args.get("longitude", 127.0703))
    radius = float(request.args.get("radius", 3))

    all_incidents = get_all_accidents_from_file()  # force_refresh=False (기본값)

    filtered_items = [
        item for item in all_incidents
        if haversine_km(user_lat, user_lon, item["latitude"], item["longitude"]) <= radius
    ]

    try:
        with open(ROAD_ACCIDENTS_FILE, "w", encoding="utf-8") as f:
            json.dump(filtered_items, f, ensure_ascii=False, indent=4)
        print(f"\n[NEARBY] {len(filtered_items)}건을 '{ROAD_ACCIDENTS_FILE}'에 저장했습니다.")
        return jsonify({"ok": True, "message": f"Saved {len(filtered_items)} items to {ROAD_ACCIDENTS_FILE}"})

    except Exception as e:
        print(f"Error writing to {ROAD_ACCIDENTS_FILE}: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


# ⭐️ --- [새로 추가된 엔드포인트 (TTS 전용)] --- ⭐️
@app.route("/api/tts_nearby", methods=["GET"])
def api_tts_nearby():
    """
    [수정] TTS용 엔드포인트. 캐시를 무시하고 항상 최신 데이터를 읽어 JSON으로 즉시 반환합니다.
    """

    # ⭐️ [수정] tts.py가 보내는 'lat', 'lon' 파라미터를 받음
    user_lat = float(request.args.get("lat", 37.6155))
    user_lon = float(request.args.get("lon", 127.0703))
    radius = float(request.args.get("radius", 3))
    k = int(request.args.get("k", DEFAULT_TOPK))

    # 1. ⭐️ [수정 3/3] force_refresh=True로 설정하여 캐시 무시
    all_incidents = get_all_accidents_from_file(force_refresh=True)

    # 2. 반경 내 사고만 필터링 (app.py v1의 nearest_items 로직과 동일)
    ranked_items = []
    for item in all_incidents:
        d = haversine_km(user_lat, user_lon, item["latitude"], item["longitude"])
        if d <= radius:
            item_with_dist = dict(item)
            item_with_dist["distance_km"] = round(d, 3)
            ranked_items.append((d, item_with_dist))

    ranked_items.sort(key=lambda t: t[0])
    final_items = [t[1] for t in ranked_items[:k]]

    print(f"\n[TTS_NEARBY] {len(final_items)}건의 데이터를 TTS 클라이언트로 반환합니다.")

    # 3. ⭐️ tts.py가 필요한 JSON 형식으로 즉시 반환
    return jsonify({
        "ok": True,
        "incidents": final_items,
        "ts": time.time(),
        "center": {"lat": user_lat, "lon": user_lon}
    })


# ⭐️ --- [추가 끝] --- ⭐️


# ───────────── Dash 앱 설정 ─────────────
dash_app = Dash(__name__, server=app, url_base_pathname='/dash/')
# ... (Dash 앱 레이아웃 및 콜백 코드는 변경 없음) ...
dash_app.layout = html.Div([
    html.H2("실시간 GPS 지도"),
    dcc.Graph(id='live-map-graph', style={'height': '60vh'}),
    dcc.Interval(id='update-interval', interval=1000),
])


@dash_app.callback(
    Output('live-map-graph', 'figure'),
    Input('update-interval', 'n_intervals'),
)
def update_map(n):
    lat = last_gps_position.get('latitude')
    lon = last_gps_position.get('longitude')
    map_fig = go.Figure()
    if lat is not None and lon is not None:
        map_fig.add_trace(go.Scattermapbox(
            lat=[lat], lon=[lon],
            mode='markers',
            marker=go.scattermapbox.Marker(size=12, color='blue'),
            name="GPS Position"
        ))
    map_fig.update_layout(
        mapbox=dict(
            style="open-street-map",
            center=dict(lat=lat or 37.2959, lon=lon or 126.8368),
            zoom=12
        ),
        margin={"r": 0, "t": 0, "l": 0, "b": 0},
        showlegend=False
    )
    return map_fig


# ───────────── 앱 실행 ─────────────
if __name__ == "__main__":
    print(f"[BOOT] ⭐️ Data Source: Local File '{DATA_FILE_PATH}'")
    print(f"[BOOT] FILE_CACHE_TTL={FILE_CACHE_TTL}s (TTS 요청은 캐시 무시)")
    # ⭐️ 로컬PC에서만 접속 가능하도록 127.0.0.1로 실행 (보안)
    app.run(host="0.0.0.0", port=8070, debug=False)