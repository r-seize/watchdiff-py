"""
Diff Engine - compares two Snapshots and produces a human-readable DiffReport.

Strategies:
  - "line"     (default): split content into lines, use LCS-based difflib.
  - "semantic": extract <p>, <h1-h6>, <li>, <td>, <th>, <blockquote> blocks from raw_html.
                Falls back to line mode if no blocks are found.
  - "word":     split content into individual words, coalescence removed+added -> modified.
  - "json":     parse content as JSON, report changes by key path (e.g. "price", "stock.qty").
                Falls back to line mode if content is not valid JSON.
"""

from __future__ import annotations

import difflib
import json
import re

from watchdiff.models import Change, ChangeType, DiffReport, Snapshot, WatchConfig

_SEMANTIC_TAGS      = ("p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "td", "th", "blockquote")
_WORD_SPLIT_RE      = re.compile(r"(\S+|\s+)")


class DiffEngine:
    """Compares two snapshots and returns a DiffReport."""

    def compare(
        self,
        before: Snapshot,
        after: Snapshot,
        config: WatchConfig,
    ) -> DiffReport:
        """
        Compare two snapshots using the strategy defined by config.diff_mode.

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

        mode = config.diff_mode

        # JSON mode: recursive key-path walk, fallback to line
        if mode == "json":
            changes = _json_diff(before.content, after.content)
            if not changes:
                # fallback - content wasn't valid JSON or no changes found via path walk
                changes = _sequence_diff(_split_content(before.content), _split_content(after.content))
            return DiffReport(
                url=config.url, target=config.target,
                label=config.label or config.url,
                before=before, after=after, changes=changes,
            )

        # Resolve units for line / semantic / word modes
        if mode == "semantic":
            before_units = _semantic_blocks(before.raw_html)
            after_units  = _semantic_blocks(after.raw_html)
            if not before_units and not after_units:
                before_units = _split_content(before.content)
                after_units  = _split_content(after.content)
        elif mode == "word":
            before_units = _word_units(before.content)
            after_units  = _word_units(after.content)
        else:  # "line"
            before_units = _split_content(before.content)
            after_units  = _split_content(after.content)

        changes = _sequence_diff(before_units, after_units)

        return DiffReport(
            url     = config.url,
            target  = config.target,
            label   = config.label or config.url,
            before  = before,
            after   = after,
            changes = changes,
        )


# ---------------------------------------------------------------------------
# Mode helpers
# ---------------------------------------------------------------------------

def _split_content(text: str) -> list[str]:
    return text.splitlines()


def _word_units(text: str) -> list[str]:
    """Split text into word-level tokens (words and whitespace runs)."""
    return [t for t in _WORD_SPLIT_RE.findall(text) if t.strip()]


def _semantic_blocks(html: str) -> list[str]:
    from bs4 import BeautifulSoup  # noqa: PLC0415
    soup   = BeautifulSoup(html, "lxml")
    blocks = []
    for tag in soup.find_all(_SEMANTIC_TAGS):
        text = tag.get_text(separator=" ").strip()
        if text:
            blocks.append(text)
    return blocks


def _json_diff(before_text: str, after_text: str) -> list[Change]:
    """Recursive key-path diff of two JSON strings. Returns [] if either is not valid JSON."""
    try:
        before_data = json.loads(before_text)
        after_data  = json.loads(after_text)
    except (json.JSONDecodeError, ValueError):
        return []

    changes: list[Change] = []
    _walk_json(before_data, after_data, [], changes)
    return changes


def _walk_json(before: object, after: object, path: list[str], changes: list[Change]) -> None:
    key_path = ".".join(path) if path else "root"

    if isinstance(before, dict) and isinstance(after, dict):
        all_keys = sorted(set(before) | set(after))
        for key in all_keys:
            child_path = path + [str(key)]
            if key not in before:
                changes.append(Change(
                    kind    = ChangeType.ADDED,
                    after   = _repr(after[key]),
                    context = ".".join(child_path),
                ))
            elif key not in after:
                changes.append(Change(
                    kind    = ChangeType.REMOVED,
                    before  = _repr(before[key]),
                    context = ".".join(child_path),
                ))
            else:
                _walk_json(before[key], after[key], child_path, changes)

    elif isinstance(before, list) and isinstance(after, list):
        for i in range(min(len(before), len(after))):
            _walk_json(before[i], after[i], path + [str(i)], changes)
        for i in range(min(len(before), len(after)), len(after)):
            changes.append(Change(
                kind    = ChangeType.ADDED,
                after   = _repr(after[i]),
                context = ".".join(path + [str(i)]),
            ))
        for i in range(min(len(before), len(after)), len(before)):
            changes.append(Change(
                kind    = ChangeType.REMOVED,
                before  = _repr(before[i]),
                context = ".".join(path + [str(i)]),
            ))

    else:
        if str(before) != str(after):
            changes.append(Change(
                kind    = ChangeType.MODIFIED,
                before  = _repr(before),
                after   = _repr(after),
                context = key_path,
            ))


def _repr(value: object) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


# ---------------------------------------------------------------------------
# Shared sequence diff (used by line / semantic / word)
# ---------------------------------------------------------------------------

def _sequence_diff(before_units: list[str], after_units: list[str]) -> list[Change]:
    changes: list[Change] = []

    matcher = difflib.SequenceMatcher(
        isjunk   = None,
        a        = before_units,
        b        = after_units,
        autojunk = False,
    )

    for opcode, a0, a1, b0, b1 in matcher.get_opcodes():
        if opcode == "equal":
            pass

        elif opcode == "insert":
            for unit in after_units[b0:b1]:
                if unit.strip():
                    changes.append(Change(
                        kind    = ChangeType.ADDED,
                        after   = unit.strip(),
                        context = _context(after_units, b0),
                    ))

        elif opcode == "delete":
            for unit in before_units[a0:a1]:
                if unit.strip():
                    changes.append(Change(
                        kind    = ChangeType.REMOVED,
                        before  = unit.strip(),
                        context = _context(before_units, a0),
                    ))

        elif opcode == "replace":
            old_block = " ".join(before_units[a0:a1]).strip()
            new_block = " ".join(after_units[b0:b1]).strip()
            if old_block and new_block:
                changes.append(Change(
                    kind    = ChangeType.MODIFIED,
                    before  = old_block,
                    after   = new_block,
                    context = _context(after_units, b0),
                ))
            elif old_block:
                changes.append(Change(kind=ChangeType.REMOVED, before=old_block))
            elif new_block:
                changes.append(Change(kind=ChangeType.ADDED, after=new_block))

    return changes


def _context(units: list[str], index: int, window: int = 1) -> str | None:
    start = max(0, index - window)
    end   = min(len(units), index + window + 1)
    ctx   = " | ".join(u.strip() for u in units[start:end] if u.strip())
    return ctx or None
