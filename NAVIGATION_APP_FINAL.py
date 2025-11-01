import dash
from dash import dcc, html, Input, Output
import plotly.graph_objects as go
from flask import Flask, request
from datetime import datetime
import math
import json
import uuid # 사용자 ID 생성을 위해 uuid 라이브러리 import

# --- Dash 앱 초기화 ---
app = dash.Dash(__name__)
server = app.server

# --- 앱 실행 시 고유한 사용자 ID 생성 ---
# 이 ID는 앱이 실행되는 동안 계속 유지됩니다.
USER_ID = str(uuid.uuid4())

# --- 지도 초기 중심 위치 (한양대 에리카) ---
INITIAL_CENTER = {'lat': 37.2959, 'lon': 126.8368}
INITIAL_ZOOM = 15

# --- 실시간 데이터 저장을 위한 변수 ---
latest_data = {
    'latitude': None, 'longitude': None, 'fused_heading': 0.0,
    'magnetometer_heading': 0.0, 'last_gyro_update_time': None,
}
FILTER_COEFFICIENT = 0.98

# --- 앱 레이아웃 ---
app.layout = html.Div([
    html.H1("아이폰 연동 최종 네비게이션", style={'textAlign': 'center'}),
    html.P(f"사용자 ID: {USER_ID}", style={'textAlign': 'center', 'color': 'grey'}),
    dcc.Graph(id='live-map-graph', style={'height': '80vh'}),
    dcc.Interval(id='map-updater', interval=1000), # 1초마다 업데이트 및 로그 출력
])

# --- 콜백: 1초마다 지도 업데이트 및 로그 출력 ---
@app.callback(
    Output('live-map-graph', 'figure'),
    Input('map-updater', 'n_intervals')
)
def update_live_map(n):
    lat1 = latest_data.get('latitude')
    lon1 = latest_data.get('longitude')
    heading = latest_data.get('fused_heading')

    fig = go.Figure()

    # ✨ 핵심 수정: location 데이터가 있을 때만 로그 출력 및 지도 그리기
    if lat1 is not None and lon1 is not None:
        # 요청하신 포맷으로 로그 출력
        print(f"[{USER_ID}, {lat1:.6f}, {lon1:.6f}, {heading:.2f}]")
        
        # 방향선 계산
        angle_rad = math.radians(90 - heading)
        distance = 0.0002
        lat2 = lat1 + distance * math.sin(angle_rad)
        lon2 = lon1 + distance * math.cos(angle_rad) / math.cos(math.radians(lat1))
        
        # 위치 점과 방향선 그리기
        fig.add_trace(go.Scattermapbox(
            lat=[lat1], lon=[lon1], mode='markers',
            marker=go.scattermapbox.Marker(size=15, color='blue'), name='현재 위치'
        ))
        fig.add_trace(go.Scattermapbox(
            lat=[lat1, lat2], lon=[lon1, lon2], mode='lines',
            line=go.scattermapbox.Line(width=3, color='red'), name='방향'
        ))
    else:
        # location 데이터가 없으면 대기 메시지 출력
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 'Location' 센서 데이터 수신 대기 중...")

    # 지도 레이아웃 설정 (항상 고정)
    fig.update_layout(
        mapbox_style="open-street-map",
        mapbox_zoom=INITIAL_ZOOM,
        mapbox_center=INITIAL_CENTER,
        margin={"r":0, "t":0, "l":0, "b":0},
        showlegend=False
    )
    return fig

# --- 아이폰 데이터 수신 및 처리 ---
@server.route("/data", methods=["POST"])
def data():
    global latest_data
    if request.method == "POST":
        try:
            json_data = json.loads(request.data)
            for d in json_data.get('payload', []):
                sensor_name = d.get("name")
                
                if sensor_name == "location":
                    values = d.get("values", {})
                    latest_data['latitude'] = values.get('latitude')
                    latest_data['longitude'] = values.get('longitude')
                
                elif sensor_name == "magnetometer":
                    values = d.get("values", {})
                    mag_x, mag_y = values.get('x', 0), values.get('y', 0)
                    heading_rad = math.atan2(mag_x, mag_y)
                    heading_deg = (math.degrees(heading_rad) + 360) % 360
                    latest_data['magnetometer_heading'] = heading_deg
                    
                    fused, mag = latest_data['fused_heading'], latest_data['magnetometer_heading']
                    diff = (mag - fused + 180) % 360 - 180
                    fused += (1.0 - FILTER_COEFFICIENT) * diff
                    latest_data['fused_heading'] = fused % 360

                elif sensor_name == "gyroscope":
                    now = datetime.fromtimestamp(d["time"] / 1e9)
                    if latest_data['last_gyro_update_time'] is not None:
                        dt = (now - latest_data['last_gyro_update_time']).total_seconds()
                        gyro_z_rad = d.get("values", {}).get('z', 0)
                        gyro_z_deg = math.degrees(gyro_z_rad)
                        fused = latest_data['fused_heading'] + gyro_z_deg * dt
                        latest_data['fused_heading'] = fused % 360
                    latest_data['last_gyro_update_time'] = now
        except Exception as e:
            print(f"데이터 처리 중 오류 발생: {e}")
    return "success"

if __name__ == '__main__':
    app.run(port=8000, host="0.0.0.0", debug=False)