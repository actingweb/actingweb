"""The wire harness: a recorder, a scenario driver, a normaliser and a comparer.

Built by the spike for ``thoughts/plans/2026-11-06-subscription-wire-baseline.md``
and landed by ``thoughts/plans/2026-11-06-peer-authorisation-fixes.md``
(Phase 0). Which plan and phase may change each recording is in
``wire/rows.toml``. Not a test file. Everything here runs in the pytest process, which also hosts the
two wire apps as uvicorn threads, so the recorder sees every request either
app serves and the snapshot reads both actors' stores through the library
with each app's own ``Config``.

A recording is a JSON document: the requests that crossed the wire during the
scenario's steps (nested: a request that started while another was open is a
child of it), the hook calls the wire apps made, and a snapshot of both actors
after every step. The normaliser replaces ids, hosts, secrets and timestamps
with names so that two runs with different actors produce the same bytes.
"""

from __future__ import annotations

import base64
import contextlib
import copy
import json
import os
import re
import threading
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from actingweb.actor import Actor
from actingweb.attribute import Attributes
from actingweb.callback_processor import CallbackProcessor
from actingweb.config import Config
from actingweb.constants import PEER_PERMISSIONS_BUCKET, TRUST_PERMISSIONS_BUCKET
from actingweb.db import get_subscription_suspension
from actingweb.interface.actor_interface import ActorInterface
from actingweb.remote_storage import RemotePeerStore
from actingweb.subscription import Subscription
from actingweb.trust import Trust

# ---------------------------------------------------------------------------
# The recorder
# ---------------------------------------------------------------------------

RECORDS: list[dict[str, Any]] = []
_OPEN: list[dict[str, Any]] = []
_LOCK = threading.Lock()
_state = {"recording": False}
# Requests a wire app is serving now, recorded or not: a step starts and ends
# only when none is in flight, so no request spills from one step into the
# next.
_INFLIGHT = {"count": 0}

_HEADERS_KEPT = ("location", "content-type", "www-authenticate", "retry-after")


def start_recording() -> None:
    """Begin a recording: clear what was recorded and open the gate."""
    with _LOCK:
        RECORDS.clear()
        _OPEN.clear()
        _state["recording"] = True


def stop_recording() -> list[dict[str, Any]]:
    """Close the gate and return a copy of what was recorded."""
    with _LOCK:
        _state["recording"] = False
        return copy.deepcopy(RECORDS)


