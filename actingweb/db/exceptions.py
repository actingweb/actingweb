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
