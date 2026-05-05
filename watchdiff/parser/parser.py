"""
Parser - extracts the content zone that the user actually wants to monitor.

Supports two target formats:
  - CSS selector: e.g. ".price", "#main > h1", "table.results td"
  - XPath:        e.g. "//div[@class='price']", "/html/body/main/p[1]"
    XPath is detected by a leading "/" or "(" character.

If target is None, the full body text is used.
"""

from __future__ import annotations

import re

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
            ParserError: if the target selector / XPath matched nothing.
        """
        if config.target:
            if _is_xpath(config.target):
                raw_html, content = _xpath_extract(str(soup), config.target, config.url)
            else:
                elements = soup.select(config.target)
                if not elements:
                    raise ParserError(
                        f"Selector {config.target!r} matched nothing on {config.url}"
                    )
                raw_html = "\n".join(str(el) for el in elements)
                content  = "\n".join(
                    el.get_text(separator="\n").strip() for el in elements
                )
        else:
            body     = soup.find("body") or soup
            raw_html = str(body)
            content  = body.get_text(separator="\n").strip()

        content = _collapse_whitespace(content)

        return Snapshot(
            url      = config.url,
            target   = config.target,
            content  = content,
            raw_html = raw_html,
        )


class ParserError(Exception):
    """Raised when the target selector / XPath cannot be found."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_xpath(target: str) -> bool:
    """Return True if target looks like an XPath expression."""
    return target.startswith("/") or target.startswith("(")


def _xpath_extract(html: str, xpath_expr: str, url: str) -> tuple[str, str]:
    """
    Extract content matching xpath_expr from html using lxml.

    Returns:
        Tuple (raw_html_string, text_content).

    Raises:
        ParserError: if XPath matched nothing or the HTML could not be parsed.
    """
    from lxml import etree  # noqa: PLC0415

    tree = etree.HTML(html.encode("utf-8"))
    if tree is None:
        raise ParserError(f"Failed to parse HTML for XPath {xpath_expr!r} on {url}")

    try:
        results = tree.xpath(xpath_expr)
    except etree.XPathError as exc:
        raise ParserError(f"Invalid XPath {xpath_expr!r}: {exc}") from exc

    if not results:
        raise ParserError(f"XPath {xpath_expr!r} matched nothing on {url}")

    html_parts = []
    text_parts = []
    for r in results:
        if isinstance(r, str):
            text_parts.append(r.strip())
            html_parts.append(r.strip())
        elif hasattr(r, "tag"):
            html_parts.append(etree.tostring(r, encoding="unicode", method="html"))
            text_parts.append("".join(r.itertext()).strip())

    return (
        "\n".join(h for h in html_parts if h),
        "\n".join(t for t in text_parts if t),
    )


def _collapse_whitespace(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())
