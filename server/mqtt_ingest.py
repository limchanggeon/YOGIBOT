"""
MQTT 수신(ingest) 레이어.

우분투 VM의 rclpy 노드(mqtt_bridge)가 브로커로 publish 한 메시지를
서버가 구독하여 ① 검증/처리 ② JSONL 저장 ③ 실시간 상태 갱신 한다.

MQTT 토픽 규약 (노드 ↔ 서버 공통):
    robot/<robot_id>/<key>     # 텔레메트리. key ∈ TELEMETRY_KEYS
    robot/<robot_id>/event     # 이벤트 로그 (event_type ...)
    robot/<robot_id>/cmd/<n>   # 서버 → 로봇 제어 명령 (n ∈ cmd_vel|goal|mission|estop)

텔레메트리 payload 는 명세서 공통 래퍼:
    {"timestamp": "...ISO8601 UTC...", "topic": "/odom", "data": { ... }}
"""
from __future__ import annotations

import json
import os
import threading

import paho.mqtt.client as mqtt

from .storage import JsonlStore, utc_now_iso


def _new_client(client_id: str) -> mqtt.Client:
    """paho-mqtt 1.x/2.x 양쪽에서 동작하는 클라이언트 생성 (VERSION1 콜백 사용)."""
    try:
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id=client_id)
    except (AttributeError, TypeError):  # paho-mqtt < 2.0
        return mqtt.Client(client_id=client_id)

MQTT_HOST = os.environ.get("MQTT_HOST", "0.0.0.0")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
ROBOT_ID = os.environ.get("ROBOT_ID", "waffle_01")

# 저장/추적 대상 텔레메트리 키 (MQTT key == 명세서 토픽명에서 / 제거)
TELEMETRY_KEYS = {
    "odom", "imu", "scan", "battery_state",
    "sensor_state", "amcl_pose", "goal_pose", "plan",
}


class Ingestor:
    """MQTT 구독 클라이언트. state(실시간 캐시)와 store(JSONL)를 갱신한다."""

    def __init__(self, state, store: JsonlStore):
        self.state = state
        self.store = store
        self._connected = threading.Event()
        self.client = _new_client(f"yogibot-server-{os.getpid()}")
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    # ---- lifecycle -------------------------------------------------
    def start(self):
        """브로커 연결 후 백그라운드 네트워크 루프 시작 (논블로킹)."""
        try:
            self.client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
        except Exception as e:  # 브로커 미기동 시에도 서버는 떠 있어야 함
            print(f"[mqtt] connect failed ({MQTT_HOST}:{MQTT_PORT}): {e}", flush=True)
        self.client.loop_start()

    def stop(self):
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass

    # ---- callbacks -------------------------------------------------
    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._connected.set()
            sub = f"robot/{ROBOT_ID}/#"
            client.subscribe(sub, qos=1)
            print(f"[mqtt] connected {MQTT_HOST}:{MQTT_PORT}, subscribed {sub}", flush=True)
        else:
            print(f"[mqtt] connect refused rc={rc}", flush=True)

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            print(f"[mqtt] bad payload on {msg.topic}: {e}", flush=True)
            return

        # robot/<id>/<...> → tail
        parts = msg.topic.split("/")
        if len(parts) < 3 or parts[0] != "robot":
            return
        tail = parts[2]

        if tail == "event":
            self._handle_event(payload)
        elif tail == "cmd":
            return  # 서버가 보낸 명령의 에코는 무시
        elif tail in TELEMETRY_KEYS:
            self._handle_telemetry(tail, payload)
        # 그 외 키는 무시 (대역폭/저장 절약)

    # ---- handlers --------------------------------------------------
    def _handle_telemetry(self, key: str, payload: dict):
        # 검증: 공통 래퍼 형태 보정
        if "data" not in payload:
            payload = {"timestamp": utc_now_iso(), "topic": f"/{key}", "data": payload}
        payload.setdefault("timestamp", utc_now_iso())
        payload.setdefault("topic", f"/{key}")
        # 서버 수신 시각도 함께 기록 (명세서 6. 타임스탬프 동기화 권장)
        payload.setdefault("received_at", utc_now_iso())

        # ① 저장
        self.store.append(key, payload)
        # ② 실시간 상태 캐시 갱신 (프론트 WS 집계용)
        self.state.update_telemetry(key, payload["data"])

    def _handle_event(self, ev: dict):
        ev.setdefault("timestamp", utc_now_iso())
        ev.setdefault("robot_id", ROBOT_ID)
        self.store.append("events", ev)
        self.state.add_event(ev)
        print(f"[event] {ev.get('event_type')} {ev}", flush=True)

        # 로봇이 목표 도착을 알리면 진행 중 미션을 마감
        et = ev.get("event_type")
        if et in ("MISSION_COMPLETE", "MISSION_FAILED"):
            result = ev.get("result", "SUCCESS" if et == "MISSION_COMPLETE" else "FAILED")
            # 진행 중 미션이 있으면 마감, 없으면 이벤트로부터 완료 미션 생성
            m = self.state.finish_mission(result, ev.get("duration_sec"), ev.get("distance_m"))
            if m is None:
                m = self.state.record_completed_mission(ev, result)
            self.store.append("missions", m)
            # 도착 완료 → 지도의 목표/경로 마커 제거 (대기 상태)
            self.state.latest.pop("goal_pose", None)
            self.state.latest.pop("plan", None)
            print(f"[mission] {m['id']} → {m['status']}", flush=True)

    # ---- 서버 → 로봇 명령 publish ----------------------------------
    def publish_cmd(self, name: str, payload: dict):
        topic = f"robot/{ROBOT_ID}/cmd/{name}"
        self.client.publish(topic, json.dumps(payload), qos=1)
