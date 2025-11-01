import os
import re
import math
import time
import json
import requests
import xml.etree.ElementTree as ET
from typing import Dict, Any, List
from typing import Optional, Tuple
from flask import Flask, jsonify, request
from flask_cors import CORS
from dash import Dash, dcc, html
from dash.dependencies import Input, Output
import plotly.graph_objects as go

# ───────────── 설정 ─────────────
DEFAULT_UTIC_KEY = "omgkB5RKRHSerjxkGIvchgMXWe9z3nvEbUFg1xGI"
UTIC_API_KEY = re.sub(r"\s+", "", os.getenv("UTIC_API_KEY", DEFAULT_UTIC_KEY))

USE_JSON_ENDPOINT = os.getenv("UTIC_USE_JSON", "0") == "1"
UTIC_URL = "http://www.utic.go.kr/guide/getRoadAccJson.do" if USE_JSON_ENDPOINT \
            else "http://www.utic.go.kr/guide/imsOpenData.do"

UTIC_CACHE_TTL = int(os.getenv("UTIC_CACHE_TTL", "15"))
DEFAULT_RADIUS_KM = float(os.getenv("DEFAULT_RADIUS_KM", "3"))
DEFAULT_TOPK = int(os.getenv("DEFAULT_TOPK", "5"))
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "10"))

ROAD_ACCIDENTS_FILE = "incident.json" 

app = Flask(__name__)
CORS(app)

USER_POS: Dict[str, Dict[str, Any]] = {}
last_gps_position = {"latitude": None, "longitude": None}

def _to_float(x) -> Optional[float]:
    try:
        if x is None: return None
        v = float(str(x).strip())
        return v if math.isfinite(v) else None
    except Exception:
        return None

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine 공식: 두 GPS 좌표 사이의 거리를 계산합니다."""
    R = 6371.0  # 지구 반경 (킬로미터)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    return 2 * R * math.asin(min(1, math.sqrt(a)))

def map_incident_type_to_level_and_color(incident_type: str) -> Tuple[int, int]:
    """사고 종류에 따른 색상 및 등급 설정"""
    if incident_type == "1":  # 사고
        return (1, 1)  # 빨간색
    elif incident_type == "2":  # 공사
        return (2, 2)  # 노란색
    elif incident_type == "3":  # 행사
        return (3, 3)  # 초록색
    elif incident_type == "4":  # 기상
        return (4, 0)  # 흰색
    elif incident_type == "5":  # 통제
        return (2, 2)  # 노란색
    elif incident_type == "6":  # 재난
        return (1, 1)  # 빨간색
    elif incident_type == "7":  # 기타
        return (7, 0)  # 흰색
    else:
        return (7, 0)  # 기본적으로 흰색

# ───────────── UTIC 데이터 수집 ─────────────
def get_road_accidents_within_radius(lat: float, lon: float, radius: float) -> List[Dict[str, Any]]:
    """특정 좌표 반경 내 사고 데이터 가져오기"""
    try:
        r = requests.get(UTIC_URL, params={"key": UTIC_API_KEY}, timeout=REQUEST_TIMEOUT,
                        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        if r.status_code != 200 or not r.content:
            return []

        root = ET.fromstring(r.content)
        nodes = root.findall(".//record")
        items = []

        for it in nodes:
            lat_val = _to_float(it.findtext(".//locationDataY"))
            lon_val = _to_float(it.findtext(".//locationDataX"))
            if lat_val is None or lon_val is None:
                continue
            _id = it.findtext(".//incidentId").strip()
            title = it.findtext(".//incidentTitle").strip()
            itype = it.findtext(".//incidenteTypeCd").strip()
            level, color = map_incident_type_to_level_and_color(itype)
            items.append({
                "id": _id, "type": itype, "title": title,
                "latitude": lat_val, "longitude": lon_val,
                "color_type": color
            })

        # 반경 내 사고만 필터링
        filtered_items = [item for item in items if haversine_km(lat, lon, item["latitude"], item["longitude"]) <= radius]

        # 파일로 저장
        with open(ROAD_ACCIDENTS_FILE, "w", encoding="utf-8") as f:
            json.dump(filtered_items, f, ensure_ascii=False, indent=4)

        return filtered_items

    except Exception as e:
        print(f"Error: {e}")
        return []

# ───────────── Flask 라우팅 ─────────────
@app.route("/data", methods=["POST"])
def receive_data():
    """GPS 데이터를 받아서 최신 위치 저장"""
    global last_gps_position
    try:
        payload = json.loads(request.data).get('payload', [])
        for d in payload:
            sensor_name = d.get("name")
            values = d.get("values", {})
            if sensor_name == "location":
                lat, lon = values.get('latitude'), values.get('longitude')
                if lat is not None and lon is not None:
                    # 사용자 gps 위도 경도 
                    last_gps_position = {"latitude": lat, "longitude": lon}
    except Exception as e:
        print(f"Error: {e}")
    return "success"

@app.route("/api/nearby", methods=["GET"])
def api_nearby():
    """반경 내 사고 정보 제공"""
    user_lat = float(request.args.get("latitude", 37.6155))
    user_lon = float(request.args.get("longitude", 127.0703))
    radius = float(request.args.get("radius", 3))

    incidents = get_road_accidents_within_radius(user_lat, user_lon, radius)
    return jsonify({"ok": True, "incidents": incidents[:DEFAULT_TOPK], "ts": time.time()})

# ───────────── Dash 앱 설정 ─────────────
dash_app = Dash(__name__, server=app, url_base_pathname='/dash/')
dash_app.layout = html.Div([
    html.H2("실시간 GPS 지도"),
    dcc.Graph(id='live-map-graph', style={'height': '60vh'}),
    dcc.Interval(id='update-interval', interval=1000),  # 1초마다 업데이트
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
        margin={"r":0,"t":0,"l":0,"b":0},
        showlegend=False
    )

    return map_fig

# ───────────── 앱 실행 ─────────────
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)
