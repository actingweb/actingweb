"""The approval notification goes to the base URI the same call wrote (3.16,
plan Phase 4): ``modify_trust_and_notify(approved=True, baseuri=new)`` told
the URL the row had before. A modify that does not notify reads nothing more.
Real storage; both backends through ``DATABASE_BACKEND``.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest import mock

from actingweb.actor import Actor
from tests._adoption_helpers import aid
from tests.test_trust_re_pair import Receiver

NEW = "https://moved.example.test/peer"


def _approve(w: Receiver, *, run_async: bool = False, **kw: Any) -> bool:
    with mock.patch.object(Actor, "reverify_pending_trust", return_value=True):
        if run_async:
            return asyncio.run(
                w.a.modify_trust_and_notify_async(
                    peerid=w.b, relationship="friend", **kw
                )
            )
        return w.a.modify_trust_and_notify(peerid=w.b, relationship="friend", **kw)


def _sent_to(post: mock.Mock) -> str:
    return str(post.call_args.kwargs["url"])


def test_the_approval_goes_to_the_new_base_uri() -> None:
    w = Receiver(approved=False)
    with mock.patch(
        "actingweb.actor.requests.post", return_value=mock.Mock(status_code=204)
    ) as post:
        assert _approve(w, approved=True, baseuri=NEW)
    assert _sent_to(post) == f"{NEW}/trust/friend/{aid(w.a)}"
    assert w.row(w.b)["baseuri"] == NEW


def test_the_async_twin_does_the_same() -> None:
    w = Receiver(approved=False)
    with mock.patch(
        "actingweb.actor.requests.post", return_value=mock.Mock(status_code=204)
    ) as post:
        assert _approve(w, run_async=True, approved=True, baseuri=NEW)
    assert _sent_to(post) == f"{NEW}/trust/friend/{aid(w.a)}"


def test_without_a_new_base_uri_the_stored_one_is_told() -> None:
    w = Receiver(approved=False)
    stored = w.row(w.b)["baseuri"]
    with mock.patch(
        "actingweb.actor.requests.post", return_value=mock.Mock(status_code=204)
    ) as post:
        assert _approve(w, approved=True)
    assert _sent_to(post) == f"{stored}/trust/friend/{aid(w.a)}"


def test_a_modify_that_does_not_notify_reads_nothing_more() -> None:
    w = Receiver()
    with (
        mock.patch("actingweb.actor.requests.post") as post,
        mock.patch.object(
            Actor, "get_trust_relationships", wraps=w.a.get_trust_relationships
        ) as reads,
    ):
        assert w.a.modify_trust_and_notify(
            peerid=w.b, relationship="friend", desc="new", baseuri=NEW
        )
    post.assert_not_called()
    assert reads.call_count == 1


def test_a_move_by_another_request_is_followed() -> None:
    """Verification 2026-11-10 (plan: else read again after the write):
    another request moved the base URI between this call's read and its
    write; the approval goes to where the row points now."""
    from actingweb.trust import Trust

    w = Receiver(approved=False)
    moved = "https://moved-meanwhile.example.test/peer"
    real_modify = Trust.modify

    def modify_then_moved(self: Trust, *a: Any, **kw: Any) -> Any:
        out = real_modify(self, *a, **kw)
        if kw.get("approved") is True:
            real_modify(
                Trust(actor_id=aid(w.a), peerid=w.b, config=w.config), baseuri=moved
            )
        return out

    with (
        mock.patch.object(Trust, "modify", modify_then_moved),
        mock.patch(
            "actingweb.actor.requests.post", return_value=mock.Mock(status_code=204)
        ) as post,
    ):
        assert _approve(w, approved=True)
    assert _sent_to(post) == f"{moved}/trust/friend/{aid(w.a)}"


def test_a_faulting_re_read_still_tells_the_peer() -> None:
    """Code review 2026-11-10: a DbError from the read after the committed
    approval answered 503 and the peer was never told (a retry finds the row
    approved and sends nothing). It is told at the URL read before."""
    from actingweb.db.exceptions import DbError
    from actingweb.trust import Trust

    w = Receiver(approved=False)
    stored = w.row(w.b)["baseuri"]
    real_get = Trust.get
    state = {"armed": False}
    real_modify = Trust.modify

    def modify_then_arm(self: Trust, *a: Any, **kw: Any) -> Any:
        out = real_modify(self, *a, **kw)
        if kw.get("approved") is True:
            state["armed"] = True
        return out

    def get_faulting_after(self: Trust, *a: Any, **kw: Any) -> Any:
        if state["armed"]:
            raise DbError("trust read", aid(w.a))
        return real_get(self, *a, **kw)

    with (
        mock.patch.object(Trust, "modify", modify_then_arm),
        mock.patch.object(Trust, "get", get_faulting_after),
        mock.patch(
            "actingweb.actor.requests.post", return_value=mock.Mock(status_code=204)
        ) as post,
    ):
        assert _approve(w, approved=True)
    assert _sent_to(post) == f"{stored}/trust/friend/{aid(w.a)}"


def test_a_replaced_row_s_base_uri_does_not_get_the_old_secret() -> None:
    """Outside voice 2026-11-10: a re-pair replacing the row between the write
    and the re-read must not send the old row's secret to the new base URI."""
    from actingweb.trust import Trust

    w = Receiver(approved=False)
    stored = w.row(w.b)["baseuri"]
    real_modify = Trust.modify

    def modify_then_repaired(self: Trust, *a: Any, **kw: Any) -> Any:
        out = real_modify(self, *a, **kw)
        if kw.get("approved") is True:
            real_modify(
                Trust(actor_id=aid(w.a), peerid=w.b, config=w.config),
                baseuri="https://elsewhere.example.test/x",
                secret="a-new-secret-0123456789",
            )
        return out

    with (
        mock.patch.object(Trust, "modify", modify_then_repaired),
        mock.patch(
            "actingweb.actor.requests.post", return_value=mock.Mock(status_code=204)
        ) as post,
    ):
        assert _approve(w, approved=True)
    assert _sent_to(post) == f"{stored}/trust/friend/{aid(w.a)}"


def test_a_secret_written_with_the_approval_is_this_call_s_own() -> None:
    """Verification re-run 1 (Issue H): the re-read row holds the secret this
    call wrote, which differed from the one read before, so the call's own
    write was taken for a re-pair and a move meanwhile was not followed."""
    from actingweb.trust import Trust

    w = Receiver(approved=False)
    moved = "https://moved-meanwhile.example.test/peer"
    real_modify = Trust.modify

    def modify_then_moved(self: Trust, *a: Any, **kw: Any) -> Any:
        out = real_modify(self, *a, **kw)
        if kw.get("approved") is True:
            real_modify(
                Trust(actor_id=aid(w.a), peerid=w.b, config=w.config), baseuri=moved
            )
        return out

    with (
        mock.patch.object(Trust, "modify", modify_then_moved),
        mock.patch(
            "actingweb.actor.requests.post", return_value=mock.Mock(status_code=204)
        ) as post,
    ):
        assert _approve(w, approved=True, secret="a-rotated-secret-0123456789")
    assert _sent_to(post) == f"{moved}/trust/friend/{aid(w.a)}"
    # Re-run 2 (Issue 11): and with the secret the row holds now.
    assert (
        post.call_args.kwargs["headers"]["Authorization"]
        == "Bearer a-rotated-secret-0123456789"
    )
