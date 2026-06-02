"""
Persistent storage for the latest bound Feishu P2P chat.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


STORE_PATH = Path(__file__).resolve().parent.parent / "data" / "binding.json"


def load_binding() -> dict[str, Any] | None:
    if not STORE_PATH.exists():
        return None

    with STORE_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_binding(chat_id: str, user_open_id: str | None = None, user_name: str | None = None) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "receive_id": chat_id,
        "receive_id_type": "chat_id",
        "user_open_id": user_open_id,
        "user_name": user_name,
    }
    with STORE_PATH.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
