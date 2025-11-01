import asyncio
import json
import os
import time
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import Dict, List, Tuple
import redis.asyncio as aioredis

# --- 설정 ---
GROUPING_DISTANCE_M = 500
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost")

# --- FastAPI 앱 및 Redis 클라이언트 설정 ---
app = FastAPI()
redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)

active_connections: Dict[str, WebSocket] = {}

# --- 핵심 로직: Redis의 위치기반 기능 활용 ---
async def update_and_get_group(node_id: str, location: Tuple[float, float]) -> List[Dict]:
    await redis_client.geoadd("vehicles", (location[1], location[0], node_id))
    nearby_vehicles = await redis_client.geosearch(
        "vehicles",
        longitude=location[1],
        latitude=location[0],
        radius=GROUPING_DISTANCE_M,
        unit="m",
        withcoord=True,
    )
    group_members = [{"node_id": name, "location": (lat, lon)} for name, (lon, lat) in nearby_vehicles]
    return group_members


# --- 서버 측 Pub/Sub 리스너 ---
async def group_update_listener():
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("group_updates")
    print("📢 그룹 업데이트 리스너 시작됨.")
    async for message in pubsub.listen():
        if message["type"] == "message":
            update_info = json.loads(message["data"])
            group_members_list = update_info.get("group_members", [])
            for member in group_members_list:
                node_id = member["node_id"]
                if node_id in active_connections:
                    conn = active_connections[node_id]
                    try:
                        await conn.send_json({"type": "group_update", "data": group_members_list})
                    except Exception:
                        pass


@app.on_event("startup")
async def startup_event():
    # await redis_client.flushdb() # 운영 환경에서는 주석 처리
    asyncio.create_task(group_update_listener())
    print("✅ 서버가 시작되었습니다.")


# --- 서버 측 웹소켓 엔드포인트 ---
@app.websocket("/ws/{node_id}")
async def websocket_endpoint(websocket: WebSocket, node_id: str):
    await websocket.accept()
    active_connections[node_id] = websocket
    print(f"✅ 차량 연결됨: {node_id} (총 {len(active_connections)}대)")
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            # P2P 릴레이 메시지 중계 로직
            if message.get("type") == "p2p_relay":
                target_id = message.get("target_id")
                if target_id in active_connections:
                    relay_payload = {
                        "type": "p2p_message",
                        "from_id": node_id,
                        "content": message.get("content")
                    }
                    await active_connections[target_id].send_json(relay_payload)
                continue

            # P2P 홀 펀칭 시그널링 메시지 중계 로직
            if message.get("type") in ["p2p_request", "p2p_response"]:
                target_id = message.get("target_id")
                if target_id in active_connections:
                    message["ip"] = websocket.client.host
                    await active_connections[target_id].send_json(message)
                continue

            # GPS 위치 업데이트 로직
            if "latitude" in message and "longitude" in message:
                loc_tuple = (message["latitude"], message["longitude"])
                await redis_client.hset(f"peer:{node_id}", mapping={
                    "node_id": node_id, "location": f"{loc_tuple[0]},{loc_tuple[1]}",
                    "last_seen": time.time()
                })
                group_members = await update_and_get_group(node_id, loc_tuple)
                await redis_client.publish("group_updates", json.dumps({"group_members": group_members}))

    except WebSocketDisconnect:
        await redis_client.zrem("vehicles", node_id)
        await redis_client.delete(f"peer:{node_id}")
        if node_id in active_connections:
            del active_connections[node_id]
        print(f"❌ 차량 연결 끊김: {node_id} (총 {len(active_connections)}대)")