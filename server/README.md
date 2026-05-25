# YogiBot Backend (FastAPI + MQTT + JSONL)

우분투(UTM)의 가상 ROS2 노드가 **MQTT**로 보낸 텔레메트리를 받아
**처리 → JSONL 파일(DB) 저장 → 프론트로 WebSocket push** 하는 서버.

전체 파이프라인/실행 순서는 루트 [PIPELINE.md](../PIPELINE.md) 참고.

## 구성

| 파일 | 역할 |
|------|------|
| `main.py` | FastAPI 앱. MQTT 구독 시작, WS push(1Hz), REST 제어 명령 |
| `mqtt_ingest.py` | MQTT 수신 → 검증/처리 → JSONL 저장 → 실시간 상태 갱신 |
| `storage.py` | `db/YYYY-MM-DD/<topic>.jsonl` 라인 단위 append (flush) |
| `mosquitto.conf` | 개발용 브로커 설정(모든 인터페이스 listen) |

## 실행

```bash
cd server
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cd ..                                    # 프로젝트 루트에서 실행(server.main 임포트)
uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload
```

MQTT 브로커가 먼저 떠 있어야 한다:

```bash
mosquitto -c server/mosquitto.conf -v
```

## 환경변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `MQTT_HOST` | `0.0.0.0` | 구독할 브로커 주소 |
| `MQTT_PORT` | `1883` | 브로커 포트 |
| `ROBOT_ID` | `waffle_01` | `robot/<id>/#` 구독 네임스페이스 |
| `YOGI_DB_ROOT` | `<repo>/db` | JSONL 저장 루트 |
| `YOGI_SIM` | (없음) | `1`이면 우분투 없이 내부 시뮬(화면 확인 전용, 저장 안 함) |

## 엔드포인트

| 종류 | 경로 | 설명 |
| ---- | ---- | ---- |
| WS  | `/ws/telemetry`     | 1Hz로 odom/battery/amcl/plan/goal/sensorState/missionState/estop 집계 push |
| GET | `/api/health`       | 헬스 + 동작모드(`mqtt`/`sim`) + 토픽별 저장 건수 |
| GET | `/api/events`       | 이벤트 로그 |
| GET | `/api/logs`         | 미션 통계/이력 (현재 정적 예시) |
| GET | `/api/cmd_log`      | 최근 송신된 제어 명령 |
| POST | `/api/cmd_vel`     | `{ "linear_x", "angular_z" }` → MQTT `cmd/cmd_vel` |
| POST | `/api/emergency_stop` | `{ "engaged" }` → MQTT `cmd/estop` |
| POST | `/api/goal`        | `{ "x", "y", "yaw" }` → MQTT `cmd/goal` |
| POST | `/api/mission`     | `{ "action": "start\|pause\|cancel\|return" }` → MQTT `cmd/mission` |

## 저장 결과 확인

```bash
curl http://localhost:8000/api/health      # stored: 토픽별 누적 저장 건수
ls db/$(date +%F)/                          # odom.jsonl battery_state.jsonl events.jsonl ...
tail -f db/$(date +%F)/odom.jsonl
```
