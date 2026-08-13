from __future__ import annotations

import json
import re


def extract_json_path(json_str: str, path: str) -> str:
    """Extract a value from a JSON string using a simple path expression."""
    try:
        obj = json.loads(json_str)
    except json.JSONDecodeError:
        return json_str

    tokens: list[str | int] = []
    for m in re.finditer(r'\[(\d+)\]|\.?([^.\[]+)', path.lstrip("$")):
        if m.group(1) is not None:
            tokens.append(int(m.group(1)))
        elif m.group(2):
            tokens.append(m.group(2))

    current = obj
    for tok in tokens:
        try:
            current = current[tok]  # type: ignore[index]
        except (KeyError, IndexError, TypeError):
            return json_str

    if isinstance(current, str):
        return current
    return json.dumps(current, ensure_ascii=False)
