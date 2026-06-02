"""
LLM API service for item scoring, summarization, and digest overview generation.
"""
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import requests

from categories import DEFAULT_CATEGORY, normalize_category


DEFAULT_SCORING_PROMPT = """你是一个技术内容策展人，为面向技术爱好者的每日精选摘要筛选文章。

对以下文章进行三个维度的评分（1-10 整数），并分配分类标签和提取 2-4 个英文关键词。

## 评分维度
### 相关性 (relevance)
- 10: 所有技术人都应该知道的重大事件/突破
- 7-9: 对大部分技术从业者有价值
- 4-6: 对特定技术领域有价值
- 1-3: 与技术行业关联不大

### 质量 (quality)
- 10: 深度分析，原创洞见，引用丰富
- 7-9: 有深度，观点独到
- 4-6: 信息准确，表达清晰
- 1-3: 浅尝辄止或纯转述

### 时效性 (timeliness)
- 10: 正在发生的重大事件 / 刚发布的重要工具
- 7-9: 近期热点相关
- 4-6: 常青内容，不过时
- 1-3: 过时或无时效价值

## 分类标签（必须选一个）
- ai-ml：AI/ML 技术本身的进展——论文、模型发布、框架/算法更新、推理优化、AI 基础设施；不包括 AI 公司融资和纯商业新闻
- security：安全漏洞、CVE、攻防技术、渗透测试、密码学、隐私保护
- engineering：可直接用于项目开发的新框架/库/技术方案、优质开源项目发布、工程最佳实践、架构设计；也包括开发工具、CLI 工具、IDE 插件、调试/部署/效率工具
- opinion：技术博客、深度分析、工程师观点、行业评论
- industry：AI/科技公司融资并购、商业动态、政策监管、产业趋势
- other：不属于以上任何类别

## 待评分文章
{articles_block}

严格按 JSON 返回，不要 markdown 代码块：
{{"results": [{{"index": 0, "relevance": 8, "quality": 7, "timeliness": 9, "category": "ai-ml", "keywords": ["LLM", "agent"]}}]}}"""

DEFAULT_SUMMARY_PROMPT = """你是一个技术内容摘要专家。为以下文章完成三件事：

1. title_zh：将英文标题翻译成自然中文，中文原标题保持不变。
2. summary：4-6 句结构化摘要，包含：核心主题（1 句）、关键论点/技术方案（2-3 句）、结论（1 句）。
   要求：直接说重点，不要"本文讨论了…"开头；包含具体技术名词、数据、方案名称；保留关键数字。
3. reason：1 句话说"为什么值得读"（说"为什么"，不是重复摘要）。

## 待摘要文章
{articles_block}

严格按 JSON 返回，不要 markdown 代码块：
{{"results": [{{"index": 0, "title_zh": "中文标题", "summary": "摘要…", "reason": "推荐理由…"}}]}}"""

DEFAULT_OVERVIEW_PROMPT = """你是一个技术情报编辑。请根据以下已筛选文章，为今天的简报写一句 30-50 字中文总览。

要求：直接点出今日重点，不要套话，不要 Markdown。

## 文章列表
{articles_block}

严格按 JSON 返回，不要 markdown 代码块：
{{"overview": "今日总览..."}}"""

DEFAULT_BUILDER_TWEETS_PROMPT = """你正在为中文读者总结一位 AI builder 的近期 X/Twitter 原帖。

要求：
- 使用中文输出。
- 用作者全名开头，不要使用 @handle。
- 只提炼实质内容：观点、产品动态、技术讨论、行业判断、经验教训。
- 2-4 句话，手机上可读。
- 如果没有实质内容，写“暂无值得特别关注的动态。”
- 必须保留至少一个原帖链接。

输入：
{items_block}

严格按 JSON 返回，不要 markdown 代码块：
{{"summary": "中文摘要..."}}"""

DEFAULT_BUILDER_BLOG_PROMPT = """你正在为中文技术读者总结 AI builder/company 官方博客全文。

要求：
- 使用中文输出。
- 100-300 字。
- 开头写清博客名和文章标题。
- 直接说核心公告、技术细节、影响和实践意义。
- 保留关键数字、产品名和原文链接。
- 不要写“本文讨论了”这类套话。

输入：
{items_block}

严格按 JSON 返回，不要 markdown 代码块：
{{"summary": "中文摘要..."}}"""

