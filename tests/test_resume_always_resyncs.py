"""A resume always sends a resync callback (3.16).

The publisher used to read the subscriber's cached option tags and, for a
peer cached without ``subscriptionresync``, send the full subscribed state
as ordinary diffs instead. That path is gone: it stored scalars as text,
kept deleted properties, and raised for a subscription to one property.
Every library since 3.10 advertises the tag; a subscriber that does not
know the type re-reads on its own schedule.
"""

from __future__ import annotations

import json
from typing import Any
from unittest import mock

import pytest


@pytest.fixture
def actor() -> Any:
    from actingweb.actor import Actor

    a = object.__new__(Actor)
    a.config = mock.Mock()
    a.id = "a1"
    a.property_lists = mock.Mock()
    a.property_lists.exists.side_effect = lambda name: name == "notes"
    return a


SUB = {"peerid": "p1", "subscriptionid": "s1", "target": "properties"}


def _resume(
    actor: Any,
    subscription: dict[str, Any],
    *,
    trust_data: dict[str, Any] | None = None,
    status: int = 204,
    wait: bool = True,
) -> tuple[bool, list[dict[str, Any]], list[Any], mock.Mock]:
    """``(result, callbacks sent, diffs stored, the PeerCapabilities class)``."""
    payloads: list[dict[str, Any]] = []
    stored: list[Any] = []
    trust = mock.Mock()
    trust.get.return_value = trust_data or {
        "baseuri": "https://peer.example/p1",
        "secret": "s",
    }
    # Cached, fresh, and without the tag: what took the removed path.
    caps = mock.Mock()
    caps.supports_resync_callbacks_cached.return_value = False
    actor.config.sync_subscription_callbacks = wait
    actor.config.root = "https://me.example/"
    with (
        mock.patch("actingweb.trust.Trust", return_value=trust),
        mock.patch(
            "actingweb.peer_capabilities.PeerCapabilities", return_value=caps
        ) as caps_class,
        mock.patch("actingweb.interface.actor_interface.ActorInterface"),
        mock.patch.object(actor, "_increment_subscription_sequence", return_value=7),
        mock.patch.object(
            actor,
            "_store_subscription_diff",
            side_effect=lambda p, s, seq, d: stored.append(d) or "url",
        ),
        mock.patch(
            "actingweb.actor._resync_url",
            side_effect=lambda c, a, t, st: f"{t}/{st}" if st else t,
        ),
        mock.patch(
            "actingweb.callback_sender.send_sync",
            side_effect=lambda send, deadline=None: (
                payloads.append(json.loads(send.body)) or status
            ),
        ),
    ):
        result = actor._callback_subscription_resync(subscription)  # noqa: SLF001
    return result, payloads, stored, caps_class


def test_a_peer_cached_without_resync_is_sent_a_resync(actor: Any) -> None:
    result, payloads, stored, _ = _resume(actor, {**SUB, "subtarget": None})
    assert result is True
    assert [p.get("type") for p in payloads] == ["resync"]
    assert payloads[0]["sequence"] == 7 and payloads[0]["url"] == "properties"
    assert stored == []  # no full state stored as a diff


def test_a_single_property_subscription_resumes(actor: Any) -> None:
    """The removed path raised here (a property is not a list of names),
    and the resume was lost."""
    actor.property_lists.exists.side_effect = lambda name: False
    result, payloads, stored, _ = _resume(actor, {**SUB, "subtarget": "status"})
    assert result is True
    assert [(p.get("type"), p["subtarget"], p["url"]) for p in payloads] == [
        ("resync", "status", "properties/status")
    ]
    assert stored == []


def test_the_resume_reads_no_capabilities(actor: Any) -> None:
    _, _, _, caps_class = _resume(actor, {**SUB, "subtarget": None})
    caps_class.assert_not_called()


@pytest.mark.parametrize(
    "subscription,trust_data",
    [
        # A peer without an endpoint (an OAuth2 client's row).
        ({**SUB, "subtarget": None}, {"baseuri": "", "secret": "s"}),
        # A subscription that is never called.
        ({**SUB, "subtarget": None, "granularity": "none"}, None),
    ],
    ids=["no endpoint", "granularity none"],
)
def test_a_subscription_that_is_not_called_still_gets_a_marker(
    actor: Any,
    subscription: dict[str, Any],
    trust_data: dict[str, Any] | None,
) -> None:
    result, payloads, stored, _ = _resume(actor, subscription, trust_data=trust_data)
    assert result is True
    assert payloads == []
    assert len(stored) == 1 and stored[0].get("type") == "resync"


def test_a_resync_that_was_not_delivered_is_reported_when_the_write_waited(
    actor: Any,
) -> None:
    """False: the caller records it and sends it again on the next resume."""
    result, payloads, _, _ = _resume(actor, {**SUB, "subtarget": None}, status=503)
    assert len(payloads) >= 1
    assert result is False


def test_a_resync_scheduled_on_a_running_loop_is_reported_as_sent(
    actor: Any,
) -> None:
    """A known limit, pinned: with nobody waiting for the send, its failure
    is recorded nowhere (the docs say which deployments wait)."""
    with mock.patch("actingweb.callback_sender.deliver", return_value=False):
        result, _, _, _ = _resume(actor, {**SUB, "subtarget": None}, wait=False)
    assert result is True
