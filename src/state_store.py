"""
Persistent state for cross-run deduplication.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Iterable


class StateStore:
    def __init__(self, path: str = "data/seen.json", ttl_days: int = 14) -> None:
        self.path = Path(path)
        self.ttl = ttl_days * 86400
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def is_seen(self, key: str) -> bool:
        return key in self.state

    def mark(self, keys: Iterable[str]) -> None:
        now = int(time.time())
        for key in keys:
            self.state.setdefault(key, now)

    def save(self) -> None:
        now = int(time.time())
        self.state = {
            key: timestamp
            for key, timestamp in self.state.items()
            if now - int(timestamp) < self.ttl
        }
        self.path.write_text(
            json.dumps(self.state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def key_for(item: dict) -> str:
        seed = (item.get("link") or item.get("title") or "").strip().lower()
        return hashlib.sha1(seed.encode("utf-8")).hexdigest()
