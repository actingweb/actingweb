#!/usr/bin/env python3
"""A live pair: two applications on two library versions, as peers.

The wire recordings (``tests/integration/wire/``) are one version of the
library talking to itself. This script answers the other question: what
happens when an application on the previous release and one on this tree
are peers. It is one launcher for both sides, built only from builder calls
both versions have, so the same file runs under either installed library.

Two commands:

``serve``
    Start one application on ``127.0.0.1``. Every request it serves is
    appended to a capture file, one JSON object per line, with secrets
    scrubbed. ``POST /pair-ctl`` (loopback only) runs the SDK operations a
    flow needs that no protocol route performs (a list write, a pull, a
    suspension, a read of the replica).

``drive``
    Run nine flows between two running sides, in both directions, and
    write the outcome of each as JSON: trust creation and approval,
    permission exchange, subscription creation, push callbacks, pull,
    suspension, resync, list diffs, deletion.

Usage (DynamoDB Local on :8001; each side its own table prefix)::

    # the previous release, in its own virtualenv
    AWS_DB_PREFIX=pair_old_ python scripts/live_pair.py serve \\
        --label v3.15.1 --port 5701 --capture /tmp/pair/old.jsonl
    # this tree (on an empty prefix the first start enables creator
    # uniqueness itself)
    AWS_DB_PREFIX=pair_new_ python scripts/live_pair.py serve \\
        --label release --port 5702 --capture /tmp/pair/new.jsonl
    python scripts/live_pair.py drive --old http://127.0.0.1:5701 \\
        --new http://127.0.0.1:5702 --out /tmp/pair/result.json

A third command, ``same-store``, is the mixed-version check of an operator
command (4.0 adoption findings, AC-40 and AC-41): the previous release
serves on one prefix under a small request loop (create an actor, an
authenticated read, a write of an indexed property) while a command of
this tree runs against the same prefix. Afterwards every actor the loop
created must be readable by both versions, and each indexed value it wrote
must be found by this tree's reverse lookup::

    AWS_DB_PREFIX=pair_same_ INDEXED_PROPERTIES=email \
        python scripts/live_pair.py serve --label v3.15.1 --port 5701 \
        --capture /tmp/pair/same.jsonl            # previous release
    AWS_DB_PREFIX=pair_same_ INDEXED_PROPERTIES=email \
        python scripts/live_pair.py same-store --old http://127.0.0.1:5701 \
        --out /tmp/pair/same-mark.json -- actingweb-mark-actors-vouched --apply
    # likewise with: -- actingweb-property-lookup backfill --apply

On PostgreSQL set ``DATABASE_BACKEND=postgresql`` and the ``PG_DB_*``
variables, and give each side its own schema with ``PG_DB_PREFIX`` (migrated
with ``alembic upgrade head`` first) instead of ``AWS_DB_PREFIX``.

Nothing here is for production: the control route has no authentication
beyond the loopback check, and the captures hold request bodies.
"""

import argparse
import base64
import json
import os
import sys
import threading
import time
import traceback
import uuid
from typing import Any

# Keys whose values never reach a capture or a result.
_SECRET_KEYS = {
    "secret",
    "passphrase",
    "verificationToken",
    "verification_token",
    "verify",
    "token",
    "access_token",
    "refresh_token",
    "client_secret",
}
CTL_PATH = "/pair-ctl"


