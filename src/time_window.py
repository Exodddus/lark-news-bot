"""
Shared time-window filtering for fetched items.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any


def hours_lookback(default: int = 168) -> int:
    try:
        return int(os.getenv("HOURS_LOOKBACK", str(default)))
    except ValueError:
        return default


def cutoff_datetime() -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=hours_lookback())


def within_lookback(value: Any) -> bool:
    if not value:
        return True
    try:
        dt = parse_datetime(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc) >= cutoff_datetime()
    except Exception:
        return True


def parse_datetime(value: str) -> datetime:
    try:
        return parsedate_to_datetime(value)
    except Exception:
        cleaned = value.strip()
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        return datetime.fromisoformat(cleaned)
