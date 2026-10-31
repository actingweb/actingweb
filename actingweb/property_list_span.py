"""Size limits and the envelope codec for property-list items.

Pure: nothing here imports ``actingweb.db`` or ``actingweb.property_list``,
so ``actingweb.config`` can read the defaults without pulling in a backend,
and the codec is list-agnostic (row-name prefixes are arguments).

**The envelope.** A v2 list item's raw stored value is either the item's
JSON (every row written before 3.16, and every item at or under the span
threshold) or an *envelope*: a JSON object whose **first** key is
``"__aw_env": 1``, with optional ``key`` and ``tok`` (the keyed-append hash
and writer token), ``span`` (``{"gen", "parts", "bytes"}``: the item's
encoded value lives in body rows) and ``v`` (the item, absent when ``span``
is present). Fields this version does not know are kept in
``Envelope.extra`` and carried across a rewrite.

**The side partition.** Body rows (and, from the keyed append, key rows)
live under the partition key ``aux_partition(actor_id)`` =
``f"{actor_id}$aux"``, named ``list:{name}-$span-{gen}-p{part:04d}`` and
``list:{name}-$key-{hash}``. Every per-actor read the library makes is
scoped to the actor's own partition, so no dump or range read of it ever
returns a body byte.
"""

import hashlib
import json
import re
import secrets
import time
from dataclasses import dataclass, field
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
    """Raise unless ``span_threshold <= max_bytes <= span_threshold * 9999``
    when both are set: an item at the ceiling must fit in the 9,999 body
    rows a span can name (each at most the threshold)."""
    if span_threshold is not None and max_bytes is not None:
        if max_bytes < span_threshold:
            raise ValueError(
                f"list_item_max_bytes ({max_bytes}) must be at least "
                f"list_item_span_threshold ({span_threshold})"
            )
        if max_bytes > span_threshold * MAX_PARTS:
            raise ValueError(
                f"list_item_max_bytes ({max_bytes}) is more than {MAX_PARTS} "
                f"body rows of list_item_span_threshold ({span_threshold}); "
                f"raise the threshold or lower the ceiling"
            )


# --- The envelope ---------------------------------------------------------

ENVELOPE_MARKER = "__aw_env"
# What every envelope's raw value starts with: json.dumps() of a dict whose
# first key is the marker. parse() and the encode refusal pin the same rule.
_ENVELOPE_PREFIX = '{"' + ENVELOPE_MARKER + '"'

# The side partition and its row shapes.
AUX_SUFFIX = "$aux"
GEN_RE = re.compile(r"^\d{13}-[0-9a-f]{16}\Z")
SPAN_ROW_RE = re.compile(r"^\d{13}-[0-9a-f]{16}-p\d{4}\Z")
KEY_ROW_RE = re.compile(r"^[0-9a-f]{64}\Z")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}\Z")


def value_digest(value_str: str) -> str:
    """The SHA-256 (hex) a span records for its joined body value."""
    return hashlib.sha256(value_str.encode("utf-8", "surrogatepass")).hexdigest()


MAX_PARTS = 9999

# The fields parse() understands; anything else rides in Envelope.extra.
_KNOWN_FIELDS = frozenset({ENVELOPE_MARKER, "key", "tok", "span", "v"})


class EnvelopeError(ValueError):
    """A stored value starts like an envelope but is not a valid one.
    ``property_list`` maps it to ``ListItemSpanError`` before any read."""


@dataclass(frozen=True)
class SpanInfo:
    """Where a spanned item's encoded value lives: ``parts`` body rows of
    generation ``gen``, ``bytes`` bytes in all, whose SHA-256 is ``sha256``
    (hex; ``None`` on an envelope written without one)."""

    gen: str
    parts: int
    bytes: int
    sha256: str | None = None


_NO_VALUE: Any = object()


@dataclass(frozen=True)
class Envelope:
    """A parsed envelope. ``value`` is the item itself (``_NO_VALUE`` when
    the item spans: read it through ``span``)."""

    key: str | None = None
    tok: str | None = None
    span: SpanInfo | None = None
    value: Any = _NO_VALUE
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def has_value(self) -> bool:
        return self.value is not _NO_VALUE


def looks_like_envelope(raw: Any) -> bool:
    """True if ``raw`` begins the way every envelope does. A plain item can
    only begin this way if it predates 3.16 (encoding refuses it since)."""
    return isinstance(raw, str) and raw.startswith(_ENVELOPE_PREFIX)


