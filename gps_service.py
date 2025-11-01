import asyncio
import json
import threading
from datetime import datetime
import uuid
import logging

# Flask (기존)
from flask import Flask, request, render_template_string

# Dash (지도 UI)
import dash
from dash import dcc, html, Input, Output, State
import plotly.graph_objects as go
import math

# WebSocket (기존)
import websockets

# 맵 매칭 (신규)
from map_matcher import MapMatcher 

# --- 1. 설정 ---
MAIN_SERVER_URI = "ws://localhost:8090"
FLASK_PORT = 8000
FLASK_HOST = "0.0.0.0"
INITIAL_CENTER = {'lat': 37.2959, 'lon': 126.8368}
# ⬇️ ★★★ 중요 ★★★ 
# OpenStreetMap에서 다운로드한 .osm 파일 경로를 지정하세요.
OSM_FILE_PATH = "your_map.osm" 
# ⬆️ ★★★ 중요 ★★★

# --- 2. 전역 변수 및 상태 ---
latest_gps_position = {"latitude": None, "longitude": None}
latest_heading_for_gui = {"heading": None}
is_heading_stream_active = False

# ⬇️ 맵 매칭 및 모드 상태
CURRENT_MODE = 'general' # 'general' (일반) 또는 'vehicle' (차량)
map_matcher = MapMatcher(osm_file_path=OSM_FILE_PATH) # 맵 매칭 객체

# --- 3. Flask 서버 및 Dash 앱 초기화 ---
app = Flask(__name__) # Flask 서버가 메인
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# Dash 앱을 Flask 서버 위에서 실행 (url_base_pathname으로 경로 분리)
dash_app = dash.Dash(__name__, server=app, url_base_pathname='/dash/')

# --- 4. Dash 앱 레이아웃 (지도 + 토글) ---
dash_app.layout = html.Div([
    html.H2("실시간 GPS/Heading 관제 대시보드", style={'textAlign': 'center'}),
    
    dcc.Store(id='current-mode-store', data=CURRENT_MODE), # 모드 상태 저장

    html.Div([
        html.H4("모드 선택 (Mode Selection)"),
        dcc.RadioItems(
            id='mode-toggle',
            options=[
                {'label': '🛰️ 일반 모드 (Raw GPS)', 'value': 'general'},
                {'label': '🚗 차량 모드 (Map-Matched)', 'value': 'vehicle'},
            ],
            value=CURRENT_MODE,
            labelStyle={'display': 'block', 'margin': '5px'}
        ),
    ], style={'padding': '20px', 'backgroundColor': '#f4f4f4', 'borderRadius': '5px', 'textAlign': 'center'}),

    dcc.Graph(id='live-map-graph', style={'height': '60vh'}),
    dcc.Graph(id='compass-graph', style={'height': '20vh'}),

    html.Div(id='status-info-panel', style={'padding': '10px', 'fontFamily': 'monospace'}),
    
    dcc.Interval(id='gui-updater', interval=1000), # 1초마다 GUI 업데이트
])

# --- 5. Dash 콜백 (UI 상호작용) ---

# 콜백 1: 모드 토글(RadioItems)을 누르면 -> dcc.Store(상태) 및 전역 변수(CURRENT_MODE) 업데이트
@dash_app.callback(
    Output('current-mode-store', 'data'),
    Input('mode-toggle', 'value')
)
def update_mode(selected_mode):
    global CURRENT_MODE
    CURRENT_MODE = selected_mode
    print(f"🚗 UI에서 모드 변경: {CURRENT_MODE}")
    return selected_mode

# ⬇️ gps_service.py의 이 함수를 통째로 교체하세요. ⬇️

