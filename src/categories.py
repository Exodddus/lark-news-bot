"""
Shared digest categories.
"""
from __future__ import annotations

from typing import Dict, Tuple


CATEGORY_ORDER: Tuple[str, ...] = (
    "ai-ml",
    "security",
    "engineering",
    "opinion",
    "industry",
    "other",
)

CATEGORY_TITLES: Dict[str, str] = {
    "ai-ml": "🤖 AI技术",
    "security": "🔒 安全",
    "engineering": "⚙️ 工程开发",
    "opinion": "💡 观点杂谈",
    "industry": "📈 行业前沿",
    "other": "📝 其他",
}

DEFAULT_CATEGORY = "other"


def normalize_category(value: str | None) -> str:
    if value in CATEGORY_TITLES:
        return value
    if value == "research":
        return "ai-ml"
    if value == "tools":
        return "engineering"
    return DEFAULT_CATEGORY
