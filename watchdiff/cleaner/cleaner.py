"""
Cleaner - strips scripts, styles, ads, and other noise from raw HTML.

The goal: keep only the human-readable content that a user actually sees.
"""

from __future__ import annotations

import re
from typing import Sequence

from bs4 import BeautifulSoup, Tag

# Tags that are pure noise and should always be stripped
_NOISE_TAGS: tuple[str, ...] = (
    "script",
    "style",
    "noscript",
    "iframe",
    "svg",
    "canvas",
    "video",
    "audio",
    "link",      # <link rel="stylesheet"> etc.
    "meta",
    "head",
)

# Common ad / tracking class/id fragments
_AD_PATTERNS: tuple[str, ...] = (
    "ad",
    "ads",
    "advertisement",
    "banner",
    "cookie",
    "gdpr",
    "popup",
    "overlay",
    "modal",
    "newsletter",
    "promo",
    "tracking",
    "analytics",
)


class Cleaner:
    """Strips noise from raw HTML and returns clean text or simplified HTML."""

    def __init__(
        self,
        extra_selectors: Sequence[str] | None   = None,
        extra_patterns: Sequence[str] | None    = None,
    ) -> None:
        """
        Args:
            extra_selectors: Additional CSS selectors to remove (e.g. ".cookie-banner").
            extra_patterns: Additional regex patterns applied to the final text.
        """
        self.extra_selectors: list[str] = list(extra_selectors or [])
        self.extra_patterns: list[re.Pattern] = [
            re.compile(p) for p in (extra_patterns or [])
        ]

    def clean(self, html: str) -> BeautifulSoup:
        """
        Parse the HTML and remove all noisy elements.

        Returns:
            A BeautifulSoup tree of the cleaned document.
        """
        soup = BeautifulSoup(html, "lxml")

        # 1. Strip known noise tags
        for tag in soup.find_all(_NOISE_TAGS):
            tag.decompose()

        # 2. Strip common ad / tracking containers by class / id heuristic
        self._strip_ad_containers(soup)

        # 3. Strip user-specified CSS selectors
        for selector in self.extra_selectors:
            for el in soup.select(selector):
                el.decompose()

        return soup

    def clean_to_text(self, html: str) -> str:
        """Clean the HTML and return normalised plain text."""
        soup        = self.clean(html)
        raw_text    = soup.get_text(separator="\n")
        return self._normalise_text(raw_text)

    def clean_to_html(self, html: str) -> str:
        """Clean the HTML and return the simplified HTML string."""
        soup = self.clean(html)
        return str(soup)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _strip_ad_containers(self, soup: BeautifulSoup) -> None:
        """Remove elements whose id/class contains ad-related keywords."""
        for tag in soup.find_all(True):  # all tags
            if not isinstance(tag, Tag) or tag.parent is None:
                continue
            raw_classes     = tag.get("class") or []
            classes         = " ".join(
                str(c) for c in (raw_classes if isinstance(raw_classes, list) else [raw_classes])
            ).lower()
            tag_id      = str(tag.get("id") or "").lower()
            combined    = f"{classes} {tag_id}"
            if any(pat in combined for pat in _AD_PATTERNS):
                tag.decompose()

    def _normalise_text(self, text: str) -> str:
        """Collapse whitespace and apply extra regex strips."""
        # Collapse blank lines
        text    = re.sub(r"\n{3,}", "\n\n", text)
        # Collapse horizontal spaces
        text    = re.sub(r"[ \t]+", " ", text)
        # Strip leading/trailing space per line
        lines   = [line.strip() for line in text.splitlines()]
        text    = "\n".join(line for line in lines if line)

        # Apply user-defined patterns
        for pattern in self.extra_patterns:
            text = pattern.sub("", text)

        return text.strip()