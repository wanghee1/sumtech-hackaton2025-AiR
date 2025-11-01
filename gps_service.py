# src/gps_service.py (Dash/MapMatcher 통합 + JSON 파일 동기화 + 시뮬레이터)
import asyncio
import json
import threading
from datetime import datetime
import uuid
import logging
import time  # 시뮬레이션 및 스케줄러용
import socket  # ⭐️ [추가 1/4] UDP 브로드캐스트를 위해 임포트

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
try:
    from map_matcher import MapMatcher
except ImportError:
    print("경고: 'map_matcher.py'를 찾을 수 없습니다. 임시 MapMatcher를 사용합니다.")


    class MapMatcher:
        def __init__(self, **kwargs): pass

        def get_snapped_coordinate(self, lat, lon): return lat, lon

# --- 1. 설정 ---
MAIN_SERVER_URI = "ws://localhost:8090"
FLASK_PORT = 8000
FLASK_HOST = "0.0.0.0"
INITIAL_CENTER = {'lat': 37.2959, 'lon': 126.8368}

OSM_FILE_PATH = "your_map.osm"
INCIDENT_FILE_PATH = "incidents.json"  # ⭐️ 이 파일을 읽습니다
INCIDENT_SYNC_INTERVAL_SECONDS = 60  # 1분 (60초) 설정

LISTENER_BROADCAST_PORT = 9999  # ⭐️ [추가 2/4] tts.py가 듣는 포트 (gps_sender.py와 동일)

# 시뮬레이션 설정
SIM_START_POS = (37.296316, 126.840977)
SIM_END_POS = (37.295551, 126.839124)
SIM_STEPS = 50
SIM_DELAY_SECONDS = 0.7

# --- 2. 전역 변수 및 상태 ---
latest_gps_position = {"latitude": None, "longitude": None}
latest_heading_for_gui = {"heading": None}
is_heading_stream_active = False

CURRENT_MODE = 'general'
try:
    map_matcher = MapMatcher(osm_file_path=OSM_FILE_PATH)
except Exception:
    print(f"경고: OSM 파일 '{OSM_FILE_PATH}' 로드 실패. 임시 MapMatcher를 사용합니다.")


    class TempMapMatcher:
        def __init__(self, **kwargs): pass

        def get_snapped_coordinate(self, lat, lon): return lat, lon


    map_matcher = TempMapMatcher()

known_pin_ids = set()

# --- 3. Flask 서버 및 Dash 앱 초기화 ---
app = Flask(__name__)
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)
dash_app = dash.Dash(__name__, server=app, url_base_pathname='/dash/')

# --- 4. Dash 앱 레이아웃 ---
# ... (Dash 레이아웃 코드는 수정 없음) ...
dash_app.layout = html.Div([
    html.H2("실시간 GPS/Heading 관제 대시보드", style={'textAlign': 'center'}),
    dcc.Store(id='current-mode-store', data=CURRENT_MODE),
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
    dcc.Interval(id='gui-updater', interval=1000),
])


# --- 5. Dash 콜백 ---
# ... (Dash 콜백은 수정 없음) ...
@dash_app.callback(
    Output('current-mode-store', 'data'),
    Input('mode-toggle', 'value')
)
def update_mode(selected_mode):
    global CURRENT_MODE
    CURRENT_MODE = selected_mode
    print(f"🚗 UI에서 모드 변경: {CURRENT_MODE}")
    return selected_mode


