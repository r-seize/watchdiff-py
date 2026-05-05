"""
BrowserFetcher - Playwright-based fetcher for JavaScript-heavy pages.

Requires: pip install "watchdiff-core[browser]"
Then run:  playwright install chromium

Usage in WatchConfig:
    WatchConfig(
        url="https://example.com",
        browser=True,
        browser_options=BrowserOptions(wait_for="networkidle", wait_for_selector=".price"),
    )
"""

from __future__ import annotations

import asyncio
import logging
import random

from watchdiff.models import WatchConfig

logger = logging.getLogger(__name__)


class BrowserFetchError(Exception):
    """Raised when a browser fetch fails."""


class AsyncBrowserFetcher:
    """Async Playwright-based fetcher (one browser launch per fetch call)."""

    async def fetch(self, config: WatchConfig) -> str:
        """
        Fetch page HTML using a headless Chromium browser.

        Args:
            config: WatchConfig with browser=True and optional browser_options.

        Returns:
            Full rendered HTML string.

        Raises:
            BrowserFetchError: if playwright is not installed or page load fails.
        """
        try:
            from playwright.async_api import async_playwright  # noqa: PLC0415
        except ImportError as exc:
            raise BrowserFetchError(
                "playwright is not installed. "
                "Run: pip install 'watchdiff-core[browser]' && playwright install chromium"
            ) from exc

        opts        = config.browser_options
        wait_until  = opts.wait_for if opts else "load"
        wait_sel    = opts.wait_for_selector if opts else None
        timeout_ms  = opts.timeout if opts else 30000

        proxy_url = random.choice(config.proxies) if config.proxies else None

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)

                ctx_kwargs: dict = {"extra_http_headers": config.headers}
                if proxy_url:
                    ctx_kwargs["proxy"] = {"server": proxy_url}
                context = await browser.new_context(**ctx_kwargs)

                page = await context.new_page()
                await page.goto(config.url, wait_until=wait_until, timeout=timeout_ms)

                if wait_sel:
                    await page.wait_for_selector(wait_sel, timeout=timeout_ms)

                html = await page.content()
                await browser.close()
                return html

        except BrowserFetchError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise BrowserFetchError(
                f"Browser fetch failed for {config.url}: {exc}"
            ) from exc


class BrowserFetcher:
    """Synchronous wrapper around AsyncBrowserFetcher - runs asyncio event loop internally."""

    def fetch(self, config: WatchConfig) -> str:
        """
        Fetch page HTML using a headless Chromium browser (sync).

        Args:
            config: WatchConfig with browser=True and optional browser_options.

        Returns:
            Full rendered HTML string.

        Raises:
            BrowserFetchError: if playwright is not installed or page load fails.
        """
        return asyncio.run(AsyncBrowserFetcher().fetch(config))
