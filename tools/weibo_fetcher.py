"""Fetch Weibo posts for idol-skill using MediaCrawler.

Usage:
    # Search posts by keyword
    python3 weibo_fetcher.py search "蔡徐坤"

    # Get posts by user ID
    python3 weibo_fetcher.py user 1669879400

Note: Requires MediaCrawler installed at ~/Workspace/MediaCrawler.
First run will prompt for QR code login via Playwright browser.
Cookie is cached after first login.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

MEDIA_CRAWLER_DIR = Path.home() / "Workspace" / "MediaCrawler"


def _run_crawler(platform: str, login_type: str, crawler_type: str,
                 keywords: str = "", user_ids: str = "") -> list[dict]:
    """Run MediaCrawler and parse output from its data directory."""
    if not MEDIA_CRAWLER_DIR.exists():
        print("Error: MediaCrawler not found at", MEDIA_CRAWLER_DIR, file=sys.stderr)
        sys.exit(1)

    cmd = [
        "uv", "run", "main.py",
        "--platform", platform,
        "--lt", login_type,
        "--type", crawler_type,
        "--save-data-option", "json",
    ]

    env = os.environ.copy()

    if crawler_type == "search" and keywords:
        env["KEYWORDS"] = keywords
    elif crawler_type == "creator" and user_ids:
        env["WEIBO_CREATOR_ID_LIST"] = user_ids

    result = subprocess.run(
        cmd,
        cwd=str(MEDIA_CRAWLER_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        print(f"MediaCrawler error: {result.stderr[:500]}", file=sys.stderr)
        return []

    # Parse output JSON files
    data_dir = MEDIA_CRAWLER_DIR / "data" / "weibo" / "json"
    posts = []
    if data_dir.exists():
        for f in sorted(data_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                items = json.loads(f.read_text())
                if isinstance(items, list):
                    posts.extend(items)
                elif isinstance(items, dict):
                    posts.append(items)
            except json.JSONDecodeError:
                continue
            if len(posts) >= 50:
                break

    return posts


def search_posts(keyword: str) -> list[dict]:
    """Search Weibo posts by keyword."""
    posts = _run_crawler("weibo", "qrcode", "search", keywords=keyword)
    results = []
    for p in posts[:20]:
        results.append({
            "id": p.get("note_id", p.get("id", "")),
            "text": p.get("content", p.get("note_content", "")),
            "author": p.get("nickname", p.get("user", {}).get("screen_name", "")),
            "time": p.get("create_time", ""),
            "likes": p.get("liked_count", 0),
            "reposts": p.get("shared_count", 0),
        })
    return results


def get_user_posts(user_id: str) -> list[dict]:
    """Get posts by Weibo user ID."""
    posts = _run_crawler("weibo", "qrcode", "creator", user_ids=user_id)
    results = []
    for p in posts[:30]:
        results.append({
            "id": p.get("note_id", p.get("id", "")),
            "text": p.get("content", p.get("note_content", "")),
            "time": p.get("create_time", ""),
            "likes": p.get("liked_count", 0),
        })
    return results


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    arg = sys.argv[2]

    if cmd == "search":
        results = search_posts(arg)
        print(json.dumps(results, ensure_ascii=False, indent=2))
    elif cmd == "user":
        results = get_user_posts(arg)
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