DEFAULT_BUILDER_PODCAST_PROMPT = """你正在为中文读者 remix 一期 AI podcast。

要求：
- 使用中文输出。
- 200-400 字。
- 用一句“The Takeaway:”开头，说明最重要的收获。
- 介绍节目/嘉宾上下文，但不要流水账复述访谈。
- 优先提炼反直觉、具体、可迁移的洞见。
- 保留具体 episode 链接。

输入：
{items_block}

严格按 JSON 返回，不要 markdown 代码块：
{{"summary": "中文 remix..."}}"""


class LLMService:
    def __init__(self, api_key: str, api_url: str, model: str, prompts_dir: str | None = None) -> None:
        self.api_key = api_key
        self.api_url = api_url
        self.model = model
        self.prompts_dir = Path(prompts_dir) if prompts_dir else Path(__file__).resolve().parent.parent / "prompts"
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        self.last_score_success_rate = 1.0

    def score_items(self, items: List[Dict]) -> List[Dict]:
        if not items:
            self.last_score_success_rate = 1.0
            return []

        batch_size = max(1, _env_int("SCORING_BATCH_SIZE", 10))
        concurrency = max(1, _env_int("SCORING_CONCURRENCY", 2))
        indexed_items = list(enumerate(items))
        batches = list(_chunks(indexed_items, batch_size))
        scored: List[Dict] = []
        successful_batches = 0

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(self._score_batch, batch) for batch in batches]
            for future in as_completed(futures):
                ok, batch_items = future.result()
                if ok:
                    successful_batches += 1
                scored.extend(batch_items)

        self.last_score_success_rate = successful_batches / len(batches)
        return sorted(scored, key=lambda item: item.get("_input_index", 0))

    def summarize_items(self, items: List[Dict]) -> List[Dict]:
        if not items:
            return []

        batch_size = max(1, _env_int("SCORING_BATCH_SIZE", 10))
        concurrency = max(1, _env_int("SCORING_CONCURRENCY", 2))
        indexed_items = list(enumerate(items))
        batches = list(_chunks(indexed_items, batch_size))
        summarized: List[Dict] = []

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(self._summarize_batch, batch) for batch in batches]
            for future in as_completed(futures):
                summarized.extend(future.result())

        return sorted(summarized, key=lambda item: item.get("_input_index", 0))

    def fallback_summaries(self, items: List[Dict]) -> List[Dict]:
        return [self._fallback_summary(index, item) for index, item in enumerate(items)]

    def build_follow_builders_digest(self, bundle: Dict[str, Any]) -> Dict[str, Any]:
        tweet_items = self.summarize_builder_tweets(bundle.get("tweet_groups", []))
        blog_items = self.summarize_builder_blogs(bundle.get("blogs", []))
        podcast_items = self.summarize_builder_podcasts(bundle.get("podcasts", []))

        sections = []
        if tweet_items:
            sections.append({"title": "X / Twitter 建造者动态", "content_type": "tweet", "items": tweet_items})
        if blog_items:
            sections.append({"title": "官方博客", "content_type": "builder_blog", "items": blog_items})
        if podcast_items:
            sections.append({"title": "Podcasts", "content_type": "podcast", "items": podcast_items})
        return {"sections": sections, "items": tweet_items + blog_items + podcast_items}

    def summarize_builder_tweets(self, groups: List[Dict]) -> List[Dict]:
        return [self._summarize_builder_item(group, "summarize-tweets.md", DEFAULT_BUILDER_TWEETS_PROMPT, "builder_tweets") for group in groups]

    def summarize_builder_blogs(self, items: List[Dict]) -> List[Dict]:
        return [self._summarize_builder_item(item, "summarize-blogs.md", DEFAULT_BUILDER_BLOG_PROMPT, "builder_blog") for item in items]

    def summarize_builder_podcasts(self, items: List[Dict]) -> List[Dict]:
        return [self._summarize_builder_item(item, "summarize-podcast.md", DEFAULT_BUILDER_PODCAST_PROMPT, "builder_podcast") for item in items]

    def generate_overview(self, items: List[Dict]) -> str:
        if not items:
            return "今日暂无可用技术情报。"

        prompt = self._render_prompt("overview.md", DEFAULT_OVERVIEW_PROMPT, self._build_overview_block(items[:10]))
        try:
            data = self._call_json_with_retries(prompt, max_tokens=300, temperature=0.3, task="overview")
            overview = str(data.get("overview", "")).strip()
            if overview:
                return overview
        except Exception as exc:
            print(f"Overview generation failed: {exc}")
        return self.fallback_overview(items)

    def fallback_overview(self, items: List[Dict]) -> str:
        count = len(items)
        top_keywords = self._top_keywords(items)
        if top_keywords:
            return f"今日筛选 {count} 条技术情报，重点关注 {top_keywords} 等方向。"
        return f"今日筛选 {count} 条技术情报，覆盖 AI、工程、安全、工具和行业动态。"

    def _score_batch(self, batch: List[Tuple[int, Dict]]) -> Tuple[bool, List[Dict]]:
        prompt = self._render_prompt("scoring.md", DEFAULT_SCORING_PROMPT, self._build_scoring_block(batch))
        try:
            data = self._call_json_with_retries(prompt, max_tokens=8192, temperature=0.2, task="scoring")
            results = self._results_by_index(data)
            return True, [self._apply_score(index, item, results.get(index)) for index, item in batch]
        except Exception as exc:
            print(f"Scoring batch failed: {exc}")
            return False, [self._default_score(index, item) for index, item in batch]

    def _summarize_batch(self, batch: List[Tuple[int, Dict]]) -> List[Dict]:
        prompt = self._render_prompt("summary.md", DEFAULT_SUMMARY_PROMPT, self._build_summary_block(batch))
        try:
            data = self._call_json_with_retries(prompt, max_tokens=8192, temperature=0.3, task="summary")
            results = self._results_by_index(data)
            return [self._apply_summary(index, item, results.get(index)) for index, item in batch]
        except Exception as exc:
            print(f"Summary batch failed: {exc}")
            return [self._fallback_summary(index, item) for index, item in batch]

    def _summarize_builder_item(self, item: Dict, prompt_name: str, fallback_template: str, task: str) -> Dict:
        prompt = self._render_builder_prompt(prompt_name, fallback_template, self._build_builder_block(item))
        try:
            data = self._call_json_with_retries(prompt, max_tokens=2048, temperature=0.3, task=task)
            summary = str(data.get("summary", "")).strip()
            if summary:
                enriched = dict(item)
                enriched.update(
                    {
                        "headline": self._builder_headline(item),
                        "summary": summary,
                        "brief": _truncate(summary, _env_int("FOLLOW_BUILDERS_CARD_SUMMARY_CHARS", 500)),
                        "summary_fallback": False,
                    }
                )
                return enriched
        except Exception as exc:
            print(f"Follow Builders {task} summary failed: {exc}")
        return self._fallback_builder_summary(item)

    def _call_json_with_retries(self, prompt: str, max_tokens: int, temperature: float, task: str) -> Dict:
        last_error: Exception | None = None
        for attempt, delay in enumerate((0, 1, 3, 9), start=1):
            if delay:
                time.sleep(delay)
            try:
                return self._call_json(prompt, max_tokens=max_tokens, temperature=temperature, task=task)
            except Exception as exc:
                last_error = exc
                print(f"LLM {task} attempt {attempt} failed: {exc}")
        if last_error:
            raise last_error
        raise RuntimeError(f"LLM {task} failed")

    def _call_json(self, prompt: str, max_tokens: int, temperature: float, task: str) -> Dict:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        response = requests.post(
            self.api_url,
            json=payload,
            headers=self.headers,
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        self._log_usage(task, data.get("usage", {}))
        content = data["choices"][0]["message"]["content"]
        return self._parse_json_content(content)

    def _render_prompt(self, filename: str, fallback_template: str, articles_block: str) -> str:
        template_path = self.prompts_dir / filename
        if template_path.exists():
            template = template_path.read_text(encoding="utf-8")
        else:
            template = fallback_template
        return template.format(articles_block=articles_block)

    def _render_builder_prompt(self, filename: str, fallback_template: str, items_block: str) -> str:
        template_path = self.prompts_dir / "follow-builders" / filename
        if template_path.exists():
            template = template_path.read_text(encoding="utf-8")
            return (
                f"{template}\n\n"
                "Additional output rule: use Chinese unless the source title is a proper noun. "
                "Return strict JSON only: {\"summary\": \"...\"}.\n\n"
                f"## Input\n{items_block}"
            )
        return fallback_template.format(items_block=items_block)

    def _parse_json_content(self, content: str) -> Dict:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines and lines[0].strip().startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()

        # 1. 完整解析
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # 2. 找最外层 {...} 再试
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                pass

        # 3. 截断恢复：从 "results": [ 开始逐个解码完整对象
        # 用于 max_tokens 不足导致输出被截断的场景
        results_pos = cleaned.find('"results"')
        if results_pos >= 0:
            array_start = cleaned.find("[", results_pos)
            if array_start >= 0:
                recovered: list = []
                decoder = json.JSONDecoder()
                pos = array_start + 1
                while pos < len(cleaned):
                    while pos < len(cleaned) and cleaned[pos] in " \t\n\r,":
                        pos += 1
                    if pos >= len(cleaned) or cleaned[pos] == "]":
                        break
                    try:
                        obj, end_pos = decoder.raw_decode(cleaned, pos)
                        recovered.append(obj)
                        pos = end_pos
                    except json.JSONDecodeError:
                        break
                if recovered:
                    return {"results": recovered}

        raise json.JSONDecodeError("Cannot parse or recover JSON", cleaned, 0)

    def _results_by_index(self, data: Dict) -> Dict[int, Dict]:
        results: Dict[int, Dict] = {}
        for result in data.get("results", []):
            try:
                results[int(result.get("index"))] = result
            except (TypeError, ValueError):
                continue
        return results

    def _apply_score(self, index: int, item: Dict, result: Dict | None) -> Dict:
        if result is None:
            return self._default_score(index, item)
        relevance = _clamp_score(result.get("relevance"))
        quality = _clamp_score(result.get("quality"))
        timeliness = _clamp_score(result.get("timeliness"))
        enriched = dict(item)
        enriched.update(
            {
                "_input_index": index,
                "relevance": relevance,
                "quality": quality,
                "timeliness": timeliness,
                "score": relevance + quality + timeliness,
                "category": normalize_category(str(result.get("category", DEFAULT_CATEGORY))),
                "keywords": _normalize_keywords(result.get("keywords")),
                "scoring_fallback": False,
            }
        )
        return enriched

    def _default_score(self, index: int, item: Dict) -> Dict:
        enriched = dict(item)
        enriched.update(
            {
                "_input_index": index,
                "relevance": 5,
                "quality": 5,
                "timeliness": 5,
                "score": 15,
                "category": DEFAULT_CATEGORY,
                "keywords": [],
                "scoring_fallback": True,
            }
        )
        return enriched

    def _apply_summary(self, index: int, item: Dict, result: Dict | None) -> Dict:
        if result is None:
            return self._fallback_summary(index, item)
        title_zh = str(result.get("title_zh") or item.get("title") or "").strip()
        summary = str(result.get("summary") or item.get("summary") or item.get("title") or "").strip()
        reason = str(result.get("reason") or self._fallback_reason(item)).strip()
        enriched = dict(item)
        enriched.update(
            {
                "_input_index": index,
                "raw_summary": item.get("summary", ""),
                "title_zh": title_zh,
                "summary": summary,
                "reason": reason,
                "headline": title_zh or item.get("title", ""),
                "brief": summary,
                "summary_fallback": False,
            }
        )
        return enriched

    def _fallback_summary(self, index: int, item: Dict) -> Dict:
        summary = str(item.get("summary") or item.get("title") or "").strip()
        brief = _truncate(summary, 180)
        enriched = dict(item)
        enriched.update(
            {
                "_input_index": index,
                "raw_summary": summary,
                "title_zh": item.get("title", ""),
                "summary": brief,
                "reason": self._fallback_reason(item),
                "headline": item.get("title", ""),
                "brief": brief,
                "summary_fallback": True,
            }
        )
        return enriched

    def _fallback_reason(self, item: Dict) -> str:
        score = item.get("score")
        if score:
            return f"综合评分 {score}/30，来自 {item.get('source_name', '未知来源')}，适合进一步细读。"
        return f"来自 {item.get('source_name', '未知来源')}，适合进一步细读。"

    def _build_scoring_block(self, batch: List[Tuple[int, Dict]]) -> str:
        blocks = []
        for index, item in batch:
            blocks.append(
                "\n".join(
                    [
                        f"Index: {index}",
                        f"Title: {item.get('title', '')}",
                        f"Source: {item.get('source_name', '')}",
                        f"Initial category: {item.get('category', '')}",
                        f"Published at: {item.get('published_at', '')}",
                        f"Description: {_truncate(item.get('summary', ''), 300)}",
                    ]
                )
            )
        return "\n\n---\n\n".join(blocks)

    def _build_summary_block(self, batch: List[Tuple[int, Dict]]) -> str:
        blocks = []
        for index, item in batch:
            blocks.append(
                "\n".join(
                    [
                        f"Index: {index}",
                        f"Title: {item.get('title', '')}",
                        f"Source: {item.get('source_name', '')}",
                        f"Score: {item.get('score', '')}/30",
                        f"Keywords: {', '.join(item.get('keywords', []))}",
                        f"Description: {_truncate(item.get('summary', ''), 800)}",
                        f"Link: {item.get('link', '')}",
                    ]
                )
            )
        return "\n\n---\n\n".join(blocks)

    def _build_overview_block(self, items: List[Dict]) -> str:
        lines = []
        for index, item in enumerate(items, start=1):
            title = item.get("title_zh") or item.get("title", "")
            keywords = ", ".join(item.get("keywords", []))
            lines.append(f"{index}. {title} | category={item.get('category', '')} | keywords={keywords}")
        return "\n".join(lines)

    def _build_builder_block(self, item: Dict) -> str:
        content_type = item.get("content_type")
        if content_type == "tweet":
            lines = [
                f"Name: {item.get('author', '')}",
                f"Handle: {item.get('handle', '')}",
                f"Bio: {item.get('bio', '')}",
                "Tweets:",
            ]
            for index, tweet in enumerate(item.get("tweets", []), start=1):
                metrics = tweet.get("metrics", {})
                lines.extend(
                    [
                        f"{index}. {tweet.get('text', '')}",
                        f"   URL: {tweet.get('url', '')}",
                        (
                            "   Metrics: "
                            f"likes={metrics.get('likes', 0)}, "
                            f"retweets={metrics.get('retweets', 0)}, "
                            f"replies={metrics.get('replies', 0)}"
                        ),
                    ]
                )
            return "\n".join(lines)

        char_limit = _env_int(
            "FOLLOW_BUILDERS_PODCAST_TRANSCRIPT_CHARS" if content_type == "podcast" else "FOLLOW_BUILDERS_BLOG_CONTENT_CHARS",
            12000 if content_type == "podcast" else 10000,
        )
        return "\n".join(
            [
                f"Type: {content_type}",
                f"Source: {item.get('source_name', '')}",
                f"Title: {item.get('title', '')}",
                f"Author: {item.get('author', '')}",
                f"Published at: {item.get('published_at', '')}",
                f"URL: {item.get('link', '')}",
                f"Content excerpt: {_truncate(item.get('body', ''), char_limit)}",
            ]
        )

    def _builder_headline(self, item: Dict) -> str:
        if item.get("content_type") == "tweet":
            return str(item.get("author") or item.get("title") or "Builder 动态")
        source = item.get("source_name", "")
        title = item.get("title", "")
        return f"{source}: {title}" if source and title else str(title or source or "Follow Builders")

    def _fallback_builder_summary(self, item: Dict) -> Dict:
        content_type = item.get("content_type")
        if content_type == "tweet":
            tweet_lines = []
            for tweet in item.get("tweets", [])[:3]:
                text = _truncate(tweet.get("text", ""), 180)
                url = tweet.get("url", "")
                tweet_lines.append(f"{text} {url}".strip())
            summary = f"{item.get('author', 'Builder')} 近期动态：" + "；".join(tweet_lines)
        elif content_type == "podcast":
            summary = (
                f"The Takeaway: {item.get('source_name', 'Podcast')} 的 {item.get('title', '')} "
                f"值得关注。{_truncate(item.get('body') or item.get('summary') or '', 360)} {item.get('link', '')}"
            ).strip()
        else:
            summary = (
                f"{item.get('source_name', '官方博客')}: {item.get('title', '')}。"
                f"{_truncate(item.get('body') or item.get('summary') or '', 360)} {item.get('link', '')}"
            ).strip()
        enriched = dict(item)
        enriched.update(
            {
                "headline": self._builder_headline(item),
                "summary": summary,
                "brief": _truncate(summary, _env_int("FOLLOW_BUILDERS_CARD_SUMMARY_CHARS", 500)),
                "summary_fallback": True,
            }
        )
        return enriched

    def _top_keywords(self, items: List[Dict]) -> str:
        counts: Dict[str, int] = {}
        for item in items:
            for keyword in item.get("keywords", []):
                counts[keyword] = counts.get(keyword, 0) + 1
        return "、".join(keyword for keyword, _ in sorted(counts.items(), key=lambda pair: pair[1], reverse=True)[:3])

    def _log_usage(self, task: str, usage: Dict[str, Any]) -> None:
        total_tokens = usage.get("total_tokens")
        if total_tokens is None:
            return
        log_path = Path(os.getenv("BOT_LOG_PATH", "bot.log"))
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with log_path.open("a", encoding="utf-8") as file:
            file.write(f"[{timestamp}] llm_{task}_tokens={total_tokens}\n")


def _chunks(items: List[Tuple[int, Dict]], size: int) -> Iterable[List[Tuple[int, Dict]]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def _clamp_score(value: Any) -> int:
    try:
        score = int(float(value))
    except (TypeError, ValueError):
        score = 5
    return min(10, max(1, score))


def _normalize_keywords(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    keywords = []
    for item in value:
        keyword = str(item).strip()
        if keyword:
            keywords.append(keyword)
        if len(keywords) >= 4:
            break
    return keywords


def _truncate(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
