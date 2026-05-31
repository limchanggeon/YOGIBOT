"""
mqtt_bridge — ROS2 ↔ MQTT 브리지

명세서 5. 워크플로우(① 추출 → ② JSON 변환 → ③ 전송)를 구현한다.

상행(로봇 → 서버):
    ROS2 텔레메트리 토픽 구독 → 명세서 공통 래퍼 JSON 직렬화
    → MQTT publish  robot/<robot_id>/<key>

하행(서버 → 로봇):
    MQTT  robot/<robot_id>/cmd/<n>  구독 → ROS2 토픽으로 재발행
    cmd_vel → /cmd_vel, goal → /goal_pose_cmd, estop → /emergency_stop

브로커 주소는 파라미터/환경변수로 지정 (Mac 호스트 IP).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import math
import time
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data

from action_msgs.msg import GoalStatus, GoalStatusArray

import paho.mqtt.client as mqtt

from std_msgs.msg import Bool, String
from geometry_msgs.msg import Twist, PoseStamped, PoseWithCovarianceStamped
from nav_msgs.msg import Odometry, Path
from sensor_msgs.msg import Imu, BatteryState, LaserScan

try:
    from turtlebot3_msgs.msg import SensorState
    HAS_SENSOR_STATE = True
except ImportError:
    HAS_SENSOR_STATE = False


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def stamp_dict(stamp) -> dict:
    return {"sec": stamp.sec, "nanosec": stamp.nanosec}


def xyz(v) -> dict:
    return {"x": v.x, "y": v.y, "z": v.z}


def quat(q) -> dict:
    return {"x": q.x, "y": q.y, "z": q.z, "w": q.w}


class MqttBridge(Node):
    def __init__(self):
        super().__init__("mqtt_bridge")
        self.robot_id = self.declare_parameter("robot_id", "waffle_01").value
        host = self.declare_parameter("broker_host", os.environ.get("MQTT_HOST", "127.0.0.1")).value
        port = int(self.declare_parameter("broker_port", int(os.environ.get("MQTT_PORT", "1883"))).value)
        # /scan 360점 전량 전송 시 대역폭 과부하 → 다운샘플 개수 (명세서 6.)
        self.scan_n = int(self.declare_parameter("scan_samples", 36).value)

        # ---- MQTT 클라이언트 (paho 1.x/2.x 호환) ----
        try:
            self.cli = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1,
                                   client_id=f"yogibot-bridge-{self.robot_id}")
        except (AttributeError, TypeError):
            self.cli = mqtt.Client(client_id=f"yogibot-bridge-{self.robot_id}")
        self.cli.on_connect = self._on_connect
        self.cli.on_message = self._on_cmd
        self.get_logger().info(f"MQTT 연결 시도 {host}:{port}")
        self.cli.connect(host, port, keepalive=30)
        self.cli.loop_start()

        # ---- 하행: 명령을 ROS2로 재발행할 퍼블리셔 ----
        # 목표는 Nav2 표준 토픽 /goal_pose 로 보낸다 (실 로봇 Nav2가 이걸 구독).
        # 같은 토픽을 텔레메트리로도 구독하므로 발행된 명령이 그대로 대시보드까지 반영됨.
        self.pub_cmd_vel = self.create_publisher(Twist, "/cmd_vel", 10)
        self.pub_goal = self.create_publisher(PoseStamped, "/goal_pose", 10)
        self.pub_estop = self.create_publisher(Bool, "/emergency_stop", 10)
        # AMCL 초기 위치 시드 (Mac 대시보드 "초기 위치 설정" 클릭으로 트리거)
        self.pub_initialpose = self.create_publisher(
            PoseWithCovarianceStamped, "/initialpose", 10)

        # ---- 상행: ROS2 토픽 구독 → MQTT ----
        self.create_subscription(Odometry, "/odom", self.on_odom, 10)
        self.create_subscription(Imu, "/imu", self.on_imu, 10)
        self.create_subscription(BatteryState, "/battery_state", self.on_batt, 10)
        self.create_subscription(PoseWithCovarianceStamped, "/amcl_pose", self.on_amcl, 10)
        # LDS-02 같은 LiDAR는 /scan을 BEST_EFFORT QoS로 publish 한다.
        # 기본 RELIABLE 로 구독하면 한 건도 못 받으니 sensor_data 프로파일로 매칭.
        self.create_subscription(LaserScan, "/scan", self.on_scan, qos_profile_sensor_data)
        self.create_subscription(PoseStamped, "/goal_pose", self.on_goal, 10)
        self.create_subscription(Path, "/plan", self.on_plan, 10)
        self.create_subscription(String, "/yogibot/event", self.on_event, 10)
        if HAS_SENSOR_STATE:
            self.create_subscription(SensorState, "/sensor_state", self.on_sensor, 10)

        # ---- Nav2 NavigateToPose 액션 결과 → MISSION_COMPLETE 이벤트 자동 발행 ----
        # 실 Nav2는 /yogibot/event 를 안 쏘니, 우리가 액션 상태를 보고 대신 쏘아 줘야
        # 서버의 미션 마감 로직(state.finish_mission)이 동작한다.
        self._reported_goals: set[str] = set()
        self._goal_start_t: dict[str, float] = {}
        self.create_subscription(GoalStatusArray, "/navigate_to_pose/_action/status",
                                 self.on_nav_status, 10)

    # ===== MQTT 연결/명령 =====
    def _on_connect(self, client, userdata, flags, rc):
        topic = f"robot/{self.robot_id}/cmd/#"
        client.subscribe(topic, qos=1)
        self.get_logger().info(f"MQTT 연결됨(rc={rc}), 명령 구독 {topic}")

    def _on_cmd(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
        except json.JSONDecodeError:
            return
        name = msg.topic.split("/")[-1]
        if name == "cmd_vel":
            t = Twist()
            t.linear.x = float(payload.get("linear_x", 0.0))
            t.angular.z = float(payload.get("angular_z", 0.0))
            self.pub_cmd_vel.publish(t)
        elif name == "goal":
            p = PoseStamped()
            p.header.frame_id = "map"
            p.header.stamp = self.get_clock().now().to_msg()
            p.pose.position.x = float(payload.get("x", 0.0))
            p.pose.position.y = float(payload.get("y", 0.0))
            # 단위 quaternion (yaw=0). yaw 지정해야 하면 payload.yaw 로 z,w 계산.
            yaw = float(payload.get("yaw", 0.0))
            # NOTE: 함수 안에 'import math' 절대 두지 말 것 — 그러면 math 가 함수 로컬로
            # 묶여 다른 분기(initialpose 등)에서 UnboundLocalError 발생. 모듈 상단 import 사용.
            p.pose.orientation.z = math.sin(yaw / 2.0)
            p.pose.orientation.w = math.cos(yaw / 2.0)
            self.pub_goal.publish(p)
        elif name == "estop":
            self.pub_estop.publish(Bool(data=bool(payload.get("engaged", False))))
        elif name == "mission":
            self.get_logger().info(f"mission 명령: {payload.get('action')}")
        elif name == "initialpose":
            # AMCL 시드 — 사용자가 대시보드에서 클릭한 (x,y,yaw)
            p = PoseWithCovarianceStamped()
            p.header.frame_id = "map"
            p.header.stamp = self.get_clock().now().to_msg()
            p.pose.pose.position.x = float(payload.get("x", 0.0))
            p.pose.pose.position.y = float(payload.get("y", 0.0))
            yaw = float(payload.get("yaw", 0.0))
            p.pose.pose.orientation.z = math.sin(yaw / 2.0)
            p.pose.pose.orientation.w = math.cos(yaw / 2.0)
            # 공분산 (xx, yy, yaw-yaw)만 의미있는 값으로
            cov = [0.0] * 36
            cov[0] = 0.25; cov[7] = 0.25; cov[35] = 0.0685
            p.pose.covariance = cov
            self.pub_initialpose.publish(p)
        self.get_logger().info(f"하행 명령 {name}: {payload}")

    # ===== 상행 publish 헬퍼 =====
    def _publish(self, key: str, data: dict, stamp=None):
        record = {"timestamp": iso_now(), "topic": f"/{key}", "data": data}
        self.cli.publish(f"robot/{self.robot_id}/{key}", json.dumps(record), qos=0)

    # ===== 토픽 콜백 (ROS2 → JSON) =====
    def on_odom(self, m: Odometry):
        self._publish("odom", {
            "header": {"stamp": stamp_dict(m.header.stamp), "frame_id": m.header.frame_id},
            "child_frame_id": m.child_frame_id,
            "pose": {"position": xyz(m.pose.pose.position),
                     "orientation": quat(m.pose.pose.orientation)},
            "twist": {"linear": xyz(m.twist.twist.linear),
                      "angular": xyz(m.twist.twist.angular)},
        })

    def on_imu(self, m: Imu):
        self._publish("imu", {
            "header": {"stamp": stamp_dict(m.header.stamp), "frame_id": m.header.frame_id},
            "orientation": quat(m.orientation),
            "angular_velocity": xyz(m.angular_velocity),
            "linear_acceleration": xyz(m.linear_acceleration),
        })

    def on_batt(self, m: BatteryState):
        # TurtleBot3 OpenCR 펌웨어가 percentage 를 0~100 스케일로 보내는 알려진 버그.
        # ROS sensor_msgs/BatteryState 표준은 0.0~1.0 → 1 보다 크면 /100 으로 정규화.
        pct = float(m.percentage)
        if pct != pct or pct == float("inf") or pct == float("-inf"):
            pct = None
        elif pct > 1.0:
            pct = pct / 100.0
        self._publish("battery_state", {
            "voltage": round(m.voltage, 3), "current": round(m.current, 3),
            "percentage": round(pct, 4) if pct is not None else None,
            "present": bool(m.present),
        })

    def on_amcl(self, m: PoseWithCovarianceStamped):
        self._publish("amcl_pose", {
            "pose": {"pose": {"position": xyz(m.pose.pose.position),
                              "orientation": quat(m.pose.pose.orientation)}},
        })

    def on_scan(self, m: LaserScan):
        # 360점 → scan_n점으로 다운샘플 (명세서 6. /scan 용량)
        # 실 LiDAR는 측정 실패 시 inf/nan을 내보낸다. JSON 표준엔 그 값이 없어
        # (json.dumps 가 Infinity 문자열을 뱉어 JSONL 파서가 깨짐) → None 으로 치환.
        raw = list(m.ranges)
        step = max(1, len(raw) // self.scan_n) if raw else 1
        ds = []
        for r in raw[::step]:
            if r != r or r == float("inf") or r == float("-inf"):
                ds.append(None)
            else:
                ds.append(round(float(r), 2))
        finite = [r for r in ds if r is not None]
        self._publish("scan", {
            "angle_min": m.angle_min, "angle_max": m.angle_max,
            "angle_increment": m.angle_increment * step,
            "range_min": m.range_min, "range_max": m.range_max,
            "ranges": ds,
            "min_range": round(min(finite), 2) if finite else None,
            "obstacle_count": sum(1 for r in finite if r < 0.5),
        })

    def on_goal(self, m: PoseStamped):
        self._publish("goal_pose", {
            "pose": {"position": xyz(m.pose.position), "orientation": quat(m.pose.orientation)},
        })

    def on_plan(self, m: Path):
        self._publish("plan", {
            "poses": [{"pose": {"position": xyz(p.pose.position)}} for p in m.poses],
        })

    def on_sensor(self, m):
        self._publish("sensor_state", {
            "left_encoder": int(m.left_encoder), "right_encoder": int(m.right_encoder),
            "bumper": int(m.bumper), "cliff": int(m.cliff),
            "sonar": float(getattr(m, "sonar", 0.0)),
            "torque": bool(m.torque), "battery": round(float(m.battery), 2),
        })

    def on_event(self, m: String):
        # 이벤트는 래퍼 없이 그대로 전달 (서버가 events.jsonl 에 저장)
        try:
            ev = json.loads(m.data)
        except json.JSONDecodeError:
            return
        ev.setdefault("timestamp", iso_now())
        self.cli.publish(f"robot/{self.robot_id}/event", json.dumps(ev), qos=1)

    # ===== Nav2 NavigateToPose 액션 상태 → MISSION_COMPLETE 자동 발행 =====
    def on_nav_status(self, msg: GoalStatusArray):
        now = time.time()
        for s in msg.status_list:
            gid = bytes(s.goal_info.goal_id.uuid).hex()
            st = s.status
            if st in (GoalStatus.STATUS_ACCEPTED, GoalStatus.STATUS_EXECUTING):
                # 시작 시각 기록 (한 번만)
                self._goal_start_t.setdefault(gid, now)
                continue
            if st in (GoalStatus.STATUS_SUCCEEDED, GoalStatus.STATUS_ABORTED,
                      GoalStatus.STATUS_CANCELED):
                if gid in self._reported_goals:
                    continue
                self._reported_goals.add(gid)
                start = self._goal_start_t.pop(gid, None)
                dur = round(now - start, 1) if start else None
                if st == GoalStatus.STATUS_SUCCEEDED:
                    result, etype = "SUCCESS", "MISSION_COMPLETE"
                elif st == GoalStatus.STATUS_ABORTED:
                    result, etype = "FAILED", "MISSION_COMPLETE"
                else:
                    result, etype = "CANCELED", "MISSION_COMPLETE"
                ev = {
                    "event_type": etype,
                    "result": result,
                    "goal_id": gid[:12],
                    "timestamp": iso_now(),
                }
                if dur is not None:
                    ev["duration_sec"] = dur
                self.cli.publish(f"robot/{self.robot_id}/event",
                                 json.dumps(ev), qos=1)
                self.get_logger().info(
                    f"Nav2 결과: {result} (gid={gid[:8]}, dur={dur}s)")
        # 무한 메모리 방지: 보고된 goal id 100개 넘으면 오래된 것 절반 비움
        if len(self._reported_goals) > 100:
            self._reported_goals = set(list(self._reported_goals)[-50:])


def main():
    rclpy.init()
    node = MqttBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.cli.loop_stop()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
