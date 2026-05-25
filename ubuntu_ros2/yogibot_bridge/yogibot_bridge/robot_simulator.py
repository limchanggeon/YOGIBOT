"""
robot_simulator — 가상 TurtleBot3 Waffle ROS2 노드

실제 로봇/Gazebo 없이도, 명세서에 정의된 토픽들을 진짜 ROS2 메시지로 publish 한다.
목표 지점을 향해 자율주행하는 것처럼 위치를 갱신하고, 배터리 방전·장애물 감지·
미션 완료 같은 이벤트도 만들어낸다.

발행 토픽:
    /odom          nav_msgs/Odometry                         10 Hz
    /imu           sensor_msgs/Imu                           10 Hz
    /battery_state sensor_msgs/BatteryState                   1 Hz
    /amcl_pose     geometry_msgs/PoseWithCovarianceStamped    5 Hz
    /scan          sensor_msgs/LaserScan                      1 Hz
    /goal_pose     geometry_msgs/PoseStamped                  1 Hz
    /plan          nav_msgs/Path                              1 Hz
    /sensor_state  turtlebot3_msgs/SensorState  (설치된 경우)  5 Hz
    /yogibot/event std_msgs/String (이벤트 JSON)             조건부

구독 토픽 (mqtt_bridge가 서버 명령을 ROS2로 변환해 줌):
    /cmd_vel          geometry_msgs/Twist     수동 속도 override
    /goal_pose_cmd    geometry_msgs/PoseStamped  새 목표 설정
    /emergency_stop   std_msgs/Bool           비상정지
"""
from __future__ import annotations

import json
import math
import random

import rclpy
from rclpy.node import Node

from std_msgs.msg import Bool, String
from geometry_msgs.msg import Twist, PoseStamped, PoseWithCovarianceStamped
from nav_msgs.msg import Odometry, Path
from sensor_msgs.msg import Imu, BatteryState, LaserScan

try:
    from turtlebot3_msgs.msg import SensorState
    HAS_SENSOR_STATE = True
except ImportError:  # turtlebot3_msgs 미설치 환경
    HAS_SENSOR_STATE = False


def yaw_to_quat(yaw: float):
    return (0.0, 0.0, math.sin(yaw / 2.0), math.cos(yaw / 2.0))


