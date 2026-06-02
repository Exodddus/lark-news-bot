"""
Load configured sources and fetch them concurrently.
"""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Tuple

from api_fetcher import ApiFetcher
from feed_fetcher import FeedFetcher


class SourceManager:
    def __init__(self, config_path: str, fetcher: FeedFetcher | None = None, api_fetcher: ApiFetcher | None = None) -> None:
        self.config_path = Path(config_path)
        timeout = _env_int("FEED_TIMEOUT", 15)
        self.fetcher = fetcher or FeedFetcher(timeout=timeout)
        self.api_fetcher = api_fetcher or ApiFetcher(timeout=timeout)

    def load_sources(self) -> List[Dict[str, Any]]:
        with self.config_path.open("r", encoding="utf-8") as file:
            sources = json.load(file)
        return [source for source in sources if source.get("enabled", True)]

    def fetch_all(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        all_items: List[Dict[str, Any]] = []
        reports: List[Dict[str, Any]] = []
        sources = self.load_sources()
        if not sources:
            return all_items, reports

        max_workers = max(1, _env_int("FEED_CONCURRENCY", 10))
        success_count = 0
        fail_count = 0
        processed = 0

        for batch_start in range(0, len(sources), max_workers):
            batch = sources[batch_start : batch_start + max_workers]
            batch_items_count = 0
            with ThreadPoolExecutor(max_workers=len(batch)) as executor:
                futures = [executor.submit(self._fetch_source_safe, source) for source in batch]
                for future in as_completed(futures):
                    items, report = future.result()
                    reports.append(report)
                    all_items.extend(items)
                    batch_items_count += len(items)
                    if report.get("ok"):
                        success_count += 1
                    else:
                        fail_count += 1

            processed += len(batch)
            print(
                "[fetch] Progress: "
                f"{processed}/{len(sources)} feeds processed "
                f"({success_count} ok, {fail_count} failed, "
                f"{batch_items_count} recent items in batch)"
            )
        return all_items, reports

    def _fetch_source_safe(self, source: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        try:
            items = self._fetch_source(source)
            return items, {
                "source_id": source["id"],
                "source_name": source["name"],
                "category": source["category"],
                "ok": True,
                "count": len(items),
            }
        except Exception as exc:
            return [], {
                "source_id": source["id"],
                "source_name": source["name"],
                "category": source["category"],
                "ok": False,
                "count": 0,
                "error": str(exc),
            }

    def _fetch_source(self, source: Dict[str, Any]) -> List[Dict[str, Any]]:
        source_type = source.get("type", "rss")
        if source_type in {"rss", "atom"}:
            return self.fetcher.fetch(source)
        if source_type == "api":
            return self.api_fetcher.fetch(source)
        raise ValueError(f"Unsupported source type: {source_type}")


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default
