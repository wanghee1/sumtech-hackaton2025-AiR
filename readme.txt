실행
0. main.py -> 서버 실행 -> 오라클 클라우드에서 상시로 돌아가는중
1. python p2p_client.py --id A -> GPS 데이터 대기
2. python rec.py --from-id A
3. python ./communication/websocket_server.py -> 웹소켓 서버
4. python gps_service.py -> 홀로렌즈로 gps 데이터 보내는 곳 + 아이폰 센서로거
5. python ai_main2.py -> yolo + 웹캠으로 물체 인식
6. python tts.py
