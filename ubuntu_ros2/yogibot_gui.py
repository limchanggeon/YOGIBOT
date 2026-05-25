#!/usr/bin/env python3
"""
YogiBot 송신 패널 (우분투 GUI)

우분투(UTM)에서 ROS2 데이터를 "클릭만으로" 서버에 보낼 수 있게 해 주는 Tkinter GUI.
ROS2를 직접 import 하지 않고 `ros2 launch` / `ros2 topic pub` 를 subprocess로 호출하므로
가볍고 안정적이다. (tkinter는 파이썬 기본 내장 → 추가 설치 불필요)

실행:
    source /opt/ros/humble/setup.bash
    source ~/ros2_ws/install/setup.bash      # yogibot_bridge 빌드해 둔 워크스페이스
    python3 yogibot_gui.py

기능:
    · 송신 시작/정지 : robot_simulator + mqtt_bridge 파이프라인을 launch/종료
    · 목표 전송      : /goal_pose_cmd
    · 수동 주행(jog) : /cmd_vel  (시뮬레이터가 약 3초간 유지)
    · E-STOP 토글    : /emergency_stop
    · 이벤트 전송    : /yogibot/event  (MISSION_COMPLETE / OBSTACLE_DETECTED / BATTERY_LOW)
"""
from __future__ import annotations

import json

# ──────────────────────────────────────────────────────────────
# 명령 빌더 (순수 함수 — GUI 없이도 테스트 가능)
# ──────────────────────────────────────────────────────────────

def build_goal_yaml(x: float, y: float) -> str:
    return f"{{header: {{frame_id: map}}, pose: {{position: {{x: {float(x)}, y: {float(y)}}}}}}}"


def build_twist_yaml(linear_x: float, angular_z: float) -> str:
    return f"{{linear: {{x: {float(linear_x)}}}, angular: {{z: {float(angular_z)}}}}}"


def build_bool_yaml(value: bool) -> str:
    return f"{{data: {str(bool(value)).lower()}}}"


def build_event_yaml(event: dict) -> str:
    # std_msgs/String 의 data 필드에 JSON 문자열을 넣는다.
    # JSON은 큰따옴표를 쓰므로 YAML 작은따옴표 스칼라 안에 안전하게 들어간다.
    js = json.dumps(event, ensure_ascii=False)
    return f"{{data: '{js}'}}"


def pub_args(topic: str, msg_type: str, yaml: str) -> list[str]:
    """`ros2 topic pub --once` 인자 리스트."""
    return ["ros2", "topic", "pub", "--once", "-w", "0", topic, msg_type, yaml]


def format_received_cmd(name: str, payload: dict) -> str:
    """Mac 관제에서 내려온 원격 명령(MQTT robot/<id>/cmd/<name>)을 보기 좋게."""
    try:
        if name == "cmd_vel":
            return f"cmd_vel   linear.x={float(payload.get('linear_x', 0)):.2f}  angular.z={float(payload.get('angular_z', 0)):.2f}"
        if name == "goal":
            return f"goal      x={float(payload.get('x', 0)):.2f}  y={float(payload.get('y', 0)):.2f}  yaw={float(payload.get('yaw', 0)):.1f}°"
        if name == "estop":
            return f"estop     engaged={str(payload.get('engaged', False)).lower()}"
        if name == "mission":
            return f"mission   action={payload.get('action', '?')}"
    except (TypeError, ValueError):
        pass
    return f"{name}   {payload}"


def launch_args(broker_host: str, broker_port: str, robot_id: str) -> list[str]:
    return [
        "ros2", "launch", "yogibot_bridge", "bringup.launch.py",
        f"broker_host:={broker_host}",
        f"broker_port:={broker_port}",
        f"robot_id:={robot_id}",
    ]


# 토픽/타입 상수 (robot_simulator 구독 토픽과 일치)
T_GOAL = ("/goal_pose_cmd", "geometry_msgs/msg/PoseStamped")
T_CMDVEL = ("/cmd_vel", "geometry_msgs/msg/Twist")
T_ESTOP = ("/emergency_stop", "std_msgs/msg/Bool")
T_EVENT = ("/yogibot/event", "std_msgs/msg/String")

