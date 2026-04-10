"""Fetch Xiaohongshu (RedNote) notes for idol-skill via Playwright browser.

Usage:
    # Login (scan QR code)
    python3 xiaohongshu_fetcher.py login

    # Search notes by keyword
    python3 xiaohongshu_fetcher.py search "蔡徐坤"

    # Get a user's notes
    python3 xiaohongshu_fetcher.py user <user_profile_url>

Uses Playwright with persistent browser profile.
First run opens browser for login, subsequent runs reuse session.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

XHS_PROFILE = Path.home() / ".config" / "idol-skill" / "xhs_browser_profile"


async def _get_context(headless: bool = True):
    """Get browser context with saved profile."""
    from playwright.async_api import async_playwright
    pw = await async_playwright().start()
    ctx = await pw.chromium.launch_persistent_context(
        user_data_dir=str(XHS_PROFILE),
        headless=headless,
        args=["--window-size=500,700"] if not headless else [],
        viewport={"width": 500, "height": 700} if not headless else {"width": 1280, "height": 800},
    )
    return pw, ctx


async def login():
    """Open browser for QR code login."""
    pw, ctx = await _get_context(headless=False)
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    await page.goto("https://www.xiaohongshu.com", timeout=15000)

    print("小红书页面已打开，请扫码或手机验证码登录")

    for _ in range(90):
        await asyncio.sleep(2)
        cookies = await ctx.cookies(["https://www.xiaohongshu.com"])
        if any(c["name"] == "web_session" for c in cookies):
            print(f"✅ 登录成功！")
            await ctx.close()
            await pw.stop()
            return

    print("❌ 登录超时")
    await ctx.close()
    await pw.stop()
    sys.exit(1)


async def check_login() -> bool:
    """Check if we have a valid session."""
    if not XHS_PROFILE.exists():
        return False
    pw, ctx = await _get_context(headless=True)
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    await page.goto("https://www.xiaohongshu.com", timeout=15000)
    cookies = await ctx.cookies(["https://www.xiaohongshu.com"])
    has_session = any(c["name"] == "web_session" for c in cookies)
    await ctx.close()
    await pw.stop()
    return has_session


async def search_notes(keyword: str, max_notes: int = 20) -> list[dict]:
    """Search notes by keyword using browser automation."""
    pw, ctx = await _get_context(headless=True)
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()

    import urllib.parse
    url = f"https://www.xiaohongshu.com/search_result?keyword={urllib.parse.quote(keyword)}&source=web_search_result_notes"
    await page.goto(url, timeout=15000, wait_until="networkidle")
    await asyncio.sleep(3)

    # Extract note cards from search results
    notes = await page.evaluate("""() => {
        const cards = document.querySelectorAll('[class*="note-item"], section.note-item, a[href*="/explore/"]');
        const results = [];
        cards.forEach(card => {
            const titleEl = card.querySelector('[class*="title"], .title, h3');
            const authorEl = card.querySelector('[class*="author"], .author, [class*="name"]');
            const link = card.closest('a') || card.querySelector('a');
            const href = link ? link.getAttribute('href') : '';

            results.push({
                title: titleEl ? titleEl.innerText.trim() : '',
                author: authorEl ? authorEl.innerText.trim() : '',
                url: href || '',
            });
        });
        return results;
    }""")

    await ctx.close()
    await pw.stop()
    return notes[:max_notes]


async def get_note_content(note_url: str) -> dict:
    """Get full content of a specific note."""
    pw, ctx = await _get_context(headless=True)
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()

    if not note_url.startswith("http"):
        note_url = f"https://www.xiaohongshu.com/explore/{note_url}"

    await page.goto(note_url, timeout=15000, wait_until="networkidle")
    await asyncio.sleep(2)

    content = await page.evaluate("""() => {
        const titleEl = document.querySelector('#detail-title, [class*="title"]');
        const descEl = document.querySelector('#detail-desc, [class*="desc"], .note-text');
        const authorEl = document.querySelector('[class*="username"], .username, [class*="author-name"]');
        const tagsEls = document.querySelectorAll('[class*="tag"], .tag a');

        return {
            title: titleEl ? titleEl.innerText.trim() : '',
            content: descEl ? descEl.innerText.trim() : '',
            author: authorEl ? authorEl.innerText.trim() : '',
            tags: Array.from(tagsEls).map(t => t.innerText.trim()).filter(t => t),
        };
    }""")

    await ctx.close()
    await pw.stop()
    return content


async def get_user_notes(user_url: str) -> list[dict]:
    """Get notes from a user's profile page."""
    pw, ctx = await _get_context(headless=True)
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()

    await page.goto(user_url, timeout=15000, wait_until="networkidle")
    await asyncio.sleep(3)

    # Scroll to load more notes
    for _ in range(3):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(2)

    notes = await page.evaluate("""() => {
        const cards = document.querySelectorAll('[class*="note-item"], section.note-item, a[href*="/explore/"]');
        const results = [];
        cards.forEach(card => {
            const titleEl = card.querySelector('[class*="title"], .title, h3, [class*="footer"]');
            const link = card.closest('a') || card.querySelector('a');
            const href = link ? link.getAttribute('href') : '';

            results.push({
                title: titleEl ? titleEl.innerText.trim() : '',
                url: href || '',
            });
        });
        return results;
    }""")

    await ctx.close()
    await pw.stop()
    return notes


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "login":
        asyncio.run(login())
    elif cmd == "check":
        ok = asyncio.run(check_login())
        print("✅ 已登录" if ok else "❌ 未登录，运行 login 先")
    elif cmd == "search":
        if len(sys.argv) < 3:
            print("Usage: python3 xiaohongshu_fetcher.py search <keyword>")
            sys.exit(1)
        results = asyncio.run(search_notes(sys.argv[2]))
        print(json.dumps(results, ensure_ascii=False, indent=2))
    elif cmd == "note":
        if len(sys.argv) < 3:
            print("Usage: python3 xiaohongshu_fetcher.py note <note_url_or_id>")
            sys.exit(1)
        result = asyncio.run(get_note_content(sys.argv[2]))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif cmd == "user":
        if len(sys.argv) < 3:
            print("Usage: python3 xiaohongshu_fetcher.py user <user_profile_url>")
            sys.exit(1)
        results = asyncio.run(get_user_notes(sys.argv[2]))
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
