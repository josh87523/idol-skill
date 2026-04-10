"""Fetch Bilibili video subtitles and info for idol-skill.

Usage:
    # Search videos by keyword
    python3 bilibili_fetcher.py search "蔡徐坤 采访"

    # Get subtitle for a specific video
    python3 bilibili_fetcher.py subtitle BV1xx411c7mD

    # Get video info
    python3 bilibili_fetcher.py info BV1xx411c7mD
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from bilibili_api import video, search, sync

# Auto-load saved credential
_credential = None
_CRED_PATH = Path.home() / ".config" / "idol-skill" / "bilibili_credential.json"
if _CRED_PATH.exists():
    from bilibili_api import Credential
    _cred_data = json.loads(_CRED_PATH.read_text())
    _credential = Credential(
        sessdata=_cred_data.get("sessdata"),
        bili_jct=_cred_data.get("bili_jct"),
        buvid3=_cred_data.get("buvid3"),
        dedeuserid=_cred_data.get("dedeuserid"),
        ac_time_value=_cred_data.get("ac_time_value"),
    )


def search_videos(keyword: str, page: int = 1, page_size: int = 10) -> list[dict]:
    """Search Bilibili videos by keyword, return list of {bvid, title, author, duration, play}."""
    result = sync(search.search_by_type(
        keyword=keyword,
        search_type=search.SearchObjectType.VIDEO,
        page=page,
    ))
    videos = []
    for item in result.get("result", []):
        videos.append({
            "bvid": item.get("bvid", ""),
            "title": item.get("title", "").replace("<em class=\"keyword\">", "").replace("</em>", ""),
            "author": item.get("author", ""),
            "duration": item.get("duration", ""),
            "play": item.get("play", 0),
            "description": item.get("description", ""),
        })
    return videos[:page_size]


def get_video_info(bvid: str) -> dict:
    """Get video metadata."""
    v = video.Video(bvid=bvid)
    return sync(v.get_info())


def get_subtitle(bvid: str) -> str | None:
    """Get subtitle text for a video. Returns None if no subtitle available."""
    v = video.Video(bvid=bvid, credential=_credential)
    info = sync(v.get_info())

    # Get cid (first page)
    pages = info.get("pages", [])
    if not pages:
        return None
    cid = pages[0]["cid"]

    # Get player info which contains subtitle URLs
    player_info = sync(v.get_player_info(cid=cid))  # needs credential for subtitles
    subtitle_list = player_info.get("subtitle", {}).get("subtitles", [])

    if not subtitle_list:
        return None

    # Prefer zh-CN subtitle
    subtitle_url = None
    for sub in subtitle_list:
        if "zh" in sub.get("lan", ""):
            subtitle_url = sub.get("subtitle_url", "")
            break
    if not subtitle_url and subtitle_list:
        subtitle_url = subtitle_list[0].get("subtitle_url", "")

    if not subtitle_url:
        return None

    # Fetch subtitle content
    import urllib.request
    if subtitle_url.startswith("//"):
        subtitle_url = "https:" + subtitle_url

    req = urllib.request.Request(subtitle_url, headers={
        "User-Agent": "Mozilla/5.0",
        "Referer": f"https://www.bilibili.com/video/{bvid}"
    })
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())

    # Extract text from subtitle JSON
    lines = []
    for item in data.get("body", []):
        content = item.get("content", "").strip()
        if content:
            lines.append(content)

    return "\n".join(lines)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    arg = sys.argv[2]

    if cmd == "search":
        results = search_videos(arg)
        print(json.dumps(results, ensure_ascii=False, indent=2))

    elif cmd == "subtitle":
        text = get_subtitle(arg)
        if text:
            print(text)
        else:
            print("No subtitle found", file=sys.stderr)
            sys.exit(1)

    elif cmd == "info":
        info = get_video_info(arg)
        # Print condensed info
        print(json.dumps({
            "title": info.get("title"),
            "desc": info.get("desc"),
            "owner": info.get("owner", {}).get("name"),
            "duration": info.get("duration"),
            "view": info.get("stat", {}).get("view"),
            "pages": len(info.get("pages", [])),
        }, ensure_ascii=False, indent=2))

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