def _envelope_obj(raw: Any) -> dict[str, Any] | None:
    """Decode ``raw`` once and classify it.

    ``None``: a plain item. That is anything not starting with the marker,
    and a valid JSON object whose marker value is not an int (a pre-3.16
    user item such as ``{"__aw_env": "x", ...}``, which reads as itself).
    A dict: an envelope with the marker ``1``, to validate further.

    Raises:
        EnvelopeError: The value starts with the marker but is not valid
            JSON (a damaged library envelope), or its marker is an int other
            than ``1`` (an envelope of a format this version does not read).
            Either is reported as malformed rather than served as an item.
    """
    if not looks_like_envelope(raw):
        return None
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        raise EnvelopeError(f"envelope is not valid JSON: {e.msg}") from None
    if not isinstance(obj, dict) or not obj or next(iter(obj)) != ENVELOPE_MARKER:
        return None
    marker = obj[ENVELOPE_MARKER]
    if not isinstance(marker, int) or isinstance(marker, bool):
        return None
    if marker != 1:
        raise EnvelopeError(f"envelope format {marker} is not one this version reads")
    return obj


def carries_library_marker(raw: Any) -> bool:
    """True if ``raw`` is a valid JSON object whose first key is the
    envelope marker with exactly the value ``1``: something this library
    wrote as an envelope (even if a later field is now damaged), and so
    safe for the span sweep to remove when it is malformed. A damaged or
    other-format envelope is reported but never removed."""
    try:
        return _envelope_obj(raw) is not None
    except EnvelopeError:
        return False


# A body generation named anywhere in a raw head, for heads that do not
# parse: their bodies are kept by the orphan sweep so a repair can recover
# them.
GEN_IN_RAW_RE = re.compile(r'"gen"\s*:\s*"(\d{13}-[0-9a-f]{16})"')


def parse(raw: Any) -> Envelope | None:
    """Parse a raw stored value. ``None`` means a plain item (decode it as
    JSON); an ``Envelope`` means read the item through it.

    See ``_envelope_obj`` for what is plain: a pre-3.16 user item that
    merely starts like an envelope (a non-int marker) reads as that item.

    Raises:
        EnvelopeError: ``raw`` starts like an envelope but is damaged
            (invalid JSON), of another format (an int marker other than
            ``1``), or malformed: ``span`` with ``parts`` not an int from 1
            to 9999, ``gen`` not of the gen shape, ``bytes`` not a
            non-negative int or ``sha256`` not 64 hex characters,
            ``key``/``tok`` not strings, or neither ``v`` nor ``span``.
    """
    obj = _envelope_obj(raw)
    if obj is None:
        return None
    key = obj.get("key")
    tok = obj.get("tok")
    if key is not None and not isinstance(key, str):
        raise EnvelopeError("envelope key is not a string")
    if tok is not None and not isinstance(tok, str):
        raise EnvelopeError("envelope tok is not a string")
    span: SpanInfo | None = None
    if "span" in obj:
        raw_span = obj["span"]
        if not isinstance(raw_span, dict):
            raise EnvelopeError("envelope span is not an object")
        gen = raw_span.get("gen")
        parts = raw_span.get("parts")
        size = raw_span.get("bytes")
        if not isinstance(gen, str) or not GEN_RE.match(gen):
            raise EnvelopeError("envelope span gen has the wrong shape")
        if (
            not isinstance(parts, int)
            or isinstance(parts, bool)
            or not 1 <= parts <= MAX_PARTS
        ):
            raise EnvelopeError("envelope span parts is not an int from 1 to 9999")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise EnvelopeError("envelope span bytes is not a non-negative int")
        digest = raw_span.get("sha256")
        if digest is not None and (
            not isinstance(digest, str) or not _SHA256_RE.match(digest)
        ):
            raise EnvelopeError("envelope span sha256 is not 64 hex characters")
        span = SpanInfo(gen=gen, parts=parts, bytes=size, sha256=digest)
    if span is None and "v" not in obj:
        raise EnvelopeError("envelope carries neither v nor span")
    extra = {k: v for k, v in obj.items() if k not in _KNOWN_FIELDS}
    return Envelope(
        key=key,
        tok=tok,
        span=span,
        value=obj["v"] if ("v" in obj and span is None) else _NO_VALUE,
        extra=extra,
    )


