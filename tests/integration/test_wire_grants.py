"""Wire rows: what a peer's grant admits on each route, recorded before the fix.

``thoughts/plans/2026-11-10-grant-enforcement-per-route.md``, Phase 0, rows
``WG1`` to ``WG19``. A recording is what the library does, right or wrong;
``wire/rows.toml`` names the phase expected to change each row and marks the
rows that record data reaching a peer that may not read it.

A is the owner. F is a friend whose override adds exclusions (``memory_*``,
``settings/private``, ``*/deep/private``) to the friend type's own; S an
associate, P a partner, D an admin peer, U a peer A has not approved, L a
peer of ``wire_legacy`` (a relationship only access rows speak for), W a peer
of ``wire_allowed`` (a property rule in the ``allowed`` shape) and N one of
``wire_named`` (a rule naming ``color``). The OAuth2 rows run on the
``wire_oauth`` app against its stand-in provider.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import re
import uuid
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, quote, quote_plus, urlparse

import pytest
import requests

from . import _oauth_stub
from ._wire import (
    WIRE_TRUST_TYPES,
    Scenario,
    WireActor,
    WireHost,
    check,
    trust_hooks_recorded,
)

pytestmark = [pytest.mark.wire, pytest.mark.xdist_group(name="wire_peer_paths")]

TOPOLOGIES = ["same_host", "two_hosts"]

# F's grant: the friend type's rule with three exclusions added.
F_GRANT: dict[str, Any] = {
    "patterns": ["*"],
    "operations": ["read", "write"],
    "excluded_patterns": [
        "private/*",
        "security/*",
        "_internal/*",
        "memory_*",
        "settings/private",
        "*/deep/private",
    ],
}
SETTINGS = {"theme": "x", "private": "s", "deep": {"private": "d"}}
CLIENT_REDIRECT = "https://client.example.test/cb"
CLIENT_STATE = "client-state-1"
PKCE_VERIFIER = "wire-pkce-verifier-" + "v" * 40


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bearer(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


def _rename_subscriber(s: Scenario, name: str) -> None:
    """The pair's B is this row's ``name`` (F): its labels say so."""
    b = s.subscribers[0]
    b.name = name
    s.names[b.id] = name
    s.names[b.creator] = f"{name}.creator"
    s.secrets[b.passphrase] = f"{name}.passphrase"
    s.secrets[s.trust_secret] = f"trust:A-{name}"


def _owner_put(a: WireActor, name: str, value: Any) -> None:
    response = requests.put(f"{a.url}/properties/{name}", json=value, auth=a.basic)
    assert response.status_code in (200, 201, 204), response.text


def _seed(a: WireActor) -> None:
    """What A holds before a row's first step."""
    _owner_put(a, "private", {"k": 1})
    _owner_put(a, "settings", SETTINGS)
    _owner_put(a, "color", "blue")
    lists = a.interface().property_lists
    lists.notes.append({"text": "n1"})
    lists.memory_personal.append({"text": "m1"})


def _a_holds(a: WireActor) -> Callable[[], Any]:
    """The extra snapshot of the REST rows: what A holds after the step."""

    def holds() -> dict[str, Any]:
        ai = a.interface()
        lists = ai.property_lists
        return {
            "properties": {
                k: v
                for k, v in sorted(ai.properties.to_dict().items())
                if k in ("private", "settings", "color", "mood", "wire_hooked")
            },
            "lists": {
                name: getattr(lists, name).to_list()
                for name in ("notes", "memory_personal", "memory_new")
                if lists.exists(name)
            },
        }

    return holds


def _world(wire_pair, topology: str = "same_host", **kwargs: Any) -> Scenario:
    """A and F (B renamed), F's grant in place; A seeded unless subscribed."""
    s = wire_pair(topology, grant=F_GRANT, **kwargs)
    _rename_subscriber(s, "F")
    return s


def _get(url: str, secret: str, **kwargs: Any) -> Callable[[], requests.Response]:
    return lambda: requests.get(url, headers=_bearer(secret), **kwargs)


def _put(url: str, secret: str, body: Any) -> Callable[[], requests.Response]:
    return lambda: requests.put(url, json=body, headers=_bearer(secret))


def _post(url: str, secret: str, body: Any) -> Callable[[], requests.Response]:
    return lambda: requests.post(url, json=body, headers=_bearer(secret))


def _delete(url: str, secret: str) -> Callable[[], requests.Response]:
    return lambda: requests.delete(url, headers=_bearer(secret))


