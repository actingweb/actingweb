import asyncio
import base64
import datetime
import json
import logging
import os
import socket
import threading
import time
from collections.abc import Callable
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.util.connection import allowed_gai_family

from actingweb import attribute, deletion, peertrustee, property, subscription, trust
from actingweb.constants import (
    DEFAULT_CREATOR,
)
from actingweb.db import (
    get_actor,
    get_actor_list,
    get_subscription_suspension,
    get_trust,
)
from actingweb.log_summary import summarize_payload
from actingweb.permission_evaluator import (
    GrantSnapshot,
    PermissionType,
    as_json_object,
    drop_excluded,
    exclusion_patterns,
    get_permission_evaluator,
)
from actingweb.property_list import ListCorruptionError
from actingweb.secret_compare import secret_digest_equals, secret_equals

from .db.creator_rules import (
    is_exempt,
    is_refused_from_callers,
    is_reserved,
    normalise_creator,
)
from .db.exceptions import CreatorTaken, DbError

logger = logging.getLogger(__name__)


def _answered_by_approved_row(body: dict[str, Any]) -> bool:
    """Whether a peer's answer for our trust row there is a row it approved.

    A verification asks the requester for our own row with the secret (or
    token) the request carried. A genuine initiator created that row
    approved before it sent the request; a pending row that whoever filed
    the request also filed at the requester's host, under our id, holds the
    same secret and is not approved there. The flag is compared as text: a
    trust POST answer carries it as ``"true"``, a GET as ``true``."""
    return str(body.get("approved")).lower() == "true"


def _has_peer_endpoint(trust_rel: dict[str, Any], actor_id: str | None) -> bool:
    """Whether a trust row's peer has ActingWeb endpoints to push to: not a
    row an OAuth2 flow wrote (``established_via``, or for a row from before
    that field its peer id and a base URI that is none or this actor's own),
    and a base URI to send to."""
    from .oauth2_server.trust_lookup import OAUTH2_SOURCES, legacy_oauth2_row

    via = trust_rel.get("established_via")
    if via in OAUTH2_SOURCES:
        return False
    if not via and legacy_oauth2_row(
        trust_rel.get("peerid"), trust_rel.get("baseuri"), actor_id
    ):
        return False
    return bool(str(trust_rel.get("baseuri") or "").strip())


def _resync_url(config: Any, actor_id: str | None, target: str, subtarget: Any) -> str:
    """The URL a resync points at: the subscription's target (and subtarget)
    on this actor."""
    url = f"{config.proto}{config.fqdn}/{actor_id}/{target}"
    return f"{url}/{subtarget}" if subtarget else url


def resync_marker(url: str) -> dict[str, str]:
    """A client's resync, stored as its next diff (it has no endpoint to
    send a resync callback to): the client re-reads ``url`` under its own
    grant, as on a resync callback. No data is stored."""
    return {"type": "resync", "url": url}


def resync_marker_url(
    raw: Any, config: Any, actor_id: str | None, target: str, subtarget: Any
) -> str | None:
    """The URL to serve for a stored resync marker, or None for any other
    diff. A marker counts only when its path on this actor is the
    subscription's own ``target[/subtarget]`` or lies under it (a resume of
    one subtarget for a whole-target subscription), so data shaped like a
    marker can only make the subscriber re-read part of what it subscribed
    to. The URL is rebuilt from the current config: a marker stored before
    a host change still points here."""
    try:
        parsed = json.loads(raw) if isinstance(raw, str | bytes) else raw
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict) or set(parsed) != {"type", "url"}:
        return None
    url = parsed.get("url")
    if parsed.get("type") != "resync" or not isinstance(url, str) or not actor_id:
        return None
    _, sep, path = url.partition(f"/{actor_id}/")
    if not sep:
        return None
    scope = f"{target}/{subtarget}" if subtarget else target
    if path != scope and not path.startswith(f"{scope}/"):
        return None
    return _resync_url(config, actor_id, path, None)


# A verification's GETs (our trust row there, then its /meta) go to a base
# URI the requester chose. The caller waits at most one deadline for both,
# whatever the peer does (headers, body, a TLS handshake sent slowly); no
# redirect is followed and at most the cap is read. The GETs run on a small
# pool of their own. Each socket a GET opens (to the peer, or to the
# environment's HTTP(S) proxy) is recorded, before its connect, as a
# duplicate descriptor, which the TLS wrap does not detach: when the deadline
# passes, the caller shuts it down, so the worker's blocked read or handshake
# fails at once and the worker is free again. A connect waits at most what is
# left of the deadline, and no further address of the name is tried after it
# (``_connect``). Only a name lookup cannot be cut short; it holds its worker
# for the resolver's own timeout, and no connect follows it once the deadline
# has passed. When every worker is busy, a verification fails closed at once
# instead of queueing. A SOCKS proxy is refused.
_REVERIFY_DEADLINE_SECONDS = 15.0
_REVERIFY_MAX_BYTES = 64 * 1024
_VERIFY_WORKERS = 8
_VERIFY_READ_TIMEOUT: tuple[float, float] = (5, 5)
_verify_pool: Any = None
_verify_pool_lock = threading.Lock()
_verify_slots = threading.BoundedSemaphore(_VERIFY_WORKERS)
# The sockets of the fetch a pool worker is running (set by ``_fetch_json``).
_verify_local = threading.local()


def _verification_pool() -> Any:
    global _verify_pool
    with _verify_pool_lock:
        if _verify_pool is None:
            from concurrent.futures import ThreadPoolExecutor

            _verify_pool = ThreadPoolExecutor(
                max_workers=_VERIFY_WORKERS, thread_name_prefix="aw-verify"
            )
        return _verify_pool


