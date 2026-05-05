"""
Diff Engine - compares two Snapshots and produces a human-readable DiffReport.

Strategies:
  - "line"     (default): split content into lines, use LCS-based difflib.
  - "semantic": extract <p>, <h1-h6>, <li>, <td>, <th>, <blockquote> blocks from raw_html,
                diff by whole block. Falls back to line mode if no blocks are found.
"""

from __future__ import annotations

import difflib

from watchdiff.models import Change, ChangeType, DiffReport, Snapshot, WatchConfig

_SEMANTIC_TAGS = ("p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "td", "th", "blockquote")


class DiffEngine:
    """Compares two snapshots and returns a DiffReport."""

    def compare(
        self,
        before: Snapshot,
        after: Snapshot,
        config: WatchConfig,
    ) -> DiffReport:
        """
        Compare two snapshots.

        Args:
            before: Previous snapshot.
            after:  New snapshot.
            config: WatchConfig (used for label, url, target, diff_mode).

        Returns:
            DiffReport with a list of Change objects.
        """
        if before.is_identical_to(after):
            return DiffReport(
                url     = config.url,
                target  = config.target,
                label   = config.label or config.url,
                before  = before,
                after   = after,
                changes = [],
            )

        if config.diff_mode == "semantic":
            before_units = _semantic_blocks(before.raw_html)
            after_units  = _semantic_blocks(after.raw_html)
            if not before_units and not after_units:
                # No semantic blocks found - fall back to line mode
                before_units = _split_content(before.content)
                after_units  = _split_content(after.content)
        else:
            before_units = _split_content(before.content)
            after_units  = _split_content(after.content)

        changes: list[Change] = []

        matcher = difflib.SequenceMatcher(
            isjunk   = None,
            a        = before_units,
            b        = after_units,
            autojunk = False,
        )

        for opcode, a0, a1, b0, b1 in matcher.get_opcodes():
            if opcode == "equal":
                pass  # no change

            elif opcode == "insert":
                for unit in after_units[b0:b1]:
                    if unit.strip():
                        changes.append(
                            Change(
                                kind    = ChangeType.ADDED,
                                after   = unit.strip(),
                                context = _context(after_units, b0),
                            )
                        )

            elif opcode == "delete":
                for unit in before_units[a0:a1]:
                    if unit.strip():
                        changes.append(
                            Change(
                                kind    = ChangeType.REMOVED,
                                before  = unit.strip(),
                                context = _context(before_units, a0),
                            )
                        )

            elif opcode == "replace":
                old_block = " ".join(before_units[a0:a1]).strip()
                new_block = " ".join(after_units[b0:b1]).strip()
                if old_block and new_block:
                    changes.append(
                        Change(
                            kind    = ChangeType.MODIFIED,
                            before  = old_block,
                            after   = new_block,
                            context = _context(after_units, b0),
                        )
                    )
                elif old_block:
                    changes.append(Change(kind=ChangeType.REMOVED, before=old_block))
                elif new_block:
                    changes.append(Change(kind=ChangeType.ADDED, after=new_block))

        return DiffReport(
            url     = config.url,
            target  = config.target,
            label   = config.label or config.url,
            before  = before,
            after   = after,
            changes = changes,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _split_content(text: str) -> list[str]:
    """Split text into lines for line-mode diffing."""
    return text.splitlines()


def _semantic_blocks(html: str) -> list[str]:
    """Extract semantic text blocks from HTML for semantic-mode diffing."""
    from bs4 import BeautifulSoup  # noqa: PLC0415

    soup   = BeautifulSoup(html, "lxml")
    blocks = []
    for tag in soup.find_all(_SEMANTIC_TAGS):
        text = tag.get_text(separator=" ").strip()
        if text:
            blocks.append(text)
    return blocks


def _context(units: list[str], index: int, window: int = 1) -> str | None:
    """Return a short surrounding context for a change."""
    start = max(0, index - window)
    end   = min(len(units), index + window + 1)
    ctx   = " | ".join(u.strip() for u in units[start:end] if u.strip())
    return ctx or None
