"""Exceptions shared across database backends."""


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