def _subscribe(
    s: Scenario, peer: WireActor, secret: str, body: dict[str, Any]
) -> requests.Response:
    """A peer's own POST of a subscription at A (no callback row at the peer)."""
    a = s.publisher
    return requests.post(
        f"{a.url}/subscriptions/{peer.id}",
        json={"target": "properties", "granularity": "high", **body},
        headers=_bearer(secret),
    )


def _sorted_lists(value: Any, keys: set[str]) -> Any:
    """``value`` with the lists under ``keys`` sorted: an order the library
    does not fix, which a recording must not compare."""
    if isinstance(value, dict):
        return {
            k: sorted(v, key=str)
            if k in keys and isinstance(v, list)
            else _sorted_lists(v, keys)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_sorted_lists(v, keys) for v in value]
    return value


def _subid_of(response: requests.Response) -> str:
    assert response.status_code == 201, response.text
    return response.json()["subscriptionid"]


# ---------------------------------------------------------------------------
# Phase 1's rows: the property tree, the listing, the bulk POST, the filter
# ---------------------------------------------------------------------------


def test_wg1_parent_of_an_excluded_tree(wire_pair):
    """WG1: F reads and overwrites ``private`` (``private/*`` excluded) and
    lists A's properties."""
    s = _world(wire_pair, subscribe=False)
    a, f = s.publisher, s.subscribers[0]
    _seed(a)
    s.extra_snapshot = _a_holds(a)
    secret = s.trust_secret
    s.step("GET private", _get(f"{a.url}/properties/private", secret))
    s.step("PUT private", _put(f"{a.url}/properties/private", secret, {"k": 2}))
    s.step("GET the listing", _get(f"{a.url}/properties", secret))
    s.step(
        "GET the listing with metadata",
        _get(f"{a.url}/properties", secret, params={"metadata": "true"}),
    )
    assert f.id
    check("WG1", s.recording())


def test_wg2_excluded_child(wire_pair):
    """WG2: F reads ``settings`` (its child ``private`` and grandchild
    ``deep/private`` excluded), the child itself, and overwrites the parent."""
    s = _world(wire_pair, subscribe=False)
    a = s.publisher
    _seed(a)
    s.extra_snapshot = _a_holds(a)
    secret = s.trust_secret
    s.step("GET settings", _get(f"{a.url}/properties/settings", secret))
    s.step("GET settings/private", _get(f"{a.url}/properties/settings/private", secret))
    s.step(
        "PUT settings",
        _put(
            f"{a.url}/properties/settings",
            secret,
            {"theme": "y", "private": "s2", "deep": {"private": "d2"}},
        ),
    )
    check("WG2", s.recording())


def test_wg3_excluded_list_tail(wire_pair):
    """WG3: F on the excluded list ``memory_personal``: the list, a tail, an
    item write by ``?index=``."""
    s = _world(wire_pair, subscribe=False)
    a = s.publisher
    _seed(a)
    s.extra_snapshot = _a_holds(a)
    secret = s.trust_secret
    base = f"{a.url}/properties/memory_personal"
    s.step("GET the list", _get(base, secret))
    s.step("GET a tail", _get(f"{base}/x", secret))
    s.step(
        "PUT a tail with ?index=0",
        lambda: requests.put(
            f"{base}/x",
            params={"index": "0"},
            json={"text": "written by F"},
            headers=_bearer(secret),
        ),
    )
    # E: a friend whose grant names the list exactly (no glob).
    e, e_secret = wire_pair.add_peer(s, "E", "friend", to="A")
    response = requests.put(
        f"{a.url}/trust/friend/{e.id}/permissions",
        json={
            "properties": {
                **F_GRANT,
                "excluded_patterns": ["private/*", "memory_personal"],
            }
        },
        auth=a.basic,
    )
    assert response.status_code in (200, 201, 204), response.text
    s.step("E GET the list", _get(base, e_secret))
    s.step("E GET a tail", _get(f"{base}/x", e_secret))
    s.step(
        "E PUT a tail with ?index=0",
        lambda: requests.put(
            f"{base}/x",
            params={"index": "0"},
            json={"text": "written by E"},
            headers=_bearer(e_secret),
        ),
    )
    check("WG3", s.recording())