def wrap(
    *,
    value: Any = _NO_VALUE,
    key: str | None = None,
    tok: str | None = None,
    span: SpanInfo | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    """Encode an envelope, marker first. Exactly one of ``value`` and
    ``span`` is given."""
    if (value is _NO_VALUE) == (span is None):
        raise ValueError("an envelope carries exactly one of value and span")
    obj: dict[str, Any] = {ENVELOPE_MARKER: 1}
    for k, v in (extra or {}).items():
        if k not in _KNOWN_FIELDS:
            obj[k] = v
    if key is not None:
        obj["key"] = key
    if tok is not None:
        obj["tok"] = tok
    if span is not None:
        obj["span"] = {"gen": span.gen, "parts": span.parts, "bytes": span.bytes}
        if span.sha256 is not None:
            obj["span"]["sha256"] = span.sha256
    else:
        obj["v"] = value
    return json.dumps(obj)


def _sanitize(text: str) -> str:
    """Replace lone surrogates the way the backends do before storing
    (``actingweb.db.utils.sanitize_json_data``), so a value is measured and
    split as it will be stored."""
    try:
        text.encode("utf-8", errors="strict")
        return text
    except UnicodeEncodeError:
        return text.encode("utf-8", errors="replace").decode("utf-8", errors="replace")


def encode_item(item: Any) -> str:
    """Encode a list item for storage: ``json.dumps(item)``, or ``str(item)``
    (sanitised) for a value JSON cannot encode.

    Raises:
        ValueError: The item is a dict carrying the reserved key
            ``__aw_env``, or its encoding starts the way an envelope does
            (the ``str(item)`` fallback can produce that). Raised before any
            write, the way ``#`` is refused in list names.
    """
    if isinstance(item, dict) and ENVELOPE_MARKER in item:
        raise ValueError(
            f"List items may not carry the reserved key '{ENVELOPE_MARKER}' "
            f"(it marks the library's own storage envelope)"
        )
    try:
        encoded = json.dumps(item)
    except (TypeError, ValueError):
        encoded = _sanitize(str(item))
    if looks_like_envelope(encoded):
        raise ValueError(
            f"List item encodes to a value starting with the reserved "
            f"envelope marker '{ENVELOPE_MARKER}'"
        )
    return encoded


def split_parts(value_str: str, part_bytes: int) -> list[str]:
    """Split ``value_str`` into non-empty parts of at most ``part_bytes``
    UTF-8 bytes each, on character boundaries. ``"".join()`` of the result
    is ``value_str``.

    Raises:
        ValueError: ``part_bytes`` is below 4 (a character could not fit),
            the split would produce an empty part, or more than 9999 parts.
    """
    if part_bytes < 4:
        raise ValueError("part_bytes must be at least 4")
    if not value_str:
        raise ValueError("cannot split an empty value")
    parts: list[str] = []
    if value_str.isascii():
        parts = [
            value_str[i : i + part_bytes] for i in range(0, len(value_str), part_bytes)
        ]
    else:
        start = 0
        size = 0
        for i, ch in enumerate(value_str):
            ch_bytes = len(ch.encode("utf-8", "surrogatepass"))
            if size + ch_bytes > part_bytes:
                parts.append(value_str[start:i])
                start = i
                size = 0
            size += ch_bytes
        parts.append(value_str[start:])
    if any(not part for part in parts):
        raise ValueError("split produced an empty part")
    if len(parts) > MAX_PARTS:
        raise ValueError(f"an item may span at most {MAX_PARTS} parts")
    return parts


def new_gen() -> str:
    """A fresh body generation: ``{unix_ms:013d}-{16 hex}``. The timestamp
    lets the orphan sweep age a generation without reading it."""
    return f"{int(time.time() * 1000):013d}-{secrets.token_hex(8)}"


def gen_age_seconds(gen: str, now: float | None = None) -> float:
    """Seconds since ``gen`` was minted (from its timestamp)."""
    minted_ms = int(gen[:13])
    current = time.time() if now is None else now
    return current - minted_ms / 1000.0


def span_prefix(list_name: str, gen: str | None = None) -> str:
    """Row-name prefix of a list's body rows, or of one generation's."""
    base = f"list:{list_name}-$span-"
    return base if gen is None else f"{base}{gen}-"


def part_names(list_name: str, gen: str, parts: int) -> list[str]:
    """The body row names of one generation, in order."""
    prefix = span_prefix(list_name, gen)
    return [f"{prefix}p{i:04d}" for i in range(parts)]


def key_prefix(list_name: str) -> str:
    """Row-name prefix of a list's key rows."""
    return f"list:{list_name}-$key-"


def key_row_name(list_name: str, key_hash: str) -> str:
    return f"{key_prefix(list_name)}{key_hash}"


def aux_partition(actor_id: str) -> str:
    """The side partition key for ``actor_id``'s body and key rows.

    Raises:
        ValueError: ``actor_id`` contains ``$``, which would make two
            actors' side partitions indistinguishable from an actor id.
    """
    if "$" in actor_id:
        raise ValueError(
            f"Actor id {actor_id!r} contains '$', which is reserved for the "
            f"property-list side partition"
        )
    return actor_id + AUX_SUFFIX