def wait_for_quiet(timeout: float = 15.0) -> None:
    """Wait until no wire app is serving a request."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with _LOCK:
            if _INFLIGHT["count"] == 0:
                return
        time.sleep(0.02)
    raise TimeoutError(f"{_INFLIGHT['count']} wire request(s) still in flight")


def _append(entry: dict[str, Any]) -> None:
    """Append ``entry`` under the most recently opened request, or at the top."""
    parent = _OPEN[-1] if _OPEN else None
    if parent is not None:
        parent["children"].append(entry)
    else:
        RECORDS.append(entry)


def record_event(kind: str, **fields: Any) -> None:
    """Record a hook call the wire app made, nested in the open request."""
    if not _state["recording"]:
        return
    with _LOCK:
        _append({"event": kind, **fields})


def _decode(body: bytes, content_type: str) -> Any:
    if not body:
        return None
    if "json" in content_type:
        try:
            return json.loads(body)
        except ValueError:
            pass
    text = body.decode("utf-8", errors="replace")
    if "html" in content_type:
        return f"<html {len(text)} chars>"
    return text


class RecordingMiddleware:
    """A pure ASGI middleware that records every HTTP request to a wire app."""

    def __init__(self, app: Any, host: str) -> None:
        self.app = app
        self.host = host

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        with _LOCK:
            _INFLIGHT["count"] += 1
        try:
            if not _state["recording"]:
                await self.app(scope, receive, send)
            else:
                await self._record(scope, receive, send)
        finally:
            with _LOCK:
                _INFLIGHT["count"] -= 1

    async def _record(self, scope: Any, receive: Any, send: Any) -> None:
        headers = {k.decode(): v.decode() for k, v in scope.get("headers", [])}
        entry: dict[str, Any] = {
            "host": self.host,
            "method": scope["method"],
            "path": scope["path"],
            "query": scope.get("query_string", b"").decode(),
            "auth": headers.get("authorization"),
            "request": None,
            "status": None,
            "headers": {},
            "response": None,
            "children": [],
        }
        req_chunks: list[bytes] = []
        resp_chunks: list[bytes] = []

        async def recv() -> Any:
            message = await receive()
            if message["type"] == "http.request":
                req_chunks.append(message.get("body", b""))
            return message

        async def snd(message: Any) -> None:
            if message["type"] == "http.response.start":
                entry["status"] = message["status"]
                for k, v in message.get("headers", []):
                    name = k.decode().lower()
                    if name in _HEADERS_KEPT:
                        entry["headers"][name] = v.decode()
            elif message["type"] == "http.response.body":
                resp_chunks.append(message.get("body", b""))
            await send(message)

        with _LOCK:
            _append(entry)
            _OPEN.append(entry)
        try:
            await self.app(scope, recv, snd)
        except Exception as exc:  # noqa: BLE001 - recorded, then re-raised
            # The status the caller received: 500 only when no response
            # had started.
            if entry["status"] is None:
                entry["status"] = 500
            entry["exception"] = type(exc).__name__
            raise
        finally:
            with _LOCK:
                with contextlib.suppress(ValueError):
                    _OPEN.remove(entry)
            entry["request"] = _decode(
                b"".join(req_chunks), headers.get("content-type", "")
            )
            entry["response"] = _decode(
                b"".join(resp_chunks), entry["headers"].get("content-type", "")
            )


# ---------------------------------------------------------------------------
# Actors, the pair and the snapshot
# ---------------------------------------------------------------------------


class WireHost:
    """One wire app: its URL and its ``ActingWebApp`` (for the ``Config``)."""

    def __init__(self, name: str, url: str, config: Config) -> None:
        self.name = name
        self.url = url
        self.config = config

    def interface(self, actor_id: str) -> ActorInterface:
        """An ``ActorInterface`` for an existing actor, under this app's config."""
        core = Actor(config=self.config)
        core.get(actor_id=actor_id)
        assert core.id == actor_id, f"actor {actor_id} not found on {self.name}"
        return ActorInterface(core)


class WireActor:
    """An actor the pair created: where it lives and how to speak for it."""

    def __init__(self, name: str, host: WireHost, record: dict[str, Any]) -> None:
        self.name = name
        self.host = host
        self.id: str = record["id"]
        self.url: str = f"{host.url}/{self.id}"
        self.creator: str = record["creator"]
        self.passphrase: str = record["passphrase"]

    @property
    def basic(self) -> tuple[str, str]:
        return (self.creator, self.passphrase)

    def interface(self) -> ActorInterface:
        return self.host.interface(self.id)


def _sub_order(row: dict[str, Any], names: dict[str, str]) -> tuple[str, ...]:
    """A subscription row's place in a snapshot: by what it subscribes to
    before its (random) id, so two subscriptions of one peer keep an order."""
    return (
        str(names.get(row["peerid"], row["peerid"])),
        str(row.get("target") or ""),
        str(row.get("subtarget") or ""),
        str(row.get("resource") or ""),
        str(row.get("granularity") or ""),
        row["subscriptionid"],
    )


_TRUST_KEPT = (
    "relationship",
    "approved",
    "peer_approved",
    "verified",
    "baseuri",
    "secret",
    "established_via",
)


def _snapshot_trust(actor: WireActor, peer: WireActor) -> dict[str, Any] | None:
    """The actor's trust row for the peer: the authorisation state only (the
    secret by name; the verification token as present or not)."""
    row = Trust(actor_id=actor.id, peerid=peer.id, config=actor.host.config).get()
    if not row:
        return None
    out = {k: row.get(k) for k in _TRUST_KEPT}
    out["has_verification_token"] = bool(row.get("verification_token"))
    return out