def test_wg4_bulk_post(wire_pair):
    """WG4: F's ``POST /properties`` with a denied key beside an allowed one,
    bulk items for an excluded list, an excluded list created, an excluded
    object posted bare."""
    s = _world(wire_pair, subscribe=False)
    a = s.publisher
    _seed(a)
    s.extra_snapshot = _a_holds(a)
    secret = s.trust_secret
    url = f"{a.url}/properties"
    s.step(
        "an allowed scalar and private/x",
        _post(url, secret, {"mood": "ok", "private/x": 1}),
    )
    s.step(
        "bulk items for memory_personal",
        _post(
            url, secret, {"memory_personal": {"items": [{"index": 0, "text": "m1b"}]}}
        ),
    )
    s.step(
        "create the list memory_new",
        _post(url, secret, {"memory_new": {"_type": "list"}}),
    )
    s.step("a bare private object", _post(url, secret, {"private": {"k": 3}}))
    check("WG4", s.recording())


def test_wg5_allowed_shape_miss(wire_pair):
    """WG5: W, whose base rule is ``{"allowed": ["notes"]}`` while the access
    table admits every property GET: ``color``, the listing, a pull."""
    s = _world(wire_pair, subscribe=False)
    a = s.publisher
    _seed(a)
    w, secret = wire_pair.add_peer(s, "W", "wire_allowed", to="A")
    s.extra_snapshot = _a_holds(a)
    s.step("GET color", _get(f"{a.url}/properties/color", secret))
    s.step("GET the listing", _get(f"{a.url}/properties", secret))
    subid = _subid_of(_subscribe(s, w, secret, {"subtarget": ""}))
    s.name(subid, "W's subscription")
    s.step("A writes color", lambda: _owner_put(a, "color", "green"))
    s.step(
        "W pulls its subscription",
        _get(f"{a.url}/subscriptions/{w.id}/{subid}", secret),
    )
    check("WG5", s.recording())


