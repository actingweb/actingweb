"""``SubscriptionManager.notify_subscribers(resource=...)`` sends a subscriber
above the resource the subtarget's whole stored value (3.16).

A receiver applies a target- or subtarget-level value whole, so the partial
``{resource: value}`` this call used to send made its replica lose the
subtarget's other keys. The property handlers already pass the stored value;
now the SDK call reads it too, only when such a subscriber exists.
"""

from __future__ import annotations

import json
from typing import Any
from unittest import mock

from actingweb.actor import Actor
from actingweb.interface.actor_interface import ActorInterface
from actingweb.interface.subscription_manager import SubscriptionManager
from actingweb.subscription import Subscription
from actingweb.trust_permissions import TrustPermissions, get_trust_permission_store
from tests._adoption_helpers import aid
from tests.test_trust_re_pair import Receiver

STORED = {"theme": "x", "private": "s", "deep": {"a": 1}}


def _world(*subs: tuple[str, str, str, str]) -> Receiver:
    """A with friends B (granted everything but ``settings/private``) and C
    (everything), ``settings`` stored, and the given subscriptions as
    ``(peer, id, subtarget, resource)``; ``"b"`` and ``"c"`` name the peers."""
    w = Receiver()
    store = get_trust_permission_store(w.config)
    for peer, excluded in ((w.b, ["settings/private"]), (w.c, [])):
        assert store.store_permissions(
            TrustPermissions(
                actor_id=aid(w.a),
                peer_id=peer,
                trust_type="friend",
                properties={
                    "patterns": ["*"],
                    "operations": ["read"],
                    "excluded_patterns": excluded,
                },
            ),
            notify_peer=False,
        )
    assert w.a.property is not None
    w.a.property["settings"] = json.dumps(STORED)
    for peer, sub_id, subtarget, resource in subs:
        assert Subscription(
            actor_id=aid(w.a),
            peerid={"b": w.b, "c": w.c}[peer],
            subid=sub_id,
            config=w.config,
        ).create(
            target="properties" if sub_id != "other" else "notes",
            subtarget=subtarget or None,
            resource=resource or None,
            granularity="high",
        )
    return w


def _notify(w: Receiver, target: str, subtarget: str, resource: str) -> dict[str, Any]:
    """Notify from a freshly loaded A; the data each subscription was sent."""
    sent: dict[str, Any] = {}
    w.config.sync_subscription_callbacks = True

    def send(prepared: Any, deadline: Any = None) -> int:
        body = json.loads(prepared.body)
        sent[body["subscriptionid"]] = body["data"]
        return 204

    actor = Actor(aid(w.a), config=w.config)
    with mock.patch("actingweb.callback_sender.send_sync", side_effect=send):
        ActorInterface(actor).subscriptions.notify_subscribers(
            target, {"a": 1}, subtarget=subtarget, resource=resource
        )
    return sent


def test_a_resource_notification_sends_the_whole_stored_value() -> None:
    w = _world(
        ("b", "target", "", ""),
        ("c", "subtarget", "settings", ""),
        ("c", "resource", "settings", "deep"),
    )
    sent = _notify(w, "properties", "settings", "deep")
    # Target level: the subtarget's whole value, less what B's grant excludes.
    assert sent["target"] == {"settings": {"theme": "x", "deep": {"a": 1}}}
    # Subtarget level: the whole value.
    assert sent["subtarget"] == STORED
    # Resource level: the resource's value, as before.
    assert sent["resource"] == {"a": 1}


def test_the_store_is_not_read_without_a_subscriber_above_the_resource() -> None:
    w = _world(("c", "resource", "settings", "deep"))
    with mock.patch.object(
        SubscriptionManager, "_stored_property", autospec=True
    ) as read:
        sent = _notify(w, "properties", "settings", "deep")
    assert sent == {"resource": {"a": 1}}
    read.assert_not_called()


def test_a_subtarget_the_store_does_not_hold_sends_what_was_passed() -> None:
    """Also what a list's name answers: its items are not a stored property."""
    w = _world(("c", "target", "", ""), ("c", "subtarget", "ghost", ""))
    sent = _notify(w, "properties", "ghost", "deep")
    assert sent == {
        "target": {"ghost": {"deep": {"a": 1}}},
        "subtarget": {"deep": {"a": 1}},
    }


def test_another_target_passes_the_data_through() -> None:
    """The library has no store to read for an application's own target:
    the caller passes the whole value (documented)."""
    w = _world(("c", "other", "", ""))
    blobs: list[str] = []

    def add_diff(self: Any, blob: str = "") -> None:
        blobs.append(blob)

    with mock.patch.object(
        Subscription, "add_diff", autospec=True, side_effect=add_diff
    ):
        _notify(w, "notes", "settings", "deep")
    assert [json.loads(b) for b in blobs] == [{"settings": {"deep": {"a": 1}}}]