def scrub(value: Any) -> Any:
    """Replace every secret value, keeping the shape."""
    if isinstance(value, dict):
        return {
            k: ("<scrubbed>" if k in _SECRET_KEYS and v else scrub(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


def _auth_shape(header: str | None) -> str | None:
    """The scheme of an ``Authorization`` header, and for Basic the user."""
    if not header:
        return None
    scheme, _, rest = header.partition(" ")
    if scheme.lower() == "basic":
        try:
            return "basic:" + base64.b64decode(rest).decode().split(":", 1)[0]
        except ValueError:
            return "basic:?"
    return scheme.lower()


def _decode(body: bytes, content_type: str) -> Any:
    if not body:
        return None
    if "json" in content_type:
        try:
            return scrub(json.loads(body))
        except ValueError:
            pass
    return f"<{len(body)} bytes, {content_type or 'no content type'}>"


class CaptureMiddleware:
    """A pure ASGI middleware: one line per request this side served."""

    def __init__(self, app: Any, label: str, path: str) -> None:
        self.app = app
        self.label = label
        self.path = path
        self.lock = threading.Lock()

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope["path"] == CTL_PATH:
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        entry: dict[str, Any] = {
            "served_by": self.label,
            "at": time.time(),
            "method": scope["method"],
            "path": scope["path"],
            "query": scope.get("query_string", b"").decode(),
            "auth": _auth_shape(headers.get("authorization")),
            "status": None,
        }
        request_chunks: list[bytes] = []
        response_chunks: list[bytes] = []
        response_type = {"value": ""}

        async def recv() -> Any:
            message = await receive()
            if message["type"] == "http.request":
                request_chunks.append(message.get("body", b""))
            return message

        async def snd(message: Any) -> None:
            if message["type"] == "http.response.start":
                entry["status"] = message["status"]
                for k, v in message.get("headers", []):
                    if k.decode().lower() == "content-type":
                        response_type["value"] = v.decode()
            elif message["type"] == "http.response.body":
                response_chunks.append(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, recv, snd)
        except Exception as exc:
            entry["exception"] = type(exc).__name__
            if entry["status"] is None:
                entry["status"] = 500
            raise
        finally:
            entry["request"] = _decode(
                b"".join(request_chunks), headers.get("content-type", "")
            )
            entry["response"] = _decode(
                b"".join(response_chunks), response_type["value"]
            )
            with self.lock, open(self.path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, sort_keys=True, default=str) + "\n")


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------


def _jsonable(value: Any) -> Any:
    """A value an SDK call returned, as JSON."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [_jsonable(v) for v in value]
    for attr in ("to_dict", "_asdict"):
        method = getattr(value, attr, None)
        if callable(method):
            try:
                return _jsonable(method())
            except Exception:  # noqa: BLE001 - a result we only describe
                break
    if hasattr(value, "__dict__"):
        return {
            k: _jsonable(v) for k, v in vars(value).items() if not k.startswith("_")
        }
    return repr(value)


def _control(config: Any, body: dict[str, Any]) -> Any:
    """Run one SDK operation for an actor of this side."""
    from actingweb.actor import Actor
    from actingweb.interface.actor_interface import ActorInterface
    from actingweb.remote_storage import RemotePeerStore

    core = Actor(config=config)
    core.get(actor_id=body["actor"])
    if core.id != body["actor"]:
        return {"error": "no such actor"}
    actor = ActorInterface(core)
    op = body["op"]
    peer = body.get("peer", "")

    if op == "list":
        lst = getattr(actor.property_lists, body["name"])
        action, args = body["action"], body.get("args", [])
        if action == "setitem":
            lst[args[0]] = args[1]
            return None
        if action == "delitem":
            del lst[args[0]]
            return None
        return _jsonable(getattr(lst, action)(*args))
    if op == "sync":
        return _jsonable(actor.subscriptions.sync_peer(peer))
    if op == "suspend":
        return actor.subscriptions.suspend(body["target"], body.get("subtarget"))
    if op == "resume":
        return actor.subscriptions.resume(body["target"], body.get("subtarget"))
    if op == "replica":
        store = RemotePeerStore(actor=actor, peer_id=peer, validate_peer_id=False)
        lists: dict[str, Any] = {}
        for name in sorted(store.list_all_lists()):
            try:
                lists[name] = store.get_list(name)
            except Exception as exc:  # noqa: BLE001 - what a reader meets
                lists[name] = {"read_error": f"{type(exc).__name__}: {exc}"}
        return {
            "scalars": {
                name: store.get_value(name) for name in sorted(store.list_all_scalars())
            },
            "lists": lists,
        }
    if op == "state":
        trust = core.get_trust_relationships(peerid=peer) if peer else []
        kept = ("relationship", "approved", "peer_approved", "verified", "peerid")
        permissions = None
        try:
            from actingweb.peer_permissions import get_peer_permission_store

            found = get_peer_permission_store(config).get_permissions(
                body["actor"], peer
            )
            permissions = _jsonable(found)
        except Exception as exc:  # noqa: BLE001 - reported, not fatal
            permissions = {"read_error": f"{type(exc).__name__}: {exc}"}
        subs_kept = (
            "peerid",
            "subscriptionid",
            "target",
            "subtarget",
            "resource",
            "granularity",
            "sequence",
            "callback",
        )
        return {
            "trust": [{k: row.get(k) for k in kept} for row in trust or []],
            "peer_permissions": scrub(permissions),
            "subscriptions": [
                {k: row.get(k) for k in subs_kept}
                for row in (core.get_subscriptions(peerid=peer) or [])
            ],
        }
    return {"error": f"unknown op {op}"}


def build_app(label: str, port: int, capture: str) -> Any:
    """The application, from builder calls both versions have."""
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse

    import actingweb
    from actingweb.interface import ActingWebApp

    aw_app = (
        ActingWebApp(
            aw_type="urn:actingweb:example.test:live-pair",
            # An explicit database= wins over DATABASE_BACKEND, so the
            # backend is read here: the pair runs on either.
            database=os.getenv("DATABASE_BACKEND", "dynamodb"),
            fqdn=f"127.0.0.1:{port}",
            proto="http://",
        )
        .with_web_ui(enable=False)
        .with_devtest(enable=False)
        .with_sync_callbacks(enable=True)
        .with_peer_profile(attributes=["displayname"])
        .with_peer_capabilities(enable=True)
        .with_peer_permissions(enable=True)
        .with_subscription_processing(
            auto_sequence=True,
            auto_storage=True,
            auto_cleanup=True,
            gap_timeout_seconds=2.0,
            max_pending=5,
        )
    )
    fastapi_app = FastAPI(title=f"live pair: {label}")

    @fastapi_app.get("/pair-info")
    def info() -> dict[str, str]:
        # Until the bump both sides report the same version at /meta: the
        # label is what tells a capture's two sides apart.
        return {
            "label": label,
            "library": actingweb.__version__,
            "library_path": os.path.dirname(actingweb.__file__),
            "python": sys.version.split()[0],
        }

    @fastapi_app.post(CTL_PATH)
    def control(request: Request, body: dict[str, Any]) -> JSONResponse:
        if request.client is None or request.client.host != "127.0.0.1":
            return JSONResponse({"error": "loopback only"}, status_code=403)
        try:
            return JSONResponse({"result": _control(aw_app.get_config(), body)})
        except Exception as exc:  # noqa: BLE001 - the outcome is the result
            return JSONResponse(
                {
                    "error": f"{type(exc).__name__}: {exc}",
                    "trace": traceback.format_exc(limit=6),
                }
            )

    aw_app.integrate_fastapi(fastapi_app)
    return CaptureMiddleware(fastapi_app, label, capture)


def serve(args: argparse.Namespace) -> int:
    import uvicorn

    os.makedirs(os.path.dirname(os.path.abspath(args.capture)), exist_ok=True)
    app = build_app(args.label, args.port, args.capture)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


# ---------------------------------------------------------------------------
# drive
# ---------------------------------------------------------------------------


class Side:
    """One running application and the actor the pair created on it."""

    def __init__(self, url: str) -> None:
        import requests

        self.http = requests
        self.url = url.rstrip("/")
        self.info: dict[str, str] = requests.get(
            f"{self.url}/pair-info", timeout=10
        ).json()
        self.label = self.info["label"]
        self.id = ""
        self.auth: tuple[str, str] = ("", "")

    def create(self, name: str) -> None:
        creator = f"{name}_{uuid.uuid4().hex[:8]}@example.test"
        response = self.http.post(f"{self.url}/", json={"creator": creator}, timeout=30)
        if response.status_code != 201:
            raise RuntimeError(f"{self.label}: create {response.status_code}")
        record = response.json()
        self.id = record["id"]
        self.auth = (record["creator"], record["passphrase"])

    @property
    def actor_url(self) -> str:
        return f"{self.url}/{self.id}"

    def call(self, method: str, path: str, **kwargs: Any) -> Any:
        return self.http.request(
            method, f"{self.actor_url}{path}", auth=self.auth, timeout=60, **kwargs
        )

    def ctl(self, op: str, **fields: Any) -> Any:
        body = {"op": op, "actor": self.id, **fields}
        answer = self.http.post(f"{self.url}{CTL_PATH}", json=body, timeout=120).json()
        if "error" in answer:
            raise RuntimeError(f"{self.label} {op}: {answer['error']}")
        return answer["result"]


def _status(response: Any) -> str:
    return f"{response.request.method} -> {response.status_code}"


def run_direction(subscriber: Side, publisher: Side) -> list[dict[str, Any]]:
    """The nine flows with ``subscriber`` initiating toward ``publisher``.

    The subscriber's side sends the trust request, the subscription request,
    the pull and the deletions; the publisher's side sends the trust
    verification, the permission callback, the push and resync callbacks.
    """
    results: list[dict[str, Any]] = []
    direction = f"{subscriber.label} -> {publisher.label}"

    def flow(name: str, steps: Any) -> bool:
        entry: dict[str, Any] = {"flow": name, "direction": direction}
        try:
            entry["observed"] = steps()
            entry["outcome"] = "completes"
        except AssertionError as exc:
            entry["outcome"] = "BREAK"
            entry["observed"] = str(exc)
        except Exception as exc:  # noqa: BLE001 - the outcome is the result
            entry["outcome"] = "ERROR"
            entry["observed"] = f"{type(exc).__name__}: {exc}"
        results.append(entry)
        return entry["outcome"] == "completes"

    def replica() -> dict[str, Any]:
        return subscriber.ctl("replica", peer=publisher.id)

    def wait_for(condition: Any, what: str, timeout: float = 15.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(0.25)
        raise AssertionError(f"{what}: not within {timeout:.0f}s")

    subscriber.create("s")
    publisher.create("p")

    def trust() -> Any:
        seen = []
        r = subscriber.call(
            "POST",
            "/trust",
            json={"url": publisher.actor_url, "relationship": "friend"},
        )
        seen.append(f"request {_status(r)}")
        assert r.status_code == 201, f"trust request: {r.status_code} {r.text[:300]}"
        r = publisher.call(
            "PUT", f"/trust/friend/{subscriber.id}", json={"approved": True}
        )
        seen.append(f"publisher approves {_status(r)}")
        assert r.status_code in (200, 204), f"approve: {r.status_code} {r.text[:300]}"
        r = subscriber.call(
            "PUT", f"/trust/friend/{publisher.id}", json={"approved": True}
        )
        seen.append(f"subscriber approves {_status(r)}")
        assert r.status_code in (200, 204), f"approve: {r.status_code} {r.text[:300]}"
        for side, peer in ((subscriber, publisher), (publisher, subscriber)):
            rows = side.ctl("state", peer=peer.id)["trust"]
            assert len(rows) == 1, f"{side.label}: {len(rows)} trust rows"
            row = rows[0]
            assert row["approved"] and row["peer_approved"] and row["verified"], (
                f"{side.label}'s row: {row}"
            )
        seen.append("both rows approved, peer_approved, verified")
        return seen

    def permissions() -> Any:
        r = publisher.call(
            "PUT",
            f"/trust/friend/{subscriber.id}/permissions",
            json={"properties": ["*"]},
        )
        assert r.status_code in (200, 201, 204), (
            f"grant: {r.status_code} {r.text[:300]}"
        )

        def stored() -> bool:
            found = subscriber.ctl("state", peer=publisher.id)["peer_permissions"]
            return bool(found) and "read_error" not in found

        wait_for(stored, "the subscriber's copy of the grant")
        return [
            f"grant {_status(r)}",
            "the subscriber stored the publisher's grant",
        ]

    def subscribe() -> Any:
        r = subscriber.call(
            "POST",
            "/subscriptions",
            json={
                "peerid": publisher.id,
                "target": "properties",
                "subtarget": "",
                "granularity": "high",
            },
        )
        assert r.status_code in (201, 204), f"subscribe: {r.status_code} {r.text[:300]}"
        for side, peer in ((subscriber, publisher), (publisher, subscriber)):
            rows = side.ctl("state", peer=peer.id)["subscriptions"]
            assert len(rows) == 1, f"{side.label}: {len(rows)} subscription rows"
        return [f"subscribe {_status(r)}", "one row on each side"]

    def push() -> Any:
        r = publisher.call("PUT", "/properties/note", json={"text": "pushed"})
        assert r.status_code in (200, 204), f"write: {r.status_code} {r.text[:300]}"
        wait_for(
            lambda: (replica()["scalars"].get("note") or {}).get("text") == "pushed",
            "the pushed value in the subscriber's replica",
        )
        return [f"write {_status(r)}", "the replica holds the pushed value"]

    def pull() -> Any:
        result = subscriber.ctl("sync", peer=publisher.id)
        assert result.get("success", True) is not False, f"sync_peer: {result}"
        summary = {
            k: result.get(k)
            for k in (
                "success",
                "subscriptions_synced",
                "total_diffs_processed",
                "error",
            )
            if k in result
        }
        return [f"sync_peer {summary}"]

    def suspension() -> Any:
        assert publisher.ctl("suspend", target="properties") is not False
        r = publisher.call("PUT", "/properties/quiet", json={"text": "while suspended"})
        assert r.status_code in (200, 204), f"write: {r.status_code}"
        time.sleep(2.0)
        assert "quiet" not in replica()["scalars"], (
            "a write during suspension reached the replica"
        )
        return ["suspended", "a write during suspension did not reach the replica"]

    def resync() -> Any:
        publisher.ctl("resume", target="properties")
        wait_for(
            lambda: (
                (replica()["scalars"].get("quiet") or {}).get("text")
                == "while suspended"
            ),
            "the value written during suspension, after the resync",
        )
        return ["resumed", "the replica holds the value written during suspension"]

    def list_diffs() -> Any:
        ops: list[tuple[str, list[Any]]] = [
            ("append", [{"id": "a", "text": "one"}]),
            ("append", [{"id": "b", "text": "two"}]),
            ("insert", [0, {"id": "c", "text": "three"}]),
            ("setitem", [1, {"id": "a", "text": "one, again"}]),
            ("delitem", [0]),
            ("extend", [[{"id": "d"}, {"id": "e"}]]),
            ("pop", []),
        ]
        expected = [
            {"id": "a", "text": "one, again"},
            {"id": "b", "text": "two"},
            {"id": "d"},
        ]
        for action, args in ops:
            publisher.ctl("list", name="notes", action=action, args=args)
        wait_for(
            lambda: replica()["lists"].get("notes") == expected,
            "the list in the subscriber's replica",
        )
        return [f"{len(ops)} list operations", "the replica's list matches"]

    def deletion() -> Any:
        seen = []
        subid = subscriber.ctl("state", peer=publisher.id)["subscriptions"][0][
            "subscriptionid"
        ]
        r = subscriber.call("DELETE", f"/subscriptions/{publisher.id}/{subid}")
        seen.append(f"subscription {_status(r)}")
        assert r.status_code in (200, 204), f"unsubscribe: {r.status_code}"
        wait_for(
            lambda: not publisher.ctl("state", peer=subscriber.id)["subscriptions"],
            "the publisher's subscription row gone",
        )
        r = subscriber.call("DELETE", f"/trust/friend/{publisher.id}")
        seen.append(f"trust {_status(r)}")
        assert r.status_code in (200, 204), f"trust delete: {r.status_code}"
        wait_for(
            lambda: not publisher.ctl("state", peer=subscriber.id)["trust"],
            "the publisher's trust row gone",
        )
        seen.append("the publisher's rows are gone")
        return seen

    flows = [
        ("trust creation and approval", trust),
        ("permission exchange", permissions),
        ("subscription creation", subscribe),
        ("push callbacks", push),
        ("pull", pull),
        ("suspension", suspension),
        ("resync", resync),
        ("list diffs", list_diffs),
        ("deletion", deletion),
    ]
    blocked = False
    for name, steps in flows:
        if blocked:
            results.append(
                {
                    "flow": name,
                    "direction": direction,
                    "outcome": "NOT RUN",
                    "observed": "needs the trust or the subscription that failed",
                }
            )
            continue
        ok = flow(name, steps)
        if not ok and name in ("trust creation and approval", "subscription creation"):
            blocked = True

    for side in (subscriber, publisher):
        try:
            side.http.delete(side.actor_url, auth=side.auth, timeout=60)
        except Exception:  # noqa: BLE001 - teardown only
            pass
    return results


def run_probes(old_url: str, new_url: str) -> list[dict[str, Any]]:
    """Probes beyond the nine flows: what each side's replica holds after a
    text value, a delete, a nested write, a low-granularity and a ``none``
    subscription, and what a second trust request does. Each records what
    it observed; reading the two directions side by side is the result."""
    out: list[dict[str, Any]] = []

    def connect(sub_url: str, pub_url: str) -> tuple[Side, Side]:
        sub, pub = Side(sub_url), Side(pub_url)
        sub.create("s")
        pub.create("p")
        r = sub.call(
            "POST", "/trust", json={"url": pub.actor_url, "relationship": "friend"}
        )
        assert r.status_code == 201, f"trust {r.status_code}"
        pub.call("PUT", f"/trust/friend/{sub.id}", json={"approved": True})
        sub.call("PUT", f"/trust/friend/{pub.id}", json={"approved": True})
        pub.call(
            "PUT", f"/trust/friend/{sub.id}/permissions", json={"properties": ["*"]}
        )
        time.sleep(1.0)
        return sub, pub

    def subscribe(sub: Side, pub: Side, subtarget: str, granularity: str) -> str:
        r = sub.call(
            "POST",
            "/subscriptions",
            json={
                "peerid": pub.id,
                "target": "properties",
                "subtarget": subtarget,
                "granularity": granularity,
            },
        )
        return _status(r)

    def settle(sub: Side, pub: Side) -> Any:
        time.sleep(2.5)
        return sub.ctl("replica", peer=pub.id)

    def cleanup(*sides: Side) -> None:
        for side in sides:
            try:
                side.http.delete(side.actor_url, auth=side.auth, timeout=60)
            except Exception:  # noqa: BLE001 - teardown only
                pass

    def probe(name: str, sub_url: str, pub_url: str, steps: Any) -> None:
        entry: dict[str, Any] = {"probe": name}
        sides: tuple[Side, ...] = ()
        try:
            sub, pub = connect(sub_url, pub_url)
            sides = (sub, pub)
            entry["direction"] = f"{sub.label} subscribes to {pub.label}"
            entry["observed"] = steps(sub, pub)
        except Exception as exc:  # noqa: BLE001 - the outcome is the result
            entry["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            cleanup(*sides)
        out.append(entry)

    def whole_target(sub: Side, pub: Side) -> Any:
        seen: dict[str, Any] = {"subscribe": subscribe(sub, pub, "", "high")}
        r = pub.call(
            "PUT",
            "/properties/title",
            data="plain text",
            headers={"Content-Type": "text/plain"},
        )
        seen["text write"] = _status(r)
        pub.call("PUT", "/properties/doc", json={"a": {"b": 1}, "c": 2})
        seen["after text and object writes"] = settle(sub, pub)["scalars"]
        r = pub.call("PUT", "/properties/doc/a", json={"b": 2})
        seen["nested write"] = _status(r)
        seen["after nested write"] = settle(sub, pub)["scalars"].get("doc")
        r = pub.call("DELETE", "/properties/title")
        seen["delete"] = _status(r)
        seen["after delete"] = sorted(settle(sub, pub)["scalars"])
        seen["sync_peer"] = {
            k: v
            for k, v in (sub.ctl("sync", peer=pub.id) or {}).items()
            if k
            in ("success", "subscriptions_synced", "total_diffs_processed", "error")
        }
        seen["after sync_peer"] = sub.ctl("replica", peer=pub.id)["scalars"]
        return seen

    def one_property(granularity: str) -> Any:
        def steps(sub: Side, pub: Side) -> Any:
            seen: dict[str, Any] = {
                "subscribe": subscribe(sub, pub, "title", granularity)
            }
            pub.call(
                "PUT",
                "/properties/title",
                data="plain text",
                headers={"Content-Type": "text/plain"},
            )
            seen["after text write"] = settle(sub, pub)["scalars"]
            if granularity == "none":
                seen["sync_peer"] = (sub.ctl("sync", peer=pub.id) or {}).get("success")
                seen["after sync_peer"] = sub.ctl("replica", peer=pub.id)["scalars"]
                pub.ctl("suspend", target="properties", subtarget="title")
                pub.call("PUT", "/properties/title", json={"text": "while suspended"})
                pub.ctl("resume", target="properties", subtarget="title")
                seen["sync_peer after resume"] = (
                    sub.ctl("sync", peer=pub.id) or {}
                ).get("success")
                seen["after resume and sync"] = sub.ctl("replica", peer=pub.id)[
                    "scalars"
                ]
            r = pub.call("DELETE", "/properties/title")
            seen["delete"] = _status(r)
            seen["after delete"] = settle(sub, pub)["scalars"]
            if granularity == "none":
                sub.ctl("sync", peer=pub.id)
                seen["after delete and sync"] = sub.ctl("replica", peer=pub.id)[
                    "scalars"
                ]
            return seen

        return steps

    def second_request(sub: Side, pub: Side) -> Any:
        seen: dict[str, Any] = {}
        r = sub.call(
            "POST", "/trust", json={"url": pub.actor_url, "relationship": "friend"}
        )
        seen["second request"] = _status(r)
        time.sleep(1.0)
        kept = ("approved", "peer_approved", "verified")
        for side, peer in ((sub, pub), (pub, sub)):
            rows = side.ctl("state", peer=peer.id)["trust"]
            seen[f"{side.label}'s rows after"] = [
                {k: row[k] for k in kept} for row in rows
            ]
        return seen

    for sub_url, pub_url in ((old_url, new_url), (new_url, old_url)):
        probe(
            "whole target: text, nested write, delete", sub_url, pub_url, whole_target
        )
        probe("one property, high", sub_url, pub_url, one_property("high"))
        probe("one property, low", sub_url, pub_url, one_property("low"))
        probe("one property, none", sub_url, pub_url, one_property("none"))
        probe("a second trust request", sub_url, pub_url, second_request)
    return out


def drive(args: argparse.Namespace) -> int:
    results: list[dict[str, Any]] = []
    results += run_direction(Side(args.old), Side(args.new))
    results += run_direction(Side(args.new), Side(args.old))
    report = {
        "sides": [Side(args.old).info, Side(args.new).info],
        "cells": results,
        "probes": run_probes(args.old, args.new) if args.probes else [],
    }
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=1)
        handle.write("\n")
    for cell in results:
        print(f"{cell['outcome']:9} {cell['direction']:22} {cell['flow']}")
    return 0 if all(c["outcome"] == "completes" for c in results) else 1


# ---------------------------------------------------------------------------
# same-store
# ---------------------------------------------------------------------------


def same_store(args: argparse.Namespace) -> int:
    """Run ``args.cmd`` (this tree) against the old side's store while the
    old side serves a request loop; then check what the loop wrote."""
    import subprocess

    import requests

    command = [c for c in args.cmd if c != "--"]
    if not command:
        raise SystemExit("same-store needs a command after --")
    old = Side(args.old)
    name = args.property
    created: list[dict[str, Any]] = []
    failures: list[str] = []
    stop = threading.Event()

    def loop() -> None:
        while not stop.is_set():
            try:
                side = Side(args.old)
                side.create("same")
                read = side.call("GET", "/properties")
                if read.status_code not in (200, 404):
                    failures.append(f"read {side.id}: {read.status_code}")
                value = f"{uuid.uuid4().hex[:12]}@example.test"
                write = side.call(
                    "PUT",
                    f"/properties/{name}",
                    data=value,
                    headers={"Content-Type": "text/plain"},
                )
                if write.status_code not in (200, 201, 204):
                    failures.append(f"write {side.id}: {write.status_code}")
                created.append({"id": side.id, "auth": side.auth})
            except Exception as exc:  # noqa: BLE001 - the outcome is the result
                failures.append(f"{type(exc).__name__}: {exc}")
            time.sleep(args.pause)

    worker = threading.Thread(target=loop, daemon=True)
    worker.start()
    time.sleep(args.warmup)
    started = time.time()
    run = subprocess.run(command, capture_output=True, text=True, check=False)
    took = time.time() - started
    time.sleep(args.warmup)
    stop.set()
    worker.join(timeout=60)

    # Read back: the old side over HTTP, this tree in-process (same prefix).
    from actingweb.config import Config
    from actingweb.interface.actor_interface import ActorInterface

    config = Config(
        database=os.getenv("DATABASE_BACKEND", "dynamodb"),
        fqdn="127.0.0.1",
        proto="http://",
    )
    unreadable_old: list[str] = []
    unreadable_new: list[str] = []
    lookups_missed: list[str] = []
    for entry in created:
        answer = requests.get(
            f"{old.url}/{entry['id']}/properties/{name}",
            auth=tuple(entry["auth"]),
            timeout=30,
        )
        if answer.status_code != 200:
            unreadable_old.append(f"{entry['id']}: {answer.status_code}")
        actor = ActorInterface.get_by_id(entry["id"], config)
        if actor is None:
            unreadable_new.append(entry["id"])
            continue
        stored = actor.properties.get(name)
        found = ActorInterface.get_by_property(name, str(stored), config)
        if stored is None or found is None or found.id != entry["id"]:
            lookups_missed.append(entry["id"])
    report = {
        "old": old.info,
        "command": command,
        "command_exit": run.returncode,
        "command_seconds": round(took, 1),
        "command_stdout_tail": run.stdout.splitlines()[-15:],
        "command_stderr_tail": run.stderr.splitlines()[-15:],
        "loop_actors": len(created),
        "loop_failures": failures,
        "unreadable_by_old": unreadable_old,
        "unreadable_by_new": unreadable_new,
        "lookups_missed": lookups_missed,
    }
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=1)
        handle.write("\n")
    ok = not (failures or unreadable_old or unreadable_new or lookups_missed)
    print(
        f"{'completes' if ok else 'FAILS':9} {' '.join(command)}: exit "
        f"{run.returncode}, {len(created)} actors by the old side, "
        f"{len(failures)} loop failures, {len(unreadable_old)} unreadable by "
        f"the old side, {len(unreadable_new)} by this tree, "
        f"{len(lookups_missed)} lookups missed"
    )
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    serve_parser = commands.add_parser("serve", help="start one side")
    serve_parser.add_argument("--label", required=True)
    serve_parser.add_argument("--port", type=int, required=True)
    serve_parser.add_argument("--capture", required=True)
    serve_parser.set_defaults(run=serve)
    drive_parser = commands.add_parser("drive", help="run the flows")
    drive_parser.add_argument("--old", required=True, help="URL of the old side")
    drive_parser.add_argument("--new", required=True, help="URL of the new side")
    drive_parser.add_argument("--out", required=True)
    drive_parser.add_argument(
        "--probes", action="store_true", help="also run the probes"
    )
    drive_parser.set_defaults(run=drive)
    same_parser = commands.add_parser(
        "same-store", help="run a command of this tree on the old side's store"
    )
    same_parser.add_argument("--old", required=True, help="URL of the old side")
    same_parser.add_argument("--out", required=True)
    same_parser.add_argument(
        "--property", default="email", help="indexed property the loop writes"
    )
    same_parser.add_argument(
        "--warmup", type=float, default=3.0, help="loop seconds before and after"
    )
    same_parser.add_argument(
        "--pause", type=float, default=0.2, help="seconds between loop rounds"
    )
    same_parser.add_argument("cmd", nargs=argparse.REMAINDER)
    same_parser.set_defaults(run=same_store)
    args = parser.parse_args()
    return int(args.run(args))


if __name__ == "__main__":
    sys.exit(main())
