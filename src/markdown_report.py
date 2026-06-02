"""
Markdown report generation for daily digests.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, List

from digest_utils import builder_meta_text, item_meta_text, top_keywords


def write_markdown_report(
    digest: Dict,
    fetch_report: List[Dict],
    stats: Dict,
    output_dir: str,
) -> Path:
    output_path = _report_path(output_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        build_markdown_report(digest, fetch_report, stats),
        encoding="utf-8",
    )
    return output_path


def build_markdown_report(digest: Dict, fetch_report: List[Dict], stats: Dict) -> str:
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    items = _flatten_items(digest)

    lines: List[str] = [
        f"# 技术情报简报 - {date_str}",
        "",
        f"> {digest.get('overview', '今日暂无可用摘要。')}",
        "",
    ]

    highlights = digest.get("highlights", [])[:3]
    if highlights:
        lines.extend(["## 今日必读 Top 3", ""])
        item_lookup = {item.get("link"): item for item in items if item.get("link")}
        for index, highlight in enumerate(highlights, start=1):
            source_item = item_lookup.get(highlight.get("link"), highlight)
            headline = highlight.get("headline") or source_item.get("headline") or source_item.get("title", "无标题")
            lines.extend(
                [
                    f"### {index}. {headline}",
                    "",
                    _link_line(source_item, headline),
                    "",
                    f"> {source_item.get('brief') or source_item.get('summary', '')}",
                    "",
                ]
            )
            reason = highlight.get("reason") or source_item.get("reason")
            if reason:
                lines.extend([f"**为什么值得读：** {reason}", ""])
            keywords = source_item.get("keywords") or []
            if keywords:
                lines.extend([f"**关键词：** {', '.join(keywords)}", ""])

    lines.extend(
        [
            "## 数据概览",
            "",
            "| 扫描源 | 抓取文章 | 时间过滤后 | 单次去重后 | seen 过滤后 | 精选 |",
            "|:---:|:---:|:---:|:---:|:---:|:---:|",
            (
                f"| {stats.get('success_sources', 0)}/{stats.get('total_sources', 0)} "
                f"| {stats.get('raw_count', 0)} "
                f"| {stats.get('normalized_count', 0)} "
                f"| {stats.get('deduped_count', 0)} "
                f"| {stats.get('unseen_count', 0)} "
                f"| **{stats.get('selected_count', len(items))}** |"
            ),
            "",
            f"- 时间窗口：{stats.get('hours_lookback', '未知')} 小时",
            f"- 调试模式：{'开启' if stats.get('debug_mode') else '关闭'}",
            f"- 生成时间：{now.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]
    )

    builder_stats = stats.get("builder_stats") or digest.get("builder_stats") or {}
    if builder_stats:
        lines.extend(
            [
                "### AI Builders Digest",
                "",
                (
                    f"- X builders：{builder_stats.get('unseen_builders_with_tweets', builder_stats.get('builders_with_tweets', 0))} "
                    f"人 / {builder_stats.get('unseen_total_tweets', builder_stats.get('total_tweets', 0))} 条动态"
                ),
                f"- 官方博客：{builder_stats.get('unseen_blog_posts', builder_stats.get('blog_posts', 0))} 篇",
                f"- Podcasts：{builder_stats.get('unseen_podcast_episodes', builder_stats.get('podcast_episodes', 0))} 期",
                f"- Feed 错误：{builder_stats.get('errors', 0)}",
                "",
            ]
        )

    keywords = top_keywords(items)
    if keywords:
        lines.extend(["## 关键词", "", ", ".join(keywords), ""])

    for section in digest.get("sections", []):
        lines.extend([f"## {section.get('title', '未命名板块')}", ""])
        for index, item in enumerate(section.get("items", []), start=1):
            headline = item.get("headline") or item.get("title_zh") or item.get("title") or "无标题"
            lines.extend(
                [
                    f"### {index}. {headline}",
                    "",
                    _link_line(item, headline),
                    "",
                    f"> {item.get('brief') or item.get('summary', '')}",
                    "",
                ]
            )
            reason = item.get("reason")
            if reason:
                lines.extend([f"**推荐理由：** {reason}", ""])
            keywords = item.get("keywords") or []
            if keywords:
                lines.extend([f"**关键词：** {', '.join(keywords)}", ""])

    if digest.get("builder_sections"):
        lines.extend(["## AI Builders Digest", ""])
        for section in digest.get("builder_sections", []):
            lines.extend([f"### {section.get('title', '未命名板块')}", ""])
            for index, item in enumerate(section.get("items", []), start=1):
                headline = item.get("headline") or item.get("title") or item.get("author") or "无标题"
                lines.extend(
                    [
                        f"#### {index}. {headline}",
                        "",
                        _builder_link_line(item, headline),
                        "",
                        f"> {item.get('summary') or item.get('brief', '')}",
                        "",
                    ]
                )

    failed = [report for report in fetch_report if not report.get("ok")]
    if failed:
        lines.extend(["## 失败源", ""])
        for report in failed[:20]:
            lines.append(f"- {report.get('source_name', report.get('source_id', '未知源'))}: {report.get('error', 'unknown error')}")
        lines.append("")

    lines.append(
        f"*扫描 {stats.get('success_sources', 0)} 源 -> 获取 {stats.get('raw_count', 0)} 篇 -> 精选 {stats.get('selected_count', len(items))} 篇*"
    )
    lines.append("")
    return "\n".join(lines)


def _report_path(output_dir: str) -> Path:
    date_str = datetime.now().strftime("%Y%m%d")
    return Path(output_dir) / f"digest-{date_str}.md"


def _flatten_items(digest: Dict) -> List[Dict]:
    items: List[Dict] = []
    for section in digest.get("sections", []):
        items.extend(section.get("items", []))
    return items


def _link_line(item: Dict, headline: str) -> str:
    link = item.get("link")
    meta = item_meta_text(item)
    if link:
        return f"[{headline}]({link}) - {meta}"
    return f"{headline} - {meta}"


def _builder_link_line(item: Dict, headline: str) -> str:
    link = item.get("link")
    meta = builder_meta_text(item)
    if link:
        return f"[{headline}]({link}) - {meta}"
    return f"{headline} - {meta}"
