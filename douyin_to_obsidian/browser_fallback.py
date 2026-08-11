#!/usr/bin/env python3
"""
Douyin browser-fallback extractor (cross-agent, cross-platform).

Used when SSR parsing AND yt-dlp both fail due to Douyin anti-scraping.

This script uses Playwright + the locally-installed system Chrome to open the
share link, execute JS, wait for the dynamic page to render, and extract the
"章节要点" (chapter summary) text that Douyin auto-generates on video pages.

Because it runs a real browser with JS, it passes Douyin's anti-bot measures
that block plain `curl`/SSR/headless `--dump-dom`.

Works identically for any agent (Hermes / Codex / OpenCode / Claude Code)
and any OS (macOS / Windows / Linux) — just needs `pip install playwright`
and Google Chrome installed.

The 章节要点 is Douyin's AI auto-summary, NOT the full transcript. It's used
as a fallback content source so the pipeline never returns empty when SSR
fails. It also captures title + aweme_id reliably.

Usage:
  python3 douyin_browser_fallback.py "https://v.douyin.com/xxxxx/" --output /tmp/out

Install:
  pip install playwright
  (uses system Chrome via channel="chrome", no browser download needed)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class FallbackResult:
    title: str = ""
    aweme_id: str = ""
    content_type: str = ""
    chapter_summary: str = ""
    page_url: str = ""
    success: bool = False


# ---------------------------------------------------------------------------
# Core extraction (Playwright + system Chrome)
# ---------------------------------------------------------------------------

def extract_with_playwright(
    share_url: str,
    *,
    timeout_ms: int = 30000,
    settle_ms: int = 6000,
) -> FallbackResult:
    """Open share URL in Playwright-driven Chrome, extract chapter summary."""
    import asyncio
    from playwright.async_api import async_playwright

    async def _run() -> FallbackResult:
        result = FallbackResult()
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                channel="chrome",  # use system Chrome, no download
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            try:
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 800},
                    locale="zh-CN",
                )
                page = await context.new_page()
                await page.goto(share_url, wait_until="domcontentloaded", timeout=timeout_ms)
                # Let the short link redirect + dynamic content settle
                await page.wait_for_timeout(settle_ms)

                result.page_url = page.url

                # Parse aweme_id + content_type from resolved URL
                m = re.search(r"douyin\.com/(?:video|note)/(\d+)", result.page_url)
                if m:
                    result.aweme_id = m.group(1)
                    result.content_type = "video" if "/video/" in result.page_url else "image"

                # Title
                result.title = await page.title()
                text = await page.evaluate("document.body.innerText")

                # Chapter summary (章节要点)
                idx = text.find("章节要点")
                if idx >= 0:
                    result.chapter_summary = text[idx:idx + 700].strip()

                result.success = bool(result.chapter_summary or result.title)
                return result
            finally:
                await browser.close()

    # Run the async coroutine (works on Python 3.9+)
    return asyncio.run(_run())


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Douyin browser-fallback: extract chapter summary via Playwright+Chrome. "
                    "Cross-agent, cross-platform. Requires: pip install playwright + Google Chrome.",
    )
    parser.add_argument("url", help="Douyin share link")
    parser.add_argument("-o", "--output", type=Path, default=Path("."), help="Output dir")
    parser.add_argument("--json", action="store_true", help="Output result as JSON")
    args = parser.parse_args()

    if not args.url:
        print("Error: No URL provided.", file=sys.stderr)
        return 1

    try:
        result = extract_with_playwright(args.url)
    except ImportError as e:
        print(f"❌ Playwright not installed: {e}", file=sys.stderr)
        print("   Install: pip install playwright  (uses system Chrome, no download)", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"❌ Browser fallback failed: {e}", file=sys.stderr)
        return 1

    if not result.success:
        print("❌ Browser fallback: page loaded but no content extracted.", file=sys.stderr)
        print("   The Douyin page may require login or captcha.", file=sys.stderr)
        return 1

    # Write output
    args.output.mkdir(parents=True, exist_ok=True)
    out_dir = args.output / f"browser_{result.aweme_id or 'unknown'}"
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "chapter_summary.txt").write_text(
        f"章节要点 (来自抖音AI摘要，非完整转写):\n\n{result.chapter_summary}\n",
        encoding="utf-8",
    )
    (out_dir / "meta.json").write_text(
        json.dumps(asdict(result), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if args.json:
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    else:
        print(f"✅ Browser fallback extracted content to: {out_dir}")
        print(f"   标题: {result.title[:60]}")
        print(f"   aweme_id: {result.aweme_id}")
        print(f"   type: {result.content_type or 'unknown'}")
        print(f"   章节摘要: {(result.chapter_summary[:80] + '...') if result.chapter_summary else '(无章节摘要)'}")
        print("")
        print("注意: 章节摘要是抖音AI生成的概要，非口播完整转写。仅作为SSR失败时的兜底。")
    return 0


if __name__ == "__main__":
    sys.exit(main())