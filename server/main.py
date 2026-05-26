"""
YogiBot Control Tower — FastAPI 서버

데이터 흐름:
    [우분투 VM] rclpy 노드 → MQTT 브로커 → (본 서버 구독/처리/JSONL 저장)
                                            → WebSocket → React 대시보드

실행 (프로젝트 루트에서):
    uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload

환경변수:
    MQTT_HOST (기본 0.0.0.0)  MQTT_PORT (1883)  ROBOT_ID (waffle_01)
    YOGI_SIM=1  → 우분투 없이 서버 내부 시뮬레이션으로 동작 (개발용)
"""
from __future__ import annotations

import asyncio
import math
import os
import random
import time
from datetime import datetime
from typing import Literal

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .mqtt_ingest import Ingestor, ROBOT_ID
from .storage import JsonlStore, utc_now_iso

SIM_MODE = os.environ.get("YOGI_SIM") == "1"

app = FastAPI(title="YogiBot Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# 로봇 상태 — MQTT ingest로 갱신되는 실시간 캐시
# ============================================================
class RobotState:
    def __init__(self):
        # 토픽 key → 최신 data (명세서 토픽별 payload). 프론트 WS 집계의 원천.
        self.latest: dict[str, dict] = {}
        self.estop = False
        self.mission_state: Literal["IDLE", "RUNNING", "PAUSED"] = "IDLE"
        self.events: list[dict] = []
        self.cmd_log: list[dict] = []
        # 미션 이력 (목표 전송 → 미션 생성, MISSION_COMPLETE 이벤트 → 종료)
        self.missions: list[dict] = []
        self._mseq = 0
        self.current_mission: dict | None = None

    def update_telemetry(self, key: str, data: dict):
        self.latest[key] = data

    def add_event(self, ev: dict):
        ev.setdefault("timestamp", utc_now_iso())
        self.events.insert(0, ev)
        self.events = self.events[:50]

    # ---- 미션 ----
    def start_mission(self, x: float, y: float, yaw: float = 0.0) -> dict:
        """목표가 전송되면 새 미션을 생성하고 진행 중으로 표시."""
        self._mseq += 1
        m = {
            "id": f"M-{self._mseq:04d}",
            "robot_id": ROBOT_ID,
            "start_time": utc_now_iso(),
            "end_time": None,
            "goal": {"x": x, "y": y, "yaw": yaw},
            "status": "RUNNING",
            "duration_sec": None,
            "distance_m": None,
        }
        self.missions.insert(0, m)
        self.missions = self.missions[:200]
        self.current_mission = m
        self.mission_state = "RUNNING"
        return m

    def record_completed_mission(self, ev: dict, result: str = "SUCCESS") -> dict:
        """진행 중 미션이 없을 때, MISSION_COMPLETE 이벤트로부터 완료 미션을 직접 기록.
        (우분투 GUI 목표/자율주행처럼 /api/goal 을 거치지 않은 경우)"""
        self._mseq += 1
        g = ev.get("goal") or {}
        end = ev.get("timestamp") or utc_now_iso()
        m = {
            "id": f"M-{self._mseq:04d}",
            "robot_id": ev.get("robot_id", ROBOT_ID),
            "start_time": end,        # 시작 시각 미상 → 완료 시각으로 대체
            "end_time": end,
            "goal": {"x": g.get("x"), "y": g.get("y"), "yaw": g.get("yaw", 0.0)},
            "status": result,
            "duration_sec": ev.get("duration_sec"),
            "distance_m": ev.get("distance_m"),
        }
        self.missions.insert(0, m)
        self.missions = self.missions[:200]
        return m

    def finish_mission(self, result: str = "SUCCESS",
                       duration_sec=None, distance_m=None) -> dict | None:
        """진행 중 미션을 종료(완료/실패)로 마감."""
        m = self.current_mission
        if not m:
            return None
        m["end_time"] = utc_now_iso()
        m["status"] = result
        if duration_sec is not None:
            m["duration_sec"] = duration_sec
        if distance_m is not None:
            m["distance_m"] = distance_m
        self.current_mission = None
        if self.mission_state == "RUNNING":
            self.mission_state = "IDLE"
        return m

    def telemetry(self) -> dict:
        """프론트(App.jsx)가 기대하는 집계 객체.
        각 키는 명세서 토픽 data를 그대로 전달한다 (구조가 1:1로 일치)."""
        return {
            "odom": self.latest.get("odom"),
            "battery": self.latest.get("battery_state"),
            "sensorState": self.latest.get("sensor_state"),
            "amclPose": self.latest.get("amcl_pose"),
            "goal": self.latest.get("goal_pose"),
            "planData": self.latest.get("plan"),
            "missionState": self.mission_state,
            "estop": self.estop,
        }


state = RobotState()
store = JsonlStore()
ingestor = Ingestor(state, store)


# ============================================================
# WebSocket: 프론트로 텔레메트리 push (1Hz)
# ============================================================
clients: set[WebSocket] = set()


@app.websocket("/ws/telemetry")
async def ws_telemetry(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    try:
        while True:
            await ws.send_json(state.telemetry())
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        pass
    finally:
        clients.discard(ws)


@app.on_event("startup")
async def _startup():
    if SIM_MODE:
        print("[server] YOGI_SIM=1 → 내부 시뮬레이션 모드 (MQTT 미사용)", flush=True)
        asyncio.create_task(_sim_loop())
    else:
        ingestor.start()


@app.on_event("shutdown")
async def _shutdown():
    ingestor.stop()
    store.close()


# ------------------------------------------------------------
# 개발용 내부 시뮬레이터 (YOGI_SIM=1). 우분투 노드 없이 화면 확인용.
# 실제 데이터 흐름은 MQTT ingest 경로가 담당한다.
# ------------------------------------------------------------
async def _sim_loop():
    t = 0
    px, py, batt = 3.21, -1.85, 0.84
    goal = {"x": 8.4, "y": 4.2}
    while True:
        t += 1
        lin = 0.0 if state.estop else 0.35 + math.sin(t / 3) * 0.15
        ang = 0.0 if state.estop else math.cos(t / 4) * 0.4
        px += lin * 0.5 * math.cos(t / 6)
        py += lin * 0.5 * math.sin(t / 6)
        batt = max(0.18, batt - 0.0005)
        yaw = t / 6
        state.update_telemetry("odom", {"twist": {"linear": {"x": lin}, "angular": {"z": ang}}})
        state.update_telemetry("battery_state", {
            "percentage": batt, "voltage": round(11.5 + batt * 1.3, 2),
            "current": round(1.2 + random.random() * 0.4, 2), "present": True})
        state.update_telemetry("sensor_state", {"bumper": 0, "cliff": 0, "torque": True})
        state.update_telemetry("amcl_pose", {"pose": {"pose": {
            "position": {"x": px, "y": py},
            "orientation": {"x": 0, "y": 0, "z": math.sin(yaw / 2), "w": math.cos(yaw / 2)}}}})
        state.update_telemetry("goal_pose", {"pose": {"position": goal}})
        state.update_telemetry("plan", {"poses": [
            {"pose": {"position": {
                "x": px + (goal["x"] - px) * (i / 11), "y": py + (goal["y"] - py) * (i / 11)}}}
            for i in range(12)]})
        await asyncio.sleep(1.0)


# ============================================================
# REST: 조회
# ============================================================
@app.get("/api/health")
def health():
    return {"ok": True, "ts": time.time(), "mode": "sim" if SIM_MODE else "mqtt",
            "stored": store.counts()}


@app.get("/api/events")
def get_events(limit: int = 30):
    return {"events": state.events[:limit]}


_WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]  # datetime.weekday(): 0=월


def _fmt_row(m: dict) -> dict:
    """미션 dict → 로그 테이블 행."""
    st = m.get("start_time") or ""
    try:
        date = datetime.fromisoformat(st).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        date = st[:16].replace("T", " ")
    dur = m.get("duration_sec")
    dist = m.get("distance_m")
    g = m.get("goal") or {}
    gx, gy = g.get("x"), g.get("y")
    to = f"({gx:.1f}, {gy:.1f})" if isinstance(gx, (int, float)) and isinstance(gy, (int, float)) else "—"
    return {
        "id": m.get("id"),
        "date": date,
        "from": "본부",
        "to": to,
        "duration": f"{int(dur)//60}분 {int(dur)%60}초" if dur is not None else "—",
        "distance": f"{dist:.1f}m" if dist is not None else "—",
        "result": m.get("status", "RUNNING"),
    }


@app.get("/api/logs")
def get_logs():
    """실제 미션 이력 기반 통계/테이블 (목업 없음)."""
    missions = state.missions
    done = [m for m in missions if m.get("duration_sec") is not None]
    avg = int(sum(m["duration_sec"] for m in done) / len(done)) if done else 0
    total_dist_m = sum((m.get("distance_m") or 0) for m in missions)

    weekly = {d: 0 for d in _WEEKDAYS}
    for m in missions:
        try:
            wd = _WEEKDAYS[datetime.fromisoformat(m["start_time"]).weekday()]
            weekly[wd] += 1
        except (ValueError, KeyError, TypeError):
            pass

    return {
        "totalMissions": len(missions),
        "avgDurationSec": avg,
        "totalDistanceKm": round(total_dist_m / 1000, 2),
        "weekly": [{"name": d, "count": weekly[d]} for d in _WEEKDAYS],
        "rows": [_fmt_row(m) for m in missions[:50]],
    }


@app.get("/api/cmd_log")
def get_cmd_log():
    return {"log": state.cmd_log[:50]}


# ============================================================
# REST: 제어 명령 → MQTT publish (서버 → 로봇)
# ============================================================
class CmdVel(BaseModel):
    linear_x: float
    angular_z: float


class EStop(BaseModel):
    engaged: bool


class Goal(BaseModel):
    x: float
    y: float
    yaw: float = 0.0


class Mission(BaseModel):
    action: Literal["start", "pause", "cancel", "return"]


def _log_cmd(topic: str, payload: str):
    entry = {"ts": datetime.now().strftime("%H:%M:%S"), "topic": topic, "payload": payload}
    state.cmd_log.insert(0, entry)
    state.cmd_log = state.cmd_log[:50]
    print(f"[cmd] {topic}  {payload}", flush=True)


@app.post("/api/cmd_vel")
def post_cmd_vel(cmd: CmdVel):
    if state.estop:
        return {"ok": False, "reason": "estop_engaged"}
    ingestor.publish_cmd("cmd_vel", {"linear_x": cmd.linear_x, "angular_z": cmd.angular_z})
    _log_cmd("/cmd_vel", f"linear.x={cmd.linear_x:.2f} angular.z={cmd.angular_z:.2f}")
    return {"ok": True}


@app.post("/api/emergency_stop")
def post_estop(req: EStop):
    state.estop = req.engaged
    if req.engaged:
        state.mission_state = "IDLE"
    ingestor.publish_cmd("estop", {"engaged": req.engaged})
    _log_cmd("/emergency_stop", f"engaged={str(req.engaged).lower()}")
    return {"ok": True, "estop": state.estop}


@app.post("/api/goal")
def post_goal(g: Goal):
    if state.estop:
        return {"ok": False, "reason": "estop_engaged"}
    # 목표 전송 → 미션으로 처리 (생성 + JSONL 기록)
    mission = state.start_mission(g.x, g.y, g.yaw)
    store.append("missions", mission)
    ingestor.publish_cmd("goal", {"x": g.x, "y": g.y, "yaw": g.yaw})
    _log_cmd("/goal_pose", f"x={g.x:.2f} y={g.y:.2f} yaw={g.yaw:.1f}° → {mission['id']}")
    return {"ok": True, "mission_id": mission["id"]}


@app.post("/api/mission")
def post_mission(m: Mission):
    if state.estop and m.action != "cancel":
        return {"ok": False, "reason": "estop_engaged"}
    if m.action == "start":
        state.mission_state = "RUNNING"
    elif m.action == "pause":
        state.mission_state = "PAUSED"
    elif m.action == "cancel":
        state.mission_state = "IDLE"
    elif m.action == "return":
        state.mission_state = "RUNNING"
    ingestor.publish_cmd("mission", {"action": m.action})
    _log_cmd("/mission", m.action.upper() if m.action != "return" else "RETURN_HOME")
    return {"ok": True, "missionState": state.mission_state}
