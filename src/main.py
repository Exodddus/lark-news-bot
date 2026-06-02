"""
Main entrypoint for the multi-source news bot.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import schedule
from dotenv import load_dotenv

from binding_store import load_binding
from follow_builders_fetcher import FollowBuildersFetcher, collect_dedupe_keys, filter_seen_bundle
from follow_builders_state import FollowBuildersStateStore
from lark_service import LarkService
from llm_service import LLMService
from markdown_report import write_markdown_report
from news_assembler import assemble_sections
from news_deduper import dedupe_items
from news_normalizer import normalize_items
from source_manager import SourceManager
from state_store import StateStore


BASE_DIR = Path(__file__).resolve().parent.parent


def is_placeholder(value: str | None) -> bool:
    if not value:
        return True
    lowered = value.lower()
    return "xxxxxxxx" in lowered or "example.com" in lowered


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


class NewsBot:
    def __init__(self) -> None:
        load_dotenv()
        self._validate_env()

        source_config_path = os.getenv("SOURCE_CONFIG_PATH", str(BASE_DIR / "config" / "sources.json"))
        self.source_manager = SourceManager(source_config_path)
        self.llm_service = LLMService(
            api_key=self._require_llm_api_key(),
            api_url=self._llm_api_url(),
            model=self._llm_model(),
        )
        state_path = os.getenv("STATE_PATH", str(BASE_DIR / "data" / "seen.json"))
        self.state_store = StateStore(state_path, ttl_days=_env_int("STATE_TTL_DAYS", 14))
        self.lark_service = self._build_lark_service()
        self.schedule_time = os.getenv("SCHEDULE_TIME", "09:00")
        self.run_on_start = os.getenv("RUN_ON_START", "false").lower() == "true"
        self.top_n = _env_int("TOP_N", 15)
        self.max_per_category = _env_int("MAX_PER_CATEGORY", 5)
        self.debug_mode = _env_bool("DEBUG_MODE", False)
        self.markdown_output_dir = os.getenv("MARKDOWN_OUTPUT_DIR", str(BASE_DIR / "data"))
        self.follow_builders_enabled = _env_bool("FOLLOW_BUILDERS_ENABLED", False)
        self.follow_builders_mode = os.getenv("FOLLOW_BUILDERS_MODE", "remote").strip().lower()
        self.follow_builders_fetcher = FollowBuildersFetcher(timeout=_env_int("FEED_TIMEOUT", 15))
        follow_builders_state_path = os.getenv(
            "FOLLOW_BUILDERS_STATE_PATH",
            str(BASE_DIR / "data" / "follow_builders_seen.json"),
        )
        self.follow_builders_state = FollowBuildersStateStore(
            follow_builders_state_path,
            ttl_days=_env_int("FOLLOW_BUILDERS_STATE_TTL_DAYS", 30),
        )

    def _require_llm_api_key(self) -> str:
        value = os.getenv("LLM_API_KEY")
        if value is None:
            raise ValueError("Missing required environment variable: LLM_API_KEY")
        return value

    def _llm_api_url(self) -> str:
        return os.getenv("LLM_API_URL", "https://api.deepseek.com/chat/completions")

    def _llm_model(self) -> str:
        return os.getenv("LLM_MODEL", "deepseek-v4-flash")

    def _build_lark_service(self) -> LarkService:
        app_id = os.getenv("LARK_APP_ID")
        app_secret = os.getenv("LARK_APP_SECRET")
        webhook_url = os.getenv("LARK_WEBHOOK_URL")

        if webhook_url:
            return LarkService(webhook_url=webhook_url)

        if app_id and app_secret:
            receive_id = os.getenv("LARK_RECEIVE_ID")
            receive_id_type = os.getenv("LARK_RECEIVE_ID_TYPE", "open_id")
            if is_placeholder(receive_id):
                binding = load_binding()
                if binding:
                    receive_id = binding.get("receive_id")
                    receive_id_type = binding.get("receive_id_type", "chat_id")
                else:
                    receive_id = None

            return LarkService(
                app_id=app_id,
                app_secret=app_secret,
                receive_id=receive_id,
                receive_id_type=receive_id_type,
            )

        raise ValueError("Configure either LARK_WEBHOOK_URL or LARK_APP_ID + LARK_APP_SECRET")

    def _validate_env(self) -> None:
        if not os.getenv("LLM_API_KEY"):
            print("Missing LLM_API_KEY")
            sys.exit(1)

        has_webhook = bool(os.getenv("LARK_WEBHOOK_URL"))
        has_app = bool(os.getenv("LARK_APP_ID") and os.getenv("LARK_APP_SECRET"))
        if not (has_webhook or has_app):
            print("Configure either webhook mode or app mode first.")
            sys.exit(1)

        if has_app and is_placeholder(os.getenv("LARK_RECEIVE_ID")) and not load_binding():
            print("App mode is enabled but no valid LARK_RECEIVE_ID or bound private chat is available yet.")
            print("Run `python listen_and_bind.py` and send a private message to the app once.")

    def _fetch_cache_path(self) -> Path:
        return BASE_DIR / "data" / "fetch_cache.json"

    def _save_fetch_cache(self, raw_items: list, fetch_report: list) -> None:
        cache_path = self._fetch_cache_path()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps({"raw_items": raw_items, "fetch_report": fetch_report}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Fetch cache saved → {cache_path}\n")

    def _load_fetch_cache(self) -> tuple[list, list]:
        cache_path = self._fetch_cache_path()
        if not cache_path.exists():
            raise FileNotFoundError(f"No fetch cache found at {cache_path}. Run without --from-cache first.")
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        raw_items = data.get("raw_items", [])
        fetch_report = data.get("fetch_report", [])
        mtime = datetime.fromtimestamp(cache_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        print(f"Loaded fetch cache from {cache_path} (saved at {mtime}, {len(raw_items)} items)\n")
        return raw_items, fetch_report

    def run(self, dry_run: bool = False, from_cache: bool = False) -> bool:
        try:
            print("\n" + "=" * 50)
            print("Starting multi-source digest task...")
            print("=" * 50 + "\n")

            if from_cache:
                print("Step 1/4: Load from fetch cache (skipping live fetch)")
                raw_items, fetch_report = self._load_fetch_cache()
            else:
                print("Step 1/4: Fetch configured sources")
                raw_items, fetch_report = self.source_manager.fetch_all()
                for report in fetch_report:
                    status = "OK" if report["ok"] else "FAIL"
                    extra = f" count={report['count']}" if report["ok"] else f" error={report['error']}"
                    print(f"  [{status}] {report['source_name']}{extra}")
                print(f"Fetched {len(raw_items)} raw items")
                self._save_fetch_cache(raw_items, fetch_report)

            print("Step 2/4: Normalize, dedupe, and filter seen items")
            normalized = []
            deduped = []
            candidates = []
            if raw_items:
                normalized = normalize_items(raw_items)
                deduped = dedupe_items(normalized)
                if self.debug_mode:
                    print("DEBUG_MODE enabled: seen-item filtering is disabled")
                    candidates = deduped
                else:
                    candidates = [
                        item
                        for item in deduped
                        if not self.state_store.is_seen(self.state_store.key_for(item))
                    ]
            else:
                print("No ordinary news items fetched; continuing to Follow Builders if enabled")
            print(
                f"Normalized={len(normalized)} Deduped={len(deduped)} Candidates={len(candidates)}\n"
            )

            print("Step 3/4: Score, summarize, and assemble digest")
            top_items: list[dict] = []
            summarized: list[dict] = []
            sections: list[dict] = []
            if candidates:
                scored = self.llm_service.score_items(candidates)
                ranked = sorted(scored, key=lambda item: item.get("score", 0), reverse=True)
                top_items = ranked[: self.top_n]
                use_fallback_digest = self.llm_service.last_score_success_rate < 0.5
                if use_fallback_digest:
                    print("Scoring success rate below 50%; using fallback summaries")
                    summarized = self.llm_service.fallback_summaries(top_items)
                else:
                    summarized = self.llm_service.summarize_items(top_items)

                sections = assemble_sections(summarized, per_section_limit=self.max_per_category)
            else:
                print("No ordinary news candidates; skipping ordinary scoring")

            builder_fetch_report: list[dict] = []
            builder_stats: dict = {}
            builder_sections: list[dict] = []
            builder_items: list[dict] = []
            if self.follow_builders_enabled:
                builder_bundle = self._fetch_follow_builders()
                builder_fetch_report = builder_bundle.get("reports", [])
                builder_bundle = filter_seen_bundle(builder_bundle, self.follow_builders_state, self.debug_mode)
                builder_stats = builder_bundle.get("stats", {})
                builder_digest = self.llm_service.build_follow_builders_digest(builder_bundle)
                builder_sections = builder_digest.get("sections", [])
                builder_items = builder_digest.get("items", [])
                print(
                    "Follow Builders: "
                    f"sections={len(builder_sections)} items={len(builder_items)} "
                    f"tweets={builder_stats.get('unseen_total_tweets', builder_stats.get('total_tweets', 0))} "
                    f"blogs={builder_stats.get('unseen_blog_posts', builder_stats.get('blog_posts', 0))} "
                    f"podcasts={builder_stats.get('unseen_podcast_episodes', builder_stats.get('podcast_episodes', 0))}"
                )
            else:
                print("FOLLOW_BUILDERS_ENABLED=false: skipping Follow Builders")

            if not sections and not builder_sections:
                print("No ordinary or Follow Builders sections assembled; aborting")
                return False

            digest = {
                "sections": sections,
                "builder_sections": builder_sections,
                "builder_stats": builder_stats,
                "highlights": self._build_highlights(summarized),
            }
            stats = self._build_stats(
                fetch_report=fetch_report,
                raw_count=len(raw_items),
                normalized_count=len(normalized),
                deduped_count=len(deduped),
                candidate_count=len(candidates),
                selected_count=len(top_items),
            )
            stats["builder_stats"] = builder_stats
            combined_fetch_report = fetch_report + builder_fetch_report
            report_path = write_markdown_report(
                digest=digest,
                fetch_report=combined_fetch_report,
                stats=stats,
                output_dir=self.markdown_output_dir,
            )
            digest["markdown_report_path"] = str(report_path)
            print(
                f"TopN={len(top_items)} Sections={len(sections)} "
                f"BuilderSections={len(builder_sections)} Markdown={report_path}\n"
            )

            if dry_run:
                print("Step 4/4: Dry run preview")
                self._print_digest_preview(digest, combined_fetch_report)
                print("Dry run completed successfully\n")
                return True

            print("Step 4/4: Send Feishu card")
            success = self.lark_service.send_card(digest, combined_fetch_report)
            if not success:
                print("Feishu send failed")
                return False

            if self.debug_mode:
                print("DEBUG_MODE enabled: skipping seen-state update")
            else:
                self.state_store.mark(self.state_store.key_for(item) for item in top_items)
                self.state_store.save()
                if self.follow_builders_enabled:
                    self.follow_builders_state.mark(collect_dedupe_keys(builder_items))
                    self.follow_builders_state.save()
            print("Task completed successfully\n")
            return True
        except Exception as exc:
            print(f"Task failed: {exc}")
            return False

    def _print_digest_preview(self, digest: dict, fetch_report: list[dict]) -> None:
        print(f"Overview: {digest.get('overview', '')}")
        for section in digest.get("sections", []):
            print(f"\n[{section.get('title', 'Section')}]")
            for item in section.get("items", []):
                print(f"- {item.get('headline', '')}")
                print(f"  {item.get('brief', '')}")
        if digest.get("highlights"):
            print("\n[Highlights]")
            for item in digest["highlights"]:
                print(f"- {item.get('headline', '')}: {item.get('reason', '')}")
        for section in digest.get("builder_sections", []):
            print(f"\n[{section.get('title', 'AI Builders Digest')}]")
            for item in section.get("items", []):
                print(f"- {item.get('headline', item.get('title', ''))}")
                print(f"  {item.get('brief') or item.get('summary', '')}")
        print("\n[Fetch Report]")
        for report in fetch_report:
            if report.get("ok"):
                print(f"- OK {report['source_name']}: {report['count']}")
            else:
                print(f"- FAIL {report['source_name']}: {report['error']}")
        if digest.get("markdown_report_path"):
            print(f"\n[Markdown Report]\n{digest['markdown_report_path']}")

    def _fetch_follow_builders(self) -> dict:
        if self.follow_builders_mode != "remote":
            print(f"FOLLOW_BUILDERS_MODE={self.follow_builders_mode} is not implemented yet; using empty bundle")
            return {"tweet_groups": [], "podcasts": [], "blogs": [], "stats": {}, "reports": [], "errors": []}
        print("Fetching Follow Builders remote feeds")
        return self.follow_builders_fetcher.fetch_remote()

    def _build_highlights(self, items: list[dict]) -> list[dict]:
        highlights = []
        for item in items[:3]:
            highlights.append(
                {
                    "headline": item.get("headline") or item.get("title_zh") or item.get("title", ""),
                    "reason": item.get("reason", ""),
                    "link": item.get("link", ""),
                }
            )
        return highlights

    def _build_stats(
        self,
        fetch_report: list[dict],
        raw_count: int,
        normalized_count: int,
        deduped_count: int,
        candidate_count: int,
        selected_count: int,
    ) -> dict:
        return {
            "total_sources": len(fetch_report),
            "success_sources": sum(1 for report in fetch_report if report.get("ok")),
            "raw_count": raw_count,
            "normalized_count": normalized_count,
            "deduped_count": deduped_count,
            "unseen_count": candidate_count,
            "selected_count": selected_count,
            "hours_lookback": _env_int("HOURS_LOOKBACK", 168),
            "debug_mode": self.debug_mode,
        }

    def _scheduled_job(self) -> None:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now}] Triggered scheduled job")
        self.run()

    def start_schedule(self) -> None:
        print(f"Bot started. Scheduled time: {self.schedule_time}")
        if self.run_on_start:
            self.run()

        schedule.every().day.at(self.schedule_time).do(self._scheduled_job)
        try:
            while True:
                schedule.run_pending()
                time.sleep(60)
        except KeyboardInterrupt:
            sys.exit(0)

    def test(self) -> None:
        success = self.run()
        sys.exit(0 if success else 1)


def main() -> None:
    bot = NewsBot()
    args = sys.argv[1:]

    dry_run = "--dry-run" in args
    from_cache = "--from-cache" in args

    if "--test" in args or "-t" in args:
        bot.test()
    elif dry_run:
        # --dry-run 始终不发送，抓取完保存缓存
        sys.exit(0 if bot.run(dry_run=True, from_cache=from_cache) else 1)
    elif from_cache:
        # --from-cache 单独使用：从缓存跑完整流程（包含发送飞书）
        sys.exit(0 if bot.run(dry_run=False, from_cache=True) else 1)
    elif "--once" in args or "-o" in args:
        bot.run()
    else:
        bot.start_schedule()


if __name__ == "__main__":
    main()
