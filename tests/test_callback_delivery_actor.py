"""The actor's side of the sender (spec-1-5 Phase 4): a resync that was not
delivered off the event loop is recorded as missed and sent again on the
next resume, with or without ``with_sync_callbacks``; callback sends leave
``last_response_code`` alone."""

from __future__ import annotations

import json
from typing import Any
from unittest import mock

import pytest

from actingweb import callback_sender
from tests._adoption_helpers import aid, create_core_actor, make_config, uuid_email


@pytest.fixture
def config() -> Any:
    return make_config()


def _subscribed(config: Any, n: int) -> Any:
    from actingweb.db import get_subscription

    actor = create_core_actor(config, uuid_email())
    for i in range(n):
        assert get_subscription(config).create(
            actor_id=aid(actor),
            peerid=f"p{i}",
            subid=f"s{i}",
            target="properties",
            callback=False,
        )
    return actor


def _trust(*_a: Any, peerid: str = "", **_k: Any) -> Any:
    trust = mock.Mock()
    trust.get.return_value = {
        "baseuri": f"https://{peerid}.example.com/{peerid}",
        "secret": "s",
        "peerid": peerid,
    }
    return trust


@pytest.mark.parametrize("failure", [503, 0])
def test_an_undelivered_resync_is_sent_again_on_the_next_resume(
    config: Any, failure: int
) -> None:
    actor = _subscribed(config, 3)
    assert not getattr(config, "sync_subscription_callbacks", False)
    assert actor.suspend_subscriptions("properties")
    sent: list[str] = []

    def send(prepared: callback_sender.PreparedSend, deadline: Any = None) -> int:
        peer = json.loads(prepared.body)["subscriptionid"]
        sent.append(peer)
        return failure if peer == "s1" else 204

    with (
        mock.patch("actingweb.trust.Trust", side_effect=_trust),
        mock.patch.object(callback_sender, "send_sync", send),
    ):
        assert actor.resume_subscriptions("properties") == 2
        assert sorted(sent) == ["s0", "s1", "s2"]
        sent.clear()
    with (
        mock.patch("actingweb.trust.Trust", side_effect=_trust),
        mock.patch.object(
            callback_sender,
            "send_sync",
            lambda p, d=None: sent.append(json.loads(p.body)["subscriptionid"]) or 204,
        ),
    ):
        assert actor.resume_subscriptions("properties") == 1
    assert sent == ["s1"]


def test_callback_sends_leave_last_response_code_alone(config: Any) -> None:
    actor = _subscribed(config, 1)
    actor.last_response_code = 123
    with (
        mock.patch("actingweb.trust.Trust", side_effect=_trust),
        mock.patch.object(callback_sender, "send_sync", return_value=500),
    ):
        actor.suspend_subscriptions("properties")
        actor.resume_subscriptions("properties")
    assert actor.last_response_code == 123


def _stored(config: Any, actor: Any) -> dict[str, Any]:
    from actingweb.db import get_property_list

    return dict(get_property_list(config).fetch(actor_id=aid(actor)) or {})


def test_a_clear_is_sent_after_its_deletes(config: Any) -> None:
    """Verification 2026-11-16 (H1): the clear's callbacks went out before
    its deletes, so a subscriber that rebuilt on that callback read every
    name back and kept it."""
    from actingweb.actor import Actor
    from actingweb.interface.actor_interface import ActorInterface

    actor = _subscribed(config, 2)
    props = ActorInterface(actor).properties
    props["x"] = "1"
    props["y"] = "2"
    held_at_send: list[dict[str, Any]] = []

    def prepare(self: Any, peerid: Any = None, **_k: Any) -> Any:
        return callback_sender.Unit(
            sends=[
                callback_sender.PreparedSend(
                    url=f"https://{peerid}.example.com/cb", body=b"{}", headers={}
                )
            ]
        )

    def send(prepared: callback_sender.PreparedSend, deadline: Any = None) -> int:
        held_at_send.append(_stored(config, actor))
        return 204

    with (
        mock.patch.object(Actor, "_prepare_callback", prepare),
        mock.patch.object(callback_sender, "send_sync", send),
    ):
        props.clear()
    assert len(held_at_send) == 2
    assert held_at_send == [{}, {}]


def test_a_value_written_during_a_clear_is_kept_and_sent(config: Any) -> None:
    """Verification 2026-11-16 (M3): a value written between the clear's
    snapshot and its deletes was deleted at the publisher while the
    subscribers kept it. It is kept, and a diff with it follows the clear's."""
    from actingweb.actor import Actor
    from actingweb.interface.actor_interface import ActorInterface
    from actingweb.property import PropertyStore as CoreStore

    actor = _subscribed(config, 1)
    props = ActorInterface(actor).properties
    props["x"] = "old"
    props["y"] = "gone"
    real = Actor.register_diffs
    calls: list[tuple[Any, Any]] = []

    def concurrent_put(self: Any, *a: Any, **k: Any) -> Any:
        calls.append((k.get("subtarget"), k.get("blob")))
        if len(calls) == 1:
            # Another request writes x after the clear's snapshot.
            CoreStore(actor_id=aid(actor), config=config)["x"] = "new"
        return real(self, *a, **k)

    with mock.patch.object(Actor, "register_diffs", concurrent_put):
        props.clear()
    assert _stored(config, actor) == {"x": "new"}
    assert calls[1:] == [("x", "new")]


def test_a_clear_whose_delete_faults_raises_and_a_retry_converges(config: Any) -> None:
    """Verification 2026-11-16 (M6): a delete that faults after the clear's
    diff raises (the handler answers 503); the subscribers were told, and
    a retry deletes the rest and tells them again."""
    from actingweb.db.exceptions import DbError
    from actingweb.interface.actor_interface import ActorInterface
    from actingweb.property import PropertyStore as CoreStore
    from actingweb.subscription import Subscription

    actor = _subscribed(config, 1)
    props = ActorInterface(actor).properties
    props["x"] = "1"
    props["y"] = "2"
    real_set = CoreStore.__setitem__
    faults = {"y": 1}

    def flaky(self: Any, k: str, v: Any) -> None:
        if v is None and faults.get(k):
            faults[k] -= 1
            raise DbError("simulated delete fault")
        real_set(self, k, v)

    with (
        mock.patch.object(CoreStore, "__setitem__", flaky),
        pytest.raises(DbError),
    ):
        props.clear()
    assert set(_stored(config, actor)) <= {"y"}
    ActorInterface(type(actor)(actor_id=aid(actor), config=config)).properties.clear()
    assert _stored(config, actor) == {}
    diffs = Subscription(
        actor_id=aid(actor), peerid="p0", subid="s0", callback=False, config=config
    ).get_diffs()
    blobs = [json.loads(d["diff"]) for d in sorted(diffs, key=lambda d: d["sequence"])]
    # Two writes, then the clear's one diff, then the retry's.
    assert blobs[-2] == {"x": "", "y": ""}
    assert blobs[-1] == {"y": ""}