def _snapshot_attribute(actor: WireActor, bucket: str, name: str) -> Any:
    row = Attributes(actor_id=actor.id, bucket=bucket, config=actor.host.config)
    found = row.get_attr(name=name)
    if not found:
        return None
    data = found.get("data")
    # Stored as a JSON string by one backend and decoded by another: compare
    # the decoded value, whose keys the comparer sorts.
    if isinstance(data, str):
        with contextlib.suppress(ValueError):
            return json.loads(data)
    return data


def _snapshot_queue(actor: WireActor, names: dict[str, str]) -> list[dict[str, Any]]:
    core = Actor(config=actor.host.config)
    core.get(actor_id=actor.id)
    rows = core.get_subscriptions(callback=False) or []
    out: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda r: _sub_order(r, names)):
        sub = Subscription(
            actor_id=actor.id,
            peerid=row["peerid"],
            subid=row["subscriptionid"],
            config=actor.host.config,
        )
        diffs = sub.get_diffs() or []
        out.append(
            {
                "peer": row["peerid"],
                "subscriptionid": row["subscriptionid"],
                "target": row.get("target"),
                "subtarget": row.get("subtarget"),
                "granularity": row.get("granularity"),
                "sequence": row.get("sequence"),
                "diffs": [
                    {
                        "sequence": d.get("sequence"),
                        "timestamp": d.get("timestamp"),
                        "data": d.get("diff", d.get("data")),
                    }
                    for d in diffs
                ],
            }
        )
    return out


def _snapshot_subscriptions(
    actor: WireActor, names: dict[str, str]
) -> list[dict[str, Any]]:
    core = Actor(config=actor.host.config)
    core.get(actor_id=actor.id)
    rows = core.get_subscriptions() or []
    keep = (
        "peerid",
        "subscriptionid",
        "target",
        "subtarget",
        "resource",
        "granularity",
        "sequence",
        "callback",
    )
    return [
        {k: row.get(k) for k in keep}
        for row in sorted(rows, key=lambda r: _sub_order(r, names))
    ]


def _snapshot_replica(subscriber: WireActor, publisher: WireActor) -> dict[str, Any]:
    store = RemotePeerStore(
        actor=subscriber.interface(), peer_id=publisher.id, validate_peer_id=False
    )
    scalars = {name: store.get_value(name) for name in sorted(store.list_all_scalars())}
    lists = {name: store.get_list(name) for name in sorted(store.list_all_lists())}
    return {"scalars": scalars, "lists": lists}


def _snapshot_callback_state(
    subscriber: WireActor, publisher: WireActor, names: dict[str, str]
) -> list[dict[str, Any]]:
    core = Actor(config=subscriber.host.config)
    core.get(actor_id=subscriber.id)
    rows = core.get_subscriptions(peerid=publisher.id, callback=True) or []
    processor = CallbackProcessor(subscriber.interface())
    out: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda r: _sub_order(r, names)):
        info = processor.get_state_info(publisher.id, row["subscriptionid"])
        out.append({"subscriptionid": row["subscriptionid"], **info})
    return out


def _snapshot_suspensions(actor: WireActor) -> list[dict[str, Any]]:
    store = get_subscription_suspension(actor.host.config, actor.id)
    return [
        {"target": target, "subtarget": subtarget or ""}
        for target, subtarget in sorted(
            store.get_all_suspended(), key=lambda t: (t[0], t[1] or "")
        )
    ]