@dash_app.callback(
    Output('live-map-graph', 'figure'),
    Output('compass-graph', 'figure'),
    Output('status-info-panel', 'children'),
    Input('gui-updater', 'n_intervals'),
    State('current-mode-store', 'data')
)
def update_gui(n, current_mode):
    lat = latest_gps_position.get('latitude')
    lon = latest_gps_position.get('longitude')
    heading = latest_heading_for_gui.get('heading')

    map_fig = go.Figure()
    center = INITIAL_CENTER

    if lat is not None and lon is not None:
        center = {'lat': lat, 'lon': lon}
        map_fig.add_trace(go.Scattermap(
            lat=[lat], lon=[lon], mode='markers',
            marker=go.scattermap.Marker(size=12, color='red' if current_mode == 'vehicle' else 'blue'),
            name='Current GPS'
        ))
    map_fig.update_layout(
        map=dict(style="open-street-map", zoom=17, center=center),
        margin={"r": 0, "t": 0, "l": 0, "b": 0},
        showlegend=False
    )

    compass_fig = go.Figure()
    if heading is not None:
        compass_fig.add_trace(go.Scatterpolar(
            r=[0, 1], theta=[heading, heading], mode='lines', line=dict(color='red', width=4)
        ))
    compass_fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=False, range=[0, 1]),
            angularaxis=dict(tickvals=[0, 90, 180, 270], ticktext=['N', 'E', 'S', 'W'], direction="clockwise",
                             rotation=90)
        ),
        margin={"r": 30, "t": 30, "l": 30, "b": 30}
    )
    status_text = f"""
    [Mode]: {current_mode.upper()} {'(도로망에 보정 중)' if current_mode == 'vehicle' else ''}
    [GPS]: {f'{lat:.6f}, {lon:.6f}' if lat else '수신 대기 중...'}
    [Heading]: {f'{heading:.2f}°' if heading else '수신 대기 중...'}
    [Heading Stream (to Unity)]: {'Active' if is_heading_stream_active else 'Inactive'}
    """
    return map_fig, compass_fig, html.Pre(status_text)


# --- 6. Flask 엔드포인트 ---

# ... (index 라우트는 수정 없음) ...
@app.route("/")
def index():
    return f"""
    <style>
        body {{ font-family: sans-serif; padding: 20px; }}
        h1 {{ color: #333; }}
        a, button {{ display: block; margin-bottom: 15px; font-size: 1.2em; padding: 10px; text-decoration: none; border-radius: 5px; }}
        a {{ background-color: #007bff; color: white; text-align: center; }}
        button {{ background-color: #28a745; color: white; border: none; cursor: pointer; width: 300px; }}
        a.sim-button {{ background-color: #ffc107; color: black; }}
    </style>
    <h1>GPS Service v2.0 (with Map)</h1>
    <a href="/dash/">[ 1. 실시간 대시보드 접속 ]</a>
    <a href="/pinpoint/">[ 2. (수동) 핀포인트 추가 UI ]</a>
    <hr>
    <form action="/load_incidents" method="POST">
        <button type="submit">
            [ 3. (수동) 'incidents.json' 파일 동기화 ]
        </button>
    </form>
    <p>ℹ️ <em>'incidents.json' 파일은 {INCIDENT_SYNC_INTERVAL_SECONDS}초마다 자동으로 동기화됩니다.</em></p>
    <hr>
    <a href="/run_sim" class="sim-button">[ 4. (TEST) 가상 GPS 시뮬레이션 시작 ]</a>
    """


# ⭐️ --- [/data 엔드포인트 수정됨] --- ⭐️
@app.route("/data", methods=["POST"])
def receive_data():
    global latest_gps_position, latest_heading_for_gui, CURRENT_MODE
    try:
        payload = json.loads(request.data).get('payload', [])
        for d in payload:
            sensor_name = d.get("name")
            values = d.get("values", {})
            if sensor_name == "location":
                lat, lon = values.get('latitude'), values.get('longitude')
                if lat is not None and lon is not None:
                    final_lat, final_lon = lat, lon
                    if CURRENT_MODE == 'vehicle':
                        snap_lat, snap_lon = map_matcher.get_snapped_coordinate(lat, lon)
                        final_lat, final_lon = snap_lat, snap_lon

                    # 1. (기존) 대시보드 및 Unity용 전역 변수 업데이트
                    latest_gps_position = {"latitude": final_lat, "longitude": final_lon}

                    # ⭐️ [추가 4/4]
                    # 2. (신규) 아이폰에서 받은 실제 데이터를 tts.py로 즉시 브로드캐스트
                    send_gps_to_listeners(final_lat, final_lon)
                    # ⭐️ --- [수정 끝] --- ⭐️

            elif sensor_name in ["heading", "compass"]:
                heading = values.get('magneticBearing')
                if heading is not None:
                    latest_heading_for_gui = {"heading": float(heading)}
    except Exception:
        pass
    return "success"


# ⭐️ --- [수정 끝] --- ⭐️


