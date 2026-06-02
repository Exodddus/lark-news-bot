"""
Group summarized items into digest sections.
"""
from __future__ import annotations

from typing import Dict, List

from categories import CATEGORY_ORDER, CATEGORY_TITLES, normalize_category


def assemble_sections(items: List[Dict], per_section_limit: int = 5) -> List[Dict]:
    grouped = {category: [] for category in CATEGORY_ORDER}
    for item in items:
        category = normalize_category(item.get("category"))
        if len(grouped[category]) < per_section_limit:
            grouped[category].append(item)

    sections: List[Dict] = []
    for category in CATEGORY_ORDER:
        section_items = grouped[category]
        if not section_items:
            continue
        sections.append(
            {
                "category": category,
                "title": CATEGORY_TITLES[category],
                "items": section_items,
            }
        )
    return sections
