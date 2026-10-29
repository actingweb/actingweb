"""Sixth iteration on the fault contract: the follow-ons from
``thoughts/verifications/2026-10-29-db-fault-semantics-and-creator-uniqueness-5.md``.
"""

from __future__ import annotations

from typing import Any
from unittest import mock

import pytest

from actingweb.db.exceptions import DbError
from tests._adoption_helpers import make_config


def _raise(*_a: Any, **_k: Any) -> Any:
    raise DbError("simulated backend fault")


def _subscribed_actor(peers: tuple[str, ...] = ("p1",)) -> tuple[Any, Any]:
    from actingweb.db import get_subscription
    from tests._adoption_helpers import aid, create_core_actor, uuid_email

    config = make_config()
    actor = create_core_actor(config, uuid_email())
    for peer in peers:
        assert get_subscription(config).create(
            actor_id=aid(actor),
            peerid=peer,
            subid=f"s-{peer}",
            target="properties",
            granularity="high",
            callback=False,
        )
    return config, actor


class TestA5ResumeFault:
    def test_a_list_read_fault_keeps_the_suspension(self) -> None:
        """At entry 31 the marker was deleted, the read folded to [] and
        resume answered 0: the suspension window was lost."""
        from tests._adoption_helpers import seam_fault

        config, actor = _subscribed_actor()
        assert actor.suspend_subscriptions("properties")
        actor.subs_list = None
        with (
            seam_fault(config, "subscription", "Subscription", "query"),
            pytest.raises(DbError),
        ):
            actor.resume_subscriptions("properties")

        assert actor.is_subscription_suspended("properties", None)

    def test_a_resync_fault_restores_the_suspension_after_every_attempt(
        self,
    ) -> None:
        _config, actor = _subscribed_actor(("p1", "p2"))
        assert actor.suspend_subscriptions("properties")
        attempted: list[str] = []

        def resync(sub: dict[str, Any], _subtarget: Any = None) -> bool:
            attempted.append(sub["peerid"])
            if sub["peerid"] == "p1":
                raise DbError("simulated")
            return True

        with (
            mock.patch.object(actor, "_callback_subscription_resync", resync),
            pytest.raises(DbError),
        ):
            actor.resume_subscriptions("properties")

        assert sorted(attempted) == ["p1", "p2"]
        assert actor.is_subscription_suspended("properties", None)

    def test_a_clean_resume_lifts_the_suspension(self) -> None:
        _config, actor = _subscribed_actor()
        assert actor.suspend_subscriptions("properties")
        with mock.patch.object(
            actor, "_callback_subscription_resync", return_value=True
        ):
            assert actor.resume_subscriptions("properties") == 1
        assert not actor.is_subscription_suspended("properties", None)


class TestB5CreatorChangeFault:
    def test_a_fault_on_the_creator_write_restores_the_marker(self) -> None:
        """At entry 36 the DbError re-raised before the restore, leaving a
        vouched actor 'creator_changed' with its creator unchanged."""
        from actingweb.actor import Actor
        from tests._adoption_helpers import aid, uuid_email

        config = make_config()
        actor = Actor(config=config)
        creator = uuid_email()
        assert actor.create(
            url="https://test.example.com/",
            creator=creator,
            passphrase="pw",
            auth_method="google_oauth2",
        )
        loaded = Actor(actor_id=aid(actor), config=config)

        with (
            mock.patch.object(Actor, "modify", _raise),
            pytest.raises(DbError),
        ):
            loaded.modify_creator_unvouched(uuid_email())

        fresh = Actor(actor_id=aid(actor), config=config)
        assert fresh.creator == creator
        assert fresh.store is not None
        assert fresh.store.auth_method == "google_oauth2"


class TestC5FaultDropsQueuedRedirectAndCookies:
    def test_map_db_error_clears_redirect_and_cookies(self) -> None:
        from actingweb.aw_web_request import AWWebObj
        from actingweb.interface.integrations._errors import map_db_error

        webobj = AWWebObj()
        webobj.response.set_redirect("https://app.example.com/after-login")
        webobj.response.set_cookie("oauth_token", "live-session")

        assert map_db_error(webobj.response, DbError("simulated"))

        assert webobj.response.status_code == 503
        assert webobj.response.redirect is None
        assert webobj.response.cookies == []


