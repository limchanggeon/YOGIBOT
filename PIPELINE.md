# YogiBot 데이터 파이프라인 — UTM 우분투 → 서버 → DB 저장

우분투(UTM VM)의 **가상 ROS2 노드**가 데이터를 만들어 MQTT로 쏘면,
Mac의 **FastAPI 서버**가 받아서 **처리 → JSONL DB 저장 → 대시보드 push** 한다.

```
┌─────────────── UTM 우분투 VM ───────────────┐        ┌──────────────── Mac 호스트 ────────────────┐
│  robot_simulator (rclpy)                    │        │  mosquitto (MQTT 브로커, 1883)              │
│    └ /odom /imu /scan /battery_state ...     │        │        ▲                                    │
│  mqtt_bridge (rclpy)                         │  MQTT  │        │ 구독 robot/waffle_01/#              │
│    └ ROS2 토픽 → JSON → publish ───────────────────────▶  FastAPI 서버 (server/main.py)            │
│      robot/waffle_01/<topic>                 │ 1883   │    ① 검증/처리  ② db/날짜/토픽.jsonl 저장   │
│                                              │        │    ③ WebSocket → React 대시보드            │
└──────────────────────────────────────────────┘        └─────────────────────────────────────────────┘
```

- DB: **JSON Lines 파일** (`db/YYYY-MM-DD/<topic>.jsonl`) — 명세서 *TurtleBot3 JSON 저장명세서* 5.2 구조
- 가상 노드: **실제 rclpy ROS2 노드** (가짜 센서값을 진짜 ROS2 토픽으로 publish)
- 전송: **MQTT** (명세서 *DB 연계 명세서* 권장 IoT 방식)

---

## 0. 사전 준비

| 위치 | 필요한 것 |
|------|-----------|
| Mac | Python 3.10+, mosquitto, 이 저장소 |
| UTM 우분투 | ROS2 (Humble 권장), `paho-mqtt`, colcon |

UTM 네트워크는 **Shared Network**(기본값) 사용 — VM이 `192.168.64.x`, Mac 호스트는 게이트웨이(`192.168.64.1`)로 접근된다.

---

## 1. Mac — MQTT 브로커 띄우기

```bash
brew install mosquitto          # 최초 1회
cd ~/Desktop/YogiBot_ControlTower
mosquitto -c server/mosquitto.conf -v
```

`server/mosquitto.conf` 는 모든 인터페이스(`0.0.0.0:1883`)에서 listen 하므로 VM에서 접속 가능하다.
방화벽이 막으면: 시스템 설정 → 네트워크 → 방화벽에서 mosquitto 허용.

## 2. Mac — FastAPI 서버 실행

```bash
cd ~/Desktop/YogiBot_ControlTower/server
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cd ..                                    # 프로젝트 루트(server의 부모)
uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload
```

기동 로그에 `[mqtt] connected ... subscribed robot/waffle_01/#` 가 보이면 브로커 연결 성공.
`http://localhost:8000/api/health` → `{"mode":"mqtt", "stored":{...}}`

## 3. Mac — 호스트 IP 확인 (VM에서 쓸 주소)

```bash
ifconfig | grep '192.168.64'      # 보통 192.168.64.1 이 호스트
```

## 4. 우분투(UTM) — 가상 ROS2 노드 실행

`ubuntu_ros2/` 폴더를 VM으로 복사한 뒤 (공유폴더/scp/git 중 편한 방법):

```bash
# ROS2 환경 + 의존성
source /opt/ros/humble/setup.bash
pip install paho-mqtt
sudo apt install python3-tk          # GUI 쓸 때 (tkinter 없을 때만)

# 빌드
mkdir -p ~/ros2_ws/src && cp -r ubuntu_ros2/yogibot_bridge ~/ros2_ws/src/
cd ~/ros2_ws && colcon build --packages-select yogibot_bridge
source install/setup.bash
```

**(A) GUI 송신 패널 — 추천 (클릭만으로)**

```bash
python3 ubuntu_ros2/yogibot_gui.py
```
→ 창에서 **브로커 IP**를 3번 Mac IP로 바꾸고 **[▶ 송신 시작]**. 목표/주행/이벤트 버튼으로 전송.

**(B) 터미널에서 직접 launch**

```bash
# broker_host = 3번에서 확인한 Mac IP
ros2 launch yogibot_bridge bringup.launch.py broker_host:=192.168.64.1
```

> 자세한 내용은 [ubuntu_ros2/README.md](ubuntu_ros2/README.md) 참고.

## 5. 확인 — 데이터가 들어와 저장되는지

```bash
# Mac: 저장 건수 증가 확인
watch -n1 'curl -s http://localhost:8000/api/health | python3 -m json.tool'

# Mac: 실제 저장 파일
ls db/$(date +%F)/                        # odom.jsonl battery_state.jsonl ...
tail -f db/$(date +%F)/odom.jsonl         # 한 줄에 레코드 하나씩 쌓임
```

대시보드까지 보려면 (프로젝트 루트 `.env.local` 이 `localhost:8000` 가리킴):

```bash
npm install && npm run dev                # http://localhost:5173
```

---

## 검증 없이 빠르게 보고 싶다면 (우분투 불필요)

서버만 내부 시뮬레이션으로 돌려 대시보드를 확인할 수 있다:

```bash
YOGI_SIM=1 uvicorn server.main:app --host 0.0.0.0 --port 8000
```

> 단, 이 모드는 MQTT/JSONL 저장 경로를 타지 않는다(화면 확인 전용).

---

## MQTT 토픽 규약 (노드 ↔ 서버 공통 계약)

| 방향 | 토픽 | payload |
|------|------|---------|
| 로봇→서버 | `robot/<id>/odom` `.../battery_state` `.../amcl_pose` `.../imu` `.../scan` `.../goal_pose` `.../plan` `.../sensor_state` | `{ "timestamp", "topic", "data" }` (명세서 공통 래퍼) |
| 로봇→서버 | `robot/<id>/event` | `{ "event_type", "timestamp", ... }` |
| 서버→로봇 | `robot/<id>/cmd/{cmd_vel\|goal\|estop\|mission}` | 명령별 JSON |

## 트러블슈팅

| 증상 | 확인 |
|------|------|
| 서버 로그 `connect failed ... Connection refused` | 1번 mosquitto 가 떠 있는지, 서버 `MQTT_HOST`(기본 0.0.0.0=로컬) |
| VM에서 브로커 접속 안 됨 | `broker_host` 가 Mac IP 맞는지, Mac 방화벽, `mosquitto -v` 로그에 VM 연결 보이는지 |
| `stored` 가 안 늘어남 | VM에서 `ros2 topic list` 로 토픽 발행 확인, bridge 로그 `MQTT 연결됨` |
| 저장 위치 바꾸기 | 서버에 `YOGI_DB_ROOT=/원하는/경로` 환경변수 |
