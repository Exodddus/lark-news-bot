#!/usr/bin/env python3
"""
Import Follow Builders reference sources into lark-news-bot config.
"""
from __future__ import annotations

import json
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent.parent
ROOT = APP_DIR.parent
REFERENCE_PATH = ROOT / "reference" / "follow-builders" / "config" / "default-sources.json"
OUTPUT_PATH = APP_DIR / "config" / "follow_builders_sources.json"


def main() -> int:
    source_data = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    imported = []

    for item in source_data.get("x_accounts", []):
        imported.append({**item, "content_type": "tweet", "enabled": True, "language": "en"})

    for item in source_data.get("podcasts", []):
        imported.append({**item, "content_type": "podcast", "enabled": True, "language": "en"})

    for item in source_data.get("blogs", []):
        imported.append({**item, "content_type": "builder_blog", "enabled": True, "language": "en"})

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(imported, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(imported)} Follow Builders sources to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
