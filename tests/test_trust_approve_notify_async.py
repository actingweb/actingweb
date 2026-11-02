"""``Actor.modify_trust_and_notify_async`` notifies the peer like the sync path.

Until 3.16 it built ``AwProxy(peer_target={"baseuri", "secret"})``; the proxy
reads ``peer_target["id"]``, so the ``KeyError`` was folded into "Not able to
notify peer async" and the peer was never told. It now delegates to the sync
method.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest import mock

import pytest

from actingweb import actor as actor_module
from actingweb.db.exceptions import DbError

TRUST = {
    "baseuri": "https://peer.example/p1",
    "secret": "s3cret",
    "approved": False,
}


def _actor() -> actor_module.Actor:
    me = actor_module.Actor.__new__(actor_module.Actor)
    me.id = "me1"
    me.config = mock.Mock()
    me.last_response_code = 0
    me.last_response_message = ""
    return me


def _run(me: actor_module.Actor, **kwargs: Any) -> Any:
    return asyncio.run(me.modify_trust_and_notify_async(**kwargs))


@pytest.fixture
def wired() -> Any:
    with (
        mock.patch.object(
            actor_module.Actor, "get_trust_relationships", return_value=[dict(TRUST)]
        ) as rels,
        mock.patch.object(actor_module.trust, "Trust") as trust_cls,
        mock.patch.object(actor_module.requests, "post") as post,
    ):
        trust_cls.return_value.modify.return_value = True
        post.return_value = mock.Mock(status_code=204, content=b"")
        yield rels, trust_cls, post


def test_approving_posts_the_approval_to_the_peer(wired: Any) -> None:
    _, _, post = wired
    me = _actor()
    assert _run(me, relationship="friend", peerid="p1", approved=True) is True
    post.assert_called_once()
    kwargs = post.call_args.kwargs
    assert kwargs["url"] == "https://peer.example/p1/trust/friend/me1"
    assert kwargs["data"] == '{"approved": true}'
    assert kwargs["headers"]["Authorization"] == "Bearer s3cret"
    assert me.last_response_code == 204


def test_an_unchanged_approval_sends_nothing(wired: Any) -> None:
    rels, _, post = wired
    rels.return_value = [dict(TRUST, approved=True)]
    assert _run(_actor(), relationship="friend", peerid="p1", approved=True) is True
    post.assert_not_called()


@pytest.mark.parametrize(
    "kwargs", [{"peerid": "p1"}, {"relationship": "friend"}], ids=["no-rel", "no-peer"]
)
def test_missing_arguments_answer_false(wired: Any, kwargs: dict[str, str]) -> None:
    _, _, post = wired
    assert _run(_actor(), approved=True, **kwargs) is False
    post.assert_not_called()


def test_no_matching_trust_answers_false(wired: Any) -> None:
    rels, _, post = wired
    rels.return_value = []
    assert _run(_actor(), relationship="friend", peerid="p1", approved=True) is False
    post.assert_not_called()


def test_a_store_fault_on_the_trust_write_propagates(wired: Any) -> None:
    _, trust_cls, post = wired
    trust_cls.return_value.modify.side_effect = DbError("trust modify", "me1")
    with pytest.raises(DbError):
        _run(_actor(), relationship="friend", peerid="p1", approved=True)
    post.assert_not_called()


def test_it_answers_what_the_sync_method_answers(wired: Any) -> None:
    _, trust_cls, _ = wired
    trust_cls.return_value.modify.return_value = False
    me = _actor()
    sync = me.modify_trust_and_notify(relationship="friend", peerid="p1", desc="d")
    assert _run(me, relationship="friend", peerid="p1", desc="d") is sync is False
