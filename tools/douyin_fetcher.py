"""Fetch Douyin video info and captions for idol-skill.

Usage:
    # Get video info + caption by URL or ID
    python3 douyin_fetcher.py video <url_or_id>

    # Search videos (via MediaCrawler)
    python3 douyin_fetcher.py search "蔡徐坤"

    # Get user's videos (via MediaCrawler)
    python3 douyin_fetcher.py user <user_url>

Note: Video info uses direct API (no login needed).
Search/user commands use MediaCrawler (requires Playwright + QR login).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

MEDIA_CRAWLER_DIR = Path.home() / "Workspace" / "MediaCrawler"


def _extract_video_id(url_or_id: str) -> str:
    """Extract video ID from various Douyin URL formats."""
    # Already an ID
    if url_or_id.isdigit():
        return url_or_id

    # Short URL (v.douyin.com/xxx) - follow redirect
    if "v.douyin.com" in url_or_id or "douyin.com" in url_or_id:
        try:
            req = urllib.request.Request(url_or_id, headers={
                "User-Agent": "Mozilla/5.0"
            })
            req.get_method = lambda: "HEAD"
            with urllib.request.urlopen(req) as resp:
                final_url = resp.url
                match = re.search(r'/video/(\d+)', final_url)
                if match:
                    return match.group(1)
        except Exception:
            pass

    # Try to extract from URL directly
    match = re.search(r'/video/(\d+)', url_or_id)
    if match:
        return match.group(1)

    return url_or_id


def get_video_info(url_or_id: str) -> dict:
    """Get video info and caption text using Douyin web API."""
    video_id = _extract_video_id(url_or_id)

    # Use Douyin's web API
    api_url = f"https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id={video_id}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer": "https://www.douyin.com/",
    }

    try:
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())

        detail = data.get("aweme_detail", {})
        if not detail:
            return {"error": "Video not found", "video_id": video_id}

        return {
            "video_id": video_id,
            "desc": detail.get("desc", ""),
            "author": detail.get("author", {}).get("nickname", ""),
            "author_id": detail.get("author", {}).get("unique_id", "") or detail.get("author", {}).get("short_id", ""),
            "likes": detail.get("statistics", {}).get("digg_count", 0),
            "comments": detail.get("statistics", {}).get("comment_count", 0),
            "shares": detail.get("statistics", {}).get("share_count", 0),
            "create_time": detail.get("create_time", ""),
            "tags": [t.get("hashtag_name", "") for t in detail.get("text_extra", []) if t.get("hashtag_name")],
        }
    except Exception as e:
        return {"error": str(e), "video_id": video_id}


def search_videos(keyword: str) -> list[dict]:
    """Search Douyin videos via MediaCrawler."""
    if not MEDIA_CRAWLER_DIR.exists():
        print("Error: MediaCrawler not found. Install at ~/Workspace/MediaCrawler", file=sys.stderr)
        sys.exit(1)

    env = os.environ.copy()
    env["KEYWORDS"] = keyword

    result = subprocess.run(
        ["uv", "run", "main.py", "--platform", "dy", "--lt", "qrcode",
         "--type", "search", "--save-data-option", "json"],
        cwd=str(MEDIA_CRAWLER_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )

    # Parse output
    data_dir = MEDIA_CRAWLER_DIR / "data" / "douyin" / "json"
    videos = []
    if data_dir.exists():
        for f in sorted(data_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:3]:
            try:
                items = json.loads(f.read_text())
                if isinstance(items, list):
                    videos.extend(items)
            except json.JSONDecodeError:
                continue

    results = []
    for v in videos[:20]:
        results.append({
            "id": v.get("note_id", v.get("aweme_id", "")),
            "desc": v.get("content", v.get("desc", "")),
            "author": v.get("nickname", ""),
            "likes": v.get("liked_count", 0),
        })
    return results


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    arg = sys.argv[2]

    if cmd == "video":
        result = get_video_info(arg)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif cmd == "search":
        results = search_videos(arg)
        print(json.dumps(results, ensure_ascii=False, indent=2))
    elif cmd == "user":
        # For user videos, use MediaCrawler creator mode
        print("User mode requires MediaCrawler. Use: python3 douyin_fetcher.py search <keyword>")
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
