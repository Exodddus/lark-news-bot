"""
Normalize raw feed items into a consistent shape.
"""
from __future__ import annotations

from typing import Dict, List

from time_window import within_lookback


def normalize_items(items: List[Dict]) -> List[Dict]:
    normalized: List[Dict] = []
    for item in items:
        title = (item.get("title") or "").strip()
        summary = (item.get("summary") or item.get("description") or "").strip()
        if not title:
            continue
        published_at = item.get("published_at", item.get("pub_date", ""))
        if not within_lookback(published_at):
            continue
        normalized.append(
            {
                "title": title,
                "summary": summary or title,
                "link": (item.get("link") or "").strip(),
                "source_id": item.get("source_id", ""),
                "source_name": item.get("source_name", ""),
                "category": item.get("category", "industry"),
                "published_at": published_at,
                "language": item.get("language", "en"),
            }
        )
    return normalized
