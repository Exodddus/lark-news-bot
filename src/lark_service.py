"""
Feishu message delivery service.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, List, Optional

import lark_oapi as lark
import requests
from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

from categories import CATEGORY_TITLES
from digest_utils import builder_meta_text, item_meta_text, truncate_text


class LarkService:
    def __init__(
        self,
        webhook_url: Optional[str] = None,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        receive_id: Optional[str] = None,
        receive_id_type: str = "open_id",
    ) -> None:
        self.webhook_url = webhook_url
        self.app_id = app_id
        self.app_secret = app_secret
        self.receive_id = receive_id
        self.receive_id_type = receive_id_type

        if app_id and app_secret:
            self.mode = "app"
            self.client = lark.Client.builder().app_id(app_id).app_secret(app_secret).build()
            print(f"Using self-built app mode with receive_id_type={receive_id_type}")
        elif webhook_url:
            self.mode = "webhook"
            self.client = None
            print("Using webhook mode")
        else:
            raise ValueError("Provide either webhook_url or app_id + app_secret")

    def _require_webhook_url(self) -> str:
        if self.webhook_url is None:
            raise ValueError("Webhook mode requires webhook_url")
        return self.webhook_url

    def _require_receive_id(self) -> str:
        if self.receive_id is None:
            raise ValueError("App mode requires receive_id")
        return self.receive_id

    def send_card(self, digest: Dict, fetch_report: List[Dict]) -> bool:
        try:
            card = self._build_card(digest, fetch_report)
            if self.mode == "webhook":
                return self._send_card_via_webhook(card)
            return self._send_card_via_app(card)
        except Exception as exc:
            print(f"Failed to send Feishu card: {exc}")
            return False

    def send_text(self, text: str) -> bool:
        try:
            if self.mode == "webhook":
                return self._send_text_via_webhook(text)
            return self._send_text_via_app(text)
        except Exception as exc:
            print(f"Failed to send text message: {exc}")
            return False

    def _send_card_via_webhook(self, card: Dict) -> bool:
        response = requests.post(
            self._require_webhook_url(),
            json={"msg_type": "interactive", "card": card},
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        response.raise_for_status()
        result = response.json()
        return result.get("code") == 0

    def _send_card_via_app(self, card: Dict) -> bool:
        request = (
            CreateMessageRequest.builder()
            .receive_id_type(self.receive_id_type)
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(self._require_receive_id())
                .msg_type("interactive")
                .content(json.dumps(card))
                .build()
            )
            .build()
        )
        response = self.client.im.v1.message.create(request)
        if not response.success():
            print(
                f"Failed to send Feishu card: code={response.code}, msg={response.msg}, log_id={response.get_log_id()}"
            )
            return False
        return True

    def _send_text_via_webhook(self, text: str) -> bool:
        response = requests.post(
            self._require_webhook_url(),
            json={"msg_type": "text", "content": {"text": text}},
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        response.raise_for_status()
        result = response.json()
        return result.get("code") == 0

    def _send_text_via_app(self, text: str) -> bool:
        request = (
            CreateMessageRequest.builder()
            .receive_id_type(self.receive_id_type)
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(self._require_receive_id())
                .msg_type("text")
                .content(json.dumps({"text": text}))
                .build()
            )
            .build()
        )
        response = self.client.im.v1.message.create(request)
        if not response.success():
            print(
                f"Failed to send text message: code={response.code}, msg={response.msg}, log_id={response.get_log_id()}"
            )
            return False
        return True

    def _build_card(self, digest: Dict, fetch_report: List[Dict]) -> Dict:
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")

        elements: List[Dict] = []

        for section in digest.get("sections", []):
            section_title = section.get("title") or CATEGORY_TITLES.get(section.get("category"), "未命名板块")
            elements.append(
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": f"**{section_title}**"},
                }
            )
            for item in section.get("items", []):
                headline = item.get("headline") or item.get("title_zh") or item.get("title") or "无标题"
                brief = item.get("brief") or item.get("summary", "")
                meta = item_meta_text(item)
                link = item.get("link", "")
                if link:
                    title_line = f"• **[{headline}]({link})**"
                else:
                    title_line = f"• **{headline}**"
                elements.append(
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": f"{title_line}\n_{meta}_\n{brief}",
                        },
                    }
                )
            elements.append({"tag": "hr"})

        for section in digest.get("builder_sections", []):
            elements.append(
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": f"**{section.get('title', 'AI Builders Digest')}**"},
                }
            )
            for item in section.get("items", []):
                headline = item.get("headline") or item.get("title") or item.get("author") or "无标题"
                brief = truncate_text(item.get("brief") or item.get("summary", ""), 500)
                meta = builder_meta_text(item)
                link = item.get("link", "")
                title_line = f"• **[{headline}]({link})**" if link else f"• **{headline}**"
                elements.append(
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": f"{title_line}\n_{meta}_\n{brief}",
                        },
                    }
                )
            elements.append({"tag": "hr"})

        highlights = digest.get("highlights", [])[:3]
        if highlights:
            elements.append(
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": "**值得细读**"},
                }
            )
            for item in highlights:
                link = item.get("link", "")
                headline = item.get("headline", "无标题")
                title_line = f"• **[{headline}]({link})**" if link else f"• **{headline}**"
                elements.append(
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": f"{title_line}\n{item.get('reason', '')}",
                        },
                    }
                )
            elements.append({"tag": "hr"})

        success_count = sum(1 for item in fetch_report if item.get("ok"))
        total_count = len(fetch_report)
        report_path = digest.get("markdown_report_path")
        note = f"Sources OK: {success_count}/{total_count} | Generated at {now.strftime('%H:%M:%S')}"
        builder_stats = digest.get("builder_stats") or {}
        if builder_stats:
            note += (
                " | Builders: "
                f"tweets={builder_stats.get('unseen_total_tweets', builder_stats.get('total_tweets', 0))}, "
                f"blogs={builder_stats.get('unseen_blog_posts', builder_stats.get('blog_posts', 0))}, "
                f"podcasts={builder_stats.get('unseen_podcast_episodes', builder_stats.get('podcast_episodes', 0))}"
            )
        if report_path:
            note += f" | Markdown: {report_path}"
        elements.append(
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": note,
                    }
                ],
            }
        )

        return {
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"📰 技术情报简报 - {date_str}",
                },
                "template": "blue",
            },
            "elements": elements,
        }
