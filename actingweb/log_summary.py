"""Summaries of request and response payloads for DEBUG logging.

Payloads that ActingWeb forwards or receives carry user- and agent-supplied
values verbatim: remote-method arguments, property values, e-mail addresses,
PKCE challenges. A DEBUG line must never print them. ``summarize_payload``
returns the shape of a payload (its key names and its size) so a log line stays
useful for tracing without holding the content.

Key names are logged, sanitised like client-supplied names (control and
format characters removed, capped at 64 characters), because a peer chooses
them. For a ``/properties`` write the key names are the property names; an
application that treats property names as sensitive should keep the
``actingweb.aw_proxy`` logger above DEBUG.
"""

from typing import Any

from .client_text import sanitize_client_name

_KEY_MAX_LEN = 64

__all__ = ["summarize_payload"]


def summarize_payload(
    obj: Any, *, encoded_len: int | None = None, max_keys: int = 20
) -> str:
    """Describe ``obj`` by its key names and size, never by its values.

    Args:
        obj: The payload the caller already holds (a dict, a list, a string).
        encoded_len: Length of the serialised payload when the caller has it
            (``len(data)`` after ``json.dumps``). Omitted from the summary when
            ``None`` and ``obj`` is not a string or bytes.
        max_keys: Maximum number of key names to list; the rest are counted.

    Returns:
        ``"keys=[a, b] bytes=N"`` for a mapping (sorted keys, ``+K more`` past
        the cap), ``"bytes=N"`` otherwise.
    """
    if encoded_len is None and isinstance(obj, str | bytes):
        encoded_len = len(obj)
    size = f"bytes={encoded_len}" if encoded_len is not None else "bytes=?"
    if isinstance(obj, dict):
        names = sorted(sanitize_client_name(str(k), max_len=_KEY_MAX_LEN) for k in obj)
        shown = names[:max_keys]
        listing = ", ".join(shown)
        if len(names) > max_keys:
            listing += f", +{len(names) - max_keys} more"
        return f"keys=[{listing}] {size}"
    return size
