"""
Parser - extracts the content zone that the user actually wants to monitor.

If a CSS selector (target) is provided, only that zone is extracted.
Otherwise the full body text is used.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from watchdiff.models import Snapshot, WatchConfig


class Parser:
    """Extracts the monitored zone from a cleaned BeautifulSoup tree."""

    def extract(
        self,
        soup: BeautifulSoup,
        config: WatchConfig,
    ) -> Snapshot:
        """
        Extract a Snapshot from a cleaned BeautifulSoup document.

        Args:
            soup:   Cleaned BeautifulSoup tree (output of Cleaner.clean).
            config: The WatchConfig describing what to monitor.

        Returns:
            A Snapshot with content and raw_html fields populated.

        Raises:
            ParserError: if the target selector matched nothing.
        """
        if config.target:
            elements = soup.select(config.target)
            if not elements:
                raise ParserError(
                    f"Selector {config.target!r} matched nothing on {config.url}"
                )
            # Combine all matched elements
            raw_html    = "\n".join(str(el) for el in elements)
            content     = "\n".join(
                el.get_text(separator="\n").strip() for el in elements
            )
        else:
            body        = soup.find("body") or soup
            raw_html    = str(body)
            content     = body.get_text(separator="\n").strip()

        # Final normalisation
        content = _collapse_whitespace(content)

        return Snapshot(
            url         = config.url,
            target      = config.target,
            content     = content,
            raw_html    = raw_html,
        )


class ParserError(Exception):
    """Raised when the target selector cannot be found."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collapse_whitespace(text: str) -> str:
    import re
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())