def test_wg6_flows_that_must_not_change(wire_pair):
    """WG6: what every phase must leave as it is."""
    s = _world(wire_pair, subscribe=False)
    a = s.publisher
    _seed(a)
    _, d_secret = wire_pair.add_peer(s, "D", "admin", to="A")
    _, l_secret = wire_pair.add_peer(s, "L", "wire_legacy", to="A")
    _, p_secret = wire_pair.add_peer(s, "P", "partner", to="A")
    s.extra_snapshot = _a_holds(a)
    f_secret = s.trust_secret
    props = f"{a.url}/properties"
    s.step("F GET color", _get(f"{props}/color", f_secret))
    s.step("F PUT color", _put(f"{props}/color", f_secret, "red"))
    s.step("F GET notes", _get(f"{props}/notes", f_secret))
    s.step(
        "F adds a notes item",
        _post(f"{props}/notes/items", f_secret, {"action": "add", "item_value": "n2"}),
    )
    s.step("F PUT settings/theme", _put(f"{props}/settings/theme", f_secret, "z"))
    s.step("D PUT private", _put(f"{props}/private", d_secret, {"k": 9}))
    s.step("D PUT settings", _put(f"{props}/settings", d_secret, SETTINGS))
    s.step("L GET color", _get(f"{props}/color", l_secret))
    for name, secret in (("F", f_secret), ("P", p_secret)):
        s.step(
            f"{name} POST /methods/wire_ping",
            _post(f"{a.url}/methods/wire_ping", secret, {}),
        )
        s.step(f"{name} GET /methods", _get(f"{a.url}/methods", secret))
        s.step(
            f"{name} POST /actions/wire_act",
            _post(f"{a.url}/actions/wire_act", secret, {}),
        )
        s.step(f"{name} GET /actions", _get(f"{a.url}/actions", secret))
    check("WG6", s.recording())


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wg7_whole_target_push_and_pull(wire_pair, topology):
    """WG7: F subscribes to all of A's properties; A writes excluded values
    and an allowed one; the push and F's pull."""
    s = _world(wire_pair, topology)
    a = s.publisher
    secret = s.trust_secret
    s.extra_snapshot = _a_holds(a)
    s.step("A writes private", lambda: _owner_put(a, "private", {"k": 1}))
    s.step("A writes settings", lambda: _owner_put(a, "settings", SETTINGS))
    s.step("A writes settings/private", lambda: _owner_put(a, "settings/private", "s2"))
    s.step(
        "A writes settings/deep/private",
        lambda: _owner_put(a, "settings/deep/private", "d2"),
    )
    s.step("A writes color", lambda: _owner_put(a, "color", "green"))
    rows = a.interface().subscriptions.get_subscriptions_from_peer(s.subscribers[0].id)
    assert len(rows) == 1, rows
    subid = rows[0].subscription_id
    s.step(
        "F pulls its subscription",
        _get(f"{a.url}/subscriptions/{s.subscribers[0].id}/{subid}", secret),
    )
    check("WG7", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wg8_subtarget_push_and_pull(wire_pair, topology):
    """WG8: F's subscriptions to the excluded list (resource ``item``), to
    ``settings``, and to ``settings`` with resource ``private``."""
    s = _world(wire_pair, topology, subscribe=False)
    a, f = s.publisher, s.subscribers[0]
    secret = s.trust_secret
    _owner_put(a, "settings", SETTINGS)
    a.interface().property_lists.memory_personal.append({"text": "m1"})
    subids = []
    for label, body in (
        ("memory_personal/item", {"subtarget": "memory_personal", "resource": "item"}),
        ("settings", {"subtarget": "settings"}),
        ("settings/private", {"subtarget": "settings", "resource": "private"}),
    ):
        subid = _subid_of(_subscribe(s, f, secret, body))
        s.name(subid, f"F's {label}")
        subids.append(subid)
    s.step(
        "A appends to memory_personal",
        lambda: a.interface().property_lists.memory_personal.append({"text": "m2"}),
    )
    s.step(
        "A writes settings",
        lambda: _owner_put(
            a, "settings", {"theme": "y", "private": "s2", "deep": {"private": "d2"}}
        ),
    )
    for subid in subids:
        s.step(
            "F pulls one subscription",
            _get(f"{a.url}/subscriptions/{f.id}/{subid}", secret),
        )
    check("WG8", s.recording(), variant=topology)


# ---------------------------------------------------------------------------
# Phase 2's rows: resources, methods, subscription creation, shared_properties
# ---------------------------------------------------------------------------


def test_wg9_category_not_mentioned(wire_pair):
    """WG9: L (no trust type) pulls a properties subscription; S, F and L read
    a property a hook serves (``wire_hooked``)."""
    s = _world(wire_pair, subscribe=False)
    a = s.publisher
    _owner_put(a, "wire_hooked", "hooked value")
    l_peer, l_secret = wire_pair.add_peer(s, "L", "wire_legacy", to="A")
    _, s_secret = wire_pair.add_peer(s, "S", "associate", to="A")
    subid = _subid_of(_subscribe(s, l_peer, l_secret, {"subtarget": ""}))
    s.name(subid, "L's subscription")
    s.step("A writes color", lambda: _owner_put(a, "color", "green"))
    s.step(
        "L pulls its subscription",
        _get(f"{a.url}/subscriptions/{l_peer.id}/{subid}", l_secret),
    )
    for name, secret in (("S", s_secret), ("F", s.trust_secret), ("L", l_secret)):
        s.step(
            f"{name} GET wire_hooked", _get(f"{a.url}/properties/wire_hooked", secret)
        )
    check("WG9", s.recording())


def test_wg10_resources(wire_pair):
    """WG10: F, S, P and D on ``/resources`` (each name a callback hook
    answers)."""
    s = _world(wire_pair, subscribe=False)
    a = s.publisher
    _, s_secret = wire_pair.add_peer(s, "S", "associate", to="A")
    _, p_secret = wire_pair.add_peer(s, "P", "partner", to="A")
    _, d_secret = wire_pair.add_peer(s, "D", "admin", to="A")
    for name, secret in (
        ("F", s.trust_secret),
        ("S", s_secret),
        ("P", p_secret),
        ("D", d_secret),
    ):
        for resource in ("x", "private/x", "public/x", "private"):
            url = f"{a.url}/resources/{resource}"
            s.step(f"{name} GET {resource}", _get(url, secret))
            s.step(f"{name} PUT {resource}", _put(url, secret, {"v": 1}))
            s.step(f"{name} DELETE {resource}", _delete(url, secret))
    check("WG10", s.recording())


def test_wg11_empty_methods_rule(wire_pair):
    """WG11: the consumer's subscriber shape, ``"methods": []`` beside an
    access row admitting ``POST /methods``."""
    s = _world(wire_pair, subscribe=False)
    a = s.publisher
    _, secret = wire_pair.add_peer(s, "R", "subscriber", to="A")
    s.step(
        "R POST /methods/wire_import",
        _post(f"{a.url}/methods/wire_import", secret, {"list": "wire_r", "items": []}),
    )
    s.step("R GET /methods", _get(f"{a.url}/methods", secret))
    check("WG11", s.recording())


def test_wg12_subscription_creation(wire_pair):
    """WG12: F subscribes to the excluded list, to ``color`` and to the whole
    target; N (``patterns: ["color"]``) to the whole target."""
    s = _world(wire_pair, subscribe=False)
    f = s.subscribers[0]
    n, n_secret = wire_pair.add_peer(s, "N", "wire_named", to="A")

    def subscribe(peer: WireActor, secret: str, subtarget: str, label: str):
        def action() -> requests.Response:
            response = _subscribe(s, peer, secret, {"subtarget": subtarget})
            if response.status_code == 201:
                s.name(response.json()["subscriptionid"], label)
            return response

        return action

    s.step(
        "F to memory_personal",
        subscribe(f, s.trust_secret, "memory_personal", "F's memory_personal"),
    )
    s.step("F to color", subscribe(f, s.trust_secret, "color", "F's color"))
    s.step("F to all properties", subscribe(f, s.trust_secret, "", "F's whole"))
    s.step("N to all properties", subscribe(n, n_secret, "", "N's whole"))
    check("WG12", s.recording())


def test_wg13_shared_properties_and_unapproved_listing(wire_pair):
    """WG13: F's ``shared_properties``; U's (A has not approved U); U lists
    its subscriptions at A."""
    s = _world(wire_pair, subscribe=False)
    a, f = s.publisher, s.subscribers[0]
    _seed(a)
    u, u_secret = wire_pair.add_peer(s, "U", "friend", to="A", approve=False)
    s.step(
        "F GET shared_properties",
        _get(f"{a.url}/trust/friend/{f.id}/shared_properties", s.trust_secret),
    )
    s.step(
        "U GET shared_properties",
        _get(f"{a.url}/trust/friend/{u.id}/shared_properties", u_secret),
    )
    s.step("U GET its subscriptions", _get(f"{a.url}/subscriptions/{u.id}", u_secret))
    check(
        "WG13",
        _sorted_lists(s.recording(), {"shared_properties", "excluded_properties"}),
    )


# ---------------------------------------------------------------------------
# Phase 3's rows: an OAuth2/MCP client's trust type (the wire_oauth app)
# ---------------------------------------------------------------------------


def _oauth_world(wire_oauth: WireHost) -> tuple[Scenario, str]:
    """A row on ``wire_oauth``: the email the provider signs in, and a bystander
    actor X the snapshot needs. The user's actor is the one the callback finds
    or makes for the email (a factory-made actor of that creator would be
    replaced), so the snapshot looks it up by its creator and names it U."""
    email = f"wire-user-{uuid.uuid4().hex[:8]}@example.test"
    response = requests.post(
        f"{wire_oauth.url}/", json={"creator": f"x-{uuid.uuid4().hex[:8]}@example.test"}
    )
    assert response.status_code == 201, response.text
    bystander = WireActor("X", wire_oauth, response.json())
    _oauth_stub.STUB["email"] = email
    # The client's trust row names the user by a normalised email.
    normalised = email.replace("@", "_at_").replace(".", "_dot_")
    names = {
        bystander.id: "X",
        bystander.creator: "X.creator",
        email: "U.creator",
        normalised: "U.creator",
    }
    secrets = {bystander.passphrase: "X.passphrase"}
    s = Scenario(bystander, [], names, secrets)

    def rows() -> dict[str, Any]:
        from actingweb.actor import Actor

        user = Actor(config=wire_oauth.config)
        user_id = user.id if user.get_from_creator(email) else None
        if user_id:
            s.name(user_id, "U")
        return {
            "user_trusts": _client_trusts(wire_oauth, user_id, s) if user_id else None,
            "system_trusts": _client_trusts(
                wire_oauth, "_actingweb_oauth2", s, only_named=True
            ),
        }

    s.extra_snapshot = rows
    return s, email


def _client_trusts(
    host: WireHost, actor_id: str, s: Scenario, *, only_named: bool = False
) -> list[dict[str, Any]]:
    """An actor's trust rows (kept fields only), in the order of their peers'
    names; ``only_named``: only rows to a client the row named (the system
    actor holds every test's clients)."""
    from actingweb.actor import Actor

    core = Actor(config=host.config)
    core.get(actor_id=actor_id)
    if not core.id:
        return []

    def label(peer: str) -> str:
        for value, name in sorted(s.names.items(), key=lambda kv: -len(kv[0])):
            peer = peer.replace(value, f"<{name}>")
        return peer

    out = []
    for row in core.get_trust_relationships() or []:
        peer = str(row.get("peerid", ""))
        if only_named and label(peer) == peer:
            continue  # another row's client on the shared system actor
        out.append(
            {
                "peerid": peer,
                "relationship": row.get("relationship"),
                "approved": row.get("approved"),
                "peer_approved": row.get("peer_approved"),
                "established_via": row.get("established_via"),
            }
        )
    return sorted(out, key=lambda r: (label(r["peerid"]), str(r["relationship"])))


def _name_secret(s: Scenario, value: str, label: str) -> None:
    """Name an OAuth2 value as it appears raw, inside a query string and
    inside a form body; for a state wrapped in JSON, its nonce too."""
    s.name(value, label, secret=True)
    for encoded in (quote(value, safe=""), quote_plus(value)):
        if encoded != value:
            s.name(encoded, label, secret=True)
    try:
        wrapped = json.loads(value)
    except ValueError:
        return
    if isinstance(wrapped, dict) and isinstance(wrapped.get("csrf"), str):
        s.name(wrapped["csrf"], f"{label}.csrf", secret=True)


def _register(
    s: Scenario, host: WireHost, body: dict[str, Any], label: str = "client"
) -> requests.Response:
    response = requests.post(f"{host.url}/oauth/register", json=body)
    if response.status_code == 201:
        data = response.json()
        s.name(data["client_id"], label)
        if data.get("client_secret"):
            _name_secret(s, data["client_secret"], f"{label}_secret")
    return response


def _challenge() -> str:
    digest = hashlib.sha256(PKCE_VERIFIER.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _token(s: Scenario, host: WireHost, form: dict[str, str]) -> requests.Response:
    response = requests.post(f"{host.url}/oauth/token", data=form)
    if response.status_code == 200:
        data = response.json()
        _name_secret(s, data["access_token"], "access_token")
        if data.get("refresh_token"):
            _name_secret(s, data["refresh_token"], "refresh_token")
    return response


def _tools_list(s: Scenario, host: WireHost) -> Callable[[], requests.Response]:
    def action() -> requests.Response:
        token = next(k for k, v in s.secrets.items() if v == "access_token")
        headers = {**_bearer(token), "Content-Type": "application/json"}
        init = requests.post(
            f"{host.url}/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "Wire Client", "version": "1.0.0"},
                },
                "id": 1,
            },
            headers=headers,
        )
        session = init.headers.get("mcp-session-id")
        if session:
            headers["Mcp-Session-Id"] = session
            s.name(session, "mcp_session", secret=True)
        return requests.post(
            f"{host.url}/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 2},
            headers=headers,
        )

    return action


