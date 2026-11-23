"""Map database faults to HTTP answers, the same way in both integrations.

A ``DbError`` means the backend could not answer (a throttle, a timeout, a
lost connection). The request is answered **503** with ``Retry-After: 5`` and
a fixed body, so a client retries instead of acting on a guess. A backend
error a retry cannot fix (a validation, size or constraint error) answers
**500** without ``Retry-After``. The exception's text goes to the log only:
it can name an actor id.

``CreatorTaken`` subclasses ``DbError`` but is a conflict, not an outage. It
is tested first and answered **409**.

The classification itself is public (``actingweb.faults``); this module maps
it to HTTP and stays private. ``is_permanent`` and ``find_db_error`` are
re-exported from there.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from actingweb.constants import ERROR_CODE_HEADER
from actingweb.db.exceptions import (
    CreatorTaken,
    DbError,
    DeletionInProgress,
)
from actingweb.faults import (
    DEFAULT_RETRY_AFTER,
    FaultClass,
    classify_fault,
    find_db_error,
    is_permanent,
)

# Re-exported: the integrations, ``actor.py`` and tests import them from here.
__all__ = ["db_error_answer", "find_db_error", "is_permanent", "map_db_error"]

logger = logging.getLogger(__name__)

RETRY_AFTER_SECONDS = str(DEFAULT_RETRY_AFTER)

UNAVAILABLE_BODY: dict[str, str] = {
    "error": "temporarily_unavailable",
    "message": "Service temporarily unavailable",
}

CONFLICT_BODY: dict[str, str] = {
    "error": "conflict",
    "message": "Creator already exists",
}

STORED_NOT_NOTIFIED_BODY: dict[str, str] = {
    "error": "stored_not_notified",
    "message": "The change was stored; its subscribers were not notified",
}

NEWER_FORMAT_BODY: dict[str, str] = {
    "error": "list_item_newer_format",
    "message": "This list holds data a later library version stored",
}


def newer_format_answer() -> tuple[int, dict[str, str], dict[str, str]]:
    """The fixed 409 for ``ListItemNewerFormatError``: no stored text, no
    list or rank name (the detail goes to the log)."""
    return (
        409,
        {ERROR_CODE_HEADER: NEWER_FORMAT_BODY["error"]},
        {**NEWER_FORMAT_BODY, "code": NEWER_FORMAT_BODY["error"]},
    )


def find_newer_format(exc: BaseException) -> BaseException | None:
    """The ``ListItemNewerFormatError`` this is or was raised from."""
    from actingweb.list_core import ListItemNewerFormatError

    current: BaseException | None = exc
    for _ in range(4):
        if current is None:
            return None
        if isinstance(current, ListItemNewerFormatError):
            return current
        current = current.__cause__
    return None


INTERNAL_BODY: dict[str, str] = {
    "error": "internal_error",
    "message": "The request could not be stored",
}


def db_error_answer(exc: BaseException) -> tuple[int, dict[str, str], dict[str, str]]:
    """The status, headers and JSON body for a ``DbError``.

    Derived from ``actingweb.faults.classify_fault``, so the HTTP answer and
    the public classification cannot disagree. Raises ``TypeError`` for
    anything else, so a caller cannot map an unrelated exception by accident.
    """
    fault = classify_fault(exc) if isinstance(exc, DbError) else None
    if fault is None:
        raise TypeError(f"not a DbError: {type(exc).__name__}")
    if fault.kind is FaultClass.CONFLICT:
        return (
            409,
            {ERROR_CODE_HEADER: CONFLICT_BODY["error"]},
            {**CONFLICT_BODY, "code": CONFLICT_BODY["error"]},
        )
    if fault.kind is FaultClass.STORED:
        # The change is stored: no Retry-After, which would invite a retry
        # that, for an unkeyed append, adds a second item.
        return (
            503,
            {ERROR_CODE_HEADER: STORED_NOT_NOTIFIED_BODY["error"]},
            {**STORED_NOT_NOTIFIED_BODY, "code": STORED_NOT_NOTIFIED_BODY["error"]},
        )
    if fault.kind is FaultClass.PERMANENT:
        return (
            500,
            {ERROR_CODE_HEADER: INTERNAL_BODY["error"]},
            {**INTERNAL_BODY, "code": INTERNAL_BODY["error"]},
        )
    # Retryable: an outage (Retry-After 5), or a wait for another request
    # that is finishing the actor's deletion (the lease's remainder).
    return (
        503,
        {
            "Retry-After": str(fault.retry_after),
            ERROR_CODE_HEADER: UNAVAILABLE_BODY["error"],
        },
        {**UNAVAILABLE_BODY, "code": UNAVAILABLE_BODY["error"]},
    )


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
    newer = find_newer_format(exc)
    fault = find_db_error(exc) if newer is None else None
    if newer is None and fault is None:
        return False
    if newer is not None:
        logger.warning(f"Refused data a later library version stored: {newer}")
        status, headers, body = newer_format_answer()
    else:
        assert fault is not None
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
    if isinstance(exc, DeletionInProgress):
        logger.info(f"Request deferred (503, Retry-After {exc.retry_after}): {exc}")
        return
    cause = exc.__cause__
    detail = f"{type(cause).__name__}: {cause}" if cause else "no cause"
    status = db_error_answer(exc)[0]
    logger.error(f"Database fault answered {status}: {exc} ({detail})")
