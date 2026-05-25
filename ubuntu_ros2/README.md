# yogibot_bridge — 우분투(UTM) ROS2 패키지

가상 TurtleBot3 Waffle을 흉내 내는 **실제 rclpy ROS2 노드** 2개로 구성된다.

| 노드 | 역할 |
|------|------|
| `robot_simulator` | 가짜 센서값으로 **진짜 ROS2 토픽** 발행(`/odom` `/imu` `/scan` `/battery_state` `/amcl_pose` `/goal_pose` `/plan`, 가능 시 `/sensor_state`). 목표를 향해 자율주행하는 것처럼 동작하고 이벤트(미션완료/장애물/배터리)도 생성. |
| `mqtt_bridge` | 그 토픽들을 구독 → 명세서 JSON으로 직렬화 → MQTT `robot/<id>/<topic>` 발행. 서버 명령(`robot/<id>/cmd/#`)은 ROS2 토픽으로 되돌려 발행. |

> `/sensor_state` 는 `turtlebot3_msgs` 가 설치돼 있을 때만 발행된다(없으면 자동 생략).

---

## 설치

```bash
# 1) ROS2 환경 (예: Humble)
source /opt/ros/humble/setup.bash

# 2) 순수 파이썬 의존성
pip install paho-mqtt

# 3) 워크스페이스에 복사 후 빌드
mkdir -p ~/ros2_ws/src
cp -r yogibot_bridge ~/ros2_ws/src/
cd ~/ros2_ws
colcon build --packages-select yogibot_bridge
source install/setup.bash
```

## 실행

### 가장 쉬운 방법 — GUI 송신 패널 (추천)

클릭만으로 파이프라인 시작/정지 + 목표·주행·이벤트 전송을 할 수 있다.

```bash
sudo apt install python3-tk          # 최초 1회 (tkinter 없을 때만)
source /opt/ros/humble/setup.bash
source ~/ros2_ws/install/setup.bash  # yogibot_bridge 빌드한 워크스페이스
python3 yogibot_gui.py
```

```text
┌──────── YogiBot 송신 패널 ────────┐
│ 1. 파이프라인  브로커IP[___] 포트[__] robot_id[__]  │
│    [▶ 송신 시작] [■ 정지]   ● 송신 중              │
│ 2. 목표 전송   x[5.0] y[3.0]  [목표 보내기]        │
│ 3. 수동 주행   ▲전진 ▼후진 ◀좌 ▶우 ■정지          │
│ 4. 비상정지    [E-STOP 켜기]  해제됨              │
│ 5. 이벤트      [미션완료][장애물감지][배터리부족]  │
│ 6. 원격 명령 수신 (Mac 관제 → 로봇)               │
│    [▶ 수신 시작]  ● 수신 중                        │
│    ⬇ goal      x=5.00 y=3.00 yaw=45.0°           │  ← Mac 대시보드가 보낸 명령
│    ⬇ estop     engaged=true                       │
│ 로그: $ ros2 launch ...                          │
└──────────────────────────────────┘
```

> **브로커 IP** 칸을 Mac 호스트 IP(UTM Shared 네트워크면 보통 `192.168.64.1`)로 바꾼 뒤
> [송신 시작]을 누르면 simulator + bridge가 함께 떠서 서버로 데이터가 흘러간다.
> 패널의 GUI는 ROS2를 직접 쓰지 않고 내부적으로 `ros2 launch` / `ros2 topic pub` 를 호출한다.

> **6. 원격 명령 수신** — [수신 시작]을 누르면 GUI가 브로커의 `robot/<id>/cmd/#` 를 구독한다.
> Mac 관제 대시보드에서 목표/주행/E-STOP/미션 버튼을 누르면(서버가 MQTT로 publish) 그 명령이
> 여기에 `⬇` 로 실시간 표시되어, **원격조종 명령이 로봇 쪽에 도달했는지 우분투에서 바로 확인**할 수 있다.
> (같은 명령을 mqtt_bridge 가 `/cmd_vel`·`/goal_pose_cmd`·`/emergency_stop` ROS2 토픽으로도 변환한다.)

### 직접 launch 로 띄우기

```bash
# broker_host = Mac 호스트 IP (UTM Shared 네트워크면 보통 192.168.64.1)
ros2 launch yogibot_bridge bringup.launch.py broker_host:=192.168.64.1
```

### 노드 따로

```bash
# 터미널 A
ros2 run yogibot_bridge robot_simulator

# 터미널 B
ros2 run yogibot_bridge mqtt_bridge --ros-args -p broker_host:=192.168.64.1
```

## 파라미터

| 노드 | 파라미터 | 기본값 | 설명 |
|------|----------|--------|------|
| robot_simulator | `robot_id` | `waffle_01` | MQTT 토픽 네임스페이스 |
| mqtt_bridge | `broker_host` | `127.0.0.1` | Mac MQTT 브로커 IP |
| mqtt_bridge | `broker_port` | `1883` | 브로커 포트 |
| mqtt_bridge | `robot_id` | `waffle_01` | `robot/<id>/...` |
| mqtt_bridge | `scan_samples` | `36` | /scan 360점 → 다운샘플 개수 (대역폭 절약) |

환경변수 `MQTT_HOST` / `MQTT_PORT` 로도 브로커 주소를 줄 수 있다.

## 동작 확인

```bash
# 토픽이 발행되는지
ros2 topic list
ros2 topic echo /odom --once

# MQTT로 나가는지 (Mac에서)
mosquitto_sub -h localhost -t 'robot/#' -v
```

## ROS2 없이 빠르게 테스트하려면?

ROS2 설치가 부담되면, `robot_simulator` 없이 `mqtt_bridge`만으로는 동작하지 않는다
(브리지는 ROS2 토픽을 구독하기 때문). ROS2가 아예 없는 환경에서 데이터 흐름만 보고 싶다면
Mac 서버를 `YOGI_SIM=1` 로 띄우는 방법이 있다 — 자세한 건 루트 [PIPELINE.md](../PIPELINE.md).
