"""Size limits and (from 3.16) the envelope codec for property-list items.

Pure: nothing here imports ``actingweb.db`` or ``actingweb.property_list``,
so ``actingweb.config`` can read the defaults without pulling in a backend.

A property-list item is stored as one row. On a backend whose rows have a
size cap (DynamoDB: 400 KB including attribute names) an item larger than
the **span threshold** is refused today with ``ListItemTooLargeError``;
an item larger than the **item ceiling** is refused on every backend that
sets one. See ``Config.list_item_span_threshold`` and
``Config.list_item_max_bytes``.
"""

from typing import Any

# The largest encoded item, in bytes, that is stored as one row on a backend
# with a row cap. DynamoDB counts attribute names plus values against
# 409,600 bytes; the actor id, the row name (``list:`` + list name + ``-#`` +
# a rank of up to 180 characters) and the three attribute names leave more
# than 19 KB of headroom at 390,000 for any list name under about 19,000
# characters. This is also the upper bound a configured threshold may take.
SPAN_THRESHOLD_DEFAULT = 390_000

# The largest piece of an encoded item written to one body row (Phase 2).
SPAN_PART_BYTES = 390_000

# The default ceiling on one item's encoded size where a row cap exists:
# 4 MiB. Derived from what the library itself does per item (about 11 body
# rows to write, about 1,056 strongly consistent read units over 6 Query
# pages to resolve on DynamoDB, roughly four copies of the value in memory
# while a request handles it), never from a platform's payload limit.
ITEM_MAX_BYTES_DEFAULT = 4 * 2**20


def encoded_size(value_str: str) -> int:
    """The size, in bytes, that ``value_str`` occupies in storage.

    Items are encoded with ``json.dumps`` and its default
    ``ensure_ascii=True``, so the value is ASCII and this equals
    ``len(value_str)``; non-ASCII text costs up to six bytes per character
    (``\\uXXXX``). The ``str(item)`` fallback for a value ``json`` cannot
    encode may hold non-ASCII text, which is why this measures UTF-8 bytes
    rather than characters.
    """
    return len(value_str.encode("utf-8", "surrogatepass"))


def default_limits(max_row_bytes: Any) -> tuple[int | None, int | None]:
    """The ``(span_threshold, max_bytes)`` defaults for a backend whose
    ``DbProperty.MAX_ROW_BYTES`` is ``max_row_bytes``.

    An ``int`` (a backend with a row cap) gives ``(390_000, 4 MiB)``;
    anything else, including ``None`` and an absent attribute, gives
    ``(None, None)``: never span, no ceiling.
    """
    if isinstance(max_row_bytes, int) and not isinstance(max_row_bytes, bool):
        return SPAN_THRESHOLD_DEFAULT, ITEM_MAX_BYTES_DEFAULT
    return None, None


def validate_span_threshold(value: Any) -> int | None:
    """Return ``value`` if it is a valid span threshold, else raise.

    ``None`` turns spanning off. Otherwise an ``int`` with
    ``0 < value <= 390_000`` (a ``bool`` is refused).
    """
    if value is None:
        return None
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 0 < value <= SPAN_THRESHOLD_DEFAULT
    ):
        raise ValueError(
            f"list_item_span_threshold must be None or an integer from 1 to "
            f"{SPAN_THRESHOLD_DEFAULT}, got {value!r}"
        )
    return value


def validate_max_bytes(value: Any) -> int | None:
    """Return ``value`` if it is a valid item ceiling, else raise.

    ``None`` removes the ceiling. Otherwise a positive ``int`` (a ``bool``
    is refused).
    """
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(
            f"list_item_max_bytes must be None or a positive integer, got {value!r}"
        )
    return value


def validate_limit_pair(span_threshold: int | None, max_bytes: int | None) -> None:
    """Raise unless ``max_bytes >= span_threshold`` when both are set."""
    if span_threshold is not None and max_bytes is not None:
        if max_bytes < span_threshold:
            raise ValueError(
                f"list_item_max_bytes ({max_bytes}) must be at least "
                f"list_item_span_threshold ({span_threshold})"
            )