#
# [수정] /pinpoint/ (수동 추가) UI 및 로직 (int)
#
@app.route("/pinpoint/", methods=["GET", "POST"])
def add_pinpoint_page():
    if request.method == "POST":
        try:
            pin_type = 0
            pin_title = request.form['label']
            color_type = int(request.form['color_type'])  # ◀◀◀ 폼에서 받은 값을 int로 변환

            message = json.dumps({
                "type": "ADD_PINPOINT",
                "payload": {
                    "id": str(uuid.uuid4()),
                    "latitude": float(request.form['latitude']),
                    "longitude": float(request.form['longitude']),
                    "label": pin_title,
                    "type": pin_type,
                    "title": pin_title,
                    "color_type": color_type  # ◀◀◀ int 값이 그대로 들어감
                }})
            send_ws(message)
            print(f"✨ 수동 핀포인트 전송: {message}")
            return "핀포인트가 HoloLens로 전송되었습니다. <a href='/pinpoint/'>돌아가기</a>"
        except Exception as e:
            return f"오류 발생: {e}. <a href='/pinpoint/'>돌아가기</a>"

    # ◀◀◀ HTML 폼을 number 타입으로 변경, 기본값 0
    return render_template_string("""
        <html><head><title>Add Pinpoint</title><meta name="viewport" content="width=device-width, initial-scale=1"></head>
        <body><h2>Pinpoint Controller</h2>
        <form method="post">
            <label>위도 (Latitude):</label><input type="number" step="any" name="latitude" required><br>
            <label>경도 (Longitude):</label><input type="number" step="any" name="longitude" required><br>
            <label>이름 (Label):</label><input type="text" name="label" required><br>
            <label>컬러 타입 (Color_Type):</label><input type="number" name="color_type" value="0" required><br>
            <button type="submit">HoloLens에 핀포인트 추가</button>
        </form></body></html>
    """)


# ... (set_mode 라우트는 수정 없음) ...
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