# 콜백 2: 1초마다(gui-updater) -> 지도, 나침반, 텍스트 업데이트
@dash_app.callback(
    Output('live-map-graph', 'figure'),
    Output('compass-graph', 'figure'),
    Output('status-info-panel', 'children'),
    Input('gui-updater', 'n_intervals'),
    State('current-mode-store', 'data') # 현재 모드 상태를 읽어옴
)
def update_gui(n, current_mode):
    lat = latest_gps_position.get('latitude')
    lon = latest_gps_position.get('longitude')
    heading = latest_heading_for_gui.get('heading')
    
    # --- 지도 (Map) ---
    map_fig = go.Figure()
    center = INITIAL_CENTER # (이전에 추가한 변수)
    
    if lat is not None and lon is not None:
        center = {'lat': lat, 'lon': lon} # GPS 수신 시 중심으로 사용
        
        # (Scattermap 트레이스 - 이 부분은 이전 수정이 올바릅니다)
        if current_mode == 'vehicle':
            snap_lat, snap_lon = map_matcher.get_snapped_coordinate(lat, lon)
            map_fig.add_trace(go.Scattermap( 
                lat=[lat], lon=[lon], mode='markers',
                marker=go.scattermap.Marker(size=10, color='blue', opacity=0.5), name='Raw GPS'
            ))
            map_fig.add_trace(go.Scattermap(
                lat=[snap_lat], lon=[snap_lon], mode='markers',
                marker=go.scattermap.Marker(size=12, color='red'), name='Snapped GPS'
            ))
        else:
            map_fig.add_trace(go.Scattermap( 
                lat=[lat], lon=[lon], mode='markers',
                marker=go.scattermap.Marker(size=12, color='blue'), name='Raw GPS'
            ))

    # --- ⬇️ [ 핵심 수정 ] ⬇️ ---
    # 'style', 'zoom', 'center'를 'map' 딕셔너리(dict) 안에 중첩시킵니다.
    map_fig.update_layout(
        map=dict( 
            style="open-street-map",
            zoom=17,
            center=center
        ),
        margin={"r":0,"t":0,"l":0,"b":0},
        showlegend=False
    )
    # --- ⬆️ [ 핵심 수정 ] ⬆️ ---
    
    # --- 나침반 (Compass) ---
    compass_fig = go.Figure()
    if heading is not None:
        compass_fig.add_trace(go.Scatterpolar(
            r=[0, 1], theta=[heading, heading], mode='lines', line=dict(color='red', width=4)
        ))
    compass_fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=False, range=[0, 1]),
            angularaxis=dict(tickvals=[0, 90, 180, 270], ticktext=['N', 'E', 'S', 'W'], direction="clockwise", rotation=90)
        ),
        margin={"r":30,"t":30,"l":30,"b":30}
    )

    # --- 상태 텍스트 (Status) ---
    status_text = f"""
    [Mode]: {current_mode.upper()} {'(도로망에 보정 중)' if current_mode == 'vehicle' else ''}
    [GPS]: {f'{lat:.6f}, {lon:.6f}' if lat else '수신 대기 중...'}
    [Heading]: {f'{heading:.2f}°' if heading else '수신 대기 중...'}
    [Heading Stream (to Unity)]: {'Active' if is_heading_stream_active else 'Inactive'}
    """
    
    return map_fig, compass_fig, html.Pre(status_text)


# --- 6. Flask 엔드포인트 (기존 /data, /add_pinpoint 등) ---
# (Dash UI를 보기 위한 루트 리디렉션)
@app.route("/")
def index():
    return f"""
    <h1>GPS Service v2.0 (with Map)</h1>
    <p><a href="/dash/">[ 실시간 대시보드 접속 ]</a></p>
    <p><a href="/pinpoint/">[ 핀포인트 추가 UI ]</a></p>
    """

@app.route("/data", methods=["POST"])
def receive_data():
    """iPhone 등에서 Raw GPS/Heading 데이터를 수신"""
    global latest_gps_position, latest_heading_for_gui
    try:
        payload = json.loads(request.data).get('payload', [])
        for d in payload:
            sensor_name = d.get("name")
            values = d.get("values", {})
            if sensor_name == "location":
                lat, lon = values.get('latitude'), values.get('longitude')
                if lat is not None and lon is not None:
                    latest_gps_position = {"latitude": lat, "longitude": lon}
            elif sensor_name in ["heading", "compass"]:
                heading = values.get('magneticBearing')
                if heading is not None:
                    latest_heading_for_gui = {"heading": float(heading)}
    except Exception:
        pass
    return "success"

# (핀포인트 UI 및 로직 - 기존과 거의 동일)
@app.route("/pinpoint/", methods=["GET", "POST"])
def add_pinpoint_page():
    if request.method == "POST":
        try:
            message = json.dumps({
                "type": "ADD_PINPOINT",
                "payload": {
                    "id": str(uuid.uuid4()),
                    "latitude": float(request.form['latitude']),
                    "longitude": float(request.form['longitude']),
                    "label": request.form['label']
                }})
            send_ws(message) # WS로 전송
            print(f"✨ 핀포인트 전송: {message}")
            return "핀포인트가 HoloLens로 전송되었습니다. <a href='/pinpoint/'>돌아가기</a>"
        except Exception as e:
            return f"오류 발생: {e}. <a href='/pinpoint/'>돌아가기</a>"
    
    # GET 요청 시 핀포인트 추가 폼 반환
    return render_template_string("""
        <html><head><title>Add Pinpoint</title><meta name="viewport" content="width=device-width, initial-scale=1"></head>
        <body><h2>Pinpoint Controller</h2>
        <form method="post">
            <label>위도 (Latitude):</label><input type="number" step="any" name="latitude" required><br>
            <label>경도 (Longitude):</label><input type="number" step="any" name="longitude" required><br>
            <label>이름 (Label):</label><input type="text" name="label" required><br>
            <button type="submit">HoloLens에 핀포인트 추가</button>
        </form></body></html>
    """)

