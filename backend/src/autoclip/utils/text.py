"""Small text helpers shared by the API and the pipeline."""
from __future__ import annotations


def truncate_words(text: str, limit: int, ellipsis: str = "…") -> str:
    """`text` cut to at most `limit` characters at a word boundary.

    Whitespace is collapsed first. A single word longer than `limit` is the
    only case cut mid-word. The ellipsis counts towards `limit`.
    """
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    room = max(1, limit - len(ellipsis))
    cut = text[:room + 1]
    head = cut.rsplit(" ", 1)[0] if " " in cut else ""
    if not head:                      # one long word: no boundary to cut at
        head = text[:room]
    return head.rstrip(" ,;:.-–—") + ellipsis
