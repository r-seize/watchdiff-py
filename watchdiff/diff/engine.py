"""
Diff Engine - compares two Snapshots and produces a human-readable DiffReport.

Strategy:
  1. Split content into logical lines / sentences.
  2. Use Python's difflib.SequenceMatcher for reliable LCS-based diffing.
  3. Map opcodes to Change objects (added / removed / modified).

This produces clean, minimal diffs without HTML noise.
"""

from __future__ import annotations

import difflib

from watchdiff.models import Change, ChangeType, DiffReport, Snapshot, WatchConfig


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

        Returns:
            DiffReport with a list of Change objects.
        """
        changes: list[Change] = []

        if before.is_identical_to(after):
            return DiffReport(
                url         = config.url,
                target      = config.target,
                label       = config.label or config.url,
                before      = before,
                after       = after,
                changes     = [],
            )

        before_lines    = _split_content(before.content)
        after_lines     = _split_content(after.content)

        matcher = difflib.SequenceMatcher(
            isjunk      = None,
            a           = before_lines,
            b           = after_lines,
            autojunk    = False,
        )

        for opcode, a0, a1, b0, b1 in matcher.get_opcodes():
            match opcode:
                case "equal":
                    pass  # no change

                case "insert":
                    for line in after_lines[b0:b1]:
                        if line.strip():
                            changes.append(
                                Change(
                                    kind    = ChangeType.ADDED,
                                    after   = line.strip(),
                                    context = _context(after_lines, b0),
                                )
                            )

                case "delete":
                    for line in before_lines[a0:a1]:
                        if line.strip():
                            changes.append(
                                Change(
                                    kind    = ChangeType.REMOVED,
                                    before  = line.strip(),
                                    context = _context(before_lines, a0),
                                )
                            )

                case "replace":
                    old_block = " ".join(before_lines[a0:a1]).strip()
                    new_block = " ".join(after_lines[b0:b1]).strip()
                    if old_block and new_block:
                        changes.append(
                            Change(
                                kind        = ChangeType.MODIFIED,
                                before      = old_block,
                                after       = new_block,
                                context     = _context(after_lines, b0),
                            )
                        )
                    elif old_block:
                        changes.append(
                            Change(kind=ChangeType.REMOVED, before=old_block)
                        )
                    elif new_block:
                        changes.append(
                            Change(kind=ChangeType.ADDED, after=new_block)
                        )

        return DiffReport(
            url         = config.url,
            target      = config.target,
            label       = config.label or config.url,
            before      = before,
            after       = after,
            changes     = changes,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _split_content(text: str) -> list[str]:
    """Split text into meaningful units for diffing.

    Splits on newlines; empty lines are preserved as markers.
    """
    return text.splitlines()


def _context(lines: list[str], index: int, window: int = 1) -> str | None:
    """Return a short surrounding context for a change."""
    start   = max(0, index - window)
    end     = min(len(lines), index + window + 1)
    ctx     = " | ".join(line.strip() for line in lines[start:end] if line.strip())
    return ctx or None