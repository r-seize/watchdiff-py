"""
Fetcher - downloads HTML from URLs.

Two implementations:
  - Fetcher: synchronous, uses httpx.Client
  - AsyncFetcher: async, uses httpx.AsyncClient
"""

from __future__ import annotations

import logging

import httpx

from watchdiff.models import WatchConfig

logger = logging.getLogger(__name__)

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; WatchDiff/1.0; "
        "+https://github.com/watchdiff/watchdiff-py)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


class FetchError(Exception):
    """Raised when an HTTP request fails."""


class Fetcher:
    """Synchronous HTTP fetcher."""

    def fetch(self, config: WatchConfig) -> str:
        """
        Download the HTML for the given config.

        Returns:
            Raw HTML string.

        Raises:
            FetchError: on network error or non-2xx response.
        """
        headers = {**_DEFAULT_HEADERS, **config.headers}
        try:
            with httpx.Client(timeout=config.timeout, follow_redirects=True) as client:
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
    """Asynchronous HTTP fetcher."""

    async def fetch(self, config: WatchConfig) -> str:
        """
        Download the HTML for the given config (async).

        Returns:
            Raw HTML string.

        Raises:
            FetchError: on network error or non-2xx response.
        """
        headers = {**_DEFAULT_HEADERS, **config.headers}
        try:
            async with httpx.AsyncClient(timeout=config.timeout, follow_redirects=True) as client:
                resp = await client.get(config.url, headers=headers)
                resp.raise_for_status()
                return resp.text
        except httpx.HTTPStatusError as exc:
            raise FetchError(
                f"HTTP {exc.response.status_code} for {config.url}"
            ) from exc
        except httpx.RequestError as exc:
            raise FetchError(f"Request failed for {config.url}: {exc}") from exc