def snapshot(
    publisher: WireActor, subscribers: list[WireActor], names: dict[str, str]
) -> dict[str, Any]:
    """What both sides hold: the queue, the replicas, the callback state, the rows."""
    return {
        "publisher": {
            "queue": _snapshot_queue(publisher, names),
            "subscriptions": _snapshot_subscriptions(publisher, names),
            "suspensions": _snapshot_suspensions(publisher),
            "trust": {s.name: _snapshot_trust(publisher, s) for s in subscribers},
            # What the publisher grants each subscriber (its override row).
            "grants": {
                s.name: _snapshot_attribute(
                    publisher, TRUST_PERMISSIONS_BUCKET, f"{publisher.id}:{s.id}"
                )
                for s in subscribers
            },
        },
        "subscribers": {
            s.name: {
                "replica": _snapshot_replica(s, publisher),
                "callback_state": _snapshot_callback_state(s, publisher, names),
                "subscriptions": _snapshot_subscriptions(s, names),
                "trust": _snapshot_trust(s, publisher),
                # The subscriber's stored copy of what the publisher grants it.
                "peer_permissions": _snapshot_attribute(
                    s, PEER_PERMISSIONS_BUCKET, f"{s.id}:{publisher.id}"
                ),
            }
            for s in subscribers
        },
    }


# ---------------------------------------------------------------------------
# The driver
# ---------------------------------------------------------------------------

Step = Callable[[], Any]


class Scenario:
    """A named list of steps; the driver records the wire and snapshots after each."""

    def __init__(
        self,
        publisher: WireActor,
        subscribers: list[WireActor],
        names: dict[str, str],
        secrets: dict[str, str],
    ) -> None:
        self.publisher = publisher
        self.subscribers = subscribers
        self.names = names
        self.secrets = secrets
        self.steps: list[dict[str, Any]] = []
        # Set by the ``wire_pair`` fixture.
        self.relationship: str = ""
        self.trust_secret: str = ""

    def name(self, value: str, label: str, *, secret: bool = False) -> None:
        """Name a value first seen mid-row (an actor id, a secret, a token),
        so the normaliser replaces it and its guard does not fail on it."""
        if secret:
            self.secrets[value] = label
        else:
            self.names[value] = label

    def step(
        self, label: str, action: Step, *, settle: Callable[[], None] | None = None
    ) -> Any:
        """Run one step with the recorder open, then snapshot both sides.

        The recorder opens when no wire request is in flight and closes when
        the action, its settle condition and every request they started have
        finished."""
        wait_for_quiet()
        start_recording()
        try:
            result = action()
            if settle is not None:
                settle()
            wait_for_quiet()
        finally:
            wire = stop_recording()
        self.steps.append(
            {
                "step": label,
                "result": _describe_result(result),
                "wire": wire,
                "after": snapshot(self.publisher, self.subscribers, self.names),
            }
        )
        return result

    def recording(self) -> dict[str, Any]:
        return normalise({"steps": self.steps}, self.names, self.secrets)


def _describe_result(result: Any) -> Any:
    if isinstance(result, requests.Response):
        body: Any
        try:
            body = result.json()
        except ValueError:
            body = result.text
        return {"status": result.status_code, "body": body}
    return result


# ---------------------------------------------------------------------------
# The normaliser
# ---------------------------------------------------------------------------