# ⭐️ --- [sync_incidents 함수 수정됨] --- ⭐️
def sync_incidents():
    """
    incidents.json 파일을 읽고,
    Unity/HoloLens로 ADD_PINPOINT/REMOVE_PINPOINT 페이로드를 전송합니다.
    """
    global known_pin_ids

    try:
        with open(INCIDENT_FILE_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # ⭐️ [수정] 'incidents.json'이 리스트([..])인지 객({"incidents": [..]})인지 확인
        incidents = []
        if isinstance(data, list):
            incidents = data  # ⭐️ 제공된 incidents.json (리스트)을 직접 사용
        elif isinstance(data, dict):
            incidents = data.get("incidents", [])  # ⭐️ 기존 방식 (객체) 호환
        else:
            raise Exception("JSON 형식이 'list' 또는 'dict'가 아닙니다.")
        # ⭐️ [수정 끝]

        new_pin_ids = set()
        add_count, update_count, remove_count = 0, 0, 0

        for incident in incidents:
            incident_id = incident.get("id")
            if not incident_id: continue

            new_pin_ids.add(incident_id)

            pin_type = incident.get('type', 0)
            pin_title = incident.get('title', 'N/A')
            color_type = incident.get('color_type', 0)

            label = f"[유형 {pin_type}] {pin_title}"

            # ⭐️ Unity/HoloLens로 보낼 페이로드 (ADD_PINPOINT)
            message = json.dumps({
                "type": "ADD_PINPOINT",
                "payload": {
                    "id": incident.get("id"),
                    "latitude": float(incident.get("latitude")),
                    "longitude": float(incident.get("longitude")),
                    "label": label,
                    "type": pin_type,
                    "title": pin_title,
                    "color_type": color_type
                }})
            send_ws(message)  # ⭐️ 웹소켓으로 페이로드 전송

            if incident_id not in known_pin_ids:
                add_count += 1
            else:
                update_count += 1

        ids_to_remove = known_pin_ids - new_pin_ids
        for pin_id in ids_to_remove:
            message = json.dumps({"type": "REMOVE_PINPOINT", "payload": {"id": pin_id}})
            send_ws(message)
            remove_count += 1

        known_pin_ids = new_pin_ids
        result_msg = f"'{INCIDENT_FILE_PATH}' 동기화: 추가({add_count}), 수정({update_count}), 삭제({remove_count})"
        print(f"✨ [Sync] {result_msg}")
        return result_msg, True

    except FileNotFoundError:
        msg = f"⚠️ [Sync] {INCIDENT_FILE_PATH} 파일을 찾을 수 없습니다."
        print(msg)
        return msg, False
    except Exception as e:
        msg = f"⚠️ [Sync] JSON 핀 로딩 중 오류: {e}"
        print(msg)
        return msg, False


# ⭐️ --- [수정 끝] --- ⭐️


# ... (load_incidents_from_file 라우트는 수정 없음) ...
@app.route("/load_incidents", methods=["POST"])
def load_incidents_from_file():
    result_msg, success = sync_incidents()

    if success:
        return f"{result_msg} <br><a href='/'>돌아가기</a>"
    else:
        if "파일을 찾을 수 없습니다" in result_msg:
            return f"오류: {result_msg} <a href='/'>돌아가기</a>", 404
        else:
            return f"오류 발생: {result_msg} <a href='/'>돌아가기</a>", 500


# ... (시뮬레이션 관련 코드는 수정 없음) ...
def generate_gps_route(start_pos, end_pos, steps):
    route = []
    start_lat, start_lon = start_pos
    end_lat, end_lon = end_pos
    lat_increment = (end_lat - start_lat) / steps
    lon_increment = (end_lon - start_lon) / steps
    for i in range(steps + 1):
        current_lat = start_lat + lat_increment * i
        current_lon = start_lon + lon_increment * i
        route.append((current_lat, current_lon))
    return route


@app.route("/add_temp_pin", methods=["POST"])
def add_temp_pin_http():
    """
    p2p_client.py가 이 엔드포인트를 호출하면,
    즉시 Unity로 ADD_PINPOINT 웹소켓 메시지를 전송합니다.
    (JSON 파일에 저장하지 않음)
    """
    try:
        data = request.json
        if not data or 'latitude' not in data or 'longitude' not in data:
            return "Invalid data", 400

        lat = float(data.get("latitude"))
        lon = float(data.get("longitude"))
        level = int(data.get("level", 0))  # p2p_client가 보낸 경고 레벨

        if level == 1:
            title = "주의"
            color_type = 1
        elif level >= 2:
            title = "경고"
            color_type = 2
        else:
            title = "알림"
            color_type = 0

        pin_id = f"TEMP_PIN_{str(uuid.uuid4())[:8]}"
        label = f"[경고: {level}] {title}"

        message = json.dumps({
            "type": "ADD_PINPOINT",
            "payload": {
                "id": pin_id,
                "latitude": lat,
                "longitude": lon,
                "label": label,
                "type": 99,  # 임시 핀 타입을 99로 지정
                "title": title,
                "color_type": color_type
            }
        })

        send_ws(message)
        print(f"✨ [HTTP] 임시 핀 즉시 전송: {pin_id}")
        return "Temp Pin Sent", 200

    except Exception as e:
        print(f"⚠️ /add_temp_pin 오류: {e}")
        return str(e), 500


def run_simulation_thread():
    global latest_gps_position, CURRENT_MODE

    print(f"--- GPS 시뮬레이션 스레드 시작 ---")
    route = generate_gps_route(SIM_START_POS, SIM_END_POS, SIM_STEPS)

    for (lat, lon) in route:
        final_lat, final_lon = lat, lon
        if CURRENT_MODE == 'vehicle':
            snap_lat, snap_lon = map_matcher.get_snapped_coordinate(lat, lon)
            final_lat, final_lon = snap_lat, snap_lon
        latest_gps_position = {"latitude": final_lat, "longitude": final_lon}

        # ⭐️ 시뮬레이터도 tts.py로 브로드캐스트
        send_gps_to_listeners(final_lat, final_lon)

        print(f"Sim Update Global: lat={final_lat:.6f}, lon={final_lon:.6f}")
        time.sleep(SIM_DELAY_SECONDS)

    print(f"--- GPS 시뮬레이션 스레드 완료 ---")


@app.route("/run_sim")
def start_simulation_route():
    print("🖥️ 웹 UI에서 가상 GPS 시뮬레이션 요청 수신")
    sim_thread = threading.Thread(target=run_simulation_thread, daemon=True)
    sim_thread.start()

    return "가상 GPS 시뮬레이션을 시작합니다... (Unity/Dash보드 확인) <br><a href='/'>돌아가기</a>"


# ... (background_incident_scheduler 스케줄러는 수정 없음) ...
def background_incident_scheduler():
    print(f"--- 'incidents.json' 자동 동기화 스레드 시작 (주기: {INCIDENT_SYNC_INTERVAL_SECONDS}초) ---")
    while True:
        time.sleep(INCIDENT_SYNC_INTERVAL_SECONDS)
        print(f"⏰ {INCIDENT_SYNC_INTERVAL_SECONDS}초 스케줄러: 'incidents.json' 자동 동기화 시작...")
        sync_incidents()

    # --- 7. WebSocket 클라이언트 (Unity와 통신) ---


# ... (WebSocket 관련 코드는 수정 없음) ...
ws_connection, async_loop = None, None


async def run_websocket_client():
    global ws_connection, async_loop, is_heading_stream_active, CURRENT_MODE
    async_loop = asyncio.get_running_loop()
    while True:
        try:
            async with websockets.connect(MAIN_SERVER_URI) as websocket:
                ws_connection = websocket
                print(f"✅ 메인 서버에 연결됨: {MAIN_SERVER_URI}")

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
                            elif t == "SET_MODE":
                                payload = data.get("payload", {})
                                new_mode = payload.get("mode")
                                if new_mode in ['general', 'vehicle']:
                                    CURRENT_MODE = new_mode
                                    print(f"🚗 Unity가 모드 변경: {CURRENT_MODE}")
                        except Exception:
                            pass

                async def producer():
                    while True:
                        if latest_gps_position["latitude"] is not None:
                            gps_message = json.dumps({
                                "type": "GPS_POSITION_UPDATE",
                                "payload": latest_gps_position
                            })
                            await websocket.send(gps_message)

                        if is_heading_stream_active and latest_heading_for_gui["heading"] is not None:
                            heading_message = json.dumps({
                                "type": "HEADING_UPDATE",
                                "payload": latest_heading_for_gui
                            })
                            await websocket.send(heading_message)

                        await asyncio.sleep(0.25)

                await asyncio.gather(consumer(), producer())
        except Exception as e:
            ws_connection = None
            is_heading_stream_active = False
            print(f"메인 서버 연결 실패. 5초 후 재시도... ({e})")
            await asyncio.sleep(5)


# --- 8. 헬퍼 및 메인 실행 ---

# ⭐️ [추가 3/4] gps_sender.py에서 가져온 브로드캐스트 함수
def send_gps_to_listeners(lat: float, lon: float):
    """
    TTS 청취자(tts.py)에게 GPS 데이터를 브로드캐스트합니다.
    """
    try:
        # 브로드캐스트 소켓 생성
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # 브로드캐스트 옵션 활성화
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

            # 보낼 데이터 (tts.py가 읽는 형식)
            data = {"latitude": lat, "longitude": lon}

            s.sendto(json.dumps(data).encode('utf-8'), ("<broadcast>", LISTENER_BROADCAST_PORT))
        return True
    except Exception as e:
        # print(f"UDP 브로드캐스트 전송 실패: {e}") # 로그가 너무 많이 찍히는 것을 방지
        return False


# ... (send_ws 헬퍼는 수정 없음) ...
def send_ws(message: str):
    if async_loop and ws_connection:
        asyncio.run_coroutine_threadsafe(ws_connection.send(message), async_loop)
    else:
        print("⚠️ WS 미연결 — 드롭:", message)


# ... (if __name__ == '__main__' 블록은 수정 없음) ...
if __name__ == '__main__':
    def run_async():
        asyncio.run(run_websocket_client())


    threading.Thread(target=run_async, daemon=True).start()

    threading.Thread(target=background_incident_scheduler, daemon=True).start()

    print("--- 서버 시작 ---")
    print(f"📡 GPS/Dash 컨트롤러 UI: http://127.0.0.1:{FLASK_PORT}/dash/")
    print(f"📍 핀포인트 추가 UI: http://127.0.0.1:{FLASK_PORT}/pinpoint/")
    print(f"📱 아이폰 데이터 수신: http://<your-ip>:{FLASK_PORT}/data (TTS 브로드캐스트 활성화됨)")
    print(f"🛰️  [시뮬레이터] 실행: http://127.0.0.1:{FLASK_PORT}/run_sim")
    print(f"⏰ 'incidents.json' 자동 동기화 활성화 (주기: {INCIDENT_SYNC_INTERVAL_SECONDS}초)")

    app.run(port=FLASK_PORT, host=FLASK_HOST, debug=False, use_reloader=False)