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