def _state_of(url: str) -> str:
    return parse_qs(urlparse(url).query)["state"][0]


_PROVIDER_LINK = re.compile(
    r'href="(https://wire-provider\.example\.test/authorize[^"]*)"'
)


def _provider_links(text: str) -> dict[str, str]:
    """The provider buttons on a page, by provider."""
    links = {}
    for href in _PROVIDER_LINK.findall(text):
        url = html.unescape(href)
        links["apple" if _oauth_stub.APPLE_CLIENT_ID in url else "google"] = url
    return links


def _page(response: requests.Response) -> dict[str, Any]:
    """What a row compares of an HTML page: its title, the inputs and options
    of its forms, and which providers it links (not the markup)."""
    text = response.text
    title = re.search(r"<title>(.*?)</title>", text, re.S)
    return {
        "status": response.status_code,
        "content_type": response.headers.get("content-type"),
        "title": title.group(1).strip() if title else None,
        "inputs": sorted(set(re.findall(r'<input[^>]*name="([^"]+)"', text))),
        # Every type in the registry, which other tests in the worker extend:
        # the wire apps' own.
        "options": [
            t
            for t in re.findall(r'<option value="([^"]+)"', text)
            if t in WIRE_TRUST_TYPES or t.startswith("wire_")
        ],
        "provider_links": sorted(_provider_links(text)),
    }


