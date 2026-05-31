"""
웨이포인트 저장소.

사용자가 대시보드 지도에서 클릭으로 찍은 점 1,2,3,…을 보관한다.
미션 탭에서 번호 클릭 → 해당 좌표로 Nav2 goal 전송.

영속: db/waypoints.json (단일 JSON). 작아서 매번 rewrite.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone

from .storage import DB_ROOT


class WaypointStore:
    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(DB_ROOT, "waypoints.json")
        self._lock = threading.Lock()
        self._items: list[dict] = []
        self._seq = 0
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            self._items = data.get("items", [])
            self._seq = data.get("seq", max((i["id"] for i in self._items), default=0))
        except (OSError, json.JSONDecodeError) as e:
            print(f"[waypoints] load failed: {e}", flush=True)

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"seq": self._seq, "items": self._items}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def list(self) -> list[dict]:
        with self._lock:
            return list(self._items)

    def add(self, x: float, y: float, yaw: float = 0.0, label: str | None = None) -> dict:
        with self._lock:
            self._seq += 1
            wp = {
                "id": self._seq,
                "label": label or str(self._seq),
                "x": float(x),
                "y": float(y),
                "yaw": float(yaw),
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            self._items.append(wp)
            self._save()
            return wp

    def delete(self, wid: int) -> bool:
        with self._lock:
            before = len(self._items)
            self._items = [w for w in self._items if w["id"] != wid]
            if len(self._items) < before:
                self._save()
                return True
            return False

    def clear(self):
        with self._lock:
            self._items = []
            self._seq = 0
            self._save()

    def get(self, wid: int) -> dict | None:
        with self._lock:
            for w in self._items:
                if w["id"] == wid:
                    return dict(w)
            return None
