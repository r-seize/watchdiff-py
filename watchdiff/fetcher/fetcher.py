"""
Fetcher - downloads HTML from URLs.

Two implementations:
  - Fetcher: synchronous, uses httpx.Client
  - AsyncFetcher: async, uses httpx.AsyncClient

Both support:
  - User-Agent rotation (config.user_agents or built-in pool of 4)
  - Proxy rotation     (config.proxies - one picked randomly per request)
  - Retry + exponential backoff (config.retries, config.retry_delay)
    Retried: network errors, timeouts, 429, 5xx
    Not retried: 4xx (except 429)
"""

from __future__ import annotations

import asyncio
import logging
import random
import time

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

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _pick_ua(config: WatchConfig) -> str:
    pool = config.user_agents if config.user_agents else _DEFAULT_USER_AGENTS
    return random.choice(pool)


def _pick_proxy(config: WatchConfig) -> str | None:
    return random.choice(config.proxies) if config.proxies else None


def _backoff(attempt: int, retry_delay: float) -> float:
    return retry_delay * (2 ** attempt)


class FetchError(Exception):
    """Raised when an HTTP request fails."""

    def __init__(self, message: str, status_code: int = 0) -> None:
        super().__init__(message)
        self.status_code = status_code


class Fetcher:
    """Synchronous HTTP fetcher with UA/proxy rotation and retry backoff."""

    def fetch(self, config: WatchConfig) -> str:
        """
        Download the HTML for the given config.

        Returns:
            Raw HTML string.

        Raises:
            FetchError: after all retries are exhausted.
        """
        headers = {**_DEFAULT_ACCEPT_HEADERS, "User-Agent": _pick_ua(config), **config.headers}
        proxy   = _pick_proxy(config)

        client_kwargs: dict = {"timeout": config.timeout, "follow_redirects": True}
        if proxy:
            client_kwargs["proxy"] = proxy

        last_exc: Exception | None = None

        for attempt in range(config.retries + 1):
            if attempt > 0:
                delay = _backoff(attempt - 1, config.retry_delay)
                logger.debug("[%s] Retry %d/%d after %.1fs", config.label, attempt, config.retries, delay)
                time.sleep(delay)
            try:
                with httpx.Client(**client_kwargs) as client:
                    resp = client.get(config.url, headers=headers)
                    if resp.status_code in _RETRYABLE_STATUS and attempt < config.retries:
                        last_exc = FetchError(f"HTTP {resp.status_code} for {config.url}")
                        continue
                    resp.raise_for_status()
                    return resp.text
            except httpx.HTTPStatusError as exc:
                code     = exc.response.status_code
                last_exc = FetchError(f"HTTP {code} for {config.url}", status_code=code)
                if code not in _RETRYABLE_STATUS or attempt >= config.retries:
                    raise FetchError(f"HTTP {code} for {config.url}", status_code=code) from exc
            except httpx.RequestError as exc:
                last_exc = FetchError(f"Request failed for {config.url}: {exc}", status_code=0)
                if attempt >= config.retries:
                    raise FetchError(f"Request failed for {config.url}: {exc}", status_code=0) from exc

        raise last_exc or FetchError(f"All retries exhausted for {config.url}", status_code=0)


class AsyncFetcher:
    """Asynchronous HTTP fetcher with UA/proxy rotation and retry backoff."""

    async def fetch(self, config: WatchConfig) -> str:
        """
        Download the HTML for the given config (async).

        Returns:
            Raw HTML string.

        Raises:
            FetchError: after all retries are exhausted.
        """
        headers = {**_DEFAULT_ACCEPT_HEADERS, "User-Agent": _pick_ua(config), **config.headers}
        proxy   = _pick_proxy(config)

        client_kwargs: dict = {"timeout": config.timeout, "follow_redirects": True}
        if proxy:
            client_kwargs["proxy"] = proxy

        last_exc: Exception | None = None

        for attempt in range(config.retries + 1):
            if attempt > 0:
                delay = _backoff(attempt - 1, config.retry_delay)
                logger.debug("[%s] Retry %d/%d after %.1fs", config.label, attempt, config.retries, delay)
                await asyncio.sleep(delay)
            try:
                async with httpx.AsyncClient(**client_kwargs) as client:
                    resp = await client.get(config.url, headers=headers)
                    if resp.status_code in _RETRYABLE_STATUS and attempt < config.retries:
                        last_exc = FetchError(f"HTTP {resp.status_code} for {config.url}")
                        continue
                    resp.raise_for_status()
                    return resp.text
            except httpx.HTTPStatusError as exc:
                code     = exc.response.status_code
                last_exc = FetchError(f"HTTP {code} for {config.url}", status_code=code)
                if code not in _RETRYABLE_STATUS or attempt >= config.retries:
                    raise FetchError(f"HTTP {code} for {config.url}", status_code=code) from exc
            except httpx.RequestError as exc:
                last_exc = FetchError(f"Request failed for {config.url}: {exc}", status_code=0)
                if attempt >= config.retries:
                    raise FetchError(f"Request failed for {config.url}: {exc}", status_code=0) from exc

        raise last_exc or FetchError(f"All retries exhausted for {config.url}", status_code=0)
