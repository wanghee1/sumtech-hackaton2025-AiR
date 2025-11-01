# sumtech-hackaton2025-AiR
AI 기반 위험 예측 시스템이 운전자의 시야 밖 잠재적 위협까지 사전에 감지하고, 이를 AR(증강현실)로 직관적인 경고를 제공합니다. 
실시간 도로교통 데이터를 연동하여 돌발 상황을 미리 안내하며, P2P 네트워크를 통해 차량 간 위험 정보(예: 사각지대 보행자)를 공유함으로써 예측 불가능한 사고 발생률을 획기적으로 줄입니다."


실행
0. main.py -> 서버 실행 -> 오라클 클라우드에서 상시로 돌아가는중
1. python p2p_client.py --id A -> GPS 데이터 대기
2. python rec.py --from-id A
3. python ./communication/websocket_server.py -> 웹소켓 서버
4. python gps_service.py -> 홀로렌즈로 gps 데이터 보내는 곳 + 아이폰 센서로거
5. python ai_main2.py -> yolo + 웹캠으로 물체 인식
6. python tts.py
