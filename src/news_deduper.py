"""
Simple link/title based deduplication.
"""
from __future__ import annotations

import re
from typing import Dict, List, Set, Tuple


def dedupe_items(items: List[Dict]) -> List[Dict]:
    seen_links: Set[str] = set()
    seen_titles: Set[Tuple[str, str]] = set()
    deduped: List[Dict] = []

    for item in items:
        link = (item.get("link") or "").strip()
        title_key = _normalize_title(item.get("title", ""))
        key = (item.get("category", ""), title_key)

        if link and link in seen_links:
            continue
        if title_key and key in seen_titles:
            continue

        if link:
            seen_links.add(link)
        if title_key:
            seen_titles.add(key)
        deduped.append(item)
    return deduped


def _normalize_title(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff ]", "", text)
    return text
