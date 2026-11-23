"""Classify a store fault: retry it, leave it, or report a conflict.

A ``DbError`` (``actingweb.db.exceptions``) means the database backend could
not answer. The integrations answer one that reaches them over HTTP; code
that must build its own answer (a webhook, a WebSocket handler, a background
job) asks :func:`classify_fault` what kind of fault it holds::

    from actingweb.faults import FaultClass, classify_fault

    try:
        actor.properties.notes = text
    except Exception as e:
        fault = classify_fault(e)
        if fault is None:
            raise
        if fault.kind is FaultClass.RETRYABLE:
            return retry_later(fault.retry_after)
        ...

The exception's own text can name an actor id: log it, never send it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from actingweb.db.exceptions import (
    AttributeKeyCollision,
    CreatorTaken,
    DbError,
    DbErrorAfterWrite,
    DeletionInProgress,
)

# ``is_permanent``, ``find_db_error`` and ``DEFAULT_RETRY_AFTER`` are the
# library's own (the HTTP mapping and the resync loop use them); the public
# names are the three below.
__all__ = ["Fault", "FaultClass", "classify_fault"]

DEFAULT_RETRY_AFTER = 5
"""Seconds to wait before retrying a transient fault."""


class FaultClass(StrEnum):
    """What a caller can do about a store fault."""

    RETRYABLE = "retryable"
    """The backend could not answer (a throttle, a timeout, a lost
    connection), or another request is finishing the actor's deletion. A
    plain ``DbError`` means nothing was written, or that the caller cannot
    tell: retry after ``retry_after`` seconds."""

    STORED = "stored"
    """The change is stored and a step after it failed
    (``DbErrorAfterWrite``). Repeating a plain set is safe; repeating an
    unkeyed append adds a second item."""

    PERMANENT = "permanent"
    """A retry meets the same answer: the request itself is the problem (an
    item over the backend's size limit, a constraint the data violates, an
    attribute key another bucket holds)."""

    CONFLICT = "conflict"
    """The creator address is held by another actor (``CreatorTaken``)."""


@dataclass(frozen=True)
class Fault:
    """A classified store fault."""

    kind: FaultClass
    retry_after: int | None
    """Seconds to wait before a retry; ``None`` when a retry is not advised."""
    error: DbError
    """The fault itself, found on the ``__cause__`` chain. For the log only."""


# Backend errors that a retry cannot fix: the request itself is the problem
# (an item over DynamoDB's 400 KB limit, a value too long for an index, a
# constraint the data violates).
_PERMANENT_DYNAMODB_CODES = frozenset(
    {
        "ValidationException",
        "SerializationException",
        "ItemCollectionSizeLimitExceededException",
    }
)
_PERMANENT_PG_CLASSES = frozenset(
    {"DataError", "IntegrityError", "ProgrammingError", "NotSupportedError"}
)


def is_permanent(exc: BaseException) -> bool:
    """Whether the backend error behind this ``DbError`` is not transient.

    Walks the ``__cause__`` chain only (the backend exception is chained
    with ``raise DbError(op) from e``); an exception reached only through
    ``__context__`` does not decide it.
    """
    current: BaseException | None = exc.__cause__
    depth = 0
    while current is not None and depth < 5:
        code = getattr(current, "cause_response_code", None)
        if code in _PERMANENT_DYNAMODB_CODES:
            return True
        for klass in type(current).__mro__:
            if klass.__name__ in _PERMANENT_PG_CLASSES and klass.__module__.startswith(
                "psycopg"
            ):
                return True
        current = current.__cause__
        depth += 1
    return False


def find_db_error(exc: BaseException) -> DbError | None:
    """The ``DbError`` this exception is, or was raised from.

    An exception that wraps a fault with ``raise ... from e`` is still a
    fault: the ``__cause__`` chain is followed a few links deep.
    ``__context__`` is not: an unrelated error raised while a ``DbError``
    was being handled is a bug.
    """
    seen = 0
    current: BaseException | None = exc
    while current is not None and seen < 5:
        if isinstance(current, DbError):
            return current
        current = current.__cause__
        seen += 1
    return None


def classify_fault(exc: BaseException) -> Fault | None:
    """The class of the store fault ``exc`` is or was raised from.

    Returns ``None`` when ``exc`` is not a store fault, so the caller's own
    handling runs. The integrations derive their HTTP answers from the same
    classification.

    A fault wrapped with ``raise ... from e`` is found up to five links down
    the ``__cause__`` chain, as the integrations find it; deeper than that,
    or reached only through ``__context__``, it is not a fault here.
    """
    fault = find_db_error(exc)
    if fault is None:
        return None
    # The subclasses first: each is a DbError with its own meaning.
    if isinstance(fault, CreatorTaken):
        return Fault(FaultClass.CONFLICT, None, fault)
    if isinstance(fault, DeletionInProgress):
        # A wait, not an outage: retry after the lease's remainder.
        return Fault(FaultClass.RETRYABLE, fault.retry_after, fault)
    if isinstance(fault, DbErrorAfterWrite):
        return Fault(FaultClass.STORED, None, fault)
    if isinstance(fault, AttributeKeyCollision) or is_permanent(fault):
        return Fault(FaultClass.PERMANENT, None, fault)
    return Fault(FaultClass.RETRYABLE, DEFAULT_RETRY_AFTER, fault)
