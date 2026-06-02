"""
Formatting helpers shared by Lark cards and Markdown reports.
"""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Iterable, List


def humanize_time(value: Any) -> str:
    if not value:
        return "时间未知"
    try:
        dt = _parse_datetime(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        return str(value).strip() or "时间未知"


def score_text(item: Dict) -> str:
    score = item.get("score")
    if score is None:
        return "未评分"
    try:
        return f"{int(score)}/30"
    except (TypeError, ValueError):
        return f"{score}/30"


def source_text(item: Dict) -> str:
    return str(item.get("source_name") or item.get("source_id") or "未知来源").strip()


def item_meta_text(item: Dict) -> str:
    return f"来源：{source_text(item)} · 时间：{humanize_time(item.get('published_at'))} · 评分：{score_text(item)}"


def builder_meta_text(item: Dict) -> str:
    parts = [f"来源：{source_text(item)}", f"时间：{humanize_time(item.get('published_at'))}"]
    author = str(item.get("author") or "").strip()
    if author and author != source_text(item):
        parts.insert(1, f"作者：{author}")
    return " · ".join(parts)


def truncate_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def top_keywords(items: Iterable[Dict], limit: int = 10) -> List[str]:
    counts: Dict[str, int] = {}
    for item in items:
        for keyword in item.get("keywords", []):
            key = str(keyword).strip()
            if key:
                counts[key] = counts.get(key, 0) + 1
    return [
        keyword
        for keyword, _count in sorted(counts.items(), key=lambda pair: pair[1], reverse=True)[:limit]
    ]


def _parse_datetime(value: str) -> datetime:
    try:
        return parsedate_to_datetime(value)
    except Exception:
        cleaned = value.strip()
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        return datetime.fromisoformat(cleaned)