# ⬇️ (신규) Unity가 모드를 변경하기 위한 엔드포인트
@app.route("/set_mode", methods=["POST"])
def set_mode_http():
    global CURRENT_MODE
    try:
        new_mode = request.form.get('mode')
        if new_mode in ['general', 'vehicle']:
            CURRENT_MODE = new_mode
            print(f"🚗 HTTP로 모드 변경: {CURRENT_MODE}")
            return "Mode set to " + new_mode
        else:
            return "Invalid mode", 400
    except Exception as e:
        return str(e), 500


# --- 7. WebSocket 클라이언트 (Unity와 통신) ---
ws_connection, async_loop = None, None

async def run_websocket_client():
    global ws_connection, async_loop, is_heading_stream_active, CURRENT_MODE
    async_loop = asyncio.get_running_loop()

    while True:
        try:
            async with websockets.connect(MAIN_SERVER_URI) as websocket:
                ws_connection = websocket
                print(f"✅ 메인 서버에 연결됨: {MAIN_SERVER_URI}")

                # 7.1. Consumer (Unity -> Python)
                async def consumer():
                    global is_heading_stream_active, CURRENT_MODE
                    async for message in websocket:
                        try:
                            data = json.loads(message)
                            t = data.get("type")
                            if t == "START_HEADING_UPDATES":
                                is_heading_stream_active = True
                            elif t == "STOP_HEADING_UPDATES":
                                is_heading_stream_active = False
                            
                            # ⬇️ (신규) Unity가 모드 변경을 요청
                            elif t == "SET_MODE":
                                payload = data.get("payload", {})
                                new_mode = payload.get("mode") # "general" or "vehicle"
                                if new_mode in ['general', 'vehicle']:
                                    CURRENT_MODE = new_mode
                                    print(f"🚗 Unity가 모드 변경: {CURRENT_MODE}")
                        except Exception:
                            pass
                
                # 7.2. Producer (Python -> Unity)
                async def producer():
                    while True:
                        payload_to_send = None
                        
                        # (A) GPS 전송 (맵 매칭 적용)
                        if latest_gps_position["latitude"] is not None:
                            raw_lat = latest_gps_position["latitude"]
                            raw_lon = latest_gps_position["longitude"]

                            if CURRENT_MODE == 'vehicle':
                                # 차량 모드: 보정된(Snapped) 좌표 전송
                                snap_lat, snap_lon = map_matcher.get_snapped_coordinate(raw_lat, raw_lon)
                                payload_to_send = {"latitude": snap_lat, "longitude": snap_lon}
                            else:
                                # 일반 모드: 원본(Raw) 좌표 전송
                                payload_to_send = {"latitude": raw_lat, "longitude": raw_lon}
                            
                            gps_message = json.dumps({
                                "type": "GPS_POSITION_UPDATE",
                                "payload": payload_to_send
                            })
                            await websocket.send(gps_message)

                        # (B) Heading 전송 (기존과 동일)
                        if is_heading_stream_active and latest_heading_for_gui["heading"] is not None:
                            heading_message = json.dumps({
                                "type": "HEADING_UPDATE",
                                "payload": latest_heading_for_gui 
                            })
                            await websocket.send(heading_message)

                        await asyncio.sleep(1) # 1초 대기

                await asyncio.gather(consumer(), producer())
        except Exception as e:
            ws_connection = None
            is_heading_stream_active = False
            print(f"메인 서버 연결 실패. 5초 후 재시도... ({e})")
            await asyncio.sleep(5)

# (헬퍼) WS로 메시지 전송
def send_ws(message: str):
    if async_loop and ws_connection:
        asyncio.run_coroutine_threadsafe(ws_connection.send(message), async_loop)
    else:
        print("⚠️ WS 미연결 — 드롭:", message)

# --- 8. 메인 실행 ---
if __name__ == '__main__':
    def run_async():
        asyncio.run(run_websocket_client())
    threading.Thread(target=run_async, daemon=True).start()

    print(f"📡 GPS/Dash 컨트롤러 UI: http://127.0.0.1:{FLASK_PORT}/dash/")
    print(f"📍 핀포인트 추가 UI: http://127.0.0.1:{FLASK_PORT}/pinpoint/")
    print(f"📱 아이폰 데이터 수신: http://<your-ip>:{FLASK_PORT}/data")
    
    # Dash(Flask) 앱 실행
    app.run(port=FLASK_PORT, host=FLASK_HOST, debug=False, use_reloader=False)