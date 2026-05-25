# YogiBot ControlTower — 프론트엔드 데이터 연동 변경사항

> 참고 문서
> - `TurtleBot3_Waffle_JSON_저장명세서.docx`
> - `ROS2_SLAM_관제_DB_연계_명세서.docx`
>
> 변경일: 2026-04-28

---

## 1. 적용된 ROS2 토픽

| 토픽 | 메시지 타입 | 용도 |
|------|------------|------|
| `/odom` | `nav_msgs/Odometry` | 선속도, 각속도, 오도메트리 위치 |
| `/battery_state` | `sensor_msgs/BatteryState` | 배터리 잔량, 전압, 전류 |
| `/sensor_state` | `turtlebot3_msgs/SensorState` | 범퍼, 낭떠러지, 토크, 엔코더 |
| `/imu` | `sensor_msgs/Imu` | 자세 quaternion (구조 정의) |
| `/amcl_pose` | `geometry_msgs/PoseWithCovarianceStamped` | SLAM 기반 정밀 위치 추정 |
| `/goal_pose` | `geometry_msgs/PoseStamped` | 현재 내비게이션 목적지 |
| `/plan` | `nav_msgs/Path` | Nav2 글로벌 경로 (waypoint 배열) |

---

## 2. 프론트엔드가 기대하는 JSON 포맷

### `/odom`
```json
{
  "timestamp": "2026-04-28T10:23:45.123Z",
  "topic": "/odom",
  "data": {
    "pose": {
      "position":    { "x": 1.234, "y": 0.567, "z": 0.0 },
      "orientation": { "x": 0.0, "y": 0.0, "z": 0.382, "w": 0.924 }
    },
    "twist": {
      "linear":  { "x": 0.15, "y": 0.0, "z": 0.0 },
      "angular": { "x": 0.0,  "y": 0.0, "z": 0.30 }
    }
  }
}
```

### `/battery_state`
```json
{
  "timestamp": "2026-04-28T10:23:45.150Z",
  "topic": "/battery_state",
  "data": {
    "voltage":    11.8,
    "current":    1.24,
    "percentage": 0.73,
    "present":    true
  }
}
```

### `/sensor_state`
```json
{
  "timestamp": "2026-04-28T10:23:45.160Z",
  "topic": "/sensor_state",
  "data": {
    "left_encoder":  12453,
    "right_encoder": 12401,
    "bumper":        0,
    "cliff":         0,
    "sonar":         0.0,
    "torque":        false,
    "battery":       11.8
  }
}
```

### `/amcl_pose`
```json
{
  "timestamp": "2026-04-28T10:23:45.100Z",
  "topic": "/amcl_pose",
  "data": {
    "pose": {
      "pose": {
        "position":    { "x": 1.230, "y": 0.565, "z": 0.0 },
        "orientation": { "x": 0.0,  "y": 0.0,   "z": 0.382, "w": 0.924 }
      }
    }
  }
}
```

### `/goal_pose`
```json
{
  "timestamp": "2026-04-28T10:23:00.000Z",
  "topic": "/goal_pose",
  "data": {
    "pose": {
      "position":    { "x": 5.0, "y": 3.0, "z": 0.0 },
      "orientation": { "x": 0.0, "y": 0.0, "z": 0.707, "w": 0.707 }
    }
  }
}
```

### `/plan`
```json
{
  "timestamp": "2026-04-28T10:23:00.100Z",
  "topic": "/plan",
  "data": {
    "poses": [
      { "pose": { "position": { "x": 1.23, "y": 0.57 } } },
      { "pose": { "position": { "x": 2.80, "y": 1.40 } } },
      { "pose": { "position": { "x": 5.00, "y": 3.00 } } }
    ]
  }
}
```

### 이벤트 로그 (JSON Lines / NoSQL)
```json
{ "event_type": "MISSION_COMPLETE", "timestamp": "...", "robot_id": "waffle_01",
  "mission_id": 9226, "result": "SUCCESS",
  "goal": { "x": 3.5, "y": 1.2 }, "duration_sec": 87.3, "distance_m": 12.45 }

{ "event_type": "OBSTACLE_DETECTED", "timestamp": "...", "robot_id": "waffle_01",
  "pose": { "x": 2.1, "y": 0.8 }, "min_range_m": 0.18, "action": "REPLANNING" }

{ "event_type": "BATTERY_LOW", "timestamp": "...", "robot_id": "waffle_01",
  "voltage": 10.8, "percentage": 0.15, "action": "RETURN_TO_BASE" }
```