_HEX32 = re.compile(r"\b[0-9a-f]{32}\b")
_PORT = re.compile(r"localhost:5[5-9]\d\d")
# Timestamp shapes the library produces, each kept as its own class so a
# format change shows as a diff and equal values stay equal.
_TS_SHAPES: list[tuple[str, re.Pattern[str]]] = [
    ("iso-z", re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z")),
    (
        "iso-offset",
        re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?[+-]\d{2}:\d{2}"),
    ),
    ("iso-naive", re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?")),
    ("space", re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(\.\d+)?")),
]
_EPOCH_KEYS = {
    "_received_at",
    "claimed_at",
    "suspended_at",
    "capabilities_fetched_at",
    "permissions_fetched_at",
}
# The trust types the wire apps register: a listing of trust types (an
# actor's /meta) keeps only these, since every app in a test worker shares
# the registry's rows and other tests add their own.
WIRE_TRUST_TYPES = {
    "admin",
    "associate",
    "friend",
    "mcp_client",
    "partner",
    "subscriber",
    "subscriber_adopted",
    "viewer",
}
_SECRET_KEYS = {
    "secret",
    "passphrase",
    "verification_token",
    "verify",
    "nonce",
    "token",
}


class Normaliser:
    def __init__(
        self, names: dict[str, str], secrets: dict[str, str], *, identity: bool = False
    ) -> None:
        # identity: number timestamp tokens by first appearance, so two equal
        # values stay equal and two distinct ones stay distinct. Off, a token
        # carries only its format class, which is what a cross-backend file
        # needs (DynamoDB stamps every diff with the module-import time).
        self.identity = identity
        self.names = dict(names)  # actor id -> name
        self.secrets = dict(secrets)  # secret value -> name
        self.subids: dict[str, str] = {}
        self.timestamps: dict[str, str] = {}
        self.epochs: dict[str, str] = {}
        self.hosts: dict[str, str] = {}

    def host(self, port_host: str, name: str) -> None:
        self.hosts[port_host] = name

    def _sub(self, subid: str) -> str:
        if subid not in self.subids:
            self.subids[subid] = f"<sub{len(self.subids) + 1}>"
        return self.subids[subid]

    def collect_subids(self, value: Any) -> None:
        """First pass: name every subscription id by first appearance, so the
        second pass can replace it inside paths and URLs as well."""
        if isinstance(value, dict):
            for k, v in value.items():
                if k in ("subscriptionid", "subid") and isinstance(v, str) and v:
                    self._sub(v)
                else:
                    self.collect_subids(v)
        elif isinstance(value, list):
            for v in value:
                self.collect_subids(v)

    def _ts(self, kind: str, value: str) -> str:
        if not self.identity:
            return f"<ts:{kind}>"
        if value not in self.timestamps:
            self.timestamps[value] = f"<ts:{kind}#{len(self.timestamps) + 1}>"
        return self.timestamps[value]

    def _epoch(self, value: Any) -> str:
        key = repr(value)
        if key not in self.epochs:
            self.epochs[key] = f"<epoch#{len(self.epochs) + 1}>"
        return self.epochs[key]

    def string(self, value: str) -> str:
        for secret, name in self.secrets.items():
            if secret and secret in value:
                value = value.replace(secret, f"<secret:{name}>")
        for actor_id, name in self.names.items():
            value = value.replace(actor_id, f"<{name}>")
        for subid, name in self.subids.items():
            value = value.replace(subid, name)
        for port_host, name in self.hosts.items():
            value = value.replace(port_host, f"<{name}>")
        for kind, pattern in _TS_SHAPES:
            match = pattern.fullmatch(value)
            if match:
                return self._ts(kind, value)
        return value

    def auth(self, header: str | None) -> str | None:
        if header is None:
            return None
        scheme, _, rest = header.partition(" ")
        if scheme.lower() == "basic":
            try:
                user = base64.b64decode(rest).decode().split(":", 1)[0]
            except (ValueError, UnicodeDecodeError):
                user = "?"
            return f"basic:{self.string(user)}"
        if scheme.lower() == "bearer":
            return f"bearer:{self.secrets.get(rest, '?unknown')}"
        return f"{scheme}:?"

    def walk(self, value: Any, key: str | None = None) -> Any:
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for k, v in value.items():
                nk = self.string(k) if isinstance(k, str) else k
                if nk == "auth" and isinstance(v, str | type(None)):
                    out[nk] = self.auth(v)
                elif nk in ("subscriptionid", "subid") and isinstance(v, str):
                    out[nk] = self._sub(v)
                elif nk in _SECRET_KEYS and isinstance(v, str):
                    # A value nobody named fails the guard: a secret first
                    # seen mid-row is named by the scenario
                    # (``Scenario.name(value, "trust:A-B#2", secret=True)``).
                    out[nk] = f"<secret:{self.secrets.get(v, '?unnamed')}>"
                elif nk in _EPOCH_KEYS and isinstance(v, int | float | str):
                    out[nk] = self._epoch(v)
                elif nk == "aw_trust_types" and isinstance(v, list):
                    out[nk] = [t for t in v if t in WIRE_TRUST_TYPES]
                else:
                    out[nk] = self.walk(v, nk)
            return out
        if isinstance(value, list):
            return [self.walk(v, key) for v in value]
        if isinstance(value, str):
            return self.string(value)
        if isinstance(value, datetime):
            # A stored row read back through the library: pynamodb returns an
            # aware datetime, psycopg a naive one; one class for both.
            return self._ts("stored", value.isoformat())
        return value


def normalise(
    recording: dict[str, Any], names: dict[str, str], secrets: dict[str, str]
) -> dict[str, Any]:
    """Replace ids, hosts, secrets and timestamps with names; fail on survivors."""
    norm = Normaliser(
        names, secrets, identity=os.environ.get("WIRE_TS_IDENTITY") == "1"
    )
    for port_host, name in _wire_hosts().items():
        norm.host(port_host, name)
    norm.collect_subids(recording)
    out = norm.walk(recording)
    text = json.dumps(out)
    leaked = _HEX32.findall(text) + _PORT.findall(text)
    for secret in secrets:
        if secret and secret in text:
            leaked.append("<a secret>")
    if "?unknown" in text:
        leaked.append("<an unknown bearer>")
    if "?unnamed" in text:
        leaked.append("<an unnamed secret>")
    assert not leaked, f"normaliser left: {sorted(set(leaked))[:5]}"
    return out


_WIRE_HOSTS: dict[str, str] = {}


def register_wire_host(port_host: str, name: str) -> None:
    _WIRE_HOSTS[port_host] = name


def _wire_hosts() -> dict[str, str]:
    return dict(_WIRE_HOSTS)


# ---------------------------------------------------------------------------
# Compare or record
# ---------------------------------------------------------------------------

WIRE_DIR = Path(__file__).parent / "wire"


def recording_requested(row: str) -> bool:
    """Whether ``WIRE_RECORD`` names ``row``: a comma-separated list of row
    ids (``WIRE_RECORD=WD6.subscriber,WQ3.subscriber``). Only the rows named
    are rewritten; there is no "all", so a re-recording cannot absorb a
    change to a row it did not mean to touch."""
    wanted = {r.strip() for r in os.environ.get("WIRE_RECORD", "").split(",")}
    return row in wanted


def check(row: str, recording: dict[str, Any], *, variant: str | None = None) -> None:
    """Compare with the row's file, or rewrite it when ``WIRE_RECORD`` names
    the row (``recording_requested``). ``row`` is the id ``rows.toml`` uses;
    ``variant`` the topology, when the row has one file per topology."""
    name = f"{row}.{variant}.json" if variant else f"{row}.json"
    path = WIRE_DIR / name
    # Keys sorted: PostgreSQL's jsonb returns object keys sorted, DynamoDB in
    # insertion order, and neither order is part of what travels.
    text = json.dumps(recording, indent=1, sort_keys=True) + "\n"
    if os.environ.get("WIRE_RECORD"):
        assert not os.environ.get("CI"), "WIRE_RECORD is refused under CI"
    if recording_requested(row):
        WIRE_DIR.mkdir(exist_ok=True)
        path.write_text(text)
        return
    assert path.exists(), f"no recording for {row}; run with WIRE_RECORD={row}"
    expected = path.read_text()
    if expected != text:
        actual = path.with_suffix(".actual.json")
        actual.write_text(text)
        import difflib

        diff = "\n".join(
            difflib.unified_diff(
                expected.splitlines(),
                text.splitlines(),
                str(path.name),
                str(actual.name),
                lineterm="",
                n=2,
            )
        )
        raise AssertionError(f"{row} differs from its recording:\n{diff[:6000]}")


def wait_until(
    condition: Callable[[], bool], timeout: float = 10.0, interval: float = 0.05
) -> None:
    """Poll ``condition`` until true; used only where a callback is fire-and-forget."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(interval)
    raise TimeoutError("condition not met")


def all_names(actors: Iterable[WireActor]) -> dict[str, str]:
    return {a.id: a.name for a in actors}
