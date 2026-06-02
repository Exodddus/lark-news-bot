"""
Persistent state for Follow Builders cross-run deduplication.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterable


class FollowBuildersStateStore:
    def __init__(self, path: str = "data/follow_builders_seen.json", ttl_days: int = 30) -> None:
        self.path = Path(path)
        self.ttl = ttl_days * 86400
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {"tweets": {}, "podcasts": {}, "blogs": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        return {
            "tweets": dict(data.get("tweets", {})),
            "podcasts": dict(data.get("podcasts", {})),
            "blogs": dict(data.get("blogs", {})),
        }

    def is_seen(self, dedupe_key: str) -> bool:
        namespace, key = self._split_key(dedupe_key)
        return key in self.state.get(namespace, {})

    def mark(self, dedupe_keys: Iterable[str]) -> None:
        now = int(time.time())
        for dedupe_key in dedupe_keys:
            namespace, key = self._split_key(dedupe_key)
            self.state.setdefault(namespace, {}).setdefault(key, now)

    def save(self) -> None:
        now = int(time.time())
        for namespace, values in list(self.state.items()):
            self.state[namespace] = {
                key: timestamp
                for key, timestamp in values.items()
                if now - int(timestamp) < self.ttl
            }
        self.path.write_text(
            json.dumps(self.state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def keys_for(item: dict) -> list[str]:
        keys = item.get("dedupe_keys")
        if isinstance(keys, list):
            return [str(key) for key in keys if key]
        key = item.get("dedupe_key")
        return [str(key)] if key else []

    @staticmethod
    def _split_key(dedupe_key: str) -> tuple[str, str]:
        if ":" not in dedupe_key:
            return "blogs", dedupe_key
        namespace, key = dedupe_key.split(":", 1)
        namespace = namespace.strip()
        if namespace not in {"tweets", "podcasts", "blogs"}:
            namespace = "blogs"
        return namespace, key.strip()
