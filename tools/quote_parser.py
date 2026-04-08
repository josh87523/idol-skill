"""Parse raw quote text (one quote per line) into structured JSON records.

Supported formats:
  - Plain text: one line = one quote
  - Source annotation: "text" — source  OR  text — source
  - Context tag prefix: [综艺] text, [采访] text, etc.
  - Empty / whitespace-only lines are skipped
  - IDs auto-increment from 1
"""

from __future__ import annotations

import re
from typing import List, Optional

VALID_CONTEXTS = {"综艺", "采访", "直播", "社媒", "同人文", "捡手机文学", "未知"}
DEFAULT_CONTEXT = "未知"

# [tag] rest-of-line
_CONTEXT_RE = re.compile(r"^\[([^\]]+)\]\s*(.+)$")

# "text" — source  OR  text — source
# Support both em-dash (—) and double-hyphen (--)
_SOURCE_RE = re.compile(r'^"(.+?)"\s*[—\-]{1,2}\s*(.+)$')
_SOURCE_PLAIN_RE = re.compile(r'^(.+?)\s*[—]{1}\s*(.+)$')


def _parse_source(line: str) -> tuple[str, Optional[str]]:
    """Extract (text, source) from a single line."""
    # Try quoted form first: "text" — source
    m = _SOURCE_RE.match(line)
    if m:
        return m.group(1).strip(), m.group(2).strip()

    # Try plain form: text — source (em-dash only to avoid false positives)
    m = _SOURCE_PLAIN_RE.match(line)
    if m:
        return m.group(1).strip(), m.group(2).strip()

    return line, None


def parse_quotes(raw: str) -> List[dict]:
    """Parse raw multi-line text into a list of quote dicts.

    Returns:
        List of dicts with keys: id, text, source, source_url, context, confirmed
    """
    results: List[dict] = []
    idx = 0

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue

        context = DEFAULT_CONTEXT

        # Check for context tag
        m = _CONTEXT_RE.match(line)
        if m:
            tag = m.group(1)
            if tag in VALID_CONTEXTS:
                context = tag
            line = m.group(2)

        text, source = _parse_source(line)

        idx += 1
        results.append(
            {
                "id": idx,
                "text": text,
                "source": source,
                "source_url": None,
                "context": context,
                "confirmed": True,
            }
        )

    return results
