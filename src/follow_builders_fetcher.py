"""
Fetch and normalize Follow Builders remote feeds.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse
from urllib.request import url2pathname

import requests


DEFAULT_X_FEED_URL = "https://raw.githubusercontent.com/zarazhangrui/follow-builders/main/feed-x.json"
DEFAULT_PODCASTS_FEED_URL = "https://raw.githubusercontent.com/zarazhangrui/follow-builders/main/feed-podcasts.json"
DEFAULT_BLOGS_FEED_URL = "https://raw.githubusercontent.com/zarazhangrui/follow-builders/main/feed-blogs.json"


class FollowBuildersFetcher:
    def __init__(self, timeout: int = 20, disable_env_proxy: bool = False) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.trust_env = not disable_env_proxy

    def fetch_remote(self) -> Dict[str, Any]:
        bundle: Dict[str, Any] = {
            "tweet_groups": [],
            "podcasts": [],
            "blogs": [],
            "stats": {},
            "reports": [],
            "errors": [],
        }
        feed_specs = [
            ("x", "Follow Builders X", _env("FOLLOW_BUILDERS_FEED_X_URL", DEFAULT_X_FEED_URL)),
            (
                "podcasts",
                "Follow Builders Podcasts",
                _env("FOLLOW_BUILDERS_FEED_PODCASTS_URL", DEFAULT_PODCASTS_FEED_URL),
            ),
            ("blogs", "Follow Builders Blogs", _env("FOLLOW_BUILDERS_FEED_BLOGS_URL", DEFAULT_BLOGS_FEED_URL)),
        ]

        for feed_type, source_name, url in feed_specs:
            try:
                data = self._load_json(url)
                normalized = self._normalize_feed(feed_type, data)
                bundle["tweet_groups"].extend(normalized.get("tweet_groups", []))
                bundle["podcasts"].extend(normalized.get("podcasts", []))
                bundle["blogs"].extend(normalized.get("blogs", []))
                generated_at = data.get("generatedAt")
                if generated_at:
                    bundle["stats"][f"{feed_type}_generated_at"] = generated_at
                bundle["reports"].append(
                    {
                        "source_id": f"follow_builders_{feed_type}",
                        "source_name": source_name,
                        "category": "follow_builders",
                        "ok": True,
                        "count": len(normalized.get("items", [])),
                    }
                )
            except Exception as exc:
                error = str(exc)
                bundle["errors"].append({"source": source_name, "error": error})
                bundle["reports"].append(
                    {
                        "source_id": f"follow_builders_{feed_type}",
                        "source_name": source_name,
                        "category": "follow_builders",
                        "ok": False,
                        "count": 0,
                        "error": error,
                    }
                )

        bundle["stats"].update(
            {
                "builders_with_tweets": len(bundle["tweet_groups"]),
                "total_tweets": sum(len(group.get("tweets", [])) for group in bundle["tweet_groups"]),
                "podcast_episodes": len(bundle["podcasts"]),
                "blog_posts": len(bundle["blogs"]),
                "errors": len(bundle["errors"]),
            }
        )
        return bundle

    def _load_json(self, location: str) -> Dict[str, Any]:
        if location.startswith("file://"):
            parsed = urlparse(location)
            path = Path(url2pathname(parsed.path))
            return json.loads(path.read_text(encoding="utf-8"))
        if location.startswith(("http://", "https://")):
            response = self.session.get(location, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        return json.loads(Path(location).read_text(encoding="utf-8"))

    def _normalize_feed(self, feed_type: str, data: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
        if feed_type == "x":
            items = self._normalize_x(data)
            return {"tweet_groups": items, "items": items}
        if feed_type == "podcasts":
            items = self._normalize_podcasts(data)
            return {"podcasts": items, "items": items}
        if feed_type == "blogs":
            items = self._normalize_blogs(data)
            return {"blogs": items, "items": items}
        return {"items": []}

    def _normalize_x(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        max_tweets = _env_int("FOLLOW_BUILDERS_MAX_TWEETS_PER_USER", 3)
        lookback_hours = _env_int("FOLLOW_BUILDERS_TWEET_LOOKBACK_HOURS", 24)
        groups: List[Dict[str, Any]] = []
        for source in data.get("x", []):
            tweets = [
                self._normalize_tweet(tweet)
                for tweet in source.get("tweets", [])[:max_tweets]
                if self._within_lookback(tweet.get("createdAt"), lookback_hours)
            ]
            tweets = [tweet for tweet in tweets if tweet.get("id") and tweet.get("url")]
            if not tweets:
                continue
            latest = max((tweet.get("published_at") or "" for tweet in tweets), default="")
            groups.append(
                {
                    "content_type": "tweet",
                    "source_name": "X / Twitter",
                    "author": source.get("name", ""),
                    "handle": source.get("handle", ""),
                    "bio": source.get("bio", ""),
                    "title": f"{source.get('name', 'Builder')} 的近期动态",
                    "body": "\n\n".join(tweet.get("text", "") for tweet in tweets),
                    "link": tweets[0].get("url", ""),
                    "published_at": latest,
                    "tweets": tweets,
                    "dedupe_keys": [f"tweets:{tweet['id']}" for tweet in tweets],
                }
            )
        return groups

    def _normalize_tweet(self, tweet: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": str(tweet.get("id", "")).strip(),
            "text": str(tweet.get("text", "")).strip(),
            "url": str(tweet.get("url", "")).strip(),
            "published_at": tweet.get("createdAt", ""),
            "metrics": {
                "likes": tweet.get("likes", 0),
                "retweets": tweet.get("retweets", 0),
                "replies": tweet.get("replies", 0),
            },
            "is_quote": bool(tweet.get("isQuote")),
            "quoted_tweet_id": tweet.get("quotedTweetId"),
        }

    def _normalize_podcasts(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        lookback_hours = _env_int("FOLLOW_BUILDERS_PODCAST_LOOKBACK_HOURS", 336)
        items: List[Dict[str, Any]] = []
        for item in data.get("podcasts", []):
            guid = str(item.get("guid") or item.get("url") or item.get("title") or "").strip()
            url = str(item.get("url", "")).strip()
            if not guid or not url or not self._within_lookback(item.get("publishedAt"), lookback_hours):
                continue
            title = str(item.get("title", "")).strip()
            items.append(
                {
                    "content_type": "podcast",
                    "source_name": item.get("name", "Podcast"),
                    "author": item.get("name", ""),
                    "title": title,
                    "body": item.get("transcript") or item.get("description") or "",
                    "summary": item.get("description", ""),
                    "link": url,
                    "published_at": item.get("publishedAt", ""),
                    "guid": guid,
                    "dedupe_key": f"podcasts:{guid}",
                }
            )
        return items

    def _normalize_blogs(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        max_articles = _env_int("FOLLOW_BUILDERS_MAX_ARTICLES_PER_BLOG", 3)
        lookback_hours = _env_int("FOLLOW_BUILDERS_BLOG_LOOKBACK_HOURS", 72)
        per_blog: dict[str, int] = {}
        items: List[Dict[str, Any]] = []
        for item in data.get("blogs", []):
            source_name = str(item.get("name", "Builder Blog")).strip()
            if per_blog.get(source_name, 0) >= max_articles:
                continue
            url = str(item.get("url", "")).strip()
            if not url or not self._within_lookback(item.get("publishedAt"), lookback_hours):
                continue
            per_blog[source_name] = per_blog.get(source_name, 0) + 1
            items.append(
                {
                    "content_type": "builder_blog",
                    "source_name": source_name,
                    "author": item.get("author", ""),
                    "title": str(item.get("title", "")).strip(),
                    "body": item.get("content") or item.get("description") or "",
                    "summary": item.get("description", ""),
                    "link": url,
                    "published_at": item.get("publishedAt", ""),
                    "dedupe_key": f"blogs:{url}",
                }
            )
        return items

    def _within_lookback(self, value: Any, hours: int) -> bool:
        if not _env_bool("FOLLOW_BUILDERS_TIME_FILTER_ENABLED", True):
            return True
        if not value:
            return True
        try:
            published_at = _parse_datetime(str(value))
        except Exception:
            return True
        now = datetime.now(timezone.utc)
        return published_at >= now - timedelta(hours=hours)


def filter_seen_bundle(bundle: Dict[str, Any], state_store: Any, debug_mode: bool) -> Dict[str, Any]:
    if debug_mode:
        return bundle

    filtered = dict(bundle)
    tweet_groups = []
    for group in bundle.get("tweet_groups", []):
        tweets = [
            tweet
            for tweet in group.get("tweets", [])
            if not state_store.is_seen(f"tweets:{tweet.get('id', '')}")
        ]
        if not tweets:
            continue
        updated = dict(group)
        updated["tweets"] = tweets
        updated["body"] = "\n\n".join(tweet.get("text", "") for tweet in tweets)
        updated["dedupe_keys"] = [f"tweets:{tweet['id']}" for tweet in tweets if tweet.get("id")]
        updated["link"] = tweets[0].get("url", "")
        tweet_groups.append(updated)

    filtered["tweet_groups"] = tweet_groups
    filtered["podcasts"] = [
        item
        for item in bundle.get("podcasts", [])
        if not state_store.is_seen(str(item.get("dedupe_key", "")))
    ]
    filtered["blogs"] = [
        item
        for item in bundle.get("blogs", [])
        if not state_store.is_seen(str(item.get("dedupe_key", "")))
    ]
    filtered["stats"] = dict(bundle.get("stats", {}))
    filtered["stats"].update(
        {
            "unseen_builders_with_tweets": len(filtered["tweet_groups"]),
            "unseen_total_tweets": sum(len(group.get("tweets", [])) for group in filtered["tweet_groups"]),
            "unseen_podcast_episodes": len(filtered["podcasts"]),
            "unseen_blog_posts": len(filtered["blogs"]),
        }
    )
    return filtered


def collect_dedupe_keys(items: List[Dict[str, Any]]) -> List[str]:
    keys: List[str] = []
    for item in items:
        item_keys = item.get("dedupe_keys")
        if isinstance(item_keys, list):
            keys.extend(str(key) for key in item_keys if key)
        elif item.get("dedupe_key"):
            keys.append(str(item["dedupe_key"]))
    return keys


def _parse_datetime(value: str) -> datetime:
    cleaned = value.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    parsed = datetime.fromisoformat(cleaned)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _env(key: str, default: str) -> str:
    return os.getenv(key, default)


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def _env_bool(key: str, default: bool = False) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
