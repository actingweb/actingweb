"""Sanitising text that clients supply about themselves.

MCP clients name themselves in ``initialize`` (``clientInfo.name`` and
``.version``) before they authenticate, and in the dynamic registration body
(``client_name``). That text is stored on trust rows, logged, and rendered by
applications — often into text an LLM reads. A name carrying newlines or
control characters can add lines to that text.

The rule (adopted from the ``actingweb_mcp`` consumer's
``helpers/client_name.py``):

- strip Unicode control (``Cc``) and format (``Cf``) characters, except
  U+200C ZERO WIDTH NON-JOINER and U+200D ZERO WIDTH JOINER, which multi-part
  emoji and Persian/Indic shaping depend on;
- collapse whitespace runs to one space and trim;
- cap names at 80 characters. Labels users edit afterwards (a trust
  relationship's ``desc``) are stripped but never capped.
"""

import unicodedata
from typing import Any

__all__ = ["CLIENT_NAME_MAX_LEN", "sanitize_client_name", "sanitize_label"]

CLIENT_NAME_MAX_LEN = 80

_KEEP = {"‌", "‍"}


def sanitize_label(value: Any) -> str:
    """Strip control and format characters and collapse whitespace.

    Not capped. A non-string becomes ``""``.
    """
    if not isinstance(value, str):
        return ""
    kept = []
    for ch in value:
        if ch in _KEEP:
            kept.append(ch)
            continue
        category = unicodedata.category(ch)
        if category in ("Cc", "Cf"):
            # Control whitespace (\\n, \\t, ...) becomes a separator, not glue.
            kept.append(" " if ch.isspace() else "")
            continue
        kept.append(ch)
    return " ".join("".join(kept).split())


def sanitize_client_name(value: Any, *, max_len: int = CLIENT_NAME_MAX_LEN) -> str:
    """:func:`sanitize_label`, capped at ``max_len`` characters."""
    return sanitize_label(value)[:max_len].rstrip()