def _without_form_length(recording: dict[str, Any]) -> dict[str, Any]:
    """The authorize form's length goes with the registry's types (see
    ``_page``): its wire entries keep only that it was a page."""

    def walk(entries: list[dict[str, Any]]) -> None:
        for entry in entries:
            if entry.get("path") == "/oauth/authorize" and isinstance(
                entry.get("response"), str
            ):
                entry["response"] = re.sub(
                    r"<html \d+ chars>", "<html>", entry["response"]
                )
            walk(entry.get("children", []))

    for step in recording["steps"]:
        walk(step["wire"])
    return recording


def _result(response: requests.Response) -> Any:
    """A step's result: a page summarised, anything else as the driver has it."""
    if "html" in response.headers.get("content-type", ""):
        return _page(response)
    return response


def _callback(
    s: Scenario, host: WireHost, state: str, *, apple: bool = False
) -> requests.Response:
    """The provider sends the browser back: GET, or Apple's form POST."""
    if apple:
        response = requests.post(
            f"{host.url}/oauth/callback/apple",
            data={"code": _oauth_stub.PROVIDER_CODE, "state": state},
            allow_redirects=False,
        )
    else:
        response = requests.get(
            f"{host.url}/oauth/callback",
            params={"code": _oauth_stub.PROVIDER_CODE, "state": state},
            allow_redirects=False,
        )
    location = response.headers.get("location", "")
    if location.startswith(CLIENT_REDIRECT):
        _name_secret(s, parse_qs(urlparse(location).query)["code"][0], "code")
    return response


