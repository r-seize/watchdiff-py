"""
Fetcher - downloads HTML from URLs.

Two implementations:
  - Fetcher: synchronous, uses httpx.Client
  - AsyncFetcher: async, uses httpx.AsyncClient

Both support:
  - User-Agent rotation (config.user_agents or built-in pool of 4)
  - Proxy rotation     (config.proxies - one picked randomly per request)
"""

from __future__ import annotations

import logging
import random

import httpx

from watchdiff.models import WatchConfig

logger = logging.getLogger(__name__)

_DEFAULT_ACCEPT_HEADERS = {
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

_DEFAULT_USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]


def _pick_ua(config: WatchConfig) -> str:
    pool = config.user_agents if config.user_agents else _DEFAULT_USER_AGENTS
    return random.choice(pool)


def _pick_proxy(config: WatchConfig) -> str | None:
    return random.choice(config.proxies) if config.proxies else None


class FetchError(Exception):
    """Raised when an HTTP request fails."""


class Fetcher:
    """Synchronous HTTP fetcher with UA and proxy rotation."""

    def fetch(self, config: WatchConfig) -> str:
        """
        Download the HTML for the given config.

        Returns:
            Raw HTML string.

        Raises:
            FetchError: on network error or non-2xx response.
        """
        headers = {**_DEFAULT_ACCEPT_HEADERS, "User-Agent": _pick_ua(config), **config.headers}
        proxy   = _pick_proxy(config)

        client_kwargs: dict = {"timeout": config.timeout, "follow_redirects": True}
        if proxy:
            client_kwargs["proxy"] = proxy

        try:
            with httpx.Client(**client_kwargs) as client:
                resp = client.get(config.url, headers=headers)
                resp.raise_for_status()
                return resp.text
        except httpx.HTTPStatusError as exc:
            raise FetchError(
                f"HTTP {exc.response.status_code} for {config.url}"
            ) from exc
        except httpx.RequestError as exc:
            raise FetchError(f"Request failed for {config.url}: {exc}") from exc


class AsyncFetcher:
    """Asynchronous HTTP fetcher with UA and proxy rotation."""

    async def fetch(self, config: WatchConfig) -> str:
        """
        Download the HTML for the given config (async).

        Returns:
            Raw HTML string.

        Raises:
            FetchError: on network error or non-2xx response.
        """
        headers = {**_DEFAULT_ACCEPT_HEADERS, "User-Agent": _pick_ua(config), **config.headers}
        proxy   = _pick_proxy(config)

        client_kwargs: dict = {"timeout": config.timeout, "follow_redirects": True}
        if proxy:
            client_kwargs["proxy"] = proxy

        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                resp = await client.get(config.url, headers=headers)
                resp.raise_for_status()
                return resp.text
        except httpx.HTTPStatusError as exc:
            raise FetchError(
                f"HTTP {exc.response.status_code} for {config.url}"
            ) from exc
        except httpx.RequestError as exc:
            raise FetchError(f"Request failed for {config.url}: {exc}") from exc
