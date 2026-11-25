"""Exceptions shared across database backends."""

from collections.abc import Iterator
from contextlib import contextmanager


class DbError(Exception):
    """A database backend operation failed unexpectedly.

    Distinct from a backend returning ``None`` (property absence) or
    ``False`` (a reported write failure): this means the backend itself
    faulted (timeout, throttle, connection error, ...). The message is
    sanitized (no backend-internal detail) but can name an actor id, so the
    integrations answer with a fixed body and never ``str(e)``; the original
    exception is chained via ``raise ... from e`` for logs.
    """

    def __init__(self, op: str, actor_id: str | None = None) -> None:
        actor_part = f" for actor {actor_id}" if actor_id else ""
        super().__init__(f"database error during {op}{actor_part}")


class DbErrorAfterWrite(DbError):
    """A property or list write was stored, and the fault came after it,
    registering its diff for subscribers (4.0).

    The value is stored; the diff is not registered, so a subscriber's copy
    stays stale until the next diff or a resync. A repeat of a plain set is
    safe (it writes the same value and registers the diff); a repeat of an
    unkeyed append adds a second item, while ``append_once`` does not. A
    plain ``DbError`` means nothing was written, or that the caller cannot
    tell. Over HTTP it answers 503 with the code ``stored_not_notified``
    and no ``Retry-After``.
    """


@contextmanager
def after_write(op: str, actor_id: str | None = None) -> Iterator[None]:
    """Raise a ``DbError`` from the block as :class:`DbErrorAfterWrite`:
    wraps the diff registration that follows a stored write."""
    try:
        yield
    except DbErrorAfterWrite:
        raise
    except DbError as e:
        raise DbErrorAfterWrite(op, actor_id) from e


class CreatorTaken(DbError):
    """A create or creator change was refused because another actor holds
    the creator.

    Raised by the actor backends under ``with_unique_creator()`` (and by
    PostgreSQL whenever its unique index exists, flag or not). It
    subclasses ``DbError`` so code that fails closed on a fault also stops
    here, but it is a conflict, not an availability fault: the HTTP layer
    answers it with 409 (the factory keeps its 403), never 503. Test for it
    before ``DbError``.
    """

    def __init__(self, creator: str | None = None) -> None:
        Exception.__init__(self, "creator is held by another actor")
        self.creator = creator


class DeletionInProgress(DbError):
    """Another request is finishing this actor's deletion right now.

    Raised when a sign-in, a repeated ``DELETE /<id>`` or the operator
    command meets an actor whose deletion tombstone is held by a live lease
    (another finisher is running the wipe). It subclasses ``DbError`` so code
    that fails closed on a fault also stops here, and the HTTP layer answers
    it with 503, but with ``Retry-After`` set to ``retry_after`` (the lease's
    remainder in whole seconds, at least 1) rather than the fixed fault
    value, and it is logged at INFO: it is a wait, not a fault. Test for it
    before ``DbError``.
    """

    def __init__(self, actor_id: str | None = None, retry_after: int = 1) -> None:
        Exception.__init__(
            self,
            f"deletion of actor {actor_id} is in progress"
            if actor_id
            else "an actor deletion is in progress",
        )
        self.actor_id = actor_id
        self.retry_after = max(1, int(retry_after))


class AttributeKeyCollision(DbError):
    """An attribute write met a row another bucket owns under the same
    composite key.

    Both backends key an attribute as ``bucket + ":" + name``, so bucket
    ``a`` name ``b:c`` and bucket ``a:b`` name ``c`` share a key, and a peer
    id may contain ``:``. A write never replaces the other bucket's row; it
    raises this instead. It subclasses ``DbError`` so fail-closed code stops
    here too, but it is not an availability fault: retrying meets the same
    row. The replica path treats it as a refused key, not a 503."""

    def __init__(self, bucket: str, name: str, actor_id: str | None = None) -> None:
        Exception.__init__(
            self,
            f"attribute key {bucket!r}/{name!r} is held by another bucket"
            + (f" for actor {actor_id}" if actor_id else ""),
        )
        self.bucket = bucket
        self.name = name
        self.actor_id = actor_id


class UnserialisableValue(ValueError, TypeError):
    """A value the store cannot encode as JSON (a ``datetime``, a ``set``, an
    object, or a non-finite number: ``NaN`` and ``Infinity`` are not JSON),
    refused before any store call: nothing was written.

    Not a ``DbError``: that answers 503 with ``Retry-After``, and a retry of
    this write can never succeed. A ``ValueError`` (a caller's bad input),
    and a ``TypeError`` too, which is what ``json`` raised before 4.0 caught
    it here.
    """

    def __init__(self, what: str, cause: BaseException) -> None:
        self.what = what
        super().__init__(f"{what} cannot be stored: not JSON-encodable ({cause})")


def require_json(value: object, what: str) -> None:
    """Raise :class:`UnserialisableValue` when ``json`` cannot encode
    ``value`` as standard JSON (a non-finite number included); called before
    a write reaches the store."""
    import json

    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as e:
        raise UnserialisableValue(what, e) from e