class _FetchSockets:
    """The sockets one verification fetch opened, as duplicate descriptors:
    shutting a duplicate down ends the connection for the TLS layer above
    the original too. ``cancel`` (the caller, at the deadline) shuts them
    down; ``release`` (the worker, when done) only closes the duplicates.
    After either, a socket that arrives is shut down at once."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._dups: list[socket.socket] = []
        self._done = False
        self.session: requests.Session | None = None

    def given_up(self) -> bool:
        return self._done

    def opened(self, sock: socket.socket) -> None:
        try:
            dup = sock.dup()
        except OSError:
            dup = None
        with self._lock:
            if not self._done and dup is not None:
                self._dups.append(dup)
                return
        # The caller has gone (or the socket cannot be tracked): end it now.
        for each in (sock, dup):
            _end_socket(each, shut=True)
        raise ConnectionAbortedError("the verification was given up")

    def cancel(self) -> None:
        self._finish(shut=True)

    def release(self) -> None:
        self._finish(shut=False)
        session, self.session = self.session, None
        if session is not None:
            try:
                session.close()
            except Exception:  # folds DbError: closing a session
                pass

    def _finish(self, shut: bool) -> None:
        with self._lock:
            self._done = True
            dups, self._dups = self._dups, []
        for dup in dups:
            _end_socket(dup, shut=shut)


def _end_socket(sock: socket.socket | None, shut: bool) -> None:
    if sock is None:
        return
    if shut:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
    try:
        sock.close()
    except OSError:
        pass


def _connect(conn: Any) -> socket.socket:
    """urllib3's ``create_connection`` for a verification's connection,
    bounded by the fetch's deadline: each address's socket is recorded
    before its connect, the connect waits at most what is left of the
    deadline, and no further address is tried once the fetch was given up or
    the deadline passed (a name with many unreachable addresses would
    otherwise hold the worker for a connect timeout per address)."""
    tracked: _FetchSockets | None = getattr(_verify_local, "sockets", None)
    deadline: float | None = getattr(_verify_local, "deadline", None)
    host = str(conn._dns_host)
    if host.startswith("["):
        host = host.strip("[]")
    limit = conn.timeout if isinstance(conn.timeout, int | float) else None
    error: OSError | None = None
    # The family as urllib3 asks for it: IPv4 only where IPv6 is unusable.
    for family, kind, proto, _name, address in socket.getaddrinfo(
        host, conn.port, allowed_gai_family(), socket.SOCK_STREAM
    ):
        left = None if deadline is None else deadline - time.monotonic()
        if (tracked is not None and tracked.given_up()) or (
            left is not None and left <= 0
        ):
            break
        sock: socket.socket | None = None
        try:
            # Inside the try: an address whose socket cannot be made (its
            # family disabled, no descriptor left) is skipped, not fatal.
            sock = socket.socket(family, kind, proto)
            if tracked is not None:
                tracked.opened(sock)  # raises (the socket ended) when given up
            for option in conn.socket_options or ():
                sock.setsockopt(*option)
            wait = (
                limit if left is None else left if limit is None else min(limit, left)
            )
            sock.settimeout(wait)
            if conn.source_address:
                sock.bind(conn.source_address)
            sock.connect(address)
            return sock
        except OSError as e:
            error = e
            if sock is not None:
                sock.close()
    raise error or TimeoutError(f"no connect to {host} before the deadline")


class _TrackedHttp(HTTPConnection):
    def _new_conn(self) -> Any:
        return _connect(self)


class _TrackedHttps(HTTPSConnection):
    def _new_conn(self) -> Any:
        return _connect(self)


class _TrackedHttpPool(HTTPConnectionPool):
    ConnectionCls = _TrackedHttp  # type: ignore[assignment]


class _TrackedHttpsPool(HTTPSConnectionPool):
    ConnectionCls = _TrackedHttps  # type: ignore[assignment]


def _tracked_pools() -> dict[str, Any]:
    return {"http": _TrackedHttpPool, "https": _TrackedHttpsPool}


class _TrackedAdapter(HTTPAdapter):
    """Every connection it opens, direct or through the environment's
    HTTP(S) proxy, is recorded (``_FetchSockets``). No retries."""

    def init_poolmanager(self, *args: Any, **kwargs: Any) -> None:
        super().init_poolmanager(*args, **kwargs)
        self.poolmanager.pool_classes_by_scheme = _tracked_pools()  # type: ignore[attr-defined]

    def proxy_manager_for(self, proxy: str, **proxy_kwargs: Any) -> Any:
        if proxy.lower().startswith("socks"):
            # Its connections are not ours to record. Said at WARNING: the
            # verification fails, and nothing else would name the cause (the
            # scheme only; the URL may carry credentials).
            logger.warning(
                "A verification was not sent: it does not go through the "
                f"environment's {proxy.split(':', 1)[0]} proxy (set an HTTP(S) "
                "proxy, or NO_PROXY for the peer)"
            )
            raise requests.exceptions.InvalidSchema(
                "A verification does not go through a SOCKS proxy"
            )
        manager = super().proxy_manager_for(proxy, **proxy_kwargs)
        manager.pool_classes_by_scheme = _tracked_pools()
        return manager


def _verification_get(
    url: str,
    headers: dict[str, str],
    sockets: _FetchSockets,
    timeout: tuple[float, float],
) -> Any:
    """The streamed, redirect-free GET of a verification, on a session whose
    connections ``sockets`` records (the session is closed with it)."""
    session = requests.Session()
    sockets.session = session
    adapter = _TrackedAdapter(max_retries=0)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session.get(
        url,
        headers=headers,
        timeout=timeout,
        allow_redirects=False,
        stream=True,
    )


def _fetch_json(
    url: str,
    headers: dict[str, str],
    deadline: float,
    sockets: _FetchSockets,
    timeout: tuple[float, float],
) -> tuple[int | None, Any]:
    """The verification GET itself, on a pool worker (see
    ``_bounded_get_json``)."""
    _verify_local.sockets = sockets
    _verify_local.deadline = deadline
    try:
        return _read_json(url, headers, deadline, sockets, timeout)
    finally:
        _verify_local.sockets = None
        _verify_local.deadline = None
        sockets.release()
        _verify_slots.release()


def _read_json(
    url: str,
    headers: dict[str, str],
    deadline: float,
    sockets: _FetchSockets,
    timeout: tuple[float, float],
) -> tuple[int | None, Any]:
    if sockets.given_up() or time.monotonic() > deadline:
        return None, None
    try:
        answer = _verification_get(url, headers, sockets, timeout)
    except Exception:  # folds DbError: peer HTTP only
        return None, None
    try:
        status = int(answer.status_code)
        if not 200 <= status < 300:
            return status, None
        chunks: list[bytes] = []
        size = 0
        for chunk in answer.iter_content(chunk_size=1024):
            size += len(chunk)
            if size > _REVERIFY_MAX_BYTES or time.monotonic() > deadline:
                return status, None
            chunks.append(chunk)
        try:
            return status, json.loads(b"".join(chunks).decode("utf-8", "ignore"))
        except ValueError:
            return status, None
    except Exception:  # folds DbError: peer HTTP only
        return None, None
    finally:
        try:
            answer.close()
        except Exception:  # folds DbError: closing a response
            pass


def _verification_deadline() -> float:
    """The deadline of one verification (its GET and its /meta)."""
    return time.monotonic() + _REVERIFY_DEADLINE_SECONDS


def _bounded_get_json(
    url: str,
    headers: dict[str, str],
    deadline: float | None = None,
    timeout: tuple[float, float] = _VERIFY_READ_TIMEOUT,
) -> tuple[int | None, Any]:
    """GET ``url`` for a verification: without following a redirect,
    reading at most ``_REVERIFY_MAX_BYTES``, and returning by ``deadline``
    (a ``time.monotonic()`` value; one ``_REVERIFY_DEADLINE_SECONDS`` from
    now when not given) whatever the peer does. Returns the status and the
    parsed JSON body (None when the answer is not 2xx JSON, too large or too
    slow; status None when there was no answer in time)."""
    from concurrent.futures import TimeoutError as FutureTimeout

    if deadline is None:
        deadline = _verification_deadline()
    budget = deadline - time.monotonic()
    if budget <= 0:
        return None, None
    if not _verify_slots.acquire(blocking=False):
        # Every worker is busy: fail closed now rather than queue.
        logger.warning(
            f"A verification at {url} was refused: every verification worker is busy"
        )
        return None, None
    sockets = _FetchSockets()
    try:
        future = _verification_pool().submit(
            _fetch_json, url, headers, deadline, sockets, timeout
        )
    except RuntimeError:  # the pool is shut down (interpreter exit)
        _verify_slots.release()
        return None, None
    try:
        return future.result(timeout=budget)
    except FutureTimeout:
        if future.cancel():  # it never started: its slot is ours to free
            _verify_slots.release()
        # The worker may be blocked on the peer's socket (a trickle, a
        # stalled handshake): shutting it down ends the read now, and a
        # socket it connects later is shut down as it arrives.
        sockets.cancel()
        logger.warning(f"A verification at {url} gave no answer in time")
        return None, None
    except Exception:  # folds DbError: peer HTTP only
        return None, None


# Rate limit for the suspension-check failure ERROR (see
# is_subscription_suspended()). Time-windowed rather than once-per-process:
# a warm serverless container — or any long-lived one — can outlive the
# incident by days, and "once ever" would report a broken suspensions table a
# single time and then stay silent through every later failure, including a
# different one. A repeating heartbeat is alertable and stops on its own once
# the fault is fixed, while still costing at most one line per window per
# container.
_SUSPENSION_ERROR_LOG_INTERVAL_SECONDS = 300.0
# The /meta check of a trust request's base URI (create_verified_trust): two
# short tries, since an unauthenticated request chooses the host.
META_CHECK_TRIES = 2
META_CHECK_TIMEOUT: tuple[float, float] = (3, 5)
_suspension_check_error_logged_at: float | None = None


class TrustReplaced(Exception):
    """A trust delete with an expected secret found the row replaced (a
    re-pair landed): the new row is left alone (3.16)."""


_EMPTIED = object()


def _prune_emptied(original: Any, kept: Any) -> Any:
    """``kept`` (``original`` after a filter) without the objects the filter
    emptied, at any depth; ``_EMPTIED`` when ``original`` was a non-empty
    object and nothing of it is left. An object empty to begin with stays."""
    if not isinstance(original, dict) or not isinstance(kept, dict):
        return kept
    if original and not kept:
        return _EMPTIED
    out: dict[str, Any] = {}
    for key, value in kept.items():
        pruned = _prune_emptied(original.get(key), value)
        if pruned is not _EMPTIED:
            out[key] = pruned
    if original and not out:
        return _EMPTIED
    return out


class ActorError(Exception):
    """Base exception class for Actor-related errors."""

    pass


class ActorNotFoundError(ActorError):
    """Raised when an actor cannot be found."""

    pass


class InvalidActorDataError(ActorError):
    """Raised when actor data is invalid or corrupted."""

    pass


class PeerCommunicationError(ActorError):
    """Raised when communication with peer actors fails."""

    pass


class TrustRelationshipError(ActorError):
    """Raised when trust relationship operations fail."""

    pass


class DummyPropertyClass:
    """Only used to deprecate get_property() in 2.4.4"""

    def __init__(self, v: Any = None) -> None:
        self.value = v


def relationship_summary(
    trusts: list[Any] | None, subscriptions: list[Any] | None
) -> tuple[list[dict[str, Any]], list[str]]:
    """What an adoption removed, for its log line and the ``actor_adopted``
    hook: each trust's ``peerid``, ``relationship``, ``approved`` and
    ``established_via`` (never its ``secret``), and the sorted subscription
    peer ids."""
    removed_trusts = [
        {
            "peerid": t.get("peerid", ""),
            "relationship": t.get("relationship", ""),
            "approved": t.get("approved"),
            "established_via": t.get("established_via"),
        }
        for t in (trusts or [])
        if isinstance(t, dict)
    ]
    peers = sorted(
        {
            str(s.get("peerid", ""))
            for s in (subscriptions or [])
            if isinstance(s, dict) and s.get("peerid")
        }
    )
    return removed_trusts, peers


class Actor:
    ###################
    # Basic operations
    ###################

    def __init__(self, actor_id: str | None = None, config: Any | None = None) -> None:
        self.config = config
        self.property_list: Any | None = None
        self.subs_list: list[dict[str, Any]] | None = None
        self.actor: dict[str, Any] | None = None
        self.passphrase: str | None = None
        self.creator: str | None = None
        self.last_response_code: int = 0
        self.last_response_message: str = ""
        # Set by create_reciprocal_trust(): the peer whose pending request it
        # approved instead of sending one (TrustManager fires the hook).
        self.last_trust_approved_on_create: str | None = None
        self.id: str | None = actor_id
        # Set by get_from_creator: the other actors with this creator that are
        # marked for replacement (``factory``), for a sign-in to sweep.
        self.factory_sibling_ids: list[str] = []
        self.creator_ids: list[str] = []
        self.creator_classes: dict[str, str] = {}
        if self.config:
            self.handle = get_actor(self.config)
        else:
            self.handle = None
        if actor_id and config:
            self.store = attribute.InternalStore(actor_id=actor_id, config=config)
            self.property = property.PropertyStore(actor_id=actor_id, config=config)
            self.property_lists = property.PropertyListStore(
                actor_id=actor_id, config=config
            )
        else:
            self.store = None
            self.property = None
            self.property_lists = None
        self.get(actor_id=actor_id)

    def get_peer_info(
        self,
        url: str,
        max_retries: int = 3,
        retry_delay: float = 0.5,
        timeout: tuple[float, float] = (5, 10),
    ) -> dict[str, Any]:
        """Contacts another actor over http/s to retrieve meta information.

        Includes retry logic for transient network failures with exponential backoff.

        Note: This sync method blocks the event loop. In FastAPI/uvicorn contexts,
        use AsyncTrustHandler which calls create_reciprocal_trust_async() instead.

        :param url: Root URI of a remote actor
        :param max_retries: Maximum number of retry attempts (default: 3)
        :param retry_delay: Initial delay between retries in seconds (default: 0.5)
        :param timeout: Connect and read timeout of each try, in seconds
        :rtype: dict
        :return: The json response from the /meta path in the data element and
            last_response_code/last_response_message set to the results of the https request

        Example::

            {
                "last_response_code": 200,
                "last_response_message": "OK",
                "data": {}
            }
        """
        import time

        last_error: Exception | None = None
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    logger.info(
                        f"Retry attempt {attempt + 1}/{max_retries} for peer info from {url}"
                    )
                else:
                    logger.debug(f"Fetching peer info from {url}")

                response = requests.get(url=url + "/meta", timeout=timeout)
                res = {
                    "last_response_code": response.status_code,
                    "last_response_message": response.content,
                    "data": json.loads(response.content.decode("utf-8", "ignore")),
                }
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        f"Got peer info from url({url}) with body("
                        f"{summarize_payload(res['data'], encoded_len=len(response.content))})"
                    )
                return res
            except (TypeError, ValueError, KeyError) as e:
                # JSON parsing errors - don't retry
                logger.warning(f"Invalid response from peer {url}: {e}")
                return {
                    "last_response_code": 500,
                    "last_response_message": str(e),
                }
            except requests.exceptions.RequestException as e:
                # Network errors - retry with exponential backoff
                last_error = e
                if attempt < max_retries - 1:
                    delay = retry_delay * (2**attempt)  # Exponential backoff
                    logger.warning(
                        f"Network error fetching peer info from {url}: {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    time.sleep(delay)
                else:
                    logger.warning(
                        f"Network error fetching peer info from {url} after "
                        f"{max_retries} attempts: {e}"
                    )

        # All retries exhausted
        return {
            "last_response_code": 500,
            "last_response_message": str(last_error) if last_error else "Unknown error",
        }

    async def get_peer_info_async(self, url: str) -> dict[str, Any]:
        """Async version of get_peer_info using httpx.

        Contacts another actor over HTTP/S to retrieve meta information without blocking.

        :param url: Root URI of a remote actor
        :return: Dict with last_response_code, last_response_message, and data
        """
        import httpx

        try:
            logger.debug(f"Fetching peer info async from {url}")
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url + "/meta")
                res = {
                    "last_response_code": response.status_code,
                    "last_response_message": response.content,
                    "data": response.json(),
                }
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        f"Got peer info async from url({url}) with body("
                        f"{summarize_payload(res['data'], encoded_len=len(response.content))})"
                    )
                return res
        except (TypeError, ValueError, KeyError) as e:
            # JSON parsing errors
            logger.warning(f"Invalid response from peer {url}: {e}")
            return {
                "last_response_code": 500,
                "last_response_message": str(e),
                "data": {},
            }
        except httpx.TimeoutException as e:
            logger.warning(f"Timeout fetching peer info async from {url}: {e}")
            return {
                "last_response_code": 408,
                "last_response_message": "Timeout",
                "data": {},
            }
        except httpx.RequestError as e:
            logger.warning(f"Network error fetching peer info async from {url}: {e}")
            return {
                "last_response_code": 500,
                "last_response_message": str(e),
                "data": {},
            }

    def _write_marker(self, store: "attribute.InternalStore", auth_method: str) -> bool:
        """Write ``auth_method``, and first, for a vouched one, the address
        it vouches for (:data:`actingweb.oauth2.VOUCHED_CREATOR`), both
        confirmed. Bound first: a marker without its address would be judged
        by the marker alone. Raises ``DbError`` on a fault."""
        from .oauth2 import UNVOUCHED_AUTH_METHODS, VOUCHED_CREATOR

        if auth_method not in UNVOUCHED_AUTH_METHODS and not store.set_confirmed(
            VOUCHED_CREATOR, normalise_creator(self.creator), raise_on_fault=True
        ):
            return False
        return store.set_confirmed("auth_method", auth_method, raise_on_fault=True)

    @staticmethod
    def _restore_marker(
        store: "attribute.InternalStore", marker: Any, creator: str | None
    ) -> bool:
        """Put back the marker a failed creator change replaced. A vouched
        one is bound to ``creator`` (the one the re-read confirmed) first,
        so a concurrent change that lands after this restore leaves the
        actor unvouched, whatever order the writes take."""
        from .oauth2 import UNVOUCHED_AUTH_METHODS, VOUCHED_CREATOR

        if (
            isinstance(marker, str)
            and marker
            and marker not in UNVOUCHED_AUTH_METHODS
            and not store.set_confirmed(VOUCHED_CREATOR, normalise_creator(creator))
        ):
            return False
        # Only while it still reads this change's "creator_changed": a
        # sign-in that cleaned the actor meanwhile wrote its own marker, and
        # an unconditional restore would put the stale one back over it.
        db = store.__dict__["_db"]
        if not db.conditional_update_attr(
            name="auth_method", old_data="creator_changed", new_data=marker or None
        ):
            # Both backends also answer False on a fault: a strict re-read
            # tells a marker that really changed from an outage, so the log
            # does not blame a sign-in that never happened.
            try:
                row = db.dbprop.get_attr_strict(
                    actor_id=db.actor_id, bucket=db.bucket, name="auth_method"
                )
            except DbError:  # folds DbError: the restore already failed; log only
                row = {"data": "creator_changed"}
            stored = row.get("data") if row is not None else None
            if stored == (marker or None):
                # The write landed and only its answer was lost (a fault after
                # the commit): it is restored.
                store.__dict__["auth_method"] = marker or None
                return True
            if stored == "creator_changed":
                logger.warning(
                    "could not restore auth_method (store fault); the actor "
                    "stays unvouched"
                )
            else:
                logger.warning(
                    "auth_method changed since this creator change wrote it; "
                    "not restored"
                )
            return False
        store.__dict__["auth_method"] = marker or None
        return True

    @staticmethod
    def _drop_pre_marker(
        store: "attribute.InternalStore | None", actor_id: str | None
    ) -> None:
        """Remove the marker written ahead of a create refused with
        ``CreatorTaken`` (its condition failed, so nothing committed), so no
        bucket is left for an id with no actor. Best effort: a
        leftover is an orphan bucket for an id nobody uses, which
        ``verify_orphans`` lists."""
        if store is None:
            return
        from .oauth2 import VOUCHED_CREATOR

        try:
            store.set_confirmed(VOUCHED_CREATOR, None)
            if not store.set_confirmed("auth_method", None):
                logger.warning(f"Marker for {actor_id} left behind a failed create")
        except Exception as e:  # folds DbError: best-effort cleanup of an unused id
            logger.warning(f"Marker for {actor_id} left behind: {e}")

    def _email_held_elsewhere(self, email: str) -> bool:
        """Under ``with_unique_creator()``, whether another actor holds
        ``email`` (its ``creators`` record), so the force-email rewrite in
        :meth:`get` is skipped instead of refused on every load. One
        consistent read; a fault raises ``DbError``, as the rewrite does."""
        if not self.config or not self.config.unique_creator or is_exempt(email):
            return False
        holder = get_actor(self.config).get_creator_holder(email)
        if holder and holder != self.id:
            # INFO: a record naming an actor that is gone (an orphan) blocks
            # the rewrite too; ``actingweb-unique-creators report`` lists it.
            logger.info(
                f"Actor {self.id}: stored email is held by {holder}; creator "
                "left unchanged"
            )
            return True
        return False

    def get(
        self, actor_id: str | None = None, *, rewrite_email: bool = True
    ) -> dict[str, Any] | None:
        """Retrieves an actor from storage or initialises if it does not exist.

        ``rewrite_email=False`` skips the ``force_email_prop_as_creator``
        rewrite, for a lookup that just matched the stored creator.
        """
        if not actor_id and not self.id:
            return None
        elif not actor_id:
            actor_id = self.id
        if self.handle and self.actor and len(self.actor) > 0:
            return self.actor
        if self.handle:
            self.actor = self.handle.get(actor_id=actor_id)
        else:
            self.actor = None
        if self.actor and len(self.actor) > 0:
            self.id = self.actor["id"]
            self.creator = self.actor["creator"]
            self.passphrase = self.actor["passphrase"]
            self.store = attribute.InternalStore(actor_id=self.id, config=self.config)
            self.property = property.PropertyStore(actor_id=self.id, config=self.config)
            self.property_lists = property.PropertyListStore(
                actor_id=self.id, config=self.config
            )
            if (
                rewrite_email
                and self.config
                and self.config.force_email_prop_as_creator
            ):
                em = self.store.email
                from .oauth2 import is_vouched_store

                # Only a vouched actor's stored email decides its creator: an
                # unvouched actor's email may be a previous creator's, and
                # adoption, not a load, decides who it belongs to.
                if (
                    em
                    and em.lower() != self.creator
                    and is_vouched_store(self.store)
                    and not self._email_held_elsewhere(em.lower())
                ):
                    try:
                        self.modify(creator=em.lower())
                    except CreatorTaken:  # folds DbError: email held elsewhere
                        # Taken between the holder read and the rename.
                        logger.warning(
                            f"Actor {self.id}: stored email is another actor's "
                            "creator; creator left unchanged"
                        )
        else:
            self.id = None
            self.creator = None
            self.passphrase = None
        return self.actor

    def get_from_property(
        self, name: str = "oauthId", value: str | None = None
    ) -> None:
        """Initialise an actor by matching on a stored property.

        Use with caution as the property's value de-facto becomes
        a security token. If multiple properties are found with the
        same value, no actor will be initialised.
        Also note that this is a costly operation as all properties
        of this type will be retrieved and proceessed.
        """
        actor_id = property.Property(
            name=name, value=value, config=self.config
        ).get_actor_id()
        if not actor_id:
            self.id = None
            self.creator = None
            self.passphrase = None
            return
        self.get(actor_id=actor_id)

    def get_from_creator(self, creator: str | None = None) -> bool:
        """Initialise an actor by matching on creator/email.

        Returns True if an actor could be loaded, otherwise False. With
        ``unique_creator`` on, the one holder of a non-exempt creator is read
        consistently (:meth:`DbActorProtocol.get_creator_holder`) and the rest
        of this docstring does not apply. When
        several actors share the creator (possible with ``unique_creator``
        off) the pick is, in order: a vouched actor, any other unvouched
        actor, a ``factory`` one; the lowest id within each group.

        The actors are listed by id only and read in id order: each is
        loaded (one gone since the listing is left out) and its marker
        classified, until the first vouched actor, which is the pick. After
        it at most :data:`actingweb.oauth2.SWEEP_LIMIT` more markers are read
        to find the ``factory`` actors a sign-in removes beside it, so the
        reads are bounded by the ranked prefix plus that limit.

        Raises ``DbError`` on a read fault, and when a marker in the ranked
        prefix cannot be read: ranking an unreadable actor like an unvouched
        one could strand the owner's actor behind it (BR).

        Sets ``factory_sibling_ids`` (the ``factory`` actors classified beside
        the pick), ``creator_ids`` (every id the listing returned) and
        ``creator_classes`` (the class of every actor read) for the sign-in to
        reuse instead of listing again.
        """
        from .oauth2 import SWEEP_LIMIT, classify_marker, row_holds_creator

        self.id = None
        self.creator = None
        self.passphrase = None
        self.factory_sibling_ids = []
        self.creator_ids = []
        self.creator_classes = {}

        if not self.config or not creator:
            return False

        lookup_creator = normalise_creator(creator)
        db = get_actor(self.config)
        if self.config.unique_creator and not is_exempt(lookup_creator):
            # Enforced: one holder, read consistently from the creators
            # record (DynamoDB) or the unique row (PostgreSQL), not from the
            # lagging index; nothing to rank and no siblings to sweep. A
            # stale record (its actor gone, or holding another creator) is
            # removed and answers False, so the create that follows takes
            # the address.
            holder = db.get_creator_holder(lookup_creator)
            self.creator_ids = [holder] if holder else []
            if not holder:
                return False
            # The row as stored, read consistently, before any force-email
            # rewrite could change the creator being looked up.
            row = get_actor(self.config).get(actor_id=holder)
            if not row or normalise_creator(row.get("creator")) != lookup_creator:
                # A stale record: its actor is gone, or holds another creator
                # now (a release that faulted, an old process's delete or
                # rename). Loading it would sign this identity into that
                # actor; repairing it lets the create that follows take the
                # address.
                repaired = db.release_stale_creator(lookup_creator, holder)
                logger.warning(
                    f"The creator record of {lookup_creator!r} named actor "
                    f"{holder}, which no longer holds it; "
                    + ("removed" if repaired else "it changed meanwhile")
                )
                self.creator_ids = []
                return False
            self.get(actor_id=holder, rewrite_email=False)
            if self.id and normalise_creator(self.creator) != lookup_creator:
                # Renamed between the check and the load: not this identity's
                # actor any more. The create that follows settles the record.
                logger.warning(
                    f"Actor {holder} was renamed away from {lookup_creator!r} "
                    "during the sign-in lookup; not loaded"
                )
                self.id = None
                self.creator = None
                self.passphrase = None
                self.actor = None
                self.store = None
                self.property = None
                self.property_lists = None
                self.creator_ids = []
                return False
            return bool(self.id)

        listed = db.get_by_creator(creator=lookup_creator, ids_only=True) or []
        rows: list[dict[str, Any]] = [listed] if isinstance(listed, dict) else listed
        ids = sorted({str(r["id"]) for r in rows if r and r.get("id")})
        self.creator_ids = ids
        if not ids:
            return False
        if len(ids) == 1:
            if not row_holds_creator(db.get(actor_id=ids[0]), lookup_creator):
                # Renamed away since the index listed it (BK): not this
                # creator's actor.
                self.creator_ids = []
                return False
            self.get(actor_id=ids[0])
            return bool(self.id)

        logger.warning(f"Multiple actors share creator {lookup_creator!r}: {ids}")
        rank_of = {"vouched": 0, "unvouched": 1, "replace": 2}
        classes: dict[str, str] = {}
        ranked: list[tuple[int, str]] = []
        tail_left: int | None = None
        for candidate_id in ids:
            if tail_left is not None:
                # Past the pick: only factory actors to remove beside it
                # matter, and one whose marker cannot be read is not touched.
                if tail_left <= 0:
                    break
                tail_left -= 1
                tail_class = classify_marker(self.config, candidate_id, lookup_creator)
                if tail_class is not None:
                    classes[candidate_id] = tail_class
                    # A fallback if the pick vanishes before its load.
                    ranked.append((rank_of[tail_class], candidate_id))
                continue
            if not row_holds_creator(db.get(actor_id=candidate_id), lookup_creator):
                continue  # deleted, or renamed away, since the index listed it
            marker = classify_marker(self.config, candidate_id, lookup_creator)
            if marker is None:
                raise DbError("actor marker read", candidate_id)
            classes[candidate_id] = marker
            rank = rank_of[marker]
            ranked.append((rank, candidate_id))
            if rank == 0:
                tail_left = SWEEP_LIMIT
        self.creator_classes = classes
        # Best first; an actor deleted between the ranking and its load is
        # passed over for the next one, as the per-row loop did before 3.16.
        for _rank, candidate_id in sorted(ranked):
            self.get(actor_id=candidate_id)
            if self.id:
                break
        if not self.id:
            return False
        self.factory_sibling_ids = [
            i for i, c in classes.items() if c == "replace" and i != self.id
        ]
        return True

    def create(
        self,
        url: str,
        creator: str,
        passphrase: str,
        actor_id: str | None = None,
        delete: bool = False,
        trustee_root: str | None = None,
        hooks: Any = None,
        auth_method: str = "app",
        *,
        replace_holder: str | None = None,
    ) -> bool:
        """ "Creates a new actor and persists it.

        With ``unique_creator`` a non-exempt creator another actor holds
        raises :class:`~actingweb.db.exceptions.CreatorTaken`. If delete is
        True, the existing actors with the same creator are deleted first
        (not atomically). ``replace_holder`` names the actor that holds the
        creator now: the backend moves the creator to the new actor in the
        same step as the create (:meth:`DbActorProtocol.replace_creator_holder`),
        and the caller removes the old actor afterwards. Without the flag, a
        create never returns an existing actor.

        ``auth_method`` records how the actor came to exist and is written to
        the ``_internal`` store before ``actor_created`` fires, only when a
        row was actually persisted. It is a trust assertion: ``"app"`` means
        the calling application vouches for ``creator``; pass ``"factory"``
        for anything created from unauthenticated input. An unvouched actor
        (see :func:`actingweb.oauth2.is_vouched_actor`) is replaced or
        cleaned when a sign-in later proves the address.

        Raises:
            ValueError: A caller-supplied ``actor_id`` contains ``$`` (it
                separates an actor's property-list side partition,
                ``{actor_id}$aux``) or is longer than 251 characters (the
                side partition key must fit PostgreSQL's 255-character
                ``properties.id``). Raised before any write; generated ids
                are 32 hex characters and never affected.
        """
        if actor_id is not None and ("$" in actor_id or len(actor_id) > 251):
            raise ValueError(
                "A caller-supplied actor id may not contain '$' or be longer "
                "than 251 characters"
            )
        seed = url
        now = datetime.datetime.now(datetime.UTC)
        seed += now.strftime("%Y%m%dT%H%M%S%f")
        # Random bytes too: two creates in the same microsecond (two
        # processes) would otherwise get the same id, and the marker written
        # ahead of the row would land in the other actor's bucket.
        seed += os.urandom(16).hex()
        if len(creator) > 0:
            self.creator = creator
        else:
            self.creator = DEFAULT_CREATOR
        if is_reserved(self.creator):
            # "#…" and "#dup-" belong to the uniqueness bookkeeping; only
            # actingweb-unique-creators writes them, through modify().
            logger.warning(
                f"Refusing to create an actor with reserved creator {self.creator!r}"
            )
            self.creator = None
            return False
        if self.config and self.config.unique_creator:
            # The backend enforces uniqueness: a create for a held creator
            # raises CreatorTaken, which propagates. There is no passphrase
            # match any more (it returned the existing actor to whoever
            # guessed its passphrase).
            if delete:
                # Not atomic: the caller asked for the existing actors to go.
                # A held creator has one holder, read consistently (the
                # index can still miss a just-created one).
                db = get_actor(self.config)
                if is_exempt(self.creator):
                    ids = [
                        c["id"]
                        for c in db.get_by_creator(
                            creator=self.creator, consistent=True
                        )
                        or []
                        if c
                    ]
                else:
                    holder = db.get_creator_holder(self.creator)
                    ids = [holder] if holder else []
                for victim_id in ids:
                    # The constructor loads it; delete() acts on a loaded row.
                    victim = Actor(actor_id=victim_id, config=self.config)
                    if victim.id:
                        victim.delete()
            # Actors left with the default creator are moved to their stored
            # email by ``actingweb-unique-creators resolve
            # --default-creator-to-email`` (and by get()'s rewrite as each is
            # loaded), not by every create.

        if passphrase and len(passphrase) > 0:
            self.passphrase = passphrase
        else:
            self.passphrase = self.config.new_token() if self.config else ""
        if actor_id:
            self.id = actor_id
        else:
            self.id = self.config.new_uuid(seed) if self.config else ""
        if not self.handle and self.config:
            self.handle = get_actor(self.config)
        # A generated id is new, so its bucket is empty and nobody else
        # writes it: the marker goes in before the row. The row (and under
        # unique_creator its record) then never becomes visible to a sign-in
        # without it; unmarked, a sign-in arriving in between would take the
        # new actor for a legacy one and clean it in place. A caller-supplied
        # id (a system actor) can own older buckets, and keeps the marker
        # after the row (below).
        pre_marked: attribute.InternalStore | None = None
        if self.handle and not actor_id and auth_method and self.config:
            pre_marked = attribute.InternalStore(actor_id=self.id, config=self.config)
            pre_marked.mark_empty()
            try:
                marked = self._write_marker(pre_marked, auth_method)
            except DbError:  # folds DbError: re-raised (503), nothing created
                self.id = None
                self.passphrase = None
                self.handle = None
                raise
            if not marked:
                logger.error(
                    f"Actor {self.id}: the auth_method marker did not land; "
                    "nothing created"
                )
                self.id = None
                self.passphrase = None
                self.handle = None
                return False
        created = False
        if self.handle:
            try:
                created = self.handle.create(
                    creator=self.creator,
                    passphrase=self.passphrase,
                    actor_id=self.id,
                    replace_holder=replace_holder,
                )
            except CreatorTaken:
                self._drop_pre_marker(pre_marked, self.id)
                self.id = None
                self.passphrase = None
                self.handle = None
                self.store = None
                raise
            except DbError:
                # Ambiguous: the create may have committed (a lost
                # acknowledgement). Keep the marker: on an unused id it is an
                # orphan bucket, on a committed row it is what keeps the next
                # sign-in from cleaning it as legacy.
                raise
        # Generated ids are never reused, but create(actor_id=...) accepts a
        # caller-supplied one. A stale tombstone would report the new actor as
        # deleted for the rest of the retention window.
        #
        # Only when the row was actually persisted. create() returns False if
        # the id is already taken — including by an actor mid-deletion, whose
        # row survives until the wipe's last step — and clearing the tombstone
        # there would strip the marker off a deletion still in progress,
        # reopening the very race it guards. A backend insert failure is the
        # same shape: nothing created, so nothing to un-tombstone.
        if created and actor_id:
            # A caller-supplied id is the only kind a tombstone can name, so
            # its clear is confirmed: a live actor left tombstoned would have
            # its writes suppressed and, at its next sign-in, be taken for a
            # stalled deletion. A fault fails the create (503); the swap's row
            # is kept, as the marker rollback below keeps it.
            try:
                deletion.clear_actor_tombstone(self.id, self.config, strict=True)
            except DbError:
                logger.error(
                    f"Actor {self.id}: its deletion tombstone could not be "
                    "confirmed cleared; failing the create"
                )
                if replace_holder is None:
                    try:
                        if self.handle:
                            self.handle.delete()
                    except Exception as e:  # folds DbError: rollback inside the DbError handler, which re-raises the original fault
                        logger.error(f"Actor {self.id}: row removal raised: {e}")
                self.id = None
                self.passphrase = None
                self.handle = None
                self.store = None
                raise
        elif created:
            deletion.clear_actor_tombstone(self.id, self.config)
        if not created:
            # The id was taken (by a live actor, or one mid-deletion) or the
            # insert failed: nothing was created, and the bucket under this id
            # is not ours to write. Unbind, so a caller that ignores the False
            # cannot modify or delete the actor that holds the id. With a
            # generated id that bucket is not touched either: nothing here
            # proves the marker in it is the one this create wrote.
            self.id = None
            self.passphrase = None
            self.handle = None
            self.store = None
            return False
        if pre_marked is not None:
            self.store = pre_marked
        else:
            self.store = attribute.InternalStore(actor_id=self.id, config=self.config)
            if not actor_id:
                # A generated id is new, so its bucket is empty; skip the
                # read. A caller-supplied one (a system actor) can own older
                # buckets.
                self.store.mark_empty()
        self.property = property.PropertyStore(actor_id=self.id, config=self.config)
        self.property_lists = property.PropertyListStore(
            actor_id=self.id, config=self.config
        )

        # Record how the actor was created, before anything else lands in
        # its bucket, so a rollback has only the row to remove (a generated
        # id already has it, written before the row).
        if self.store and auth_method and pre_marked is None:
            try:
                marked = self._write_marker(self.store, auth_method)
                fault: DbError | None = None
            except DbError as e:  # folds DbError: re-raised after the rollback
                # A store fault answers 503, like the trustee_root write
                # below; a mismatch stays the False refusal.
                marked, fault = False, e
            if not marked:
                # An actor without its marker reads as legacy, and the next
                # sign-in would wipe it. Undo the creation: only the row, since
                # a fixed id (a system actor) can own buckets that predate it.
                if replace_holder is not None:
                    # The swap moved the creator to this row: deleting it
                    # would leave the creator held by nobody while the old
                    # holder lives on. Keep it; unmarked, the next sign-in
                    # cleans it in place.
                    logger.error(
                        f"Actor {self.id}: the auth_method marker did not land "
                        f"after taking the creator from {replace_holder}; "
                        "keeping the row"
                    )
                    rolled_back = True
                else:
                    logger.error(
                        f"Actor {self.id}: the auth_method marker did not land; "
                        "removing the new actor row"
                    )
                    rolled_back = False

                try:
                    rolled_back = rolled_back or bool(
                        self.handle and self.handle.delete()
                    )
                except Exception as e:  # folds DbError: rollback of a create whose marker did not land; logged, next sign-in cleans the row
                    logger.error(f"Actor {self.id}: row removal raised: {e}")
                    rolled_back = False
                if not rolled_back:
                    logger.error(
                        f"Actor {self.id}: removing the unmarked actor failed; "
                        "its next sign-in cleans it in place"
                    )
                self.id = None
                self.passphrase = None
                self.handle = None
                self.store = None
                if fault is not None:
                    raise fault
                return False

        if (
            trustee_root
            and isinstance(trustee_root, str)
            and len(trustee_root) > 0
            and self.store
        ):
            try:
                self.store.trustee_root = trustee_root
            except DbError:
                # The actor would exist without its trustee_root and without
                # actor_created having fired. Remove the row, as for a lost
                # marker, and let the fault reach the caller (503): a retry
                # starts clean instead of leaving an unannounced actor.
                logger.error(
                    f"Actor {self.id}: the trustee_root write faulted; "
                    "removing the new actor row"
                )
                try:
                    # Not after a swap: the row holds the creator now (see
                    # the marker rollback above).
                    if self.handle and replace_holder is None:
                        self.handle.delete()
                        if not actor_id:
                            # A generated id's _internal bucket (its marker)
                            # was written by this create alone.
                            attribute.Attributes(
                                actor_id=self.id, bucket="_internal", config=self.config
                            ).delete_bucket()
                except Exception as e:  # folds DbError: rollback inside the DbError handler, which re-raises the original fault
                    logger.error(f"Actor {self.id}: row removal raised: {e}")
                self.id = None
                self.passphrase = None
                self.handle = None
                self.store = None
                raise

        # Execute actor_created lifecycle hook if hooks are provided
        if hooks:
            try:
                from actingweb.interface.actor_interface import ActorInterface

                registry = getattr(self.config, "service_registry", None)
                actor_interface = ActorInterface(self, service_registry=registry)
                hooks.execute_lifecycle_hooks("actor_created", actor_interface)
            except Exception as e:  # folds DbError: notification after commit
                # Log hook execution error but don't fail actor creation
                logger.warning(
                    f"Actor created successfully but lifecycle hook failed: {e}"
                )

        return True

    def creator_change_pinned(self, creator: str) -> bool:
        """Whether ``force_email_prop_as_creator`` refuses changing the creator
        to ``creator``: on, with a stored email that ``creator`` is not (nor
        ``"trustee"``). :meth:`get` would put the stored email back on the next
        load, and a sign-in for the new address in between would resolve to
        this actor. False when ``_internal`` cannot be read."""
        store = self.store
        if not self.config or not self.config.force_email_prop_as_creator:
            return False
        if not store or not store.loaded:
            return False
        own_email = store.email
        target = normalise_creator(creator)
        return (
            isinstance(own_email, str)
            and bool(own_email)
            and target not in ("trustee", own_email.lower())
        )

    def modify_creator_unvouched(self, creator: str) -> bool:
        """Change the creator to an address nobody proved, and unvouch.

        A sign-in that later proves ``creator`` then cleans the actor in place
        instead of adopting it as is (:func:`actingweb.oauth2.adopt_actor`).
        The marker becomes ``creator_changed``, written and confirmed before
        the creator changes, except when the change hands the actor to nobody
        new: ``"trustee"`` (the protocol's handoff; no sign-in resolves to it),
        the actor's own stored ``email`` (a provider or the emailed link wrote
        it), or the current creator. A marker in
        :data:`actingweb.oauth2.REPLACE_AUTH_METHODS` (``"factory"``) is kept:
        that actor is already unvouched, and is replaced rather than cleaned.

        Returns False when the creator did not change, including when
        :meth:`creator_change_pinned` refuses it. The previous marker is
        restored then, but only once a fresh read shows the stored creator
        unchanged (a failure can be a lost acknowledgement of a write that
        landed). Raises only ``DbError``, with the actor left unvouched.
        """
        from actingweb.oauth2 import REPLACE_AUTH_METHODS

        store = self.store
        if not store or not store.loaded or not self.config:
            logger.error(f"Actor {self.id}: _internal unreadable; creator not changed")
            return False
        if self.creator_change_pinned(creator):
            logger.warning(
                f"Actor {self.id}: creator is pinned to the stored email "
                "(force_email_prop_as_creator); creator not changed"
            )
            return False
        if is_refused_from_callers(creator):
            # The uniqueness bookkeeping's values and the system actors'.
            logger.warning(f"Actor {self.id}: creator {creator!r} is reserved")
            return False

        target = normalise_creator(creator)
        own_email = store.email
        previous_marker = store.auth_method
        unvouch = (
            target != self.creator
            and target != "trustee"
            and not (isinstance(own_email, str) and own_email.lower() == target)
            and previous_marker not in REPLACE_AUTH_METHODS
        )
        # Marker first: a change that lands without it would leave the actor
        # vouched under an address nobody proved.
        if unvouch and not store.set_confirmed("auth_method", "creator_changed"):
            logger.error(
                f"Actor {self.id}: could not unvouch before a creator change; "
                "creator not changed"
            )
            return False
        original = self.creator
        fault: DbError | None = None
        try:
            if self.modify(creator=creator):
                return True
        except DbError as e:  # folds DbError: raised after the marker restore below
            # Ambiguous: the creator may have landed. Put the marker back
            # only if the stored creator is unchanged, then raise.
            fault = e
        except Exception as e:
            logger.error(f"Actor {self.id}: creator change failed: {e}")
        if unvouch:
            try:
                row = get_actor(self.config).get(actor_id=self.id)
            except DbError as e:  # folds DbError: unconfirmed, so the marker stays
                if fault is None:
                    raise
                logger.error(f"Actor {self.id}: creator re-read faulted: {e}")
                row = None
            if not row or row.get("creator") != original:
                logger.error(
                    f"Actor {self.id}: creator change failed and the stored "
                    "creator could not be confirmed unchanged; auth_method left "
                    "'creator_changed'"
                )
            elif not self._restore_marker(store, previous_marker, original):
                # Unvouched, so the owner's next sign-in cleans it.
                logger.error(
                    f"Actor {self.id}: creator unchanged but auth_method is "
                    f"still 'creator_changed' (was {previous_marker!r})"
                )
        if fault is not None:
            raise fault
        return False

    def modify(self, creator: str | None = None, passphrase: str | None = None) -> bool:
        """Change the actor's creator and/or passphrase.

        Returns the backend result. DynamoDB raises when the save fails and
        PostgreSQL returns ``False``; callers that must know treat both as
        failure. The in-memory values change only after the backend reported
        success.
        """
        if not self.handle or not (creator or passphrase):
            logger.debug("Attempted modify of actor with no handle or no param changed")
            return False
        if creator:  # None or "" stays "no change"; the helper maps None to ""
            creator = normalise_creator(creator)
        ok = self.handle.modify(
            creator=creator or None,
            passphrase=passphrase.encode("utf-8") if passphrase else None,
        )
        if not ok:
            return False
        if creator:
            self.creator = creator
            if self.actor:
                self.actor["creator"] = creator
        if passphrase:
            self.passphrase = passphrase
            if self.actor:
                self.actor["passphrase"] = passphrase
        return True

    def delete(
        self,
        notify_peers: bool = True,
        *,
        _pre_reads: tuple[Any, Any] | None = None,
        _between_steps: Callable[[], None] | None = None,
    ) -> bool:
        """Deletes an actor and cleans up all relevant stored data.

        ``notify_peers=False`` skips the remote DELETE calls to peers and
        trustees (``requests.delete``) and keeps every local cleanup. Use it
        when the peer URLs are not trustworthy. When the actor's deletion
        tombstone recorded ``notify_peers=False`` (a replacement at adoption,
        whose peers a squatter chose), that wins over the argument.

        Returns True when the actor row is gone, including when a repeated
        call on the same object finds it already gone. A backend fault raises
        ``DbError``.

        **Resumable.** Every step tolerates rows that are already gone, and
        the row goes last, so calling ``delete()`` again after it raised
        part-way finishes the wipe. Applications deleting through HTTP or a
        sign-in go through :func:`actingweb.deletion_finish.finish_deletion`,
        which also runs the lifecycle hooks; this method runs none.

        The trust and subscription lists are read **first**, strictly: a read
        fault raises before anything is deleted and before the tombstone is
        written, so a throttle never deletes an actor without notifying its
        peers (B8). Once the reads pass, the tombstone is (re-)stamped and the
        wipe runs. ``_pre_reads`` is for the finisher, which has already made
        those reads (the fetched ``Trusts`` and ``Subscriptions`` wrappers);
        ``_between_steps`` is its lease keeper, run before each step that can
        wait on a peer.

        The actor row is removed **last**, so the actor keeps resolving for the
        duration of the wipe. Existence checks therefore fail open here, and
        that is why the tombstone is written before the first destructive
        step: it is readable throughout the wipe, whereas ``get()`` cannot
        distinguish mid-deletion from live. See :mod:`actingweb.deletion`.
        """
        if not self.id:
            # Loading an id whose row is gone leaves no id: nothing to wipe
            # here (a stalled wipe whose row went is finished by
            # actingweb-deletions).
            logger.debug("Attempted delete of actor with no id")
            return False
        if not self.handle:
            if self.config:
                # A repeated call after the row went: done. A strict read, so
                # "no handle because the read failed" is not mistaken for it.
                row = self._row_strict()
                if row is None:
                    return True
            logger.debug("Attempted delete of actor with no handle")
            return False
        if _pre_reads is not None:
            trusts, subs = _pre_reads
            relationships = trusts.fetch()  # cached by the finisher's strict read
        else:
            subs = subscription.Subscriptions(actor_id=self.id, config=self.config)
            subs.fetch()  # strict: raises DbError before anything is removed
            trusts = trust.Trusts(actor_id=self.id, config=self.config)
            relationships = trusts.fetch()  # strict, same
        notify_peers = deletion.restamp(self.id, self.config, notify_peers)

        def step() -> None:
            if _between_steps is not None:
                _between_steps()

        step()
        self.delete_peer_trustee(shorttype="*", notify_peers=notify_peers)
        if not self.property_list:
            self.property_list = property.Properties(
                actor_id=self.id, config=self.config
            )
        self.property_list.delete()
        subs.delete()
        if relationships:
            for rel in relationships:
                if isinstance(rel, dict) and "peerid" in rel:
                    step()
                    self.delete_reciprocal_trust(
                        peerid=rel.get("peerid", ""),
                        delete_peer=True,
                        notify_peers=notify_peers,
                    )
        trusts.delete()
        step()
        buckets = attribute.Buckets(actor_id=self.id, config=self.config)
        buckets.delete()
        # A backend that answers False for a row that is already gone (a
        # conditional delete, a repeated call) is told apart from one that
        # did not confirm the removal by a strict read.
        gone = bool(self.handle.delete()) or self._row_strict() is None
        if gone and _pre_reads is None and self.config:
            # Not called by the finisher (which marks its own tombstone):
            # start the tombstone's retention TTL, or it would stay
            # unfinished, with no TTL, for ever.
            deletion.finish_unleased(self.id, self.config)
        return gone

    def _row_strict(self) -> dict[str, Any] | None:
        """This actor's row, read strictly (``DbError`` on a fault)."""
        from .db import get_actor

        if not self.config:
            return None
        db = get_actor(self.config)
        row = db.get(actor_id=self.id)
        return row if row else None

    ######################
    # Advanced operations
    ######################

    def set_property(self, name, value):
        """Sets an actor's property name to value. (DEPRECATED, use actor's property store!)"""
        if self.property:
            self.property[name] = value

    def get_property(self, name):
        """Retrieves a property object named name. (DEPRECATED, use actor's property store!)"""
        return DummyPropertyClass(self.property[name] if self.property else None)

    def delete_property(self, name):
        """Deletes a property name. (DEPRECATED, use actor's property store!)"""
        if self.property:
            self.property[name] = None

    def delete_properties(self):
        """Deletes all properties."""
        if not self.property_list:
            self.property_list = property.Properties(
                actor_id=self.id, config=self.config
            )
        return self.property_list.delete()

    def get_properties(self):
        """Retrieves properties from db and returns a dict."""
        self.property_list = property.Properties(actor_id=self.id, config=self.config)
        return self.property_list.fetch()

    def delete_peer_trustee(
        self,
        shorttype: str | None = None,
        peerid: str | None = None,
        notify_peers: bool = True,
    ) -> bool:
        if not peerid and not shorttype:
            return False
        if shorttype == "*":
            if self.config and self.config.actors:
                for t in self.config.actors:
                    self.delete_peer_trustee(shorttype=t, notify_peers=notify_peers)
            return True
        if (
            shorttype
            and self.config
            and self.config.actors
            and shorttype not in self.config.actors
        ):
            logger.error(f"Got a request to delete an unknown actor type({shorttype})")
            return False
        peer_data = None
        new_peer = None
        if peerid:
            new_peer = peertrustee.PeerTrustee(
                actor_id=self.id, peerid=peerid, config=self.config
            )
            peer_data = new_peer.get()
            if (
                isinstance(peer_data, bool)
                or not peer_data
                or (isinstance(peer_data, dict) and len(peer_data) == 0)
            ):
                return False
        elif shorttype:
            new_peer = peertrustee.PeerTrustee(
                actor_id=self.id, short_type=shorttype, config=self.config
            )
            peer_data = new_peer.get()
            if (
                isinstance(peer_data, bool)
                or not peer_data
                or (isinstance(peer_data, dict) and len(peer_data) == 0)
            ):
                return False
        if not peer_data or isinstance(peer_data, bool):
            return False
        if notify_peers:
            logger.info(f"Deleting peer actor at {peer_data['baseuri']}")
            u_p = b"trustee:" + peer_data["passphrase"].encode("utf-8")
            headers = {
                "Authorization": "Basic " + base64.b64encode(u_p).decode("utf-8"),
            }
            try:
                response = requests.delete(
                    url=peer_data["baseuri"], headers=headers, timeout=(5, 10)
                )
                self.last_response_code = response.status_code
                self.last_response_message = (
                    response.content.decode("utf-8", "ignore")
                    if isinstance(response.content, bytes)
                    else str(response.content)
                )
            except Exception:  # folds DbError: peer HTTP only
                logger.debug(
                    "Not able to delete peer actor remotely due to network issues"
                )
                self.last_response_code = 408
                return False
            # 404: the remote actor is already gone, for example after an
            # earlier attempt whose local cleanup below raised; finish it.
            if response.status_code != 404 and (
                response.status_code < 200 or response.status_code > 299
            ):
                logger.debug(
                    "Not able to delete peer actor remotely, peer is unwilling"
                )
                return False
        # Delete trust, peer is already deleted remotely
        if peer_data and not self.delete_reciprocal_trust(
            peerid=peer_data["peerid"], delete_peer=False, notify_peers=notify_peers
        ):
            logger.debug("Not able to delete peer actor trust in db")
        if new_peer and not new_peer.delete():
            logger.debug("Not able to delete peer actor in db")
            return False
        return True

    def get_peer_trustee(self, shorttype=None, peerid=None):
        """Get a peer, either existing or create it as trustee

        Will retrieve an existing peer or create a new and establish trust.
        If no trust exists, a new trust will be established.
        Use either peerid to target a specific known peer, or shorttype to
        allow creation of a new peer if none exists
        """
        if not peerid and not shorttype:
            return None
        if (
            shorttype
            and self.config
            and self.config.actors
            and shorttype not in self.config.actors
        ):
            logger.error(f"Got a request to create an unknown actor type({shorttype})")
            return None
        if peerid:
            new_peer = peertrustee.PeerTrustee(
                actor_id=self.id, peerid=peerid, config=self.config
            )
        else:
            new_peer = peertrustee.PeerTrustee(
                actor_id=self.id, short_type=shorttype, config=self.config
            )
        peer_data = new_peer.get()
        if peer_data and not isinstance(peer_data, bool) and len(peer_data) > 0:
            logger.debug("Found peer in getPeer, now checking existing trust...")
            dbtrust = trust.Trust(
                actor_id=self.id, peerid=peer_data["peerid"], config=self.config
            )
            new_trust = dbtrust.get()
            if new_trust and len(new_trust) > 0:
                return peer_data
            logger.debug("Did not find existing trust, will create a new one")
        factory = ""
        if (
            self.config
            and self.config.actors
            and shorttype
            and shorttype in self.config.actors
        ):
            factory = self.config.actors[shorttype]["factory"]
        # If peer did not exist, create it as trustee
        if not peer_data or isinstance(peer_data, bool) or len(peer_data) == 0:
            if len(factory) == 0:
                logger.error(
                    f"Peer actor of shorttype({shorttype}) does not have factory set."
                )
            params = {
                "creator": "trustee",
                "trustee_root": (self.config.root + self.id) if self.config else "",
            }
            data = json.dumps(params)
            logger.debug(f"Creating peer actor at factory({factory})")
            response = None
            try:
                response = requests.post(
                    url=factory,
                    data=data,
                    timeout=(5, 10),
                    headers={"Content-Type": "application/json"},
                )
                if response:
                    self.last_response_code = response.status_code
                    self.last_response_message = (
                        response.content.decode("utf-8", "ignore")
                        if isinstance(response.content, bytes)
                        else str(response.content)
                    )
            except Exception:  # folds DbError: peer HTTP only
                logger.debug("Not able to create new peer actor")
                self.last_response_code = 408
            logger.info(f"Created peer actor, response code: {self.last_response_code}")
            if self.last_response_code < 200 or self.last_response_code > 299:
                return None
            try:
                if response and response.content:
                    content_str = (
                        response.content.decode("utf-8", "ignore")
                        if isinstance(response.content, bytes)
                        else str(response.content)
                    )
                    data = json.loads(content_str)
                else:
                    data = {}
            except (TypeError, ValueError, KeyError):
                logger.warning(
                    f"Not able to parse response when creating peer at factory({factory})"
                )
                return None
            if response and "Location" in response.headers:
                baseuri = response.headers["Location"]
            elif response and "location" in response.headers:
                baseuri = response.headers["location"]
            else:
                logger.warning(
                    "No location uri found in response when creating a peer as trustee"
                )
                baseuri = ""
            res = self.get_peer_info(baseuri)
            if (
                not res
                or res["last_response_code"] < 200
                or res["last_response_code"] >= 300
            ):
                return None
            info_peer = res["data"]
            if (
                not info_peer
                or ("id" in info_peer and not info_peer["id"])
                or ("type" in info_peer and not info_peer["type"])
            ):
                logger.info(
                    f"Received invalid peer info when trying to create peer actor at: {factory}"
                )
                return None
            new_peer = peertrustee.PeerTrustee(
                actor_id=self.id,
                peerid=info_peer["id"],
                peer_type=info_peer["type"],
                config=self.config,
            )
            if not new_peer.create(baseuri=baseuri, passphrase=data["passphrase"]):
                logger.error(
                    f"Failed to create in db new peer Actor({self.id}) at {baseuri}"
                )
                return None
        # Now peer exists, create trust
        new_peer_data = new_peer.get()
        if not new_peer_data or isinstance(new_peer_data, bool):
            return None
        secret = self.config.new_token() if self.config else ""
        relationship = ""
        if (
            self.config
            and self.config.actors
            and shorttype
            and shorttype in self.config.actors
        ):
            relationship = self.config.actors[shorttype]["relationship"]
        new_trust = self.create_reciprocal_trust(
            url=new_peer_data["baseuri"],
            secret=secret,
            desc="Trust from trustee to " + (shorttype or ""),
            relationship=relationship,
        )
        if not new_trust or len(new_trust) == 0:
            logger.warning(
                f"Not able to establish trust relationship with peer at factory({factory})"
            )
        else:
            # Approve the relationship
            params = {
                "approved": True,
            }
            u_p = b"trustee:" + new_peer_data["passphrase"].encode("utf-8")
            headers = {
                "Authorization": "Basic " + base64.b64encode(u_p).decode("utf-8"),
                "Content-Type": "application/json",
            }
            data = json.dumps(params)
            try:
                response = requests.put(
                    url=new_peer_data["baseuri"]
                    + "/trust/"
                    + relationship
                    + "/"
                    + (self.id or ""),
                    data=data,
                    headers=headers,
                    timeout=(5, 10),
                )
                if response:
                    self.last_response_code = response.status_code
                    self.last_response_message = (
                        response.content.decode("utf-8", "ignore")
                        if isinstance(response.content, bytes)
                        else str(response.content)
                    )
            except Exception:  # folds DbError: peer HTTP only
                self.last_response_code = 408
                self.last_response_message = (
                    "Not able to approve peer actor trust remotely"
                )
            if self.last_response_code < 200 or self.last_response_code > 299:
                logger.debug("Not able to delete peer actor remotely")
        return new_peer_data

    def get_trust_relationship(self, peerid=None):
        if not peerid:
            return None
        return trust.Trust(actor_id=self.id, peerid=peerid, config=self.config).get()

    def get_trust_relationships(self, relationship="", peerid="", trust_type=""):
        """Retrieves all trust relationships or filtered."""
        trust_list = trust.Trusts(actor_id=self.id, config=self.config)
        relationships = trust_list.fetch()
        rels = []
        if relationships:
            for rel in relationships:
                if isinstance(rel, dict):
                    if len(relationship) > 0 and relationship != rel.get(
                        "relationship", ""
                    ):
                        continue
                    if len(peerid) > 0 and peerid != rel.get("peerid", ""):
                        continue
                    if len(trust_type) > 0 and trust_type != rel.get("type", ""):
                        continue
                rels.append(rel)
        return rels

    def modify_trust_and_notify(
        self,
        relationship=None,
        peerid=None,
        baseuri="",
        secret="",
        desc="",
        approved=None,
        verified=None,
        verification_token=None,
        peer_approved=None,
        # Client metadata for OAuth2 clients
        client_name=None,
        client_version=None,
        client_platform=None,
        oauth_client_id=None,
        # Connection tracking
        last_accessed=None,
        last_connected_via=None,
    ):
        """Changes a trust relationship and notifies the peer if approval is
        changed. ``approved``, ``verified`` and ``peer_approved`` are a bool
        or ``"true"``/``"false"``; anything else raises ``ValueError``
        (3.16), before anything is read or written."""
        # Text is a flag here too: "true" meets the approval gate, the
        # binding to the row read and the peer's notification below.
        approved = trust.as_flag(approved)
        verified = trust.as_flag(verified)
        peer_approved = trust.as_flag(peer_approved)
        if not relationship or not peerid:
            return False
        relationships = self.get_trust_relationships(
            relationship=relationship, peerid=peerid
        )
        if not relationships:
            return False
        this_trust = relationships[0]
        if (
            approved is True
            and not this_trust.get("approved")
            and not this_trust.get("verified")
            and not self.reverify_pending_trust(peerid)
        ):
            # Only a verified row is approved (3.16): its secret is whatever
            # the requester chose, and anyone can file a request under a
            # peer's id (Trust.modify refuses the write as well).
            logger.warning(
                f"Refused to approve the trust with {peerid}: the request is "
                "not verified (create the trust toward the peer's URL instead)"
            )
            return False

        # IMPORTANT: Save approval to database BEFORE notifying peer
        # This prevents race condition where peer tries to subscribe back
        # before our approval is saved
        dbtrust = trust.Trust(actor_id=self.id, peerid=peerid, config=self.config)
        try:
            result = dbtrust.modify(
                baseuri=baseuri,
                secret=secret,
                desc=desc,
                approved=approved,
                verified=verified,
                verification_token=verification_token,
                peer_approved=peer_approved,
                client_name=client_name,
                client_version=client_version,
                client_platform=client_platform,
                oauth_client_id=oauth_client_id,
                last_accessed=last_accessed,
                last_connected_via=last_connected_via,
                # An approval lands on the row read above, or not at all: a
                # row replaced meanwhile (another request) is not approved
                # unseen, and the peer is told with the secret it holds.
                only_if_secret=(
                    str(this_trust.get("secret") or "") or None
                    if approved is True
                    else None
                ),
            )
        except DbError:
            raise
        except Exception as e:
            logger.error(f"Exception in dbtrust.modify: {e}", exc_info=True)
            return False
        if not result:
            # Not written (the row is gone, replaced, or not verified): the
            # peer is not told anything changed.
            logger.warning(f"The trust with {peerid} was not modified")
            return False

        # Now that approval is saved, notify peer so their auto-subscribe will succeed
        headers = {}
        if approved is True and this_trust["approved"] is False:
            params = {
                "approved": True,
            }
            # The base URI this call wrote, else the row's as it stands after
            # the write (3.16: the notification went to the URL the row had
            # before, also when another request had moved it meanwhile).
            if not baseuri:
                try:
                    after: Any = trust.Trust(
                        actor_id=self.id, peerid=peerid, config=self.config
                    ).get()
                except DbError as e:  # folds DbError: the approval committed
                    # The peer is still told, at the URL read before the
                    # write: a 503 now would leave it never told (a retry
                    # finds the row approved and sends nothing).
                    logger.warning(f"Re-read of the trust with {peerid} failed: {e}")
                    after = None
                if after and not secret_equals(
                    str(after.get("secret") or ""), str(this_trust["secret"] or "")
                ):
                    # Replaced since (a re-pair): its base URI is not where
                    # this row's secret goes; the URL read before stands.
                    after = None
                baseuri_now = str((after or this_trust).get("baseuri") or "")
            else:
                baseuri_now = baseuri
            requrl = baseuri_now + "/trust/" + relationship + "/" + self.id
            if this_trust["secret"]:
                headers = {
                    "Authorization": "Bearer " + this_trust["secret"],
                    "Content-Type": "application/json",
                }
            data = json.dumps(params)
            # Note the POST here instead of PUT. POST is used to used to notify about
            # state change in the relationship (i.e. not change the object as PUT
            # would do)
            logger.debug(
                "Trust relationship has been approved, notifying peer at url("
                + requrl
                + ")"
            )
            try:
                response = requests.post(
                    url=requrl, data=data, headers=headers, timeout=(5, 10)
                )
                self.last_response_code = response.status_code
                self.last_response_message = (
                    response.content.decode("utf-8", "ignore")
                    if isinstance(response.content, bytes)
                    else str(response.content)
                )
            except Exception:  # folds DbError: peer HTTP only
                logger.debug("Not able to notify peer at url(" + requrl + ")")
                self.last_response_code = 500
        return result

    async def modify_trust_and_notify_async(
        self,
        relationship: str | None = None,
        peerid: str | None = None,
        baseuri: str = "",
        secret: str = "",
        desc: str = "",
        approved: bool | None = None,
        verified: bool | None = None,
        verification_token: str | None = None,
        peer_approved: bool | None = None,
        # Client metadata for OAuth2 clients
        client_name: str | None = None,
        client_version: str | None = None,
        client_platform: str | None = None,
        oauth_client_id: str | None = None,
        # Connection tracking
        last_accessed: Any = None,
        last_connected_via: str | None = None,
    ) -> Any:
        """Async version of modify_trust_and_notify: the same change and the
        same peer notification, run off the event loop.

        Delegates to the sync method in a worker thread, so the two cannot
        drift: the notification is the ``POST trust/<rel>/<id>`` the peer
        handles as an approval, with the same error handling around the
        trust write. (Until 3.16 this method built its own proxy with a peer
        target ``AwProxy`` cannot read, so it never notified the peer.)
        ``asyncio.to_thread`` copies context variables, so request
        correlation carries over. Cancelling the await does not stop the
        worker thread: the trust write and the notification still complete,
        so a caller that times out should re-read the trust rather than retry
        the change.
        """
        import asyncio

        return await asyncio.to_thread(
            self.modify_trust_and_notify,
            relationship=relationship,
            peerid=peerid,
            baseuri=baseuri,
            secret=secret,
            desc=desc,
            approved=approved,
            verified=verified,
            verification_token=verification_token,
            peer_approved=peer_approved,
            client_name=client_name,
            client_version=client_version,
            client_platform=client_platform,
            oauth_client_id=oauth_client_id,
            last_accessed=last_accessed,
            last_connected_via=last_connected_via,
        )

    def create_reciprocal_trust(
        self,
        url,
        secret=None,
        desc="",
        relationship="",  # trust type/permission level (e.g., "friend", "admin") - goes in URL
        trust_type="",  # peer's expected ActingWeb mini-app type for validation (optional)
    ):
        """Creates a new reciprocal trust relationship locally and by requesting a relationship from a peer actor.

        Args:
            relationship: The trust type/permission level to request (friend, admin, etc.)
            trust_type: Expected peer mini-app type for validation (optional)
        """
        # Whether this call approved a waiting request instead of sending
        # one: set by _approve_on_create, read by TrustManager for its hook.
        self.last_trust_approved_on_create = None
        if len(url) == 0:
            return False
        from .trust import is_valid_peer_baseuri

        if not is_valid_peer_baseuri(url):
            # Stored as the peer's base URI: the same shape a peer must
            # give when it asks us.
            logger.warning("Refused to request trust from an invalid peer URL")
            return False
        if not secret or len(secret) == 0:
            return False
        res = self.get_peer_info(url)
        if (
            not res
            or res["last_response_code"] < 200
            or res["last_response_code"] >= 300
        ):
            return False
        peer = res["data"]
        from .trust import is_valid_peer_id

        if not is_valid_peer_id(peer.get("id")):
            # The peer names itself: refuse an id that is not plainly one
            # (it is shown to the owner and built into links).
            logger.warning(
                "Received an invalid peer id when trying to establish trust: %r",
                url,
            )
            return False
        if not peer["id"] or not peer["type"] or len(peer["type"]) == 0:
            logger.info(
                "Received invalid peer info when trying to establish trust: " + url
            )
            return False
        if len(trust_type) > 0:
            if trust_type.lower() != peer["type"].lower():
                logger.info("Peer is of the wrong actingweb type: " + peer["type"])
                return False
        if not relationship or len(relationship) == 0:
            relationship = self.config.default_relationship if self.config else ""
        existing = trust.Trust(
            actor_id=self.id, peerid=peer["id"], config=self.config
        ).get()
        if (
            existing
            and self._is_unproven_pending(existing)
            and not self._re_pair_refusal(url, existing, relationship)
            and self.reverify_pending_trust(peer["id"])
        ):
            # A genuine request whose first verification failed (a timeout,
            # say) verifies now: it is approved below, not replaced, so the
            # peer's own row still matches ours. Only one for this
            # relationship at this URL: any other is replaced as before.
            existing = trust.Trust(
                actor_id=self.id, peerid=peer["id"], config=self.config
            ).get()
        replace_pending = self._is_unproven_pending(existing)
        if existing and replace_pending:
            # A request nobody proved (unverified, unapproved): anyone can
            # file one under the peer's id. It is replaced by this owner's own
            # request, with this owner's secret, never approved as it is.
            logger.warning(
                f"Replacing an unverified pending trust request for {peer['id']} "
                "with this actor's own request"
            )
        elif existing:
            # A re-pair: our row stays as it is until the peer accepts.
            refusal = self._re_pair_refusal(url, existing, relationship)
            if refusal:
                logger.warning(f"Not re-pairing with {peer['id']}: {refusal}")
                return False
            if not existing.get("approved"):
                # The peer's verified request waits for this owner: creating
                # the trust approves it, and the peer is told.
                return self._approve_on_create(peer["id"], existing)
            request = self._re_pair_request(existing, secret, desc, relationship)
            try:
                response = requests.post(
                    url=request["url"],
                    data=request["data"],
                    timeout=(5, 10),
                    headers=request["headers"],
                )
            except Exception as e:  # folds DbError: peer HTTP only
                return self._re_pair_unknown(
                    peer["id"], existing, secret, relationship, f"no answer ({e})"
                )
            if response.status_code >= 500:
                return self._re_pair_unknown(
                    peer["id"],
                    existing,
                    secret,
                    relationship,
                    f"{response.status_code} {response.reason}",
                )
            return self._finish_re_pair(
                peer["id"], secret, response.status_code, response.reason
            )
        # Create trust, so that peer can do a verify on the relationship (using
        # verification_token) when we request the relationship
        dbtrust = trust.Trust(actor_id=self.id, peerid=peer["id"], config=self.config)
        if not dbtrust.create(
            baseuri=url,
            secret=secret,
            peer_type=peer["type"],
            relationship=relationship,
            approved=True,
            verified=True,  # Requesting actor has verified=True by default per ActingWeb spec
            desc=desc,
            established_via="trust",
            only_if_absent=not replace_pending,
            only_if_pending=replace_pending,
        ):
            logger.warning(
                "Trying to establish a new Reciprocal trust when peer relationship already exists ("
                + peer["id"]
                + ")"
            )
            return False
        # Since we are initiating the relationship, we implicitly approve it
        # It is not verified until the peer has verified us
        new_trust = dbtrust.get()
        params = {
            "baseuri": (self.config.root if self.config else "") + (self.id or ""),
            "id": self.id,
            "type": self.config.aw_type if self.config else "",
            "secret": secret,
            "desc": desc,
            "verify": new_trust["verification_token"] if new_trust else "",
        }
        requrl = url + "/trust/" + relationship
        data = json.dumps(params)
        logger.debug(
            f"Creating reciprocal trust at url({requrl}) for peer {params.get('id', 'unknown')}"
        )
        try:
            response = requests.post(
                url=requrl,
                data=data,
                timeout=(5, 10),
                headers={
                    "Content-Type": "application/json",
                },
            )
            self.last_response_code = response.status_code
            self.last_response_message = (
                response.content.decode("utf-8", "ignore")
                if isinstance(response.content, bytes)
                else str(response.content)
            )
        except Exception:  # folds DbError: peer HTTP only
            logger.debug("Not able to create trust with peer, deleting my trust.")
            self._drop_failed_attempt(peer["id"], secret)
            return False
        if self.last_response_code == 201 or self.last_response_code == 202:
            # Reload the trust to check if approval was done
            mod_trust = trust.Trust(
                actor_id=self.id, peerid=peer["id"], config=self.config
            )
            mod_trust_data = mod_trust.get()
            if not mod_trust_data or len(mod_trust_data) == 0:
                logger.error(
                    "Couldn't find trust relationship after peer POST and verification"
                )
                return False
            if self.last_response_code == 201:
                # Already approved by peer (probably auto-approved)
                # Do it direct on the trust (and not self.modifyTrustAndNotify) to avoid a callback
                # to the peer
                mod_trust.modify(peer_approved=True)
            return mod_trust.get()
        else:
            logger.debug("Not able to create trust with peer, deleting my trust.")
            self._drop_failed_attempt(peer["id"], secret)
            return False

    async def create_reciprocal_trust_async(
        self,
        url,
        secret=None,
        desc="",
        relationship="",
        trust_type="",
    ):
        """Async version of create_reciprocal_trust - prevents blocking on peer HTTP calls.

        Creates a new reciprocal trust relationship locally and by requesting a relationship from a peer actor.
        """
        # Whether this call approved a waiting request instead of sending
        # one: set by _approve_on_create, read by TrustManager for its hook.
        self.last_trust_approved_on_create = None
        if len(url) == 0:
            return False
        from .trust import is_valid_peer_baseuri

        if not is_valid_peer_baseuri(url):
            # Stored as the peer's base URI: the same shape a peer must
            # give when it asks us.
            logger.warning("Refused to request trust from an invalid peer URL")
            return False
        if not secret or len(secret) == 0:
            return False

        # Get peer info async
        res = await self.get_peer_info_async(url)
        if (
            not res
            or res["last_response_code"] < 200
            or res["last_response_code"] >= 300
        ):
            return False
        peer = res["data"]
        from .trust import is_valid_peer_id

        if not is_valid_peer_id(peer.get("id")):
            # The peer names itself: see create_reciprocal_trust().
            logger.warning(
                "Received an invalid peer id when trying to establish trust: %r",
                url,
            )
            return False
        if not peer.get("id") or not peer.get("type") or len(peer["type"]) == 0:
            logger.info(
                "Received invalid peer info when trying to establish trust: " + url
            )
            return False
        if len(trust_type) > 0:
            if trust_type.lower() != peer["type"].lower():
                logger.info("Peer is of the wrong actingweb type: " + peer["type"])
                return False
        if not relationship or len(relationship) == 0:
            relationship = self.config.default_relationship if self.config else ""

        import httpx

        existing = trust.Trust(
            actor_id=self.id, peerid=peer["id"], config=self.config
        ).get()
        if (
            existing
            and self._is_unproven_pending(existing)
            and not self._re_pair_refusal(url, existing, relationship)
            and await asyncio.to_thread(self.reverify_pending_trust, peer["id"])
        ):
            # See create_reciprocal_trust(): a request that verifies now is
            # approved, not replaced.
            existing = trust.Trust(
                actor_id=self.id, peerid=peer["id"], config=self.config
            ).get()
        replace_pending = self._is_unproven_pending(existing)
        if existing and replace_pending:
            # See create_reciprocal_trust(): an unproven request is replaced.
            logger.warning(
                f"Replacing an unverified pending trust request for {peer['id']} "
                "with this actor's own request"
            )
        elif existing:
            # A re-pair: our row stays as it is until the peer accepts.
            refusal = self._re_pair_refusal(url, existing, relationship)
            if refusal:
                logger.warning(f"Not re-pairing with {peer['id']}: {refusal}")
                return False
            if not existing.get("approved"):
                # The peer's verified request waits for this owner: creating
                # the trust approves it, and the peer is told.
                return await asyncio.to_thread(
                    self._approve_on_create, peer["id"], existing
                )
            request = self._re_pair_request(existing, secret, desc, relationship)
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.post(
                        request["url"],
                        content=request["data"],
                        headers=request["headers"],
                    )
            except Exception as e:  # folds DbError: peer HTTP only (InvalidURL too)
                return await self._re_pair_unknown_async(
                    peer["id"], existing, secret, relationship, f"no answer ({e})"
                )
            if response.status_code >= 500:
                return await self._re_pair_unknown_async(
                    peer["id"],
                    existing,
                    secret,
                    relationship,
                    f"{response.status_code} {response.reason_phrase}",
                )
            return self._finish_re_pair(
                peer["id"], secret, response.status_code, response.reason_phrase
            )

        # Create trust locally (synchronous DB operation)
        dbtrust = trust.Trust(actor_id=self.id, peerid=peer["id"], config=self.config)
        if not dbtrust.create(
            baseuri=url,
            secret=secret,
            peer_type=peer["type"],
            relationship=relationship,
            approved=True,
            verified=True,
            desc=desc,
            established_via="trust",
            only_if_absent=not replace_pending,
            only_if_pending=replace_pending,
        ):
            logger.warning(
                f"Trying to establish a new Reciprocal trust when peer relationship already exists ({peer['id']})"
            )
            return False

        # Request relationship from peer async
        new_trust = dbtrust.get()
        params = {
            "baseuri": (self.config.root if self.config else "") + (self.id or ""),
            "id": self.id,
            "type": self.config.aw_type if self.config else "",
            "secret": secret,
            "desc": desc,
            "verify": new_trust["verification_token"] if new_trust else "",
        }

        requrl = url + "/trust/" + relationship
        data = json.dumps(params)
        # The body carries the new trust secret and verification token.
        if logger.isEnabledFor(logging.INFO):
            logger.info(
                f"Requesting trust relationship async from peer at ({requrl}) with "
                f"data({summarize_payload(params, encoded_len=len(data))})"
            )
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    requrl,
                    content=data,
                    headers={"Content-Type": "application/json"},
                )
                self.last_response_code = response.status_code
                self.last_response_message = (
                    response.content.decode("utf-8", "ignore")
                    if isinstance(response.content, bytes)
                    else str(response.content)
                )
        except httpx.TimeoutException:
            logger.debug("Timeout creating trust with peer async, deleting my trust.")
            self._drop_failed_attempt(peer["id"], secret)
            return False
        except Exception as e:  # folds DbError: peer HTTP only
            # Any failure of the request drops the attempt, as the sync twin
            # does (3.16: an exception that was not an httpx error, an
            # invalid URL say, left the half-made row behind).
            logger.debug(
                f"Not able to create trust with peer async: {e}, deleting my trust."
            )
            self._drop_failed_attempt(peer["id"], secret)
            return False

        if self.last_response_code == 201 or self.last_response_code == 202:
            # Reload trust to check if approval was done
            mod_trust = trust.Trust(
                actor_id=self.id, peerid=peer["id"], config=self.config
            )
            mod_trust_data = mod_trust.get()
            if not mod_trust_data or len(mod_trust_data) == 0:
                logger.error(
                    "Couldn't find trust relationship after peer POST and verification"
                )
                return False
            if self.last_response_code == 201:
                # Already approved by peer (probably auto-approved)
                mod_trust.modify(peer_approved=True)
            return mod_trust.get()
        else:
            logger.debug("Not able to create trust with peer async, deleting my trust.")
            self._drop_failed_attempt(peer["id"], secret)
            return False

    def reverify_pending_trust(self, peerid: str) -> bool:
        """Whether the trust row for ``peerid`` is verified, re-running the
        creation's verification for one that is not (3.16).

        A row stored unverified holds the secret its requester chose. Before
        anything approves it, ask the host at its base URI for our own trust
        row there with that secret as bearer (as the lost-answer probe does):
        only a host holding the secret answers with a row naming us, and the
        row must be one that host approved (an initiator's own row is). A
        pending row filed there under our id by whoever filed this one holds
        the same secret, so an unapproved answer proves nothing. The base
        URI's ``/meta`` must name the peer too, as at creation. A pass marks
        the row verified, conditioned on its secret being unchanged."""
        current = trust.Trust(actor_id=self.id, peerid=peerid, config=self.config)
        row = current.get()
        if not row:
            return False
        if row.get("verified"):
            return True
        secret = str(row.get("secret") or "")
        if not secret:
            return False
        url, headers = self._re_pair_probe_request(
            row, secret, str(row.get("relationship") or "")
        )
        deadline = _verification_deadline()
        status, body = _bounded_get_json(url, headers, deadline)
        if not (
            isinstance(status, int)
            and 200 <= status < 300
            and isinstance(body, dict)
            and body.get("peerid") == self.id
            and _answered_by_approved_row(body)
        ):
            logger.warning(
                f"The trust request from {peerid} did not verify on a second "
                f"check (status {status})"
            )
            return False
        if not self._base_uri_serves(str(row.get("baseuri") or ""), peerid, deadline):
            logger.warning(
                f"The trust request from {peerid} verified, but its base URI "
                "does not serve that actor"
            )
            return False
        if not current.modify(verified=True, only_if_secret=secret):
            return False
        logger.info(f"The trust request from {peerid} verified on a second check")
        return True

    def _drop_failed_attempt(self, peerid: str, attempt_secret: str) -> None:
        """Delete this call's own row after the peer refused or did not
        answer: only while it still holds the secret this attempt wrote (a
        row another request wrote meanwhile stays) and the peer has not
        approved it (an approval whose answer was lost keeps the trust). The
        read and the delete are two steps: a row replaced between them is a
        narrow window this accepts."""
        current = trust.Trust(actor_id=self.id, peerid=peerid, config=self.config)
        row = current.get()
        if not row:
            return
        if row.get("secret") != attempt_secret:
            logger.warning(
                f"Kept the trust row for {peerid}: another request replaced this "
                "attempt's row"
            )
        elif row.get("peer_approved"):
            logger.warning(
                f"Kept the trust row for {peerid}: the peer approved it, though "
                "its answer to the request was lost"
            )
        else:
            current.delete()

    @staticmethod
    def _is_unproven_pending(existing: dict[str, Any] | None) -> bool:
        """A row nobody proved or accepted (neither verified nor approved):
        an initiator replaces it with its own request instead of approving
        it, since its secret is whatever its requester chose."""
        return bool(existing) and not (
            (existing or {}).get("verified") or (existing or {}).get("approved")
        )

    def _approve_on_create(
        self, peerid: str, existing: dict[str, Any]
    ) -> dict[str, Any] | bool:
        """Approve a peer's pending request when this actor's owner creates
        the trust toward it, notifying the peer as an approval does."""
        if not self.modify_trust_and_notify(
            relationship=existing.get("relationship"), peerid=peerid, approved=True
        ):
            logger.warning(f"Could not approve the pending trust with {peerid}")
            return False
        logger.info(f"Approved the pending trust request from {peerid}")
        self.last_trust_approved_on_create = peerid
        return (
            trust.Trust(actor_id=self.id, peerid=peerid, config=self.config).get()
            or False
        )

    @staticmethod
    def _re_pair_refusal(url: str, existing: dict[str, Any], relationship: str) -> str:
        """Why a re-pair must not be sent, or "".

        The current secret goes out as the bearer, so the request goes only
        to the stored base URI: a URL whose ``/meta`` merely claims the
        peer's id gets nothing (a moved peer is re-pointed by updating the
        base URI first). A different relationship is a delete and a new
        pairing, not a re-pair."""
        stored = str(existing.get("baseuri") or "").rstrip("/")
        if not stored or url.rstrip("/") != stored:
            return (
                "the URL is not the trust's stored base URI (a moved peer: "
                "update the base URI with PUT /trust/<rel>/<peer> first)"
            )
        if (existing.get("relationship") or "") != (relationship or ""):
            return (
                f"the trust is '{existing.get('relationship')}', not "
                f"'{relationship}' (delete it and pair again)"
            )
        return ""

    def _re_pair_request(
        self,
        existing: dict[str, Any],
        secret: str,
        desc: str,
        relationship: str,
    ) -> dict[str, Any]:
        """The trust request for a peer this actor already trusts, to its
        stored base URI: the new secret in the body, the current one as the
        bearer (the peer accepts a re-pair only from the holder of the
        current secret)."""
        params = {
            "baseuri": (self.config.root if self.config else "") + (self.id or ""),
            "id": self.id,
            "type": self.config.aw_type if self.config else "",
            "secret": secret,
            "desc": desc,
            "verify": existing.get("verification_token") or "",
        }
        return {
            "url": str(existing.get("baseuri") or "").rstrip("/")
            + "/trust/"
            + relationship,
            "data": json.dumps(params),
            "headers": {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {existing.get('secret') or ''}",
            },
        }

    def _re_pair_probe_request(
        self, existing: dict[str, Any], secret: str, relationship: str
    ) -> tuple[str, dict[str, str]]:
        """The GET that asks the peer whether it holds ``secret`` for us: our
        own trust row at the stored base URI, the new secret as bearer."""
        url = (
            str(existing.get("baseuri") or "").rstrip("/")
            + f"/trust/{relationship}/{self.id}"
        )
        return url, {"Authorization": f"Bearer {secret}"}

    def _re_pair_probed(
        self, peerid: str, secret: str, status: int | None, body: Any, why: str
    ) -> dict[str, Any] | bool:
        """Finish a re-pair whose answer was lost, from the probe's result."""
        # 200 approved, 202 pending: either way the peer authenticated the
        # new secret, so it holds it; only if the answer is our trust row
        # there (a proxy or catch-all page answering 200 proves nothing).
        if (
            status in (200, 202)
            and isinstance(body, dict)
            and body.get("peerid") == self.id
        ):
            approved = str(body.get("approved")).lower() == "true"
            logger.info(
                f"Re-pairing with {peerid}: the answer was lost ({why}), but the "
                "peer holds the new secret"
            )
            return self._finish_re_pair(
                peerid, secret, 201 if approved else 202, "confirmed by a probe"
            )
        logger.warning(
            f"Re-pairing with {peerid}: no answer ({why}), and the peer did not "
            f"confirm the new secret (probe: {status}); the existing trust is "
            "unchanged here. If requests to the peer now answer 401 or 403 with "
            "the existing secret, the peer accepted it: delete the trust on both "
            "sides (?notify=false) and pair again"
        )
        return False

    def _re_pair_unknown(
        self,
        peerid: str,
        existing: dict[str, Any],
        secret: str,
        relationship: str,
        why: str,
    ) -> dict[str, Any] | bool:
        """The re-pair's answer was lost or a server error: the peer may have
        swapped the secret. Ask it, with the new secret."""
        url, headers = self._re_pair_probe_request(existing, secret, relationship)
        try:
            probe = requests.get(url=url, headers=headers, timeout=(5, 10))
            status: int | None = probe.status_code
            try:
                body: Any = probe.json() if status in (200, 202) else None
            except ValueError:
                body = None
        except Exception:  # folds DbError: peer HTTP only
            status, body = None, None
        return self._re_pair_probed(peerid, secret, status, body, why)

    async def _re_pair_unknown_async(
        self,
        peerid: str,
        existing: dict[str, Any],
        secret: str,
        relationship: str,
        why: str,
    ) -> dict[str, Any] | bool:
        """Async twin of ``_re_pair_unknown``."""
        import httpx

        url, headers = self._re_pair_probe_request(existing, secret, relationship)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                probe = await client.get(url, headers=headers)
            status: int | None = probe.status_code
            try:
                body: Any = probe.json() if status in (200, 202) else None
            except ValueError:
                body = None
        except Exception:  # folds DbError: peer HTTP only (InvalidURL too)
            status, body = None, None
        return self._re_pair_probed(peerid, secret, status, body, why)

    def _finish_re_pair(
        self, peerid: str, secret: str, status: int, reason: str
    ) -> dict[str, Any] | bool:
        """Store the new secret once the peer accepted the re-pair (201 or
        202); on anything else leave the existing row as it was."""
        self.last_response_code = status
        if status not in (201, 202):
            logger.warning(
                f"Re-pairing with {peerid} was refused: {status} {reason}; the "
                "existing trust is unchanged (a moved peer is re-pointed by "
                "updating its base URI; a new relationship is a delete and a "
                "new pairing)"
            )
            return False
        current = trust.Trust(actor_id=self.id, peerid=peerid, config=self.config)
        # 201: the peer has approved; 202: it has not (its owner decides).
        if not current.modify(secret=secret, peer_approved=status == 201):
            logger.error(
                f"Re-pairing with {peerid}: the peer accepted the new secret but "
                "storing it failed, so the two sides now hold different secrets; "
                "delete the trust on both sides (?notify=false) and pair again"
            )
            return False
        logger.info(f"Re-paired with {peerid}: the trust's secret was replaced")
        return (
            trust.Trust(actor_id=self.id, peerid=peerid, config=self.config).get()
            or False
        )

    def create_verified_trust(
        self,
        baseuri="",
        peerid=None,
        approved=False,
        secret=None,
        verification_token=None,
        trust_type=None,  # peer's ActingWeb mini-app type (e.g., "urn:actingweb:example.com:banking")
        peer_approved=None,
        relationship=None,  # trust type/permission level (e.g., "friend", "admin", "partner")
        desc="",
    ):
        """Creates a new trust when requested and call backs to initiating actor to verify relationship.

        Args:
            trust_type: The peer's ActingWeb mini-application type URI
            relationship: The trust type/permission level (friend, admin, etc.)
        """
        if not peerid or len(baseuri) == 0 or not relationship:
            return False
        from .trust import is_valid_peer_baseuri, is_valid_peer_id

        if not is_valid_peer_id(peerid) or not is_valid_peer_baseuri(baseuri):
            # Both come from the requesting peer and reach the owner's UI.
            logger.warning("Refused a trust request with an invalid peer id or baseuri")
            return False
        # A creation request never replaces a verified or approved row: that
        # peer re-pairs with ``replace_trust_secret`` (proving its current
        # secret). A pending row (neither verified nor approved: a request
        # nobody proved or accepted) is replaced only by a request that
        # verifies (owner, 2026-11-08).
        existing = trust.Trust(
            actor_id=self.id, peerid=peerid, config=self.config
        ).get()
        if existing and (existing.get("verified") or existing.get("approved")):
            logger.warning(
                f"Refused a trust creation request for {peerid}: a verified or "
                "approved trust row exists"
            )
            return False
        requrl = baseuri + "/trust/" + relationship + "/" + self.id
        verify_deadline: float | None = None
        if not secret or len(secret) == 0:
            logger.debug(
                "No secret received from requesting peer("
                + peerid
                + ") at url ("
                + requrl
                + "). Verification is not possible."
            )
            verified = False
        else:
            headers = {
                "Authorization": "Bearer " + secret,
            }
            logger.debug(
                f"Verifying trust at requesting peer({peerid}) at url ({requrl})"
            )
            # Bounded: an unauthenticated request names this URL (3.16).
            verify_deadline = _verification_deadline()
            status, data = _bounded_get_json(requrl, headers, verify_deadline)
            self.last_response_code = status if status is not None else 408
            self.last_response_message = ""
            if not isinstance(data, dict):
                logger.debug(
                    f"No usable answer when verifying trust at url ({requrl}): "
                    f"status {status}"
                )
                verified = False
            else:
                logger.debug(
                    f"Verifying trust response: verified={data.get('verified', False)}, "
                    f"approved={data.get('approved', False)}, "
                    f"peer_approved={data.get('peer_approved', False)}"
                )
                # The requester's own row must be approved: an initiator
                # creates its row approved before it sends the request, and
                # a pending row anyone filed under the requester's id answers
                # with whatever token its filer chose (3.16, the
                # mirrored-request hole). A 2xx: the spec's "200 OK".
                verified = bool(
                    _answered_by_approved_row(data)
                    and secret_digest_equals(
                        data.get("verification_token"), verification_token
                    )
                )
        if verified and not self._base_uri_serves(baseuri, peerid, verify_deadline):
            # The verification proves only that the requester controls the
            # base URI it sent. Its /meta must also name the peer id, which
            # catches a peer sending the wrong base URI; a hostile host
            # answers its own /meta, so this proves nothing about the id.
            logger.warning(
                f"Trust request for {peerid}: its base URI does not serve that "
                "actor; stored as unverified"
            )
            verified = False
        if approved and not verified:
            # Auto-accept approves only a request that verified (owner,
            # 2026-11-08): an approved row is never replaced, so an
            # unverified one would block the real peer until the owner
            # deletes it. It waits for the owner's approval instead.
            logger.warning(
                f"Trust request for {peerid} did not verify; not approved automatically"
            )
            approved = False
        new_trust = trust.Trust(actor_id=self.id, peerid=peerid, config=self.config)
        if existing:
            # A pending row: replaced only by a request that verified, in one
            # conditional write (it must still be pending), its custom
            # permissions cleared after the write wins.
            if not verified:
                logger.warning(
                    f"Refused a trust creation request for {peerid}: a pending row "
                    "exists and the request did not verify"
                )
                return False
            created = new_trust.create(
                baseuri=baseuri,
                secret=secret or "",
                peer_type=trust_type or "",
                approved=approved,
                peer_approved=peer_approved if peer_approved is not None else False,
                relationship=relationship,
                verified=verified,
                desc=desc,
                established_via="trust",
                only_if_pending=True,
            )
        else:
            # One conditional write: a row created since the read above (a
            # request racing this one) is never replaced.
            created = new_trust.create(
                baseuri=baseuri,
                secret=secret or "",
                peer_type=trust_type or "",
                approved=approved,
                peer_approved=peer_approved if peer_approved is not None else False,
                relationship=relationship,
                verified=verified,
                desc=desc,
                established_via="trust",
                only_if_absent=True,
            )
        if not created:
            logger.warning(
                f"Refused a trust creation request for {peerid}: a row was created "
                "meanwhile"
            )
            return False
        if existing:
            # Logged once the conditional write won, not before it.
            logger.warning(
                f"Trust request for {peerid} replaced its pending row (base URI "
                f"{existing.get('baseuri')} -> {baseuri}); the previous requester's "
                "secret no longer works here"
            )
        return new_trust.get()

    def _base_uri_serves(
        self, baseuri: str, peerid: str, deadline: float | None = None
    ) -> bool:
        """Whether ``<baseuri>/meta`` names ``peerid`` as its id. The
        requester answers this itself: it catches a wrong base URI, not a
        false id. Two short tries (a second only when the first got no
        answer), through the bounded verification GET and within
        ``deadline`` (one of its own when not given): an unauthenticated
        request names this host."""
        if deadline is None:
            deadline = _verification_deadline()
        url = baseuri.rstrip("/") + "/meta"
        for _ in range(META_CHECK_TRIES):
            status, data = _bounded_get_json(url, {}, deadline, META_CHECK_TIMEOUT)
            if status is not None:
                return (
                    200 <= status < 300
                    and isinstance(data, dict)
                    and data.get("id") == peerid
                )
            if time.monotonic() >= deadline:
                break
        return False

    def replace_trust_secret(
        self,
        peerid: str,
        relationship: str,
        secret: str,
        *,
        proven_secret: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        """Swap the credentials of an existing trust: a re-pair.

        The caller has authenticated the request as ``peerid`` with the
        trust's current secret (``handlers/trust.py``). Only the secret
        changes, with a fresh verification token and ``peer_approved``
        (``verified`` stays as it was); the relationship, ``approved``, base URI,
        description, creation time and grants stay. Returns the updated row,
        or None and the reason it was refused (the row is then unchanged):
        a different relationship (delete and pair again), no new secret, or
        a new secret already in use on any of this actor's rows, the peer's
        own included, as creation refuses; a row neither verified nor approved
        (a pending request is replaced only by a request that verifies); or a
        row whose secret is no longer ``proven_secret``, the bearer the
        request authenticated with (the swap is one write conditioned on it,
        so a row replaced since the request authenticated never takes the
        new secret; without it, the secret read here)."""
        current = trust.Trust(actor_id=self.id, peerid=peerid, config=self.config)
        row = current.get()
        if not row:
            return None, "no trust row"
        if (row.get("relationship") or "") != (relationship or ""):
            return None, "a different relationship"
        if not (row.get("verified") or row.get("approved")):
            return None, "a pending request (it is replaced only by one that verifies)"
        if not secret:
            return None, "no new secret"
        if self.config and get_trust(self.config).is_token_in_db(
            actor_id=self.id, token=secret
        ):
            return None, "the new secret is already in use"
        if not current.modify(
            secret=secret,
            verification_token=self.config.new_token() if self.config else "",
            # ``verified`` stays as it was: proving a secret the requester
            # may have chosen itself (a pending row) is not a verification.
            peer_approved=True,
            only_if_secret=proven_secret or str(row.get("secret") or ""),
        ):
            return None, "the row changed since the request authenticated"
        # Read back through a fresh object: after modify() the cached row
        # holds the flags as the strings the backends were given.
        updated = trust.Trust(actor_id=self.id, peerid=peerid, config=self.config).get()
        return (updated or None), "" if updated else "the row could not be read back"

    def delete_reciprocal_trust(
        self,
        peerid: str | None = None,
        delete_peer: bool = False,
        notify_peers: bool = True,
        *,
        expected_secret: str | None = None,
        before_local_delete: Callable[[dict[str, Any]], None] | None = None,
    ) -> bool:
        """Deletes a trust relationship and requests deletion of peer's relationship as well.

        ``notify_peers=False`` skips the remote DELETE (``delete_peer`` is then
        ignored) and runs only the local cleanup.

        ``expected_secret`` (3.16): delete only the row with this secret, the
        one the caller authorised against. It is compared before the remote
        DELETE, again just before the local cleanup, and by the row delete
        itself; a row a re-pair replaced is left alone and ``TrustReplaced``
        raises. A re-pair landing between the second check and the row delete
        keeps its row, without the subscriptions the cleanup removed (the
        remaining window; the peer's next sync re-creates them).

        ``before_local_delete`` (3.16): called with each row after its last
        secret check and before its local cleanup (the trust handler fires
        ``trust_deleted`` there, so a delete that loses fires nothing).
        """
        failed_once = False  # For multiple relationships, this will be True if at least one deletion at peer failed
        success_once = False  # True if at least one relationship was deleted at peer
        from .oauth2_server.trust_lookup import OAUTH2_SOURCES

        if not peerid:
            rels = self.get_trust_relationships()
        else:
            rels = self.get_trust_relationships(peerid=peerid)
        for rel in rels:
            if expected_secret is not None and not secret_equals(
                str(rel.get("secret") or ""), expected_secret
            ):
                raise TrustReplaced(rel.get("peerid"))
            # For OAuth2-established trusts, there is no remote actor endpoint to call.
            # Skip remote deletion and delete locally only.
            is_oauth2_trust = (
                (rel.get("established_via") in OAUTH2_SOURCES)
                or (rel.get("type") == "oauth2")
                or (rel.get("type") == "oauth2_client")
                or (str(rel.get("peerid", "")).split(":", 1)[0] in OAUTH2_SOURCES)
            )
            # Additional safety check: prevent self-deletion if baseuri points to this actor
            is_self_deletion = (
                rel.get("baseuri", "").endswith(f"/{self.id}")
                or rel.get("baseuri", "") == f"{self.config.root}{self.id}"
                if self.config
                else False
            )

            if not notify_peers:
                pass
            elif delete_peer and not is_oauth2_trust and not is_self_deletion:
                url = rel["baseuri"] + "/trust/" + rel["relationship"] + "/" + self.id
                headers = {}
                if rel["secret"]:
                    headers = {
                        "Authorization": "Bearer " + rel["secret"],
                    }
                logger.info(f"Deleting reciprocal relationship at {url}")
                try:
                    response = requests.delete(
                        url=url, headers=headers, timeout=(5, 10)
                    )
                except Exception:  # folds DbError: peer HTTP only
                    logger.debug(
                        "Failed to delete reciprocal relationship at url(" + url + ")"
                    )
                    failed_once = True
                    continue
                if (
                    response.status_code < 200 or response.status_code > 299
                ) and response.status_code != 404:
                    logger.debug(
                        "Failed to delete reciprocal relationship at url(" + url + ")"
                    )
                    failed_once = True
                    continue
                else:
                    success_once = True
            elif delete_peer and (is_oauth2_trust or is_self_deletion):
                # Treat as successful remote delete for OAuth2 trusts and self-deletions
                reason = (
                    "OAuth2-established trust"
                    if is_oauth2_trust
                    else "self-deletion detected"
                )
                logger.debug(
                    f"Skipping remote delete for {reason}; deleting locally only"
                )
                success_once = True
            current = None
            if expected_secret is not None or before_local_delete is not None:
                current = trust.Trust(
                    actor_id=self.id, peerid=rel["peerid"], config=self.config
                ).get()
            if expected_secret is not None:
                if current and not secret_equals(
                    str(current.get("secret") or ""), expected_secret
                ):
                    raise TrustReplaced(rel.get("peerid"))
            if before_local_delete is not None and current:
                # After the last secret check and before anything local goes
                # (3.16): a lost race fires nothing, a row another delete
                # already removed fires nothing, and the caller's hook can
                # still read the row's data (the cached peer profile).
                before_local_delete(dict(current))
            if not self.subs_list:
                # strict=False: a fault leaves this peer's subscriptions as
                # orphans rather than failing the trust deletion.
                self.subs_list = subscription.Subscriptions(
                    actor_id=self.id, config=self.config
                ).fetch(strict=False)
            # Delete this peer's subscriptions
            if self.subs_list:
                for sub in self.subs_list:
                    if sub["peerid"] == rel["peerid"]:
                        logger.debug(
                            "Deleting subscription("
                            + sub["subscriptionid"]
                            + ") as part of trust deletion."
                        )
                        sub_obj = self.get_subscription_obj(
                            peerid=sub["peerid"],
                            subid=sub["subscriptionid"],
                            callback=sub["callback"],
                        )
                        if sub_obj:
                            sub_obj.delete()
            # Clean up remote peer data (RemotePeerStore)
            # No config check needed - delete_all() is a no-op if no data exists
            try:
                from .interface.actor_interface import ActorInterface
                from .remote_storage import RemotePeerStore

                actor_interface = ActorInterface(self)
                store = RemotePeerStore(
                    actor_interface,
                    rel["peerid"],
                    validate_peer_id=False,
                )
                store.delete_all()
                logger.info(f"Cleaned up RemotePeerStore for peer {rel['peerid']}")
            except ImportError:
                pass  # RemotePeerStore not available
            except DbError:
                raise
            except Exception as e:
                logger.warning(
                    f"Failed to cleanup RemotePeerStore for {rel['peerid']}: {e}"
                )

            # Clean up callback processor state
            # No config check needed - clear operation is a no-op if no state exists
            try:
                from .callback_processor import CallbackProcessor

                processor = CallbackProcessor(self)  # type: ignore[arg-type]
                processor.clear_all_state_for_peer(rel["peerid"])
                logger.info(
                    f"Cleaned up CallbackProcessor state for peer {rel['peerid']}"
                )
            except ImportError:
                pass  # CallbackProcessor not available
            except DbError:
                raise
            except Exception as e:
                logger.warning(
                    f"Failed to cleanup callback state for {rel['peerid']}: {e}"
                )

            # Clean up cached peer profile
            # No config check needed - delete is a no-op if no profile exists
            if self.config is not None and self.id is not None:
                try:
                    from .peer_profile import get_peer_profile_store

                    profile_store = get_peer_profile_store(self.config)
                    profile_store.delete_profile(self.id, rel["peerid"])
                    logger.info(f"Cleaned up peer profile for peer {rel['peerid']}")
                except ImportError:
                    pass  # Peer profile system not available
                except DbError:
                    raise
                except Exception as e:
                    logger.warning(
                        f"Failed to cleanup peer profile for {rel['peerid']}: {e}"
                    )

            # Clean up cached peer capabilities (methods/actions)
            # No config check needed - delete is a no-op if nothing cached
            if self.config is not None and self.id is not None:
                try:
                    from .peer_capabilities import get_cached_capabilities_store

                    capabilities_store = get_cached_capabilities_store(self.config)
                    capabilities_store.delete_capabilities(self.id, rel["peerid"])
                    logger.info(
                        f"Cleaned up peer capabilities for peer {rel['peerid']}"
                    )
                except ImportError:
                    pass  # Peer capabilities system not available
                except DbError:
                    raise
                except Exception as e:
                    logger.warning(
                        f"Failed to cleanup peer capabilities for {rel['peerid']}: {e}"
                    )

            # Clean up cached peer permissions
            # No config check needed - delete is a no-op if nothing cached
            if self.config is not None and self.id is not None:
                try:
                    from .peer_permissions import get_peer_permission_store

                    peer_permissions_store = get_peer_permission_store(self.config)
                    peer_permissions_store.delete_permissions(self.id, rel["peerid"])
                    logger.info(
                        f"Cleaned up peer permissions cache for peer {rel['peerid']}"
                    )
                except ImportError:
                    pass  # Peer permissions caching not available
                except DbError:
                    raise
                except Exception as e:
                    logger.warning(
                        f"Failed to cleanup peer permissions cache for {rel['peerid']}: {e}"
                    )

            # Finally the trust record itself, with its OAuth2 cleanup
            # (thoughts/reference/trust-row-deletion-invariants.md).
            dbtrust = trust.Trust(
                actor_id=self.id, peerid=rel["peerid"], config=self.config
            )
            deleted = (
                dbtrust.delete(only_if_secret=expected_secret)
                if expected_secret is not None
                else dbtrust.delete()
            )
            if not deleted and expected_secret is not None:
                current = trust.Trust(
                    actor_id=self.id, peerid=rel["peerid"], config=self.config
                ).get()
                if current and not secret_equals(
                    str(current.get("secret") or ""), expected_secret
                ):
                    # Lost to a re-pair: not a fault.
                    raise TrustReplaced(rel.get("peerid"))
            if (
                not deleted
                and trust.Trust(
                    actor_id=self.id, peerid=rel["peerid"], config=self.config
                ).get()
            ):
                # False also means the row was already gone: an earlier row's
                # cleanup (a client's sibling rows) or a peer's reciprocal
                # DELETE removed it after the list above was read. Only a row
                # still there is a failure, and not a peer's refusal: callers
                # (Actor.delete, purge) bulk-delete what is left, which would
                # skip this row's cleanup.
                raise DbError("trust delete", self.id)
        if notify_peers and delete_peer and (not success_once or failed_once):
            return False
        return True

    def purge_relationships(self, notify_peers: bool = False) -> dict[str, Any]:
        """Remove every trust, subscription and peer-trustee row of this actor.

        Used when a sign-in proves the address over an actor nobody vouched
        for, so a relationship made while the actor was unvouched cannot
        outlive the adoption. All side-stores are cleaned (permissions,
        remote-peer data, callback state, subscriptions with diffs). With
        ``notify_peers=False`` (the default) no request leaves the process:
        the peer URLs were chosen by whoever created the relationship.

        ``Trusts.delete()`` reports success whatever the backend did, so the
        lists are re-read afterwards and ``confirmed`` says whether they (the
        peer-trustee rows too) are empty. The reads are strict: PostgreSQL
        answers a caught fault with an empty list, which must not pass for
        "nothing left", so a fault
        before the wipe removes nothing and a fault after it leaves
        ``confirmed`` False. Trust secrets are never included in the returned
        summary.
        """
        from actingweb.db import (
            get_peer_trustee_list,
            get_subscription_list,
            get_trust_list,
        )

        unconfirmed: dict[str, Any] = {
            "trusts": [],
            "subscription_peers": [],
            "confirmed": False,
        }
        config = self.config
        if not config:
            return unconfirmed
        try:
            # Read once each, through the wrappers the wipe then deletes with
            # (they keep what they read). The subscriptions first: removing a
            # trust also removes that peer's subscriptions, which would empty
            # the summary.
            subs = subscription.Subscriptions(actor_id=self.id, config=self.config)
            sub_rows = subs.fetch() or []  # strict: raises DbError
            trusts = trust.Trusts(actor_id=self.id, config=self.config)
            relationships = trusts.fetch() or []  # strict, same
        except DbError:
            raise
        except Exception as e:
            logger.error(f"Purge of actor {self.id}: could not read its lists: {e}")
            return unconfirmed
        removed_trusts, subscription_peers = relationship_summary(
            relationships, sub_rows
        )
        for rel in relationships:
            if isinstance(rel, dict) and rel.get("peerid"):
                self.delete_reciprocal_trust(
                    peerid=rel["peerid"],
                    delete_peer=False,
                    notify_peers=notify_peers,
                )
        trusts.delete()

        subs.delete()

        self.delete_peer_trustee(shorttype="*", notify_peers=notify_peers)
        # delete_peer_trustee("*") visits only the types in config.actors; a
        # row for a type dropped since (or never listed) stays. Remove the
        # rest locally.
        peer_list = get_peer_trustee_list(config)
        try:
            if peer_list.fetch(actor_id=self.id, strict=True):
                peer_list.delete()
        except DbError:
            raise
        except Exception as e:
            logger.error(f"Purge of actor {self.id}: peer trustees not removed: {e}")

        try:
            trusts_left = get_trust_list(config).fetch(actor_id=self.id, strict=True)
            subs_left = get_subscription_list(config).fetch(
                actor_id=self.id, strict=True
            )
            peers_left = get_peer_trustee_list(config).fetch(
                actor_id=self.id, strict=True
            )
            confirmed = not trusts_left and not subs_left and not peers_left
        except DbError:
            raise
        except Exception as e:
            logger.error(f"Purge of actor {self.id}: could not re-read its lists: {e}")
            confirmed = False
        return {
            "trusts": removed_trusts,
            "subscription_peers": subscription_peers,
            "confirmed": confirmed,
        }

    def create_subscription(
        self,
        peerid=None,
        target=None,
        subtarget=None,
        resource=None,
        granularity=None,
        subid=None,
        callback=False,
    ):
        new_sub = subscription.Subscription(
            actor_id=self.id,
            peerid=peerid,
            subid=subid,
            callback=callback,
            config=self.config,
        )
        new_sub.create(
            target=target,
            subtarget=subtarget,
            resource=resource,
            granularity=granularity,
        )
        # Invalidate the cached subscription list so register_diffs() on this
        # instance sees the new subscription. Previously each caller had to
        # remember this (only handlers/subscription.py did), so subscriptions
        # created through the interface layer silently received no diffs for
        # the rest of the instance's lifetime — unbounded where an Actor is
        # cached across requests. NOTE: this only refreshes *this* instance;
        # another process, or a cross-request cached Actor elsewhere, still
        # holds its own list. See thoughts/todo/subs-list-cache-asymmetry.md.
        self.subs_list = None
        return new_sub.get()

    def create_remote_subscription(
        self, peerid=None, target=None, subtarget=None, resource=None, granularity=None
    ):
        """Creates a new subscription at peerid."""
        if not peerid or not target:
            return False
        relationships = self.get_trust_relationships(peerid=peerid)
        if not relationships:
            return False
        peer = relationships[0]
        params = {
            "id": self.id,
            "target": target,
        }
        if subtarget:
            params["subtarget"] = subtarget
        if resource:
            params["resource"] = resource
        if granularity and len(granularity) > 0:
            params["granularity"] = granularity
        requrl = peer["baseuri"] + "/subscriptions/" + self.id
        data = json.dumps(params)
        headers = {
            "Authorization": "Bearer " + peer["secret"],
            "Content-Type": "application/json",
        }
        try:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Creating remote subscription at url("
                    + requrl
                    + ") with body ("
                    + summarize_payload(params, encoded_len=len(data))
                    + ")"
                )
            response = requests.post(
                url=requrl, data=data, headers=headers, timeout=(5, 10)
            )
            self.last_response_code = response.status_code
            self.last_response_message = (
                response.content.decode("utf-8", "ignore")
                if isinstance(response.content, bytes)
                else str(response.content)
            )
        except Exception:  # folds DbError: peer HTTP only
            return None
        if self.last_response_code == 403:
            # The peer's grant does not admit it (3.16: a subscription needs
            # read access to what it names); said, not only returned as None.
            logger.warning(
                f"Peer {peerid} refused a subscription to "
                f"{'/'.join(p for p in (target, subtarget, resource) if p)}: "
                "the grant it gives this actor does not let this actor read it"
            )
            return None
        try:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Created remote subscription at url("
                    + requrl
                    + ") and got JSON response ("
                    + summarize_payload(response.content)
                    + ")"
                )
            content_str = (
                response.content.decode("utf-8", "ignore")
                if isinstance(response.content, bytes)
                else str(response.content)
            )
            data = json.loads(content_str)
        except ValueError:
            return None
        if "subscriptionid" in data:
            subid = data["subscriptionid"]
        else:
            return None
        if self.last_response_code == 201:
            self.create_subscription(
                peerid=peerid,
                target=target,
                subtarget=subtarget,
                resource=resource,
                granularity=granularity,
                subid=subid,
                callback=True,
            )
            if "Location" in response.headers:
                return response.headers["Location"]
            elif "location" in response.headers:
                return response.headers["location"]
        else:
            return None

    def get_subscriptions(
        self,
        peerid: str | None = None,
        target: str | None = None,
        subtarget: str | None = None,
        resource: str | None = None,
        callback: bool | None = None,
        *,
        strict: bool = True,
    ) -> list[dict[str, Any]] | None:
        """Retrieves subscriptions from db.

        Args:
            peerid: Filter by peer ID (None = all peers)
            target: Filter by target (None = all targets)
            subtarget: Filter by subtarget (None = all subtargets)
            resource: Filter by resource (None = all resources)
            callback: Filter by callback flag (None = all, False = inbound, True = outbound)
            strict: When False, a read fault answers ``[]`` instead of raising

        Returns:
            List of subscription dictionaries, or None if actor has no ID

        Raises:
            DbError: on a read fault (unless ``strict=False``)
        """
        if not self.id:
            return None
        if not self.subs_list:
            self.subs_list = subscription.Subscriptions(
                actor_id=self.id, config=self.config
            ).fetch(strict=strict)
        ret = []
        if self.subs_list:
            for sub in self.subs_list:
                if not peerid or (peerid and sub["peerid"] == peerid):
                    if not target or (target and sub["target"] == target):
                        if not subtarget or (
                            subtarget and sub["subtarget"] == subtarget
                        ):
                            if not resource or (
                                resource and sub["resource"] == resource
                            ):
                                if callback is None or sub["callback"] == callback:
                                    ret.append(sub)
        return ret

    def get_subscription(self, peerid=None, subid=None, callback=False):
        """Retrieves a single subscription identified by peerid and subid."""
        if not subid:
            return False
        return subscription.Subscription(
            actor_id=self.id,
            peerid=peerid,
            subid=subid,
            callback=callback,
            config=self.config,
        ).get()

    def get_subscription_obj(self, peerid=None, subid=None, callback=False):
        """Retrieves a single subscription identified by peerid and subid."""
        if not subid:
            return False
        return subscription.Subscription(
            actor_id=self.id,
            peerid=peerid,
            subid=subid,
            callback=callback,
            config=self.config,
        )

    def delete_remote_subscription(self, peerid=None, subid=None):
        if not subid or not peerid:
            return False
        trust_rel = self.get_trust_relationship(peerid=peerid)
        if not trust_rel:
            return False
        sub = self.get_subscription(peerid=peerid, subid=subid)
        if not sub:
            sub = self.get_subscription(peerid=peerid, subid=subid, callback=True)
        if not sub or "callback" not in sub or not sub["callback"]:
            url = trust_rel["baseuri"] + "/subscriptions/" + self.id + "/" + subid
        else:
            url = (
                trust_rel["baseuri"]
                + "/callbacks/subscriptions/"
                + self.id
                + "/"
                + subid
            )
        headers = {
            "Authorization": "Bearer " + trust_rel["secret"],
        }
        try:
            logger.info(f"Deleting remote subscription at {url}")
            response = requests.delete(url=url, headers=headers, timeout=(5, 10))
            self.last_response_code = response.status_code
            self.last_response_message = (
                response.content.decode("utf-8", "ignore")
                if isinstance(response.content, bytes)
                else str(response.content)
            )
            if response.status_code == 204:
                return True
            # A refusal leaves the peer holding a subscription nobody serves:
            # visible at WARNING, with the status (403 most often means the
            # peer's access rows do not admit DELETE on its subscription).
            log = logger.error if response.status_code == 403 else logger.warning
            log(
                f"Failed to delete remote subscription at {url}: {response.status_code}"
            )
            return False
        except Exception:  # folds DbError: peer HTTP only
            return False

    def delete_subscription(self, peerid=None, subid=None, callback=False):
        """Deletes a specified subscription"""
        if not subid:
            return False

        # For outbound subscriptions (callback=True), check if we need to clean up RemotePeerStore
        # We need to check this BEFORE deletion to know how many subscriptions exist
        should_cleanup_remote_peer_store = False
        if callback and peerid:
            try:
                # CRITICAL: Clear the subscription cache to get fresh data from database
                # Otherwise we might see stale subscriptions or the one we're about to delete
                self.subs_list = None

                # Check if we have any other outbound subscriptions to this peer
                other_subs = self.get_subscriptions(peerid=peerid, callback=True)

                # Filter out the current subscription being deleted
                # IMPORTANT: Field name is "subscriptionid" not "subid"
                remaining_subs = [
                    s for s in (other_subs or []) if s.get("subscriptionid") != subid
                ]

                if remaining_subs:
                    logger.debug(
                        f"Not cleaning up RemotePeerStore for {peerid} - "
                        f"{len(remaining_subs)} other outbound subscription(s) still active"
                    )
                else:
                    # Mark for cleanup after successful deletion
                    should_cleanup_remote_peer_store = True
            except DbError:
                raise
            except Exception as e:
                logger.warning(
                    f"Failed to check RemotePeerStore cleanup for {peerid}: {e}"
                )

        sub = subscription.Subscription(
            actor_id=self.id,
            peerid=peerid,
            subid=subid,
            callback=callback,
            config=self.config,
        )
        result = sub.delete()

        # Clear subscription cache after deletion to ensure fresh data on next access
        self.subs_list = None

        # Clean up RemotePeerStore AFTER successful deletion to avoid data loss
        # Note: should_cleanup_remote_peer_store is only True when peerid is not None
        if result and should_cleanup_remote_peer_store and peerid:
            try:
                from .interface.actor_interface import ActorInterface
                from .remote_storage import RemotePeerStore

                # No other outbound subscriptions to this peer, safe to clean up
                actor_interface = ActorInterface(self)  # type: ignore[arg-type]
                store = RemotePeerStore(
                    actor_interface,
                    peerid,
                    validate_peer_id=False,
                )
                store.delete_all()
                logger.info(f"Cleaned up RemotePeerStore for peer {peerid}")
            except ImportError:
                pass  # RemotePeerStore not available
            except Exception as e:  # folds DbError: best-effort cleanup after the subscription delete committed
                logger.warning(f"Failed to clean up RemotePeerStore for {peerid}: {e}")

        return result

    def callback_subscription(
        self, peerid=None, sub_obj=None, sub=None, diff=None, blob=None
    ):
        if not peerid or not diff or not sub or not blob:
            logger.warning("Missing parameters in callbackSubscription")
            return
        if "granularity" in sub and sub["granularity"] == "none":
            return
        trust_rel = self.get_trust_relationship(peerid)
        if not trust_rel:
            return
        if not _has_peer_endpoint(trust_rel, self.id):
            # An OAuth2 client's row (its subscriptions are kept under it
            # since 3.16): the client reads its diffs, nothing is pushed to
            # it. Its base URI is empty or this actor's own.
            return

        # The one filter the pull paths use too: a properties diff as the
        # peer may read it; another target's diff only while the peer may
        # still have the subscription (3.16).
        filtered_blob = self.filter_subscription_blob(
            peerid, sub, blob, snapshot=self.grant_for(peerid, row=trust_rel)
        )
        if filtered_blob is None:
            return  # Nothing to send after filtering
        blob = filtered_blob

        params = {
            "id": self.id,
            "subscriptionid": sub["subscriptionid"],
            "target": sub["target"],
            "sequence": diff["sequence"],
            "timestamp": str(diff["timestamp"]),
            "granularity": sub["granularity"],
        }
        if sub["subtarget"]:
            params["subtarget"] = sub["subtarget"]
        if sub["resource"]:
            params["resource"] = sub["resource"]
        if sub["granularity"] == "high":
            try:
                params["data"] = json.loads(blob)
            except (TypeError, ValueError, KeyError):
                params["data"] = blob
        if sub["granularity"] == "low":
            params["url"] = (
                (self.config.root if self.config else "")
                + (self.id or "")
                + "/subscriptions/"
                + trust_rel["peerid"]
                + "/"
                + sub["subscriptionid"]
                + "/"
                + str(diff["sequence"])
            )
        requrl = (
            trust_rel["baseuri"]
            + "/callbacks/subscriptions/"
            + self.id
            + "/"
            + sub["subscriptionid"]
        )
        data = json.dumps(params)
        headers = {
            "Authorization": "Bearer " + trust_rel["secret"],
            "Content-Type": "application/json",
        }

        # Helper function for sync callback
        def _send_callback_sync():
            """Send subscription callback using requests (blocking)."""
            try:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Doing sync callback on subscription at url("
                        + requrl
                        + ") with body("
                        + summarize_payload(params, encoded_len=len(data))
                        + ")"
                    )
                response = requests.post(
                    url=requrl,
                    data=data.encode("utf-8"),
                    headers=headers,
                    timeout=(5, 10),
                )
                self.last_response_code = response.status_code
                self.last_response_message = (
                    response.content.decode("utf-8", "ignore")
                    if isinstance(response.content, bytes)
                    else str(response.content)
                )
                # Log the response for debugging callback delivery issues
                if response.status_code == 204:
                    logger.info(
                        f"Callback seq={diff.get('sequence')} delivered successfully (204)"
                    )
                else:
                    logger.warning(
                        f"Callback seq={diff.get('sequence')} returned {response.status_code}: "
                        f"{self.last_response_message[:200] if self.last_response_message else 'no message'}"
                    )
                # NOTE: Don't clear diffs immediately after 204 response. The subscriber
                # might have added the callback to a pending queue (due to sequence gaps),
                # and the diff would be lost. Diffs are cleared when the subscriber
                # explicitly confirms processing via PUT /subscriptions/{id} with sequence.
            except (requests.RequestException, requests.Timeout, ConnectionError) as e:
                logger.warning(
                    f"Callback seq={diff.get('sequence')} failed - peer did not respond: {e}"
                )
                self.last_response_code = 0
                self.last_response_message = (
                    "No response from peer for subscription callback"
                )

        # Check if sync callbacks are forced (recommended for Lambda/serverless)
        use_sync = getattr(self.config, "sync_subscription_callbacks", False)
        if use_sync:
            logger.info(
                f"Sync callback seq={diff.get('sequence')} to {sub.get('peerid', 'unknown')}"
            )
            _send_callback_sync()
            return

        # Fire callback asynchronously to avoid blocking the caller
        async def _send_callback_async():
            """Send subscription callback using httpx (non-blocking)."""
            import httpx

            try:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Doing async callback on subscription at url("
                        + requrl
                        + ") with body("
                        + summarize_payload(params, encoded_len=len(data))
                        + ")"
                    )
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(10.0, connect=5.0)
                ) as client:
                    response = await client.post(
                        requrl, content=data.encode("utf-8"), headers=headers
                    )
                self.last_response_code = response.status_code
                self.last_response_message = (
                    response.content.decode("utf-8", "ignore")
                    if isinstance(response.content, bytes)
                    else str(response.content)
                )
                # NOTE: Don't clear diffs immediately after 204 response. The subscriber
                # might have added the callback to a pending queue (due to sequence gaps),
                # and the diff would be lost. Diffs are cleared when the subscriber
                # explicitly confirms processing via PUT /subscriptions/{id} with sequence.
            except (httpx.HTTPError, httpx.TimeoutException) as e:
                logger.debug(f"Peer did not respond to callback on url({requrl}): {e}")
                self.last_response_code = 0
                self.last_response_message = (
                    "No response from peer for subscription callback"
                )

        # Schedule the async callback without blocking (may be lost on Lambda freeze!)
        try:
            import asyncio

            loop = asyncio.get_running_loop()
            # We're in an async context - create a background task
            loop.create_task(_send_callback_async())
            logger.debug(
                f"Async callback seq={diff.get('sequence')} to {sub.get('peerid', 'unknown')} (fire-and-forget)"
            )
        except RuntimeError:
            # No running event loop - fall back to sync request
            logger.debug("No async loop, falling back to sync callback")
            _send_callback_sync()

    async def create_verified_trust_async(
        self,
        baseuri="",
        peerid=None,
        approved=False,
        secret=None,
        verification_token=None,
        trust_type=None,
        peer_approved=None,
        relationship=None,
        desc="",
    ):
        """Async version - wraps sync method in asyncio.to_thread to prevent blocking."""
        import asyncio

        return await asyncio.to_thread(
            self.create_verified_trust,
            baseuri=baseuri,
            peerid=peerid,
            approved=approved,
            secret=secret,
            verification_token=verification_token,
            trust_type=trust_type,
            peer_approved=peer_approved,
            relationship=relationship,
            desc=desc,
        )

    async def delete_reciprocal_trust_async(
        self,
        peerid: str | None = None,
        delete_peer: bool = False,
        *,
        expected_secret: str | None = None,
        before_local_delete: Callable[[dict[str, Any]], None] | None = None,
    ) -> bool:
        """Async version - wraps sync method in asyncio.to_thread to prevent
        blocking (``expected_secret`` and ``before_local_delete`` as in the
        sync method)."""
        import asyncio

        return await asyncio.to_thread(
            self.delete_reciprocal_trust,
            peerid=peerid,
            delete_peer=delete_peer,
            expected_secret=expected_secret,
            before_local_delete=before_local_delete,
        )

    async def create_remote_subscription_async(
        self,
        peerid=None,
        target=None,
        subtarget=None,
        resource=None,
        granularity=None,
    ):
        """Async version - wraps sync method in asyncio.to_thread to prevent blocking."""
        import asyncio

        return await asyncio.to_thread(
            self.create_remote_subscription,
            peerid=peerid,
            target=target,
            subtarget=subtarget,
            resource=resource,
            granularity=granularity,
        )

    async def delete_remote_subscription_async(self, peerid=None, subid=None):
        """Async version - wraps sync method in asyncio.to_thread to prevent blocking."""
        import asyncio

        return await asyncio.to_thread(
            self.delete_remote_subscription, peerid=peerid, subid=subid
        )

    async def callback_subscription_async(
        self, peerid=None, sub_obj=None, sub=None, diff=None, blob=None
    ):
        """Async version - wraps sync method in asyncio.to_thread to prevent blocking."""
        import asyncio

        return await asyncio.to_thread(
            self.callback_subscription,
            peerid=peerid,
            sub_obj=sub_obj,
            sub=sub,
            diff=diff,
            blob=blob,
        )

    @staticmethod
    def _diff_part(rules: Any, path: str, value: Any) -> Any:
        """``value`` (a diff's part at ``path``) without excluded parts, and
        without any object the filter emptied: the subscriber replaces a
        property with what a diff carries, so an emptied ``{}`` would wipe
        its copy of the parts it may read. ``_EMPTIED`` when nothing is left
        of a non-empty object (3.16).

        A value that is JSON text of an object (a form-posted property, an
        SDK write of a JSON string: what a direct read parses) is filtered
        as the object and sent as text again."""
        if isinstance(value, str) and exclusion_patterns(rules):
            as_object = as_json_object(value)
            if as_object is not None:
                kept_object = _prune_emptied(
                    as_object, drop_excluded(rules, path, as_object)
                )
                if kept_object is _EMPTIED:
                    return _EMPTIED
                return value if kept_object == as_object else json.dumps(kept_object)
        kept = drop_excluded(rules, path, value)
        return _prune_emptied(value, kept)

    def grant_for(self, peerid: str, *, row: Any = None) -> GrantSnapshot | None:
        """What ``peerid`` is granted here, read once (3.16), or None when it
        cannot be read for a reason other than storage (callers send
        nothing). ``row``: the trust row when the caller read it already.
        ``DbError`` raises."""
        if not self.config or not self.id:
            return None
        try:
            evaluator = get_permission_evaluator(self.config)
            if row is None:
                return evaluator.snapshot(str(self.id), peerid)
            return evaluator.snapshot(str(self.id), peerid, row=row)
        except DbError:
            raise
        except Exception as e:
            logger.error(f"Grant for {peerid} could not be read: {e}")
            return None

    def filter_subscription_blob(
        self,
        peerid: str,
        sub: dict[str, Any],
        blob: Any,
        *,
        snapshot: GrantSnapshot | None = None,
    ) -> str | None:
        """A subscription diff as ``peerid`` may read it, or None when it may
        read none of it (3.16). The one filter for the pushed callback
        (``callback_subscription``) and the pulled diffs
        (``GET /subscriptions/<peer>/<subid>`` and ``/<seq>``).

        Only a ``properties`` subscription is filtered (other targets are the
        application's, served as their callbacks are, while the peer may
        still subscribe to them: the creation check is asked again). Each part is decided
        at its full path: a subscription to one property (a subtarget, and a
        resource under it) carries that path's value, sent when the peer may
        read the path; a subscription to the whole target carries an object
        keyed by property, each key decided on its own. In every case an
        object value loses the descendants the grant excludes, at any depth,
        rooted at the path it sits at. A ``list:<name>`` key is a list, a
        top-level property, decided by its bare name.

        ``snapshot``: the peer's grant when the caller read it already (a
        pull serving many diffs reads it once). Fail closed: no grant, a
        value that is not an object for a whole-target subscription, or an
        error yields None."""
        as_text = (
            blob
            if isinstance(blob, str)
            else blob.decode("utf-8", "ignore")
            if isinstance(blob, bytes)
            else json.dumps(blob)
        )
        if snapshot is None:
            snapshot = self.grant_for(peerid)
        if sub.get("target") != "properties":
            # Another target's content is the application's; whether the
            # peer may still have the subscription is asked again (3.16): a
            # grant narrowed after it was made delivers nothing.
            return as_text if self._may_still_subscribe(sub, snapshot) else None
        if snapshot is None or not self.config:
            return None
        try:
            parsed: Any = json.loads(as_text)
        except (TypeError, ValueError):
            parsed = as_text
        subtarget = str(sub.get("subtarget") or "")
        try:
            if not subtarget:
                if not isinstance(parsed, dict):
                    return None
                kept = self._readable_keys(snapshot, "", parsed)
                return json.dumps(kept) if kept else None
            resource = str(sub.get("resource") or "")
            path = f"{subtarget}/{resource}" if resource else subtarget
            if not self._may_read(snapshot, path):
                return None
            rules = snapshot.rules(PermissionType.PROPERTIES)
            if isinstance(parsed, str):
                # The property's value as JSON text: filtered as the object
                # a direct read would parse (3.16).
                part = self._diff_part(rules, path, parsed)
                if part is _EMPTIED:
                    return None
                return as_text if part == parsed else json.dumps(part)
            if not isinstance(parsed, dict):
                return as_text
            if resource:
                kept_value = self._diff_part(rules, path, parsed)
            else:
                # A resource-level write arrives as ``{resource: value}``:
                # the value is the property's, kept whole except the parts
                # the grant excludes, at their paths under the subtarget. A
                # ``list:<name>`` key is a list, decided by its bare name.
                lists = {
                    k: v
                    for k, v in parsed.items()
                    if k.startswith("list:") and self._may_read(snapshot, k[5:])
                }
                kept_value = self._diff_part(
                    rules,
                    subtarget,
                    {k: v for k, v in parsed.items() if not k.startswith("list:")},
                )
                if lists:
                    # A list's diff object passes whole once its name may be
                    # read (3.16): its keys are not property paths.
                    kept_value = {
                        **({} if kept_value is _EMPTIED else kept_value),
                        **lists,
                    }
        except DbError:
            raise
        except Exception as e:
            logger.error(f"Permission check failed for a diff to {peerid}: {e}")
            return None
        if kept_value is _EMPTIED:
            return None
        if kept_value == parsed:
            return as_text
        return json.dumps(kept_value) if kept_value else None

    def _may_still_subscribe(
        self, sub: dict[str, Any], snapshot: GrantSnapshot | None
    ) -> bool:
        """The creation check for a subscription to a target other than
        ``properties``, asked at delivery (3.16). Fail closed.

        A target the grant has a category for (``resources``, ``methods``,
        ``actions``) is decided by the grant as at creation; an
        application's own target only needs an approved trust: its creation
        row (``subscriptions/<id>``) is the route's gate, and a subscription
        the application made itself never passed it."""
        if snapshot is None or not self.config:
            return False
        from .access_decision import SUBSCRIBABLE, subscription_allowed

        if str(sub.get("target") or "") not in SUBSCRIBABLE:
            return bool(snapshot.approved)

        try:
            return subscription_allowed(
                self.config,
                str(self.id),
                snapshot.peer_id,
                str(sub.get("target") or ""),
                str(sub.get("subtarget") or ""),
                str(sub.get("resource") or ""),
                evaluator=get_permission_evaluator(self.config),
                snapshot=snapshot,
            ).allowed
        except DbError:
            raise
        except Exception as e:
            logger.error(f"Subscription re-check for {snapshot.peer_id} failed: {e}")
            return False

    def _may_read(self, snapshot: GrantSnapshot, path: str) -> bool:
        """Whether the peer may read ``path``: the one access decision, as a
        direct read asks it (3.16): a stated rule answers, a grant that does
        not mention properties leaves it to the access table (never for a
        client)."""
        assert self.config is not None
        from .access_decision import decide

        evaluator = get_permission_evaluator(self.config)
        decision = decide(
            self.config,
            str(self.id),
            snapshot.peer_id,
            PermissionType.PROPERTIES,
            path,
            "read",
            evaluator=evaluator,
            snapshot=snapshot,
        )
        if not decision.allowed:
            logger.debug(
                f"Permission denied: {self.id}:{snapshot.peer_id} -> "
                f"properties:{path!r}:read ({decision.reason})"
            )
        return decision.allowed

    def _readable_keys(
        self, snapshot: GrantSnapshot, parent: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        """``data``'s keys (each at ``<parent>/<key>``, or ``<key>`` at the
        top) that the peer may read, each without its excluded descendants.
        A ``list:<name>`` key is decided by the list's bare name."""
        rules = snapshot.rules(PermissionType.PROPERTIES)
        kept: dict[str, Any] = {}
        for key, value in data.items():
            name = key[5:] if key.startswith("list:") else key
            path = f"{parent}/{key}" if parent else name
            if key.startswith("list:") and path != name:
                if not self._may_read(snapshot, name):
                    continue
            if not self._may_read(snapshot, path):
                logger.debug(f"Filtered {path!r} from a diff to {snapshot.peer_id}")
                continue
            if key.startswith("list:"):
                # A list's diff object (list, operation, items): a list's
                # unit is its name, decided above; its keys are not property
                # paths an exclusion could name (3.16).
                kept[key] = value
                continue
            part = self._diff_part(rules, path, value)
            if part is not _EMPTIED:
                kept[key] = part
        return kept

    def _filter_full_state(
        self,
        peerid: str,
        subtarget: str,
        full_state: dict[str, Any],
        list_keys: set[str],
    ) -> dict[str, Any]:
        """A full-state diff (``_get_full_state_for_subscription``) without
        the parts the peer's grant excludes, at their true paths (3.16).

        For a subtarget the state is wrapped one level deeper than a diff
        (``{subtarget: value}``), so the pull filter, which still decides
        whether the peer may read it at all, would look for the children at
        the wrong paths. A list's state is not descended (a list's unit is
        its name). With no grant to read, the state is left to the pull
        filter, which then sends nothing."""
        snapshot = self.grant_for(peerid)
        if snapshot is None:
            return full_state
        rules = snapshot.rules(PermissionType.PROPERTIES)

        def kept(path: str, value: Any) -> Any:
            if path in list_keys:
                return value
            if isinstance(value, str):
                try:
                    parsed = json.loads(value)
                except ValueError:
                    return value
                filtered = drop_excluded(rules, path, parsed)
                return value if filtered == parsed else json.dumps(filtered)
            return drop_excluded(rules, path, value)

        if subtarget:
            return {
                k: kept(subtarget, v) if k == subtarget else v
                for k, v in full_state.items()
            }
        return {k: kept(k, v) for k, v in full_state.items()}

    # =========================================================================
    # Subscription Suspension Management
    # =========================================================================

    def is_subscription_suspended(
        self, target: str, subtarget: str | None = None
    ) -> bool:
        """Check if diff registration is suspended for a target/subtarget.

        Args:
            target: Target resource (e.g., "properties")
            subtarget: Optional subtarget (e.g., property name)

        Returns:
            True if suspended, False otherwise

        Raises:
            DbError: the suspension could not be read (3.16). "Not suspended"
                and "could not tell" are different answers; register_diffs()
                lets it propagate after the write committed, so the caller
                answers 503 rather than firing callbacks a suspension meant to
                hold back.
        """
        if not self.config or not self.id:
            return False
        try:
            db = get_subscription_suspension(self.config, self.id)
            return db.is_suspended(target, subtarget)
        except DbError:
            raise
        except Exception as e:  # folds DbError: handled by the clause above; this logs a non-DbError backend error as not suspended
            # "Not suspended" and "could not tell" must not look the same:
            # a missing suspensions table (TableDoesNotExist) or a denied
            # read makes every target look un-suspended, so a bulk import's
            # suspend() silently no-ops and per-item callbacks fire anyway.
            # Log loudly — but at most once per window per process:
            # register_diffs() calls this on every property write, so an
            # unconditional ERROR would flood the log at write rate (the same
            # shape as the per-construction DescribeTable this release
            # removed). Failures in between stay at DEBUG.
            global _suspension_check_error_logged_at
            now = time.monotonic()
            if (
                _suspension_check_error_logged_at is None
                or now - _suspension_check_error_logged_at
                >= _SUSPENSION_ERROR_LOG_INTERVAL_SECONDS
            ):
                _suspension_check_error_logged_at = now
                logger.error(
                    "Suspension check FAILED for %s/%s%s — treating as NOT "
                    "suspended, so subscription diffs and callbacks will fire "
                    "during any suspended window. Verify the subscription "
                    "suspensions table exists and is readable "
                    "(python -m actingweb.db.verify_tables). Repeats at most "
                    "every %.0fs per process; failures in between are logged "
                    "at DEBUG: %s",
                    self.id,
                    target,
                    f"/{subtarget}" if subtarget else "",
                    _SUSPENSION_ERROR_LOG_INTERVAL_SECONDS,
                    e,
                )
            else:
                logger.debug(
                    "Suspension check failed for %s/%s%s: %s",
                    self.id,
                    target,
                    f"/{subtarget}" if subtarget else "",
                    e,
                )
            return False

    def suspend_subscriptions(self, target: str, subtarget: str | None = None) -> bool:
        """Suspend diff registration for a target/subtarget.

        While suspended, property changes will NOT register diffs or trigger callbacks.
        Call resume_subscriptions() to lift suspension and send resync callbacks.

        Args:
            target: Target resource (e.g., "properties")
            subtarget: Optional subtarget (e.g., property name)

        Returns:
            True if newly suspended, False if already suspended
        """
        if not self.config or not self.id:
            return False
        try:
            db = get_subscription_suspension(self.config, self.id)
            return db.suspend(target, subtarget)
        except DbError:
            raise
        except Exception as e:
            logger.error(f"Error suspending subscriptions: {e}")
            return False

    def resume_subscriptions(self, target: str, subtarget: str | None = None) -> int:
        """Resume diff registration and send resync callbacks.

        Sends a resync callback to ALL subscriptions on this target/subtarget,
        telling them to do a full GET to re-sync their state. An OAuth2
        client's subscription gets a resync marker as its next diff instead
        (it re-reads the target under its own grant).

        Args:
            target: Target resource (e.g., "properties")
            subtarget: Optional subtarget (e.g., property name)

        Returns:
            The number of resync callbacks sent
        """
        if not self.config or not self.id:
            return 0
        try:
            db = get_subscription_suspension(self.config, self.id)
            # The resync is the only recovery for the changes made while
            # suspended (they stored no diff and moved no sequence), so read
            # the subscribers strictly before the marker goes: a fault then
            # answers 503 with the suspension still in place.
            subs = self.get_subscriptions(
                target=target, subtarget=None, callback=False, strict=True
            )
            # A previous resume whose resyncs did not all land left a record
            # of the subscribers that missed theirs (D-e): this call re-sends
            # to those only, read before the suspension check, since that
            # resume already removed the suspension.
            pending = self._resync_pending(target, subtarget)
            missed: list[str] = []
            count = 0
            retried: set[str] = set()
            if pending is not None:
                existing = {_resync_id(s) for s in subs or [] if s}
                retried = {i for i in pending if i in existing}
                retry_subs = [s for s in subs or [] if _resync_id(s) in retried]
                count = self._send_resync_callbacks(
                    target, subtarget, retry_subs, None, missed=missed
                )
            # A suspension set after that earlier resume (a second bulk
            # import) is still lifted by this call: falling through, not
            # returning, so its subscribers get their resync too.
            try:
                resumed = db.resume(target, subtarget)
            except DbError:
                # The delete may have landed with its answer lost; put the
                # marker back so the retry finds something to resume.
                self._restore_suspension(db, target, subtarget)
                if pending is not None:
                    self._write_resync_pending(target, subtarget, missed)
                raise
            if resumed:
                # Send resync callbacks to every affected subscriber not
                # resynced just above (that resync already carries the
                # current state); the ones that miss are recorded for the
                # next call.
                rest = [s for s in subs or [] if s and _resync_id(s) not in retried]
                count += self._send_resync_callbacks(
                    target, subtarget, rest, db, missed=missed
                )
            if pending is not None or missed:
                self._write_resync_pending(target, subtarget, missed)
            return count
        except DbError:
            raise
        except Exception as e:
            logger.error(f"Error resuming subscriptions: {e}")
            return 0

    def _send_resync_callbacks(
        self,
        target: str,
        subtarget: str | None,
        subs: list[dict[str, Any]] | None = None,
        suspension: Any = None,
        *,
        missed: list[str] | None = None,
    ) -> int:
        """Send resync callbacks to all subscriptions on target/subtarget.

        ``missed`` collects the subscription ids whose resync did not land
        (an HTTP failure or a permanent store error), for the record a later
        :meth:`resume_subscriptions` re-sends to. A subscription kept under
        an OAuth2 client's trust row is sent nothing (a client reads its
        diffs): its resync is a marker stored as its next diff (it re-reads the
        target under its own grant), counted when stored and missed when not.

        Every subscriber gets its attempt. If any hit a transient fault, the
        suspension is put back (when ``suspension`` is given) and the first
        such fault raised, so the caller's retry resends to all of them. A
        permanent fault (one a retry cannot fix, such as an item over the
        backend's size limit) is logged as that subscriber's failure: putting
        the suspension back for it would keep the target suspended for good.
        A resync that fails over HTTP is not counted either; a return value
        below the number of subscribers means some missed the resync.

        Args:
            target: Target resource
            subtarget: Optional subtarget
            subs: The subscriptions, read strictly by the caller
            suspension: The suspension store to restore on a fault

        Returns:
            Number of callbacks sent successfully
        """
        if subs is None:
            subs = self.get_subscriptions(
                target=target, subtarget=None, callback=False, strict=True
            )
        if not subs:
            return 0

        count = 0
        fault: DbError | None = None
        for sub in subs:
            sub_target = sub.get("target", "")
            sub_subtarget = sub.get("subtarget")

            # Match target
            if sub_target != target:
                continue

            # Match subtarget if specified
            # Empty subtarget in subscription means "all subtargets", so it matches any filter
            if subtarget is not None and sub_subtarget and sub_subtarget != subtarget:
                continue

            # Send resync callback
            # If we resumed a specific subtarget, use that for the resync
            # (even if the subscription itself has no subtarget or a different one)
            resync_subtarget = subtarget if subtarget else sub_subtarget
            try:
                if self._callback_subscription_resync(sub, resync_subtarget):
                    count += 1
                elif missed is not None:
                    missed.append(_resync_id(sub))
            except DbError as e:  # folds DbError: transient ones raised after the loop
                from .interface.integrations._errors import is_permanent

                if is_permanent(e):
                    logger.error(
                        f"Resync of subscription {sub.get('subscriptionid')} hit a "
                        f"permanent store error; that subscriber missed it: {e}"
                    )
                    if missed is not None:
                        missed.append(_resync_id(sub))
                    continue
                logger.error(
                    f"Resync of subscription {sub.get('subscriptionid')} faulted: {e}"
                )
                fault = fault or e

        logger.info(f"Sent {count} resync callbacks for {target}/{subtarget}")
        if fault is not None:
            if suspension is not None:
                self._restore_suspension(suspension, target, subtarget)
            raise fault
        return count

    _RESYNC_PENDING_BUCKET = "_resync_pending"

    @staticmethod
    def _resync_key(target: str, subtarget: str | None) -> str:
        return f"{target}:{subtarget or ''}"

    def _resync_pending(self, target: str, subtarget: str | None) -> list[str] | None:
        """The subscription ids a previous resume's resync missed for this
        target/subtarget, or None when there is no record. Strict."""
        from .db import get_attribute

        if not self.config or not self.id:
            return None
        row = get_attribute(self.config).get_attr_strict(
            actor_id=self.id,
            bucket=self._RESYNC_PENDING_BUCKET,
            name=self._resync_key(target, subtarget),
        )
        data = row.get("data") if row else None
        if not isinstance(data, dict) or not isinstance(data.get("ids"), list):
            return None
        return [str(i) for i in data["ids"]]

    def _write_resync_pending(
        self, target: str, subtarget: str | None, missed: list[str]
    ) -> None:
        """Record who missed the resync, or remove the record when nobody
        did. Raises ``DbError``: a lost record would lose the retry."""
        from .db import get_attribute

        if not self.config or not self.id:
            return
        db = get_attribute(self.config)
        name = self._resync_key(target, subtarget)
        if missed:
            db.set_attr(
                actor_id=self.id,
                bucket=self._RESYNC_PENDING_BUCKET,
                name=name,
                data={"ids": sorted(set(missed))},
            )
            logger.warning(
                f"Resync for {target}/{subtarget}: {len(set(missed))} subscriber(s) "
                "missed it; the next resume_subscriptions() re-sends to them"
            )
        else:
            db.delete_attr(
                actor_id=self.id, bucket=self._RESYNC_PENDING_BUCKET, name=name
            )

    def _restore_suspension(
        self, suspension: Any, target: str, subtarget: str | None
    ) -> None:
        """Put a suspension back after a resume faulted, best effort."""
        try:
            suspension.suspend(target, subtarget)
        except DbError as e:  # folds DbError: the caller raises the original fault
            logger.error(
                f"Could not confirm the suspension of {target}/{subtarget} is "
                f"back after a resume fault; a retry may find nothing to "
                f"resume: {e}"
            )

    def _send_resync_callback_sync(
        self, callback_url: str, payload: dict, secret: str, peer_id: str
    ) -> bool:
        """Send resync callback synchronously (blocking).

        Args:
            callback_url: URL to send the callback to
            payload: Callback payload
            secret: Trust secret for authentication
            peer_id: Peer ID (for logging)

        Returns:
            True if callback was sent successfully
        """
        import httpx

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    callback_url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {secret}",
                    },
                )

            if response.status_code in (200, 204):
                logger.info(
                    f"Sent resync callback to {peer_id} for subscription "
                    f"{payload.get('subscriptionid')}"
                )
                return True
            else:
                logger.warning(
                    f"Resync callback to {peer_id} failed: {response.status_code}"
                )
                return False

        except Exception as e:  # folds DbError: peer HTTP only
            logger.error(f"Error sending resync callback to {peer_id}: {e}")
            return False

    def _send_resync_callback_async(
        self, callback_url: str, payload: dict, secret: str, peer_id: str
    ) -> None:
        """Send resync callback asynchronously (fire-and-forget).

        Args:
            callback_url: URL to send the callback to
            payload: Callback payload
            secret: Trust secret for authentication
            peer_id: Peer ID (for logging)
        """

        async def _send():
            import httpx

            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        callback_url,
                        json=payload,
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {secret}",
                        },
                    )

                if response.status_code in (200, 204):
                    logger.info(
                        f"Sent resync callback to {peer_id} for subscription "
                        f"{payload.get('subscriptionid')}"
                    )
                else:
                    logger.warning(
                        f"Resync callback to {peer_id} failed: {response.status_code}"
                    )

            except Exception as e:  # folds DbError: peer HTTP only
                logger.error(f"Error sending resync callback to {peer_id}: {e}")

        try:
            import asyncio

            loop = asyncio.get_running_loop()
            loop.create_task(_send())
            logger.debug(
                f"Async resync callback to {peer_id} for subscription "
                f"{payload.get('subscriptionid')} (fire-and-forget)"
            )
        except RuntimeError:
            # No event loop - fallback to sync
            logger.debug("No async loop, falling back to sync resync callback")
            self._send_resync_callback_sync(callback_url, payload, secret, peer_id)

    def _callback_subscription_resync(
        self, subscription: dict, override_subtarget: str | None = None
    ) -> bool:
        """Send a resync callback to a single subscription.

        Checks peer capability before sending resync. If peer doesn't support
        the subscriptionresync option, falls back to low-granularity callback.

        Respects the sync_subscription_callbacks configuration to determine
        whether to send callbacks synchronously (blocking) or asynchronously
        (fire-and-forget).

        Args:
            subscription: Subscription dict with peerid, subscriptionid, callback, etc.
            override_subtarget: Optional subtarget to use instead of subscription's subtarget
                              (used when resuming a specific subtarget on a broader subscription)

        Returns:
            True if callback was sent/scheduled successfully, or, for an
            OAuth2 client's trust row (nothing is pushed to it), a resync
            marker was stored as its next diff (``resync_marker``)
        """
        from datetime import UTC, datetime

        peer_id = subscription.get("peerid", "")
        sub_id = subscription.get("subscriptionid", "")
        target = subscription.get("target", "")
        # Use override_subtarget if provided, otherwise use subscription's subtarget
        sub_subtarget = (
            override_subtarget
            if override_subtarget is not None
            else subscription.get("subtarget")
        )

        # Get trust relationship to construct callback URL
        from .trust import Trust

        trust = Trust(actor_id=self.id, peerid=peer_id, config=self.config)
        trust_data = trust.get()

        if not trust_data:
            logger.warning(f"No trust found for peer {peer_id}")
            return False
        if not _has_peer_endpoint(trust_data, self.id):
            # An OAuth2 client's row (as in callback_subscription): nothing is
            # pushed to it, it reads its diffs. The changes made while
            # suspended stored none, so its next diff is a resync marker:
            # the client re-reads the URL under its own grant. No data is
            # stored, so nothing escapes its grant, and a second marker (a
            # retried resume) only repeats the re-read.
            if not self.config:
                return False
            new_seq = self._increment_subscription_sequence(peer_id, sub_id)
            if not new_seq:
                logger.warning(
                    f"Subscription {sub_id} for {peer_id} is gone; no resync stored"
                )
                return False
            return bool(
                self._store_subscription_diff(
                    peer_id,
                    sub_id,
                    new_seq,
                    resync_marker(
                        _resync_url(self.config, self.id, target, sub_subtarget)
                    ),
                )
            )

        # Construct callback URL from trust relationship (same as callback_subscription)
        callback_url = (
            trust_data.get("baseuri", "")
            + "/callbacks/subscriptions/"
            + (self.id or "")
            + "/"
            + sub_id
        )

        if not callback_url or not trust_data.get("baseuri"):
            logger.warning(
                f"No callback URL for subscription {sub_id} - missing baseuri in trust"
            )
            return False

        # Check if peer supports resync callbacks (use cached data only)
        from .interface.actor_interface import ActorInterface
        from .peer_capabilities import PeerCapabilities

        actor_interface = ActorInterface(self)
        caps = PeerCapabilities(actor_interface, peer_id)

        # Use cached capabilities without blocking on network fetch
        # If cache is expired or not available, assume support (optimistic)
        supports_resync_cached = caps.supports_resync_callbacks_cached()
        if supports_resync_cached is None:
            # Cache expired or not available - assume support to avoid blocking
            # This is optimistic but safe: if peer doesn't support resync,
            # the receiver will process it as a regular low-granularity callback
            supports_resync = True
            logger.debug(
                f"Capabilities not cached for peer {peer_id}, "
                f"assuming resync support (optimistic)"
            )

            # Schedule background refresh to update cache for next time
            # This doesn't block the current operation
            try:
                import asyncio

                async def _refresh_capabilities():
                    try:
                        await caps.refresh_async()
                        logger.debug(
                            f"Background refresh of capabilities for {peer_id}"
                        )
                    except Exception as e:  # folds DbError: background capability-cache refresh, best-effort
                        logger.debug(
                            f"Background capability refresh failed for {peer_id}: {e}"
                        )

                loop = asyncio.get_running_loop()
                loop.create_task(_refresh_capabilities())
            except RuntimeError:
                # No event loop - skip background refresh
                # Next operation will still use optimistic approach
                pass
        else:
            supports_resync = supports_resync_cached
            logger.debug(
                f"Using cached capability for peer {peer_id}: "
                f"resync_supported={supports_resync}"
            )

        # Increment sequence number
        new_seq = self._increment_subscription_sequence(peer_id, sub_id)
        if not new_seq:
            logger.warning(
                f"Subscription {sub_id} for {peer_id} is gone; no resync sent"
            )
            return False

        # Build resource URL for resync
        if not self.config:
            logger.warning("No config available for building resource URL")
            return False
        resource_url = _resync_url(self.config, self.id, target, sub_subtarget)

        # Build callback payload - use resync type only if peer supports it
        if supports_resync:
            # Resync callback per protocol spec v1.4
            payload = {
                "id": self.id,
                "subscriptionid": sub_id,
                "target": target,
                "subtarget": sub_subtarget,
                "sequence": new_seq,
                "timestamp": datetime.now(UTC).isoformat(),
                "granularity": subscription.get("granularity", "high"),
                "type": "resync",
                "url": resource_url,
            }
            logger.debug(f"Sending resync callback to peer {peer_id} (supports resync)")
        else:
            # Fallback: create a full-state diff and send low-granularity callback
            # Get the full current state
            list_keys: set[str] = set()
            full_state = self._get_full_state_for_subscription(
                target, sub_subtarget, list_keys
            )
            # A list's full state is an "extend" diff nested under the list
            # name. Over the span threshold, list diffs become references
            # (the subscriber re-reads), per list and then largest first
            # until the whole blob fits the diff row, so the store does not
            # fail on the row cap.
            from .property_list import fit_full_state

            full_state = self._filter_full_state(
                peer_id, sub_subtarget or "", full_state, list_keys
            )
            full_state = fit_full_state(full_state, self.config, list_keys=list_keys)

            # Store as a subscription diff
            diff_url = self._store_subscription_diff(
                peer_id, sub_id, new_seq, full_state
            )
            if not diff_url:
                return False

            # Send low-granularity callback with URL to subscription diff
            payload = {
                "id": self.id,
                "subscriptionid": sub_id,
                "target": target,
                "subtarget": sub_subtarget,
                "sequence": new_seq,
                "timestamp": datetime.now(UTC).isoformat(),
                "granularity": "low",
                "url": diff_url,
            }
            logger.info(
                f"Peer {peer_id} does not support resync callbacks, "
                f"creating full-state diff for low-granularity callback"
            )

        # Get trust secret for authentication (already fetched above)
        secret = trust_data.get("secret", "")

        # Check sync configuration (like diff callbacks do)
        use_sync = getattr(self.config, "sync_subscription_callbacks", False)

        if use_sync:
            # Lambda mode: blocking call
            logger.info(f"Sync resync callback to {peer_id}")
            return self._send_resync_callback_sync(
                callback_url, payload, secret, peer_id
            )
        else:
            # Local mode: async fire-and-forget
            self._send_resync_callback_async(callback_url, payload, secret, peer_id)
            return True  # Scheduled (not confirmed)

    def _get_full_state_for_subscription(
        self,
        target: str,
        subtarget: str | None,
        list_keys: set[str] | None = None,
    ) -> dict[str, Any]:
        """Get the full current state for a subscription target.

        Args:
            target: Subscription target (e.g., "properties")
            subtarget: Optional subtarget (e.g., list name for property lists)
            list_keys: When given, the keys of the result that are list diffs
                are added to it, so a caller can tell a list from a scalar
                property of the same shape (``fit_full_state``).

        Returns:
            Dict containing the full state
        """
        if target == "properties":
            if subtarget:
                # Specific property list or property
                if hasattr(self, "property_lists") and self.property_lists:
                    if self.property_lists.exists(subtarget):
                        # It's a list - return all items
                        list_attr = getattr(self.property_lists, subtarget)
                        if list_keys is not None:
                            list_keys.add(subtarget)
                        reference, pairs = self._list_state_reference(
                            subtarget, list_attr
                        )
                        if reference is not None:
                            return {subtarget: reference}
                        try:
                            if pairs is not None:
                                # The heads are in hand: resolve from them,
                                # one range read in all.
                                items = self._resolve_list_heads(list_attr, pairs)
                            else:
                                items = list(list_attr)
                        except ListCorruptionError as e:
                            logger.error(
                                f"List '{subtarget}' is corrupted, cannot build "
                                f"full-state resync for it: {e}"
                            )
                            return {}
                        logger.debug(
                            f"Getting full state for list '{subtarget}': {len(items)} items"
                        )
                        # Return as list operation format for diff
                        return {
                            subtarget: {
                                "list": subtarget,
                                "operation": "extend",
                                "items": items,
                            }
                        }

                # Try as scalar property
                prop_data = self.get_property(subtarget)
                if prop_data is not None:
                    logger.debug(f"Getting full state for property '{subtarget}'")
                    return {subtarget: prop_data}
                logger.warning(f"Subtarget '{subtarget}' not found as list or property")
                return {}
            else:
                # All properties - get both scalars and lists.
                # list_all_with_rows() pays for one whole-partition dump
                # and returns it alongside the names, so every list's
                # contents below are served from that dump
                # (to_list_from_rows()) instead of a second whole-list
                # Query per list -- this is the fallback path for peers
                # that don't support incremental resync, so it is lower
                # frequency than the web UI's equivalent fix but still one
                # headless consumers actually reach.
                result = {}
                # Get scalar properties
                all_props = self.get_properties()
                if all_props:
                    result.update(all_props)
                # Get property lists
                if hasattr(self, "property_lists") and self.property_lists:
                    list_names, list_rows = self.property_lists.list_all_with_rows()
                    for list_name in list_names:
                        list_attr = getattr(self.property_lists, list_name)
                        list_attr.prime_from_rows(list_rows)
                        if list_keys is not None:
                            list_keys.add(list_name)
                        reference, _ = self._list_state_reference(
                            list_name, list_attr, list_rows
                        )
                        if reference is not None:
                            result[list_name] = reference
                            continue
                        try:
                            items = list_attr.to_list_from_rows(list_rows)
                        except ListCorruptionError as e:
                            logger.error(
                                f"List '{list_name}' is corrupted, skipping it "
                                f"in full-state resync (other lists still "
                                f"included): {e}"
                            )
                            continue
                        result[list_name] = {
                            "list": list_name,
                            "operation": "extend",
                            "items": items,
                        }
                logger.debug(
                    f"Getting full state for all properties: {len(result)} keys"
                )
                return result
        return {}

    @staticmethod
    def _resolve_list_heads(list_attr: Any, pairs: list[tuple[Any, Any]]) -> list[Any]:
        """The items for heads read with ``resolve=False``: plain items as
        read, spanned ones through ``item_at``. An item deleted since the
        heads were read is dropped (the delete won, as in ``to_list()``); a
        broken one raises ``ListCorruptionError`` as before."""
        from .property_list import UNRESOLVED
        from .property_list import ListCorruptionError as _Corrupt

        items: list[Any] = []
        for handle, item in pairs:
            if item is not UNRESOLVED:
                items.append(item)
                continue
            try:
                items.append(list_attr.item_at(handle)[1])
            except _Corrupt:
                raise
            except IndexError:
                continue
        return items

    def _list_state_reference(
        self, list_name: str, list_attr: Any, rows: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any] | None, list[tuple[Any, Any]] | None]:
        """``(reference, pairs)`` for a list's full state.

        ``reference`` is the full-state reference for a list whose items
        together exceed the span threshold, sized from the heads alone so no
        spanned body is read only to be dropped; ``None`` when the list fits
        (or there is no threshold, or the list is v1). ``pairs`` are the
        heads this read (``items_with_handles(resolve=False)``, for a
        single list without ``rows``), so the caller resolves the items
        from them instead of reading the list again; ``None`` otherwise.
        """
        from .property_list import UNRESOLVED
        from .property_list import ListCorruptionError as _Corrupt
        from .property_list_span import encoded_size

        threshold = getattr(self.config, "list_item_span_threshold", None)
        if not isinstance(threshold, int) or isinstance(threshold, bool):
            return None, None
        core = getattr(list_attr, "_list_prop", list_attr)
        pairs: list[tuple[Any, Any]] | None = None
        try:
            if core.storage_format() != 2:
                return None, None  # a v1 list never spans: read it as before
            if rows is not None:
                sizes = list_attr.sizes_from_rows(rows)
            else:
                heads: list[tuple[Any, Any]] = list_attr.items_with_handles(
                    resolve=False
                )
                pairs = heads
                sizes = [
                    (
                        handle.bytes
                        if handle.bytes is not None
                        else encoded_size(handle.raw_value)
                    )
                    if item is UNRESOLVED
                    else encoded_size(json.dumps(item))
                    for handle, item in heads
                ]
        except (ValueError, _Corrupt):
            return None, None  # v1, or a malformed head: read as before
        total = sum(sizes)
        if total + 2 * len(sizes) + 64 <= threshold:
            return None, pairs
        return {
            "list": list_name,
            "operation": "extend",
            "spanned": True,
            "bytes": total,
        }, None

    def _store_subscription_diff(
        self, peer_id: str, subscription_id: str, sequence: int, data: dict[str, Any]
    ) -> str:
        """Store a subscription diff and return its URL.

        Args:
            peer_id: Peer actor ID
            subscription_id: Subscription ID
            sequence: Sequence number (already incremented)
            data: Diff data to store

        Returns:
            URL to fetch this diff, or "" when it was not stored
        """
        import json

        from .db import get_subscription_diff

        if not self.config:
            logger.error("No config available for storing subscription diff")
            return ""

        # Store diff using low-level diff protocol (sequence already incremented)
        logger.debug(
            f"Storing subscription diff for {subscription_id} seq={sequence}, "
            f"data keys: {list(data.keys())}"
        )

        diff_handle = get_subscription_diff(self.config)
        blob = json.dumps(data)

        logger.debug(f"Diff blob size: {len(blob)} chars")

        success = diff_handle.create(
            actor_id=self.id,
            subid=subscription_id,
            diff=blob,
            seqnr=sequence,
        )

        if not success:
            # Refused (the number already has a diff) or missing arguments: a
            # URL here would point the subscriber at another change's diff.
            logger.error(
                f"Failed to store subscription diff for {subscription_id} seq={sequence}, "
                f"actor_id={self.id}"
            )
            return ""
        logger.info(
            f"Successfully stored subscription diff for {subscription_id} seq={sequence}"
        )

        # Build URL to this diff
        # Format: /{actor_id}/subscriptions/{peer_id}/{subscription_id}/{sequence}
        diff_url = (
            f"{self.config.proto}{self.config.fqdn}/{self.id}"
            f"/subscriptions/{peer_id}/{subscription_id}/{sequence}"
        )
        logger.debug(f"Diff URL: {diff_url}")
        return diff_url

    def _increment_subscription_sequence(
        self, peer_id: str, subscription_id: str
    ) -> int:
        """Increment and return the new sequence number for a subscription.

        Args:
            peer_id: Peer actor ID
            subscription_id: Subscription ID

        Returns:
            New sequence number, or 0 when the subscription no longer exists
        """
        sub_obj = self.get_subscription_obj(peerid=peer_id, subid=subscription_id)
        if not sub_obj:
            return 0

        # Use the increase_seq() method which increments and returns new sequence.
        # 0 when the subscription row is gone: there is no number to give, and
        # 1 would repeat one the subscriber already has.
        new_seq = sub_obj.increase_seq()
        return new_seq if new_seq else 0

    def _leave_sequence_gap(self, sub: dict[str, Any]) -> bool:
        """Move a subscription's sequence on without a diff, so the
        subscriber sees a gap at the next diff and recovers (the protocol's
        "MUST continue incrementing sequence numbers for each change").

        Used when a change got no diff because a read faulted. If the
        increment faults too, nothing can mark the change and it is lost.
        """
        if not self.config or not self.id:
            return True
        from .db import get_subscription

        try:
            moved = get_subscription(self.config).increment_seq(
                actor_id=self.id,
                peerid=sub.get("peerid"),
                subid=sub.get("subscriptionid"),
            )
        except DbError as e:  # folds DbError: reported to register_diffs, which raises after the loop
            logger.error(
                f"Diff for subscription {sub.get('subscriptionid')} lost: no gap "
                f"could be left either: {e}"
            )
            return False
        if moved:
            logger.warning(
                f"Left a gap at sequence {moved} of subscription "
                f"{sub.get('subscriptionid')} for a diff that was not registered"
            )
        return True

    # =========================================================================
    # Diff Registration
    # =========================================================================

    def register_diffs(self, target=None, subtarget=None, resource=None, blob=None):
        """Registers a blob diff against all subscriptions with the correct target, subtarget, and resource.

        If resource is set, the blob is expected to be the FULL resource object, not a diff.

        Note: Skips registration if the target/subtarget is currently suspended.
        Use suspend_subscriptions() and resume_subscriptions() to manage suspension.
        """
        if blob is None or not target:
            return

        # Get all subscriptions, both with the specific subtarget/resource and those
        # without. Deliberately BEFORE the suspension check: with no subscriptions
        # on this target, nothing below the loop runs and the old order paid a
        # suspension GetItem *plus* this fetch to reach the same no-op — on every
        # property write. Suspension and "no subscribers" are the same outcome
        # here, so the cheaper discriminator goes first. (Costs one extra fetch
        # for an actor that is both subscribed and suspended; that fetch is
        # memoised per actor instance and is dwarfed by the callback fan-out
        # suspension exists to avoid.)
        # Strict: the write that produced the diff has committed and stays,
        # but a fault here raises DbError, so the caller answers 503 instead of
        # a lost diff no subscriber could detect (no sequence moves).
        subs = self.get_subscriptions(
            target=target, subtarget=None, resource=None, callback=False, strict=True
        )
        if not subs:
            return

        # Check suspension BEFORE registering diffs
        if self.is_subscription_suspended(target, subtarget):
            logger.debug(
                f"Skipping diff registration for {target}/{subtarget}: suspended"
            )
            return
        if subtarget and resource:
            logger.debug(
                "register_diffs() - blob(%s chars), target(%s), subtarget(%s), resource(%s), # of subs(%s)",
                len(blob),
                target,
                subtarget,
                resource,
                len(subs),
            )
        elif subtarget:
            logger.debug(
                "register_diffs() - blob(%s chars), target(%s), subtarget(%s), # of subs(%s)",
                len(blob),
                target,
                subtarget,
                len(subs),
            )
        else:
            logger.debug(
                "register_diffs() - blob(%s chars), target(%s), # of subs(%s)",
                len(blob),
                target,
                len(subs),
            )
        lost: DbError | None = None
        for sub in subs:
            registered = False
            try:
                # Skip the ones without correct subtarget
                if subtarget and sub["subtarget"] and sub["subtarget"] != subtarget:
                    logger.debug("     - no match on subtarget, skipping...")
                    continue
                # Skip the ones without correct resource
                if resource and sub["resource"] and sub["resource"] != resource:
                    logger.debug("     - no match on resource, skipping...")
                    continue
                sub_obj = self.get_subscription_obj(
                    peerid=sub["peerid"], subid=sub["subscriptionid"]
                )
                if not sub_obj:
                    continue
                sub_obj_data = sub_obj.get()
                logger.debug(
                    "     - processing subscription(%s) for peer(%s) with target(%s) subtarget(%s) and resource(%s)",
                    sub["subscriptionid"],
                    sub["peerid"],
                    sub_obj_data["target"],
                    sub_obj_data["subtarget"] or "",
                    sub_obj_data["resource"] or "",
                )
                # Subscription with a resource, but this diff is on a higher level
                if (
                    (not resource or not subtarget)
                    and sub_obj_data["subtarget"]
                    and sub_obj_data["resource"]
                ):
                    # Create a json diff on the subpart that this subscription
                    # covers
                    try:
                        jsonblob = json.loads(blob)
                        if not subtarget:
                            subblob = json.dumps(
                                jsonblob[sub_obj_data["subtarget"]][
                                    sub_obj_data["resource"]
                                ]
                            )
                        else:
                            subblob = json.dumps(jsonblob[sub_obj_data["resource"]])
                    except (TypeError, ValueError, KeyError):
                        # The diff does not contain the resource
                        logger.debug(
                            "         - subscription has resource(%s), no matching blob found in diff",
                            sub_obj_data["resource"],
                        )
                        continue
                    logger.debug(
                        "         - subscription has resource(%s), adding diff(%s chars)",
                        sub_obj_data["resource"],
                        len(subblob),
                    )
                    finblob = subblob
                # The diff is on the resource, but the subscription is on a
                # higher level
                elif resource and not sub_obj_data["resource"]:
                    # Since we have a resource, we know the blob is the entire resource, not a diff
                    # If the subscription is for a sub-target, send [resource] = blob
                    # If the subscription is for a target, send [subtarget][resource] = blob
                    upblob = {}
                    try:
                        jsonblob = json.loads(blob)
                        if not sub_obj_data["subtarget"]:
                            upblob[subtarget] = {}
                            upblob[subtarget][resource] = jsonblob
                        else:
                            upblob[resource] = jsonblob
                    except (TypeError, ValueError, KeyError):
                        if not sub_obj_data["subtarget"]:
                            upblob[subtarget] = {}
                            upblob[subtarget][resource] = blob
                        else:
                            upblob[resource] = blob
                    finblob = json.dumps(upblob)
                    logger.debug(
                        "         - diff has resource(%s), subscription has not, adding diff(%s bytes)",
                        resource,
                        len(finblob),
                    )
                # Subscriptions with subtarget, but this diff is on a higher level
                elif not subtarget and sub_obj_data["subtarget"]:
                    # Create a json diff on the subpart that this subscription
                    # covers
                    subblob = None
                    try:
                        jsonblob = json.loads(blob)
                        subblob = json.dumps(jsonblob[sub_obj_data["subtarget"]])
                    except (TypeError, ValueError, KeyError):
                        # The diff blob does not contain the subtarget
                        pass
                    logger.debug(
                        "         - subscription has subtarget(%s), adding diff(%s bytes)",
                        sub_obj_data["subtarget"],
                        len(subblob) if subblob else 0,
                    )
                    finblob = subblob
                # The diff is on the subtarget, but the subscription is on the
                # higher level
                elif subtarget and not sub_obj_data["subtarget"]:
                    # Create a data["subtarget"] = blob diff to give correct level
                    # of diff to subscriber
                    upblob = {}
                    try:
                        jsonblob = json.loads(blob)
                        upblob[subtarget] = jsonblob
                    except (TypeError, ValueError, KeyError):
                        upblob[subtarget] = blob
                    finblob = json.dumps(upblob)
                    logger.debug(
                        "         - diff has subtarget(%s), subscription has not, adding diff(%s chars)",
                        subtarget,
                        len(finblob),
                    )
                else:
                    # The diff is correct for the subscription
                    logger.debug(
                        "         - exact target/subtarget match, adding diff(%s chars)",
                        len(blob),
                    )
                    finblob = blob
                if sub_obj:
                    diff = sub_obj.add_diff(blob=finblob)
                else:
                    diff = None
                # add_diff returned, so it used a sequence number: a failure
                # from here on leaves a stored diff or a gap already.
                registered = True
                if not diff:
                    logger.warning(
                        "Failed when registering a diff to subscription (%s). Will not send callback.",
                        sub["subscriptionid"],
                    )
                else:
                    # Direct call - callback_subscription handles sync/async internally
                    self.callback_subscription(
                        peerid=sub["peerid"],
                        sub_obj=sub_obj,
                        sub=sub_obj_data,
                        diff=diff,
                        blob=finblob,
                    )
            except DbError as e:  # folds DbError: one subscriber skipped; gap tried
                # One subscriber's fault must not stop the others or fail the
                # write that produced the diff, which has committed.
                logger.error(
                    f"Diff registration for subscription {sub.get('subscriptionid')} "
                    f"skipped on a store fault: {e}"
                )
                if not registered:
                    # The read faulted before the resource checks below it,
                    # so a subscriber that would have got no diff can get a
                    # gap too; it resyncs needlessly, which is safe.
                    if not self._leave_sequence_gap(sub):
                        lost = lost or e
        if lost is not None:
            # Neither a diff nor a gap for some subscriber: the change is
            # undetectable for it. The write stands; the caller answers 503.
            raise lost


def _resync_id(sub: dict[str, Any]) -> str:
    """A subscription's key in the resync record: subscription ids are
    unique per peer, not per publisher."""
    return f"{sub.get('peerid')}:{sub.get('subscriptionid')}"


class Actors:
    """Handles all actors"""

    def fetch(self):
        if not self.list:
            return False
        if self.actors is not None:
            return self.actors
        self.actors = self.list.fetch()
        return self.actors

    def __init__(self, config=None):
        self.config = config
        if self.config:
            self.list = get_actor_list(self.config)
        else:
            self.list = None
        self.actors = None
        self.fetch()
