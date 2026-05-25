"""
JSONL 저장소.

명세서 `TurtleBot3_Waffle_JSON_저장명세서` 5.2 디렉토리 구조를 따른다:

    db/
    ├── 2026-05-26/
    │   ├── odom.jsonl
    │   ├── imu.jsonl
    │   ├── scan.jsonl
    │   ├── battery_state.jsonl
    │   ├── sensor_state.jsonl
    │   ├── amcl_pose.jsonl
    │   ├── goal_pose.jsonl
    │   ├── plan.jsonl
    │   └── events.jsonl
    └── images/

한 줄에 JSON 레코드 하나(JSON Lines). append 마다 flush 하여
비정상 종료 시 유실을 막는다(명세서 7. 주의사항 "파일 flush").
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone

# 프로젝트 루트(server/의 부모)의 db/ 에 저장. 환경변수로 재정의 가능.
DB_ROOT = os.environ.get(
    "YOGI_DB_ROOT",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db"),
)


class JsonlStore:
    """토픽별 .jsonl 파일에 append 하는 스레드 안전 저장소.

    날짜가 바뀌면 자동으로 새 날짜 디렉토리/파일로 로테이션한다.
    파일 핸들은 (날짜, 토픽키)별로 캐싱한다.
    """

    def __init__(self, root: str = DB_ROOT):
        self.root = root
        self._lock = threading.Lock()
        self._handles: dict[tuple[str, str], "object"] = {}
        self._counts: dict[str, int] = {}

    def _today(self) -> str:
        # 로컬 날짜 기준 디렉토리(파일 관리 편의). 레코드 내부 timestamp는 UTC.
        return datetime.now().strftime("%Y-%m-%d")

    def _handle(self, key: str):
        date = self._today()
        cache_key = (date, key)
        fh = self._handles.get(cache_key)
        if fh is None:
            day_dir = os.path.join(self.root, date)
            os.makedirs(day_dir, exist_ok=True)
            fh = open(os.path.join(day_dir, f"{key}.jsonl"), "a", encoding="utf-8")
            self._handles[cache_key] = fh
        return fh

    def append(self, key: str, record: dict) -> None:
        """`key`.jsonl 에 record 한 줄을 append + flush."""
        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            fh = self._handle(key)
            fh.write(line + "\n")
            fh.flush()
            self._counts[key] = self._counts.get(key, 0) + 1

    def counts(self) -> dict[str, int]:
        """프로세스 시작 후 토픽별 누적 저장 건수(모니터링용)."""
        with self._lock:
            return dict(self._counts)

    def close(self) -> None:
        with self._lock:
            for fh in self._handles.values():
                try:
                    fh.close()
                except Exception:
                    pass
            self._handles.clear()


def utc_now_iso() -> str:
    """ISO 8601 UTC (명세서 3. 공통 구조의 timestamp 형식)."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")
