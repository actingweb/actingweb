"""Map database faults to HTTP answers, the same way in both integrations.

A ``DbError`` means the backend could not answer (a throttle, a timeout, a
lost connection). The request is answered **503** with ``Retry-After: 5`` and
a fixed body, so a client retries instead of acting on a guess. A backend
error a retry cannot fix (a validation, size or constraint error) answers
**500** without ``Retry-After``. The exception's text goes to the log only:
it can name an actor id.

``CreatorTaken`` subclasses ``DbError`` but is a conflict, not an outage. It
is tested first and answered **409**.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from actingweb.constants import ERROR_CODE_HEADER
from actingweb.db.exceptions import CreatorTaken, DbError

logger = logging.getLogger(__name__)

RETRY_AFTER_SECONDS = "5"

UNAVAILABLE_BODY: dict[str, str] = {
    "error": "temporarily_unavailable",
    "message": "Service temporarily unavailable",
}

CONFLICT_BODY: dict[str, str] = {
    "error": "conflict",
    "message": "Creator already exists",
}

INTERNAL_BODY: dict[str, str] = {
    "error": "internal_error",
    "message": "The request could not be stored",
}

# Backend errors that a retry cannot fix: the request itself is the problem
# (an item over DynamoDB's 400 KB limit, a value too long for an index, a
# constraint the data violates). They answer 500 without Retry-After.
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

    Walks the ``__cause__`` chain (the backend exception is chained with
    ``raise DbError(op) from e``).
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
        current = current.__cause__ or current.__context__
        depth += 1
    return False


def db_error_answer(exc: BaseException) -> tuple[int, dict[str, str], dict[str, str]]:
    """The status, headers and JSON body for a ``DbError``.

    Raises ``TypeError`` for anything else, so a caller cannot map an
    unrelated exception by accident.
    """
    if isinstance(exc, CreatorTaken):
        return 409, {ERROR_CODE_HEADER: CONFLICT_BODY["error"]}, dict(CONFLICT_BODY)
    if isinstance(exc, DbError):
        if is_permanent(exc):
            return (
                500,
                {ERROR_CODE_HEADER: INTERNAL_BODY["error"]},
                dict(INTERNAL_BODY),
            )
        return (
            503,
            {
                "Retry-After": RETRY_AFTER_SECONDS,
                ERROR_CODE_HEADER: UNAVAILABLE_BODY["error"],
            },
            dict(UNAVAILABLE_BODY),
        )
    raise TypeError(f"not a DbError: {type(exc).__name__}")


def find_db_error(exc: BaseException) -> DbError | None:
    """The ``DbError`` this exception is, or was raised from.

    A handler that wraps a fault in its own exception still answers 503:
    the ``__cause__``/``__context__`` chain is followed a few links deep.
    """
    seen = 0
    current: BaseException | None = exc
    while current is not None and seen < 5:
        if isinstance(current, DbError):
            return current
        current = current.__cause__ or current.__context__
        seen += 1
    return None


def reason_phrase(status: int) -> str:
    """The HTTP reason phrase for a status ``db_error_answer`` gives."""
    return {409: "Conflict", 500: "Internal Server Error"}.get(
        status, "Service Unavailable"
    )


def map_db_error(
    response: Any, exc: BaseException, cors: dict[str, str] | None = None
) -> bool:
    """Answer an ActingWeb response object for a ``DbError``.

    Sets the status, ``Retry-After`` (503 only), the fixed JSON body and the
    ``cors`` headers (from ``error_cors_headers`` for the request's route) on
    ``response`` (an ``aw_web_request`` response), drops any redirect and
    cookies the handler queued, and returns True. Returns
    False, touching nothing, when ``exc`` is not a database fault, so the
    caller's own mapping runs.
    """
    fault = find_db_error(exc)
    if fault is None:
        return False
    status, headers, body = db_error_answer(fault)
    log_db_error(fault)
    response.set_status(status, reason_phrase(status))
    # Whatever the handler queued before the fault does not go out with it:
    # a redirect would replace the fault answer with a 302, and a cookie set
    # before a later write faulted (a session) would sign the client in. A
    # cookie that expires one (a logout) still goes: dropping it would keep
    # a session the handler meant to end.
    if hasattr(response, "redirect"):
        response.redirect = None
    if hasattr(response, "cookies"):
        response.cookies = [
            c
            for c in response.cookies
            if isinstance(c.get("max_age"), int) and c["max_age"] <= 0
        ]
    for key, value in {**headers, **(cors or {})}.items():
        response.headers[key] = value
    response.headers["Content-Type"] = "application/json"
    response.body = json.dumps(body)
    return True


# Routes the SPA calls cross-origin with credentials: their normal answers
# carry ``spa_cors_headers`` (the origin allowlist), and so must a 503.
_SPA_ROUTES = frozenset(
    {
        "/oauth/logout",
        "/oauth/session",
        "/oauth/revoke",
        "/oauth/config",
        "/oauth/email",
    }
)

# The OAuth2 server endpoints answer with wildcard CORS headers.
_WILDCARD_CORS: dict[str, str] = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type, mcp-protocol-version",
}


def is_spa_path(path: str) -> bool:
    """Whether a request path is one the SPA calls cross-origin."""
    return path.startswith("/oauth/spa/") or path in _SPA_ROUTES


def error_cors_headers(path: str, origin: str, config: Any) -> dict[str, str]:
    """The CORS headers a database-fault answer on ``path`` must carry, so a
    cross-origin browser client can read the 503 instead of seeing a network
    error: the SPA allowlist on the SPA routes, the wildcard set on the other
    OAuth2 endpoints, a wildcard set without credentials on ``/``, none
    elsewhere."""
    if path == "/":
        # Any page may read the fault, but without credentials: the body is
        # fixed and needs none, and RootFactoryHandler's own reflection of
        # the origin with credentials is not a pattern to copy.
        return {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Authorization, Content-Type, Accept",
            "Access-Control-Expose-Headers": f"Retry-After, {ERROR_CODE_HEADER}",
        }
    if is_spa_path(path):
        from ...handlers.oauth2_spa import spa_cors_headers

        return spa_cors_headers(config, origin)
    if path.startswith("/oauth/"):
        return {
            **_WILDCARD_CORS,
            "Access-Control-Expose-Headers": f"Retry-After, {ERROR_CODE_HEADER}",
        }
    return {}


def log_db_error(exc: DbError) -> None:
    """One log line per mapped fault, with the chained backend cause."""
    if isinstance(exc, CreatorTaken):
        logger.info(f"Request refused: {exc}")
        return
    cause = exc.__cause__
    detail = f"{type(cause).__name__}: {cause}" if cause else "no cause"
    status = 500 if is_permanent(exc) else 503
    logger.error(f"Database fault answered {status}: {exc} ({detail})")
