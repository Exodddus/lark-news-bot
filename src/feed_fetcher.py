"""
Single-feed fetcher for RSS and Atom sources.
"""
from __future__ import annotations

import html
import re
from typing import Any, Dict, List

import feedparser
import requests

from time_window import within_lookback


class FeedFetcher:
    def __init__(self, timeout: int = 20, disable_env_proxy: bool = True) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.trust_env = not disable_env_proxy
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

    def fetch(self, source: Dict[str, Any]) -> List[Dict[str, Any]]:
        url = source["url"]
        response = self.session.get(url, headers=self.headers, timeout=self.timeout)
        response.raise_for_status()

        parsed = feedparser.parse(response.content)
        max_items = source.get("max_items")
        entries: List[Dict[str, Any]] = []
        for entry in parsed.entries:
            if max_items is not None and len(entries) >= max_items:
                break
            published_at = self._as_text(
                entry.get("published", entry.get("updated", ""))
            )
            if not within_lookback(published_at):
                continue
            entries.append(
                {
                    "title": self._as_text(entry.get("title", "")),
                    "link": self._pick_link(entry),
                    "summary": self._clean_text(
                        self._as_text(entry.get("summary", entry.get("description", "")))
                    ),
                    "published_at": published_at,
                    "author": self._as_text(entry.get("author", "")),
                    "source_id": source["id"],
                    "source_name": source["name"],
                    "category": source["category"],
                    "language": source.get("language", "en"),
                }
            )
        return entries

    def _pick_link(self, entry: Any) -> str:
        link = self._as_text(entry.get("link", ""))
        if link:
            return link
        links = entry.get("links", [])
        if isinstance(links, list):
            for item in links:
                href = self._as_text(getattr(item, "href", "") or item.get("href", ""))
                if href:
                    return href
        return ""

    def _as_text(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return " ".join(self._as_text(item) for item in value)
        return str(value)

    def _clean_text(self, text: str) -> str:
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
        text = " ".join(text.split())
        return text[:600]