class RobotSimulator(Node):
    def __init__(self):
        super().__init__("robot_simulator")
        self.robot_id = self.declare_parameter("robot_id", "waffle_01").value

        # ---- 내부 상태 ----
        self.x, self.y, self.yaw = 3.21, -1.85, 0.0
        self.lin, self.ang = 0.0, 0.0
        self.battery = 0.84
        self.goal = (8.4, 4.2)
        self.estop = False
        self.manual_ticks = 0          # /cmd_vel override 잔여 틱
        self.left_enc, self.right_enc = 12453, 12401
        self._battery_low_fired = False

        # ---- 퍼블리셔 ----
        self.pub_odom = self.create_publisher(Odometry, "/odom", 10)
        self.pub_imu = self.create_publisher(Imu, "/imu", 10)
        self.pub_batt = self.create_publisher(BatteryState, "/battery_state", 10)
        self.pub_amcl = self.create_publisher(PoseWithCovarianceStamped, "/amcl_pose", 10)
        self.pub_scan = self.create_publisher(LaserScan, "/scan", 10)
        self.pub_goal = self.create_publisher(PoseStamped, "/goal_pose", 10)
        self.pub_plan = self.create_publisher(Path, "/plan", 10)
        self.pub_event = self.create_publisher(String, "/yogibot/event", 10)
        if HAS_SENSOR_STATE:
            self.pub_sensor = self.create_publisher(SensorState, "/sensor_state", 10)

        # ---- 구독 (서버 명령) ----
        self.create_subscription(Twist, "/cmd_vel", self.on_cmd_vel, 10)
        self.create_subscription(PoseStamped, "/goal_pose_cmd", self.on_goal_cmd, 10)
        self.create_subscription(Bool, "/emergency_stop", self.on_estop, 10)

        # ---- 타이머 (주기별) ----
        self.create_timer(0.1, self.tick_fast)    # 10Hz: odom/imu
        self.create_timer(0.2, self.tick_amcl)    # 5Hz: amcl/sensor_state
        self.create_timer(1.0, self.tick_slow)    # 1Hz: battery/scan/goal/plan

        msg = "with /sensor_state" if HAS_SENSOR_STATE else "(turtlebot3_msgs 없음 → /sensor_state 생략)"
        self.get_logger().info(f"robot_simulator 시작 [{self.robot_id}] {msg}")

    # ===== 명령 콜백 =====
    def on_cmd_vel(self, msg: Twist):
        self.lin, self.ang = msg.linear.x, msg.angular.z
        self.manual_ticks = 30  # 약 3초간 수동값 유지
        self.get_logger().info(f"/cmd_vel 수신 lin={self.lin:.2f} ang={self.ang:.2f}")

    def on_goal_cmd(self, msg: PoseStamped):
        self.goal = (msg.pose.position.x, msg.pose.position.y)
        self.get_logger().info(f"새 목표 수신 {self.goal}")

    def on_estop(self, msg: Bool):
        self.estop = msg.data
        self.get_logger().warn(f"비상정지 {'ON' if self.estop else 'OFF'}")

    # ===== 시뮬레이션 스텝 (10Hz) =====
    def _step_motion(self):
        if self.estop:
            self.lin = self.ang = 0.0
            return
        if self.manual_ticks > 0:
            self.manual_ticks -= 1
        else:
            # 목표를 향한 단순 자율주행
            dx, dy = self.goal[0] - self.x, self.goal[1] - self.y
            dist = math.hypot(dx, dy)
            target_yaw = math.atan2(dy, dx)
            yaw_err = math.atan2(math.sin(target_yaw - self.yaw), math.cos(target_yaw - self.yaw))
            self.ang = max(-1.0, min(1.0, 1.5 * yaw_err))
            self.lin = 0.0 if dist < 0.15 else min(0.22, 0.4 * dist)
            if dist < 0.15:
                self._on_goal_reached()
        dt = 0.1
        self.yaw += self.ang * dt
        self.x += self.lin * math.cos(self.yaw) * dt
        self.y += self.lin * math.sin(self.yaw) * dt
        self.left_enc += int(self.lin * 100)
        self.right_enc += int(self.lin * 100)

    def _on_goal_reached(self):
        self._emit_event({
            "event_type": "MISSION_COMPLETE", "result": "SUCCESS",
            "mission_id": random.randint(1000, 9999),
            "goal": {"x": self.goal[0], "y": self.goal[1]},
            "duration_sec": round(random.uniform(40, 180), 1),
            "distance_m": round(random.uniform(10, 70), 2),
        })
        # 새 목표 무작위 지정
        self.goal = (round(random.uniform(-5, 9), 2), round(random.uniform(-5, 5), 2))

    # ===== 타이머: 10Hz =====
    def tick_fast(self):
        self._step_motion()
        now = self.get_clock().now().to_msg()

        odom = Odometry()
        odom.header.stamp = now
        odom.header.frame_id = "odom"
        odom.child_frame_id = "base_footprint"
        odom.pose.pose.position.x = self.x
        odom.pose.pose.position.y = self.y
        qx, qy, qz, qw = yaw_to_quat(self.yaw)
        odom.pose.pose.orientation.x, odom.pose.pose.orientation.y = qx, qy
        odom.pose.pose.orientation.z, odom.pose.pose.orientation.w = qz, qw
        odom.twist.twist.linear.x = self.lin
        odom.twist.twist.angular.z = self.ang
        self.pub_odom.publish(odom)

        imu = Imu()
        imu.header.stamp = now
        imu.header.frame_id = "imu_link"
        imu.orientation.x, imu.orientation.y, imu.orientation.z, imu.orientation.w = qx, qy, qz, qw
        imu.angular_velocity.z = self.ang + random.uniform(-0.002, 0.002)
        imu.linear_acceleration.x = random.uniform(-0.02, 0.02)
        imu.linear_acceleration.z = 9.8 + random.uniform(-0.03, 0.03)
        self.pub_imu.publish(imu)

    # ===== 타이머: 5Hz =====
    def tick_amcl(self):
        now = self.get_clock().now().to_msg()
        amcl = PoseWithCovarianceStamped()
        amcl.header.stamp = now
        amcl.header.frame_id = "map"
        amcl.pose.pose.position.x = self.x + random.uniform(-0.01, 0.01)
        amcl.pose.pose.position.y = self.y + random.uniform(-0.01, 0.01)
        qx, qy, qz, qw = yaw_to_quat(self.yaw)
        amcl.pose.pose.orientation.z, amcl.pose.pose.orientation.w = qz, qw
        self.pub_amcl.publish(amcl)

        if HAS_SENSOR_STATE:
            ss = SensorState()
            ss.header.stamp = now
            ss.left_encoder = self.left_enc
            ss.right_encoder = self.right_enc
            ss.bumper = 0
            ss.cliff = 0
            ss.torque = True
            ss.battery = float(11.5 + self.battery * 1.3)
            self.pub_sensor.publish(ss)

    # ===== 타이머: 1Hz =====
    def tick_slow(self):
        now = self.get_clock().now().to_msg()

        # 배터리
        if not self.estop:
            self.battery = max(0.05, self.battery - 0.003)
        batt = BatteryState()
        batt.header.stamp = now
        batt.voltage = float(11.5 + self.battery * 1.3)
        batt.current = float(1.2 + random.uniform(0, 0.4))
        batt.percentage = float(self.battery)
        batt.present = True
        self.pub_batt.publish(batt)

        if self.battery < 0.2 and not self._battery_low_fired:
            self._battery_low_fired = True
            self._emit_event({
                "event_type": "BATTERY_LOW", "voltage": round(batt.voltage, 2),
                "percentage": round(self.battery, 3), "action": "RETURN_TO_BASE"})

        # LiDAR (명세서 권장: 1Hz로 다운샘플 저장)
        scan = LaserScan()
        scan.header.stamp = now
        scan.header.frame_id = "base_scan"
        scan.angle_min = -math.pi
        scan.angle_max = math.pi
        scan.angle_increment = 2 * math.pi / 360
        scan.range_min = 0.12
        scan.range_max = 3.5
        scan.ranges = [round(random.uniform(0.4, 3.4), 2) for _ in range(360)]
        self.pub_scan.publish(scan)

        # 가끔 장애물 감지 이벤트
        if random.random() < 0.05:
            self._emit_event({
                "event_type": "OBSTACLE_DETECTED",
                "pose": {"x": round(self.x, 2), "y": round(self.y, 2)},
                "min_range_m": round(random.uniform(0.12, 0.3), 2), "action": "REPLANNING"})

        # 목표 + 글로벌 경로
        goal = PoseStamped()
        goal.header.stamp = now
        goal.header.frame_id = "map"
        goal.pose.position.x, goal.pose.position.y = self.goal
        self.pub_goal.publish(goal)

        path = Path()
        path.header.stamp = now
        path.header.frame_id = "map"
        for i in range(12):
            p = PoseStamped()
            p.header.frame_id = "map"
            p.pose.position.x = self.x + (self.goal[0] - self.x) * (i / 11)
            p.pose.position.y = self.y + (self.goal[1] - self.y) * (i / 11)
            path.poses.append(p)
        self.pub_plan.publish(path)

    # ===== 이벤트 publish (std_msgs/String JSON) =====
    def _emit_event(self, ev: dict):
        ev["robot_id"] = self.robot_id
        self.pub_event.publish(String(data=json.dumps(ev)))
        self.get_logger().info(f"event: {ev['event_type']}")


def main():
    rclpy.init()
    node = RobotSimulator()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