# jog 프리셋: (라벨, linear.x, angular.z)
JOG = {
    "▲ 전진": (0.20, 0.0),
    "▼ 후진": (-0.15, 0.0),
    "◀ 좌회전": (0.0, 0.6),
    "▶ 우회전": (0.0, -0.6),
    "■ 정지": (0.0, 0.0),
}

# 이벤트 프리셋
EVENTS = {
    "미션완료": {"event_type": "MISSION_COMPLETE", "result": "SUCCESS",
                "duration_sec": 87.3, "distance_m": 12.45},
    "장애물감지": {"event_type": "OBSTACLE_DETECTED", "min_range_m": 0.18,
                  "action": "REPLANNING"},
    "배터리부족": {"event_type": "BATTERY_LOW", "voltage": 10.8,
                  "percentage": 0.15, "action": "RETURN_TO_BASE"},
}


# ──────────────────────────────────────────────────────────────
# GUI (tkinter) — 위 빌더를 subprocess로 실행
# ──────────────────────────────────────────────────────────────
def run_gui():  # pragma: no cover (디스플레이 필요)
    import os
    import shutil
    import signal
    import subprocess
    import threading
    import tkinter as tk
    from datetime import datetime
    from tkinter import ttk, scrolledtext

    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        mqtt = None

    class App:
        def __init__(self, root: tk.Tk):
            self.root = root
            self.proc: subprocess.Popen | None = None
            self.estop_on = False
            self.rx_client = None          # 원격 명령 수신용 MQTT 클라이언트
            root.title("YogiBot 송신 패널")
            root.geometry("580x820")

            self._build_pipeline_box()
            self._build_goal_box()
            self._build_jog_box()
            self._build_estop_box()
            self._build_event_box()
            self._build_receive_box()
            self._build_log_box()

            if shutil.which("ros2") is None:
                self.log("⚠ 'ros2' 명령을 찾을 수 없습니다. ROS2를 source 한 터미널에서 실행하세요.")
            else:
                self.log("준비됨. 브로커 IP를 Mac 호스트로 바꾼 뒤 [송신 시작]을 누르세요.")

            root.protocol("WM_DELETE_WINDOW", self.on_close)

        # ---- 위젯 ----
        def _section(self, title):
            f = ttk.LabelFrame(self.root, text=title, padding=8)
            f.pack(fill="x", padx=10, pady=5)
            return f

        def _build_pipeline_box(self):
            f = self._section("1. 파이프라인 (simulator + bridge)")
            row = ttk.Frame(f); row.pack(fill="x")
            ttk.Label(row, text="브로커 IP").pack(side="left")
            self.host = ttk.Entry(row, width=15); self.host.insert(0, "127.0.0.1")
            self.host.pack(side="left", padx=4)
            ttk.Label(row, text="포트").pack(side="left")
            self.port = ttk.Entry(row, width=6); self.port.insert(0, "1883")
            self.port.pack(side="left", padx=4)
            ttk.Label(row, text="robot_id").pack(side="left")
            self.rid = ttk.Entry(row, width=10); self.rid.insert(0, "waffle_01")
            self.rid.pack(side="left", padx=4)

            row2 = ttk.Frame(f); row2.pack(fill="x", pady=(8, 0))
            self.btn_start = ttk.Button(row2, text="▶ 송신 시작", command=self.start)
            self.btn_start.pack(side="left")
            self.btn_stop = ttk.Button(row2, text="■ 정지", command=self.stop, state="disabled")
            self.btn_stop.pack(side="left", padx=6)
            self.status = ttk.Label(row2, text="● 정지", foreground="gray")
            self.status.pack(side="left", padx=10)

        def _build_goal_box(self):
            f = self._section("2. 목표 전송 (/goal_pose_cmd)")
            ttk.Label(f, text="x").pack(side="left")
            self.gx = ttk.Entry(f, width=8); self.gx.insert(0, "5.0"); self.gx.pack(side="left", padx=4)
            ttk.Label(f, text="y").pack(side="left")
            self.gy = ttk.Entry(f, width=8); self.gy.insert(0, "3.0"); self.gy.pack(side="left", padx=4)
            ttk.Button(f, text="목표 보내기", command=self.send_goal).pack(side="left", padx=8)

        def _build_jog_box(self):
            f = self._section("3. 수동 주행 (/cmd_vel — 약 3초 유지)")
            for label, (lin, ang) in JOG.items():
                ttk.Button(f, text=label, width=8,
                           command=lambda l=lin, a=ang, t=label: self.send_jog(l, a, t)
                           ).pack(side="left", padx=3)

        def _build_estop_box(self):
            f = self._section("4. 비상정지 (/emergency_stop)")
            self.btn_estop = ttk.Button(f, text="E-STOP 켜기", command=self.toggle_estop)
            self.btn_estop.pack(side="left")
            self.estop_lbl = ttk.Label(f, text="해제됨", foreground="green")
            self.estop_lbl.pack(side="left", padx=10)

        def _build_event_box(self):
            f = self._section("5. 이벤트 전송 (/yogibot/event → events.jsonl)")
            for name in EVENTS:
                ttk.Button(f, text=name, command=lambda n=name: self.send_event(n)
                           ).pack(side="left", padx=4)

        def _build_receive_box(self):
            f = self._section("6. 원격 명령 수신 (Mac 관제 → 로봇)")
            row = ttk.Frame(f); row.pack(fill="x")
            self.btn_rx = ttk.Button(row, text="▶ 수신 시작", command=self.toggle_receive)
            self.btn_rx.pack(side="left")
            self.rx_status = ttk.Label(row, text="● 끊김", foreground="gray")
            self.rx_status.pack(side="left", padx=10)
            ttk.Label(row, text="(robot/<id>/cmd/# 구독)").pack(side="left")
            self.rxtxt = scrolledtext.ScrolledText(f, height=7, font=("monospace", 9))
            self.rxtxt.pack(fill="both", expand=True, pady=(6, 0))

        def _build_log_box(self):
            f = self._section("로그")
            self.txt = scrolledtext.ScrolledText(f, height=8, font=("monospace", 9))
            self.txt.pack(fill="both", expand=True)

        # ---- 로그 ----
        def log(self, msg: str):
            self.txt.insert("end", msg.rstrip() + "\n")
            self.txt.see("end")

        # ---- 파이프라인 시작/정지 ----
        def start(self):
            if self.proc and self.proc.poll() is None:
                self.log("이미 송신 중입니다.")
                return
            args = launch_args(self.host.get().strip(), self.port.get().strip(), self.rid.get().strip())
            self.log("$ " + " ".join(args))
            try:
                self.proc = subprocess.Popen(
                    args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1, start_new_session=True)
            except FileNotFoundError:
                self.log("✗ ros2 실행 실패. ROS2/워크스페이스를 source 했는지 확인하세요.")
                return
            threading.Thread(target=self._pump, daemon=True).start()
            self.btn_start.config(state="disabled")
            self.btn_stop.config(state="normal")
            self.status.config(text="● 송신 중", foreground="#0a0")

        def _pump(self):
            assert self.proc and self.proc.stdout
            for line in self.proc.stdout:
                self.root.after(0, self.log, line)
            self.root.after(0, self._on_proc_exit)

        def _on_proc_exit(self):
            self.status.config(text="● 정지", foreground="gray")
            self.btn_start.config(state="normal")
            self.btn_stop.config(state="disabled")
            self.log("— 파이프라인 종료됨 —")

        def stop(self):
            if self.proc and self.proc.poll() is None:
                try:
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGINT)
                except ProcessLookupError:
                    pass
                self.log("정지 요청(SIGINT) 전송…")

        # ---- 1회성 publish ----
        def _pub(self, topic_type, yaml, desc):
            topic, mtype = topic_type
            args = pub_args(topic, mtype, yaml)

            def worker():
                try:
                    r = subprocess.run(args, capture_output=True, text=True, timeout=10)
                    ok = r.returncode == 0
                    self.root.after(0, self.log,
                                    f"{'✓' if ok else '✗'} {desc}  → {topic}")
                    if not ok and r.stderr:
                        self.root.after(0, self.log, "   " + r.stderr.strip().splitlines()[-1])
                except subprocess.TimeoutExpired:
                    self.root.after(0, self.log, f"✗ {desc} 타임아웃 (구독자 없음?)")
                except FileNotFoundError:
                    self.root.after(0, self.log, "✗ ros2 없음 — ROS2 source 확인")
            threading.Thread(target=worker, daemon=True).start()

        def send_goal(self):
            try:
                x, y = float(self.gx.get()), float(self.gy.get())
            except ValueError:
                self.log("✗ x, y 숫자를 확인하세요."); return
            self._pub(T_GOAL, build_goal_yaml(x, y), f"목표 ({x}, {y})")

        def send_jog(self, lin, ang, label):
            self._pub(T_CMDVEL, build_twist_yaml(lin, ang), f"주행 {label}")

        def toggle_estop(self):
            self.estop_on = not self.estop_on
            self._pub(T_ESTOP, build_bool_yaml(self.estop_on),
                      f"E-STOP {'ON' if self.estop_on else 'OFF'}")
            self.btn_estop.config(text="E-STOP 끄기" if self.estop_on else "E-STOP 켜기")
            self.estop_lbl.config(text="비상정지" if self.estop_on else "해제됨",
                                  foreground="red" if self.estop_on else "green")

        def send_event(self, name):
            self._pub(T_EVENT, build_event_yaml(EVENTS[name]), f"이벤트 {name}")

        # ---- 원격 명령 수신 (MQTT robot/<id>/cmd/#) ----
        def rx_log(self, msg: str):
            ts = datetime.now().strftime("%H:%M:%S")
            self.rxtxt.insert("end", f"[{ts}] {msg}\n")
            self.rxtxt.see("end")

        def toggle_receive(self):
            if self.rx_client is not None:
                self._rx_disconnect()
                return
            if mqtt is None:
                self.rx_log("✗ paho-mqtt 미설치 — pip install paho-mqtt")
                return
            host, port, rid = self.host.get().strip(), self.port.get().strip(), self.rid.get().strip()
            try:
                cli = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1,
                                  client_id=f"yogibot-gui-rx-{os.getpid()}")
            except (AttributeError, TypeError):
                cli = mqtt.Client(client_id=f"yogibot-gui-rx-{os.getpid()}")
            cli.user_data_set(rid)
            cli.on_connect = self._rx_on_connect
            cli.on_message = self._rx_on_message
            cli.on_disconnect = self._rx_on_disconnect
            try:
                cli.connect(host, int(port), keepalive=30)
            except Exception as e:
                self.rx_log(f"✗ 브로커 연결 실패 {host}:{port} — {e}")
                return
            cli.loop_start()
            self.rx_client = cli
            self.btn_rx.config(text="■ 수신 정지")
            self.rx_log(f"브로커 {host}:{port} 연결 시도, robot/{rid}/cmd/# 구독")

        def _rx_disconnect(self):
            if self.rx_client is not None:
                try:
                    self.rx_client.loop_stop()
                    self.rx_client.disconnect()
                except Exception:
                    pass
                self.rx_client = None
            self.btn_rx.config(text="▶ 수신 시작")
            self.rx_status.config(text="● 끊김", foreground="gray")

        def _rx_on_connect(self, client, userdata, flags, rc):
            client.subscribe(f"robot/{userdata}/cmd/#", qos=1)
            self.root.after(0, self.rx_status.config, {"text": "● 수신 중", "foreground": "#0a0"})
            self.root.after(0, self.rx_log, f"✓ 연결됨 (rc={rc}). Mac 관제 명령 대기 중…")

        def _rx_on_disconnect(self, client, userdata, rc):
            self.root.after(0, self.rx_status.config, {"text": "● 끊김", "foreground": "gray"})

        def _rx_on_message(self, client, userdata, msg):
            name = msg.topic.split("/")[-1]
            try:
                payload = json.loads(msg.payload.decode())
            except (UnicodeDecodeError, json.JSONDecodeError):
                payload = {"raw": msg.payload[:80]}
            self.root.after(0, self.rx_log, "⬇ " + format_received_cmd(name, payload))

        def on_close(self):
            self._rx_disconnect()
            self.stop()
            self.root.after(300, self.root.destroy)

    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    run_gui()
