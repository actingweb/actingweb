"""A sign-in on a vouched actor whose deletion stalled (AW3, R2, R4).

Plan: thoughts/plans/2026-11-02-3-16-adoption-fault-followups.md, Phase 1.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any
from unittest.mock import patch

import pytest

from actingweb import deletion
from actingweb.actor import Actor
from actingweb.db import get_attribute
from actingweb.db.exceptions import DbError, DeletionInProgress
from actingweb.interface.hooks import HookRegistry
from actingweb.oauth2 import OAuth2Authenticator, OAuth2Provider
from tests._adoption_helpers import aid, create_core_actor, make_config, uuid_email

EVENTS = ("actor_created", "actor_deleted", "actor_deleted_complete")
_PAST = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1)


@pytest.fixture
def env() -> tuple[Any, OAuth2Authenticator, list[str]]:
    hooks = HookRegistry()
    events: list[str] = []
    for name in EVENTS:

        def record(actor: Any, _name: str = name, **kwargs: Any) -> None:
            events.append(_name)

        hooks.register_lifecycle_hook(name, record)
    config = make_config(hooks)
    provider = OAuth2Provider(
        "google",
        {
            "client_id": "cid",
            "client_secret": "csec",
            "auth_uri": "https://provider.test/auth",
            "token_uri": "https://provider.test/token",
            "userinfo_uri": "https://provider.test/userinfo",
            "scope": "openid email",
            "redirect_uri": "https://test.example.com/oauth/callback",
        },
    )
    return config, OAuth2Authenticator(config, provider), events


def _stalled(config: Any, actor_id: str, *, leased: bool = False) -> None:
    """A resumable tombstone whose actor_deleted already ran: a DELETE that
    stopped part-way."""
    data = deletion.create_leased_tombstone(
        actor_id,
        config,
        reason="deleted",
        notify_peers=True,
        hook_kwargs={},
        client_ids=[],
        now=None if leased else _PAST,
    )
    assert deletion.update_tombstone(actor_id, config, data, {"hook_fired": True})


class TestStalledVouched:
    def test_a_sign_in_finishes_the_wipe_and_creates_a_new_actor(
        self, env: Any
    ) -> None:
        config, auth, events = env
        creator = uuid_email()
        live = create_core_actor(config, creator, auth_method="google_oauth2")
        events.clear()
        _stalled(config, aid(live))

        signed_in = auth.lookup_or_create_actor_by_identifier(
            creator, finish_stalled_deletion=True
        )

        assert signed_in is not None and signed_in.id != aid(live)
        assert signed_in.creator == creator
        assert Actor(actor_id=aid(live), config=config).id is None
        assert events == ["actor_deleted_complete", "actor_created"]

    def test_under_a_live_lease_the_sign_in_waits(self, env: Any) -> None:
        config, auth, events = env
        creator = uuid_email()
        live = create_core_actor(config, creator, auth_method="google_oauth2")
        events.clear()
        _stalled(config, aid(live), leased=True)

        with pytest.raises(DeletionInProgress) as caught:
            auth.lookup_or_create_actor_by_identifier(
                creator, finish_stalled_deletion=True
            )
        assert caught.value.retry_after >= 1
        assert Actor(actor_id=aid(live), config=config).id == aid(live)
        assert events == []

    def test_an_unreadable_tombstone_store_fails_closed(self, env: Any) -> None:
        config, auth, _events = env
        creator = uuid_email()
        create_core_actor(config, creator, auth_method="google_oauth2")
        real = type(get_attribute(config)).get_attr_strict

        def faulting(*args: Any, **kw: Any) -> Any:
            if "_deleted_actors" in (kw.get("bucket"), *args):
                raise DbError("tombstone read")
            return real(*args, **kw)

        with (
            patch.object(type(get_attribute(config)), "get_attr_strict", faulting),
            pytest.raises(DbError),
        ):
            auth.lookup_or_create_actor_by_identifier(
                creator, finish_stalled_deletion=True
            )

    def test_a_reason_less_tombstone_keeps_the_actor(
        self, env: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        config, auth, _events = env
        creator = uuid_email()
        live = create_core_actor(config, creator, auth_method="google_oauth2")
        deletion.mark_actor_deleted(aid(live), config)  # pre-resumable shape
        try:
            with caplog.at_level(logging.WARNING, logger="actingweb.oauth2"):
                signed_in = auth.lookup_or_create_actor_by_identifier(
                    creator, finish_stalled_deletion=True
                )
            assert signed_in is not None and signed_in.id == aid(live)
            assert "no recorded reason" in caplog.text
        finally:
            deletion.clear_actor_tombstone(aid(live), config)

    def test_a_per_request_lookup_never_wipes(self, env: Any) -> None:
        config, auth, events = env
        creator = uuid_email()
        live = create_core_actor(config, creator, auth_method="google_oauth2")
        _stalled(config, aid(live))
        events.clear()

        found = auth.lookup_or_create_actor_by_identifier(creator)

        assert found is not None and found.id == aid(live)
        assert events == []

    def test_the_email_link_does_not_finish_it(self, env: Any) -> None:
        from actingweb.oauth2 import adopt_actor

        config, _auth, _events = env
        creator = uuid_email()
        live = create_core_actor(config, creator, auth_method="google_oauth2")
        _stalled(config, aid(live))

        result = adopt_actor(
            Actor(actor_id=aid(live), config=config),
            provider=None,
            config=config,
            hooks=None,
            verified_by_email=True,
            finish_stalled_deletion=True,
        )

        assert result is None
        assert Actor(actor_id=aid(live), config=config).id == aid(live)


class TestUnvouchedLegacyTombstone:
    def test_an_unvouched_actor_with_a_reason_less_tombstone_is_finished_quietly(
        self, env: Any
    ) -> None:
        """R4 is vouched-only: a reason-less tombstone on an unvouched actor is
        most likely a stalled replacement, finished as before, its peers not
        notified."""
        config, auth, events = env
        creator = uuid_email()
        squat = create_core_actor(config, creator, auth_method="factory")
        deletion.mark_actor_deleted(aid(squat), config)
        events.clear()
        seen: list[bool] = []
        real = Actor.delete

        def spy(self: Any, notify_peers: bool = True, **kw: Any) -> Any:
            seen.append(notify_peers)
            return real(self, notify_peers, **kw)

        with patch.object(Actor, "delete", spy):
            adopted = auth.lookup_or_create_actor_by_identifier(creator)

        assert adopted is not None and adopted.id != aid(squat)
        assert seen == [False]
        assert "actor_deleted" not in events  # it ran when the tombstone was written


class TestSweepSkipsALeasedSibling:
    def test_a_sibling_being_wiped_elsewhere_is_left_to_it(self, env: Any) -> None:
        from actingweb.oauth2 import _sweep_factory_actors

        config, _auth, events = env
        creator = uuid_email()
        sibling = create_core_actor(config, creator, auth_method="factory")
        _stalled(config, aid(sibling), leased=True)
        events.clear()

        result = _sweep_factory_actors(config, None, creator, [aid(sibling)])

        assert result is not None and result[1] == []
        assert Actor(actor_id=aid(sibling), config=config).id == aid(sibling)