def _callback_step(
    s: Scenario, host: WireHost, state: str, *, apple: bool = False
) -> Callable[[], Any]:
    return lambda: _result(_callback(s, host, state, apple=apple))


def _authorize_params(client_id: str) -> dict[str, str]:
    return {
        "client_id": client_id,
        "redirect_uri": CLIENT_REDIRECT,
        "response_type": "code",
        "state": CLIENT_STATE,
        "code_challenge": _challenge(),
        "code_challenge_method": "S256",
    }


def _client_body(**extra: Any) -> dict[str, Any]:
    return {
        "client_name": "Wire Client",
        "redirect_uris": [CLIENT_REDIRECT],
        **extra,
    }


def test_wg14_anonymous_registration(wire_oauth):
    """WG14: an anonymous registration asking for ``admin`` and for
    ``client_credentials``; the token; ``tools/list``."""
    s, _ = _oauth_world(wire_oauth)
    s.step(
        "register",
        lambda: _register(
            s,
            wire_oauth,
            _client_body(grant_types=["client_credentials"], trust_type="admin"),
        ),
    )
    client_id = next(k for k, v in s.names.items() if v == "client")
    secret = next(k for k, v in s.secrets.items() if v == "client_secret")
    s.step(
        "client_credentials token",
        lambda: _token(
            s,
            wire_oauth,
            {
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": secret,
            },
        ),
    )
    s.step("tools/list", _tools_list(s, wire_oauth))
    check("WG14", s.recording())


def test_wg15_client_posts_the_form_itself(wire_oauth):
    """WG15: a client posts the authorize form itself with ``admin``; the
    provider callback follows; no form was ever shown to the user."""
    s, _ = _oauth_world(wire_oauth)
    _register(s, wire_oauth, _client_body())
    client_id = next(k for k, v in s.names.items() if v == "client")

    def post_form() -> requests.Response:
        response = requests.post(
            f"{wire_oauth.url}/oauth/authorize",
            data={
                **_authorize_params(client_id),
                "provider": "google",
                "trust_type": "admin",
            },
            allow_redirects=False,
        )
        location = response.headers.get("location", "")
        if "state=" in location:
            _name_secret(s, _state_of(location), "provider_state")
        return response

    response = s.step("client POSTs the form", post_form)
    state = _state_of(response.headers["location"])
    s.step("provider callback", _callback_step(s, wire_oauth, state))
    check("WG15", s.recording())


def test_wg16_honest_flows(wire_oauth):
    """WG16: the form as the user sees it (asked for as JSON, then as HTML);
    for one client a POST with ``mcp_client`` and the GET callback, the token
    and ``tools/list``, then a POST choosing Apple and Apple's form-POST
    callback; for a second client the two provider buttons followed as they
    are (Google's GET callback, Apple's form-POST callback)."""
    s, _ = _oauth_world(wire_oauth)
    _register(s, wire_oauth, _client_body())
    _register(s, wire_oauth, _client_body(client_name="Wire Client 2"), "client2")
    client_id = next(k for k, v in s.names.items() if v == "client")
    client2_id = next(k for k, v in s.names.items() if v == "client2")
    client_secret = next(k for k, v in s.secrets.items() if v == "client_secret")
    links: dict[str, str] = {}

    def get_form(cid: str, accept: str) -> Callable[[], Any]:
        def action() -> Any:
            response = requests.get(
                f"{wire_oauth.url}/oauth/authorize",
                params=_authorize_params(cid),
                headers={"Accept": accept},
            )
            for name, url in _provider_links(response.text).items():
                links[name] = url
                _name_secret(s, _state_of(url), f"{name}_link_state")
            return _result(response)

        return action

    def post_form(provider: str, label: str) -> Callable[[], requests.Response]:
        def action() -> requests.Response:
            response = requests.post(
                f"{wire_oauth.url}/oauth/authorize",
                data={
                    **_authorize_params(client_id),
                    "provider": provider,
                    "trust_type": "mcp_client",
                },
                allow_redirects=False,
            )
            location = response.headers.get("location", "")
            if "state=" in location:
                _name_secret(s, _state_of(location), label)
            return response

        return action

    s.step("GET the form as JSON", get_form(client_id, "application/json"))
    s.step("GET the form as HTML", get_form(client_id, "text/html"))
    assert set(links) == {"apple", "google"}, links

    response = s.step("POST the form, Google", post_form("google", "google_state"))
    state = _state_of(response.headers["location"])
    s.step("GET callback", _callback_step(s, wire_oauth, state))
    code = next(k for k, v in s.secrets.items() if v == "code")
    s.step(
        "token for the code",
        lambda: _token(
            s,
            wire_oauth,
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": CLIENT_REDIRECT,
                "client_id": client_id,
                "client_secret": client_secret,
                "code_verifier": PKCE_VERIFIER,
            },
        ),
    )
    s.step("tools/list", _tools_list(s, wire_oauth))

    response = s.step("POST the form, Apple", post_form("apple", "apple_state"))
    state = _state_of(response.headers["location"])
    s.step(
        "Apple's form-POST callback", _callback_step(s, wire_oauth, state, apple=True)
    )

    # The second client's form, its buttons followed with no type chosen.
    links.clear()
    s.step("client2: GET the form as HTML", get_form(client2_id, "text/html"))
    assert set(links) == {"apple", "google"}, links
    s.step(
        "client2: the Google button's link, GET callback",
        _callback_step(s, wire_oauth, _state_of(links["google"])),
    )
    # The Apple button's link: its state is a nonce wrapped in JSON by the
    # authorization URL (the plan's Phase 0 notes).
    s.step(
        "client2: the Apple button's link, form-POST callback",
        _callback_step(s, wire_oauth, _state_of(links["apple"]), apple=True),
    )
    check("WG16", _without_form_length(s.recording()))