class TestD5H5DiffStorage:
    def test_a_taken_number_is_refused_not_overwritten(self) -> None:
        """At entry 36 DynamoDB's unconditional save overwrote the first diff."""
        from actingweb.db import get_subscription_diff
        from tests._adoption_helpers import aid

        config, actor = _subscribed_actor()
        first = get_subscription_diff(config)
        assert first.create(
            actor_id=aid(actor), subid="s-p1", diff='{"first": 1}', seqnr=1
        )
        assert (
            get_subscription_diff(config).create(
                actor_id=aid(actor), subid="s-p1", diff='{"second": 2}', seqnr=1
            )
            is False
        )
        stored = get_subscription_diff(config).get(
            actor_id=aid(actor), subid="s-p1", seqnr=1
        )
        assert stored and stored["data"] == '{"first": 1}'

    def test_diffs_list_in_sequence_order(self) -> None:
        from actingweb.db import get_subscription_diff, get_subscription_diff_list
        from tests._adoption_helpers import aid

        config, actor = _subscribed_actor()
        for seqnr in (2, 10, 1):
            assert get_subscription_diff(config).create(
                actor_id=aid(actor), subid="s-p1", diff="{}", seqnr=seqnr
            )
        listed = get_subscription_diff_list(config).fetch(
            actor_id=aid(actor), subid="s-p1"
        )
        assert [d["sequence"] for d in listed or []] == [1, 2, 10]


class TestK5McpConflictLabel:
    def test_a_creator_taken_answers_409_conflict(self) -> None:
        from actingweb.db.exceptions import CreatorTaken
        from tests.mcp_helpers import make_mcp_handler

        handler = make_mcp_handler()
        handler._db_fault_response(1, CreatorTaken("creator taken"))
        assert handler.response.status_code == 409
        assert handler.response.status_message == "Conflict"


class TestA6C6ResumeEdges:
    def test_a_permanent_resync_fault_does_not_pin_the_suspension(self) -> None:
        """At entry 37 any DbError put the suspension back, so one subscriber
        over the item size limit kept the target suspended for good."""
        _config, actor = _subscribed_actor(("p1", "p2"))
        assert actor.suspend_subscriptions("properties")
        cause = Exception("Item size has exceeded the maximum allowed size")
        cause.cause_response_code = "ValidationException"  # type: ignore[attr-defined]

        def resync(sub: dict[str, Any], _subtarget: Any = None) -> bool:
            if sub["peerid"] == "p1":
                raise DbError("subscription diff create") from cause
            return True

        with mock.patch.object(actor, "_callback_subscription_resync", resync):
            assert actor.resume_subscriptions("properties") == 1
        assert not actor.is_subscription_suspended("properties", None)

    def test_a_resume_that_faults_puts_the_marker_back(self) -> None:
        from actingweb.db import get_subscription_suspension
        from tests._adoption_helpers import aid

        config, actor = _subscribed_actor()
        assert actor.suspend_subscriptions("properties")
        db = get_subscription_suspension(config, aid(actor))
        real_resume = type(db).resume

        def lands_then_raises(self: Any, target: str, subtarget: Any = None) -> bool:
            real_resume(self, target, subtarget)
            raise DbError("simulated lost answer")

        with (
            mock.patch.object(type(db), "resume", lands_then_raises),
            pytest.raises(DbError),
        ):
            actor.resume_subscriptions("properties")
        assert actor.is_subscription_suspended("properties", None)


class TestB6FallbackDiffRefused:
    def test_no_url_for_a_diff_that_was_not_stored(self) -> None:
        from actingweb.db import get_subscription_diff
        from tests._adoption_helpers import aid

        config, actor = _subscribed_actor()
        assert get_subscription_diff(config).create(
            actor_id=aid(actor), subid="s-p1", diff="{}", seqnr=4
        )
        assert actor._store_subscription_diff("p1", "s-p1", 4, {"x": 1}) == ""


class TestE6CreatorChangeLanded:
    def test_a_landed_change_that_raises_keeps_creator_changed(self) -> None:
        """The security property behind B5: a creator that did change is
        never left under a vouched marker."""
        from actingweb.actor import Actor
        from tests._adoption_helpers import aid, uuid_email

        config = make_config()
        config.force_email_prop_as_creator = False
        actor = Actor(config=config)
        assert actor.create(
            url="https://test.example.com/",
            creator=uuid_email(),
            passphrase="pw",
            auth_method="google_oauth2",
        )
        real_modify = Actor.modify
        new = uuid_email()

        def lands_then_raises(self: Actor, **kw: Any) -> bool:
            real_modify(self, **kw)
            raise DbError("simulated lost answer")

        loaded = Actor(actor_id=aid(actor), config=config)
        with (
            mock.patch.object(Actor, "modify", lands_then_raises),
            pytest.raises(DbError),
        ):
            loaded.modify_creator_unvouched(new)

        fresh = Actor(actor_id=aid(actor), config=config)
        assert fresh.creator == new
        assert fresh.store is not None
        assert fresh.store.auth_method == "creator_changed"


class TestF6ExpiringCookieKept:
    def test_a_logout_cookie_still_goes_out_with_the_fault(self) -> None:
        from actingweb.aw_web_request import AWWebObj
        from actingweb.interface.integrations._errors import map_db_error

        webobj = AWWebObj()
        webobj.response.set_cookie("oauth_token", "live-session")
        webobj.response.set_cookie("refresh_token", "", max_age=0)

        assert map_db_error(webobj.response, DbError("simulated"))
        assert [c["name"] for c in webobj.response.cookies] == ["refresh_token"]
