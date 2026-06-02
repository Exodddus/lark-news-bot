"""
Fetchers for JSON/API-based sources.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List

import requests

from time_window import cutoff_datetime, within_lookback


class ApiFetcher:
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
        api_kind = source.get("api_kind")
        if api_kind == "semantic_scholar":
            return self._fetch_semantic_scholar(source)
        if api_kind == "hn_algolia":
            return self._fetch_hn_algolia(source)
        raise ValueError(f"Unsupported api source kind: {api_kind}")

    def _fetch_semantic_scholar(self, source: Dict[str, Any]) -> List[Dict[str, Any]]:
        params = dict(source.get("params", {}))
        headers = dict(self.headers)
        api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
        if api_key:
            headers["x-api-key"] = api_key

        response = self.session.get(
            source["url"],
            params=params,
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()

        items: List[Dict[str, Any]] = []
        for paper in data.get("data", []):
            title = paper.get("title") or ""
            abstract = paper.get("abstract") or ""
            url = paper.get("url") or ""
            publication_date = paper.get("publicationDate") or str(paper.get("year") or "")
            if not within_lookback(publication_date):
                continue

            items.append(
                {
                    "title": title,
                    "summary": abstract,
                    "link": url,
                    "published_at": publication_date,
                    "author": ", ".join(author.get("name", "") for author in paper.get("authors", [])[:3]),
                    "source_id": source["id"],
                    "source_name": source["name"],
                    "category": source["category"],
                    "language": source.get("language", "en"),
                }
            )
        return items

    def _fetch_hn_algolia(self, source: Dict[str, Any]) -> List[Dict[str, Any]]:
        params = dict(source.get("params", {}))
        cutoff_ts = int(cutoff_datetime().timestamp())
        existing_filter = params.get("numericFilters")
        lookback_filter = f"created_at_i>{cutoff_ts}"
        if existing_filter:
            params["numericFilters"] = f"{existing_filter},{lookback_filter}"
        else:
            params["numericFilters"] = lookback_filter
        response = self.session.get(
            source["url"],
            params=params,
            headers=self.headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()

        items: List[Dict[str, Any]] = []
        for hit in data.get("hits", []):
            title = hit.get("title") or hit.get("story_title") or ""
            url = hit.get("url") or hit.get("story_url") or ""
            published_at = hit.get("created_at", "")
            if not title:
                continue
            if not within_lookback(published_at):
                continue
            items.append(
                {
                    "title": title,
                    "summary": hit.get("story_text") or "",
                    "link": url,
                    "published_at": published_at,
                    "author": hit.get("author", ""),
                    "source_id": source["id"],
                    "source_name": source["name"],
                    "category": source["category"],
                    "language": source.get("language", "en"),
                }
            )
        return items