def test_wg17_owner_created_client(wire_oauth):
    """WG17: a client the actor's owner created uses ``client_credentials``."""
    from actingweb.interface.oauth_client_manager import OAuth2ClientManager

    s, _ = _oauth_world(wire_oauth)
    owner = s.publisher
    s.name(owner.id, "U")
    s.names[owner.creator] = "U.creator"
    s.secrets[owner.passphrase] = "U.passphrase"
    created = OAuth2ClientManager(owner.id, wire_oauth.config).create_client(
        "Wire Owner Client"
    )
    s.name(created["client_id"], "client")
    _name_secret(s, created["client_secret"], "client_secret")
    s.extra_snapshot = lambda: {
        "owner_trusts": _client_trusts(wire_oauth, owner.id, s),
        "system_trusts": _client_trusts(
            wire_oauth, "_actingweb_oauth2", s, only_named=True
        ),
    }
    s.step(
        "client_credentials token",
        lambda: _token(
            s,
            wire_oauth,
            {
                "grant_type": "client_credentials",
                "client_id": created["client_id"],
                "client_secret": created["client_secret"],
            },
        ),
    )
    s.step("tools/list", _tools_list(s, wire_oauth))
    check("WG17", s.recording())


# ---------------------------------------------------------------------------
# Phase 4's rows: the grant-delete callback and the trust hooks
# ---------------------------------------------------------------------------


def test_wg18_grant_delete(wire_pair):
    """WG18: A deletes F's permission override, then again."""
    s = _world(wire_pair, subscribe=False)
    a, f = s.publisher, s.subscribers[0]
    url = f"{a.url}/trust/friend/{f.id}/permissions"
    s.step("A deletes F's override", lambda: requests.delete(url, auth=a.basic))
    s.step("A deletes it again", lambda: requests.delete(url, auth=a.basic))
    check("WG18", s.recording())


def test_wg19_trust_hooks(wire_pair):
    """WG19: which trust hook each approving and deleting route fires, and
    with which arguments."""
    s = _world(wire_pair, subscribe=False)
    a = s.publisher
    g, _ = wire_pair.add_peer(s, "G", "friend", to="A", approve=False)
    h, _ = wire_pair.add_peer(s, "H", "friend", to="A", approve=False)
    with trust_hooks_recorded():
        url = f"{a.url}/trust/friend/{g.id}"
        s.step(
            "A approves G by REST",
            lambda: requests.put(url, json={"approved": True}, auth=a.basic),
        )
        s.step(
            "A approves G by REST again",
            lambda: requests.put(url, json={"approved": True}, auth=a.basic),
        )
        s.step(
            "A approves H through TrustManager",
            lambda: a.interface().trust.approve_relationship(h.id),
        )
        s.step("A deletes G by REST", lambda: requests.delete(url, auth=a.basic))
        s.step(
            "A deletes H through TrustManager",
            lambda: a.interface().trust.delete_relationship(h.id),
        )
    check("WG19", s.recording())