---

## 3. UI 변경 사항

### 3-1. 지도 (Map)

| 항목 | 기존 | 변경 후 |
|------|------|---------|
| 로봇 마커 위치 | 브라우저 GPS | `/amcl_pose` → `odomToLatLng()` 변환 |
| 목적지 마커 | 없음 | `/goal_pose` 빨간 원 마커 추가 |
| 경로 표시 | 없음 | `/plan` waypoint 배열 → 파란 점선 Polyline |

### 3-2. 상태 카드

| 카드 | 기존 | 변경 후 | 데이터 필드 |
|------|------|---------|------------|
| 주행 속도 | 하드코딩 `0.8 m/s` | 동적 | `odom.twist.linear.x` |
| 각속도 | 없음 | 추가 | `odom.twist.angular.z` |
| 배터리 % | 하드코딩 `92` | 동적 | `battery_state.percentage × 100` |
| 배터리 전압/전류 | 없음 | 추가 | `battery_state.voltage / current` |
| 위치 카드 | 고정 "공학관 426호" | AMCL x / y / yaw | `amcl_pose.pose.pose.position` + quaternion→yaw |
| 하드웨어 상태 | 고정 "정상" | 동적 | `sensor_state.bumper / cliff / torque` |
| 작업 상태 | 고정 "이동 중" | NAVIGATING / IDLE + 목표 좌표 | `odom.twist.linear.x > 0.01` + `goal_pose` |

### 3-3. 이벤트 로그

| 항목 | 기존 | 변경 후 |
|------|------|---------|
| 로그 형식 | 배송 ID / 출발지 / 도착지 / 상태 | `event_type` 뱃지 / 시각 / 상세 |
| 이벤트 타입 | 없음 (단순 완료/취소) | `MISSION_COMPLETE` / `OBSTACLE_DETECTED` / `BATTERY_LOW` |
| 상세 내용 | 없음 | 타입별 동적 렌더링 (미션 번호·소요시간·거리 / 감지 위치·최소거리·조치 / 전압·잔량·조치) |

### 3-4. 로그 & 이력 탭

| 항목 | 기존 | 변경 후 |
|------|------|---------|
| 상태 값 | 완료 / 취소 | `SUCCESS` / `FAILED` (명세서 result 필드 기준) |
| 거리 컬럼 | 없음 | 추가 (`distance_m`) |

---

## 4. 좌표 변환 방식

오도메트리 로컬 좌표(m)를 Leaflet 위경도로 변환:

```
기준점: lat 36.3268, lng 127.3386
lat = BASE_LAT + odom_y / 111320
lng = BASE_LNG + odom_x / (111320 × cos(BASE_LAT))
```

> 실제 운용 시 기준점을 건물 입구 등 알려진 GPS 좌표로 교체 필요.

---

## 5. 백엔드 연동 방법

현재 `src/App.jsx` 상단의 `MOCK_*` 상수를 API/WebSocket 응답으로 교체하면 됩니다.

```js
// rosbridge WebSocket 연결 예시 (roslibjs)
import ROSLIB from 'roslibjs';
const ros = new ROSLIB.Ros({ url: 'ws://ROBOT_IP:9090' });

const amclTopic = new ROSLIB.Topic({ ros, name: '/amcl_pose',
  messageType: 'geometry_msgs/PoseWithCovarianceStamped' });
amclTopic.subscribe(msg => setAmclPose({ pose: msg.pose }));

const batteryTopic = new ROSLIB.Topic({ ros, name: '/battery_state',
  messageType: 'sensor_msgs/BatteryState' });
batteryTopic.subscribe(msg => setBattery({
  voltage: msg.voltage, current: msg.current,
  percentage: msg.percentage, present: msg.present
}));
```

> JSON 필드 구조는 섹션 2의 포맷과 동일해야 합니다.
