"""The one deletion finisher: resumable from its tombstone, leased, idempotent.

Plan: thoughts/plans/2026-11-02-3-16-adoption-fault-followups.md, Phase 1
(F1, T1, T2, the re-stamp, AW1).
"""

from __future__ import annotations

import datetime
from typing import Any
from unittest.mock import patch

import pytest

from actingweb import attribute, deletion
from actingweb import trust as trust_module
from actingweb.actor import Actor
from actingweb.constants import (
    CLIENT_INDEX_BUCKET,
    DELETED_ACTORS_BUCKET,
    DELETED_ACTORS_STORE,
    DELETION_TOMBSTONE_TTL,
    OAUTH2_SYSTEM_ACTOR,
)
from actingweb.db import get_attribute
from actingweb.db.exceptions import DbError, DeletionInProgress
from actingweb.deletion_finish import REASON_REPLACED, finish_deletion
from actingweb.interface.hooks import HookRegistry
from tests._adoption_helpers import (
    aid,
    create_core_actor,
    make_config,
    plant_squat_state,
    uuid_email,
)

EVENTS = ("actor_deleted", "actor_deleted_complete")


@pytest.fixture
def env() -> tuple[Any, HookRegistry, list[tuple[str, dict[str, Any]]]]:
    hooks = HookRegistry()
    events: list[tuple[str, dict[str, Any]]] = []
    for name in EVENTS:

        def record(actor: Any, _name: str = name, **kwargs: Any) -> None:
            events.append((_name, kwargs))

        hooks.register_lifecycle_hook(name, record)
    return make_config(hooks), hooks, events


def _tombstone(config: Any, actor_id: str) -> dict[str, Any] | None:
    _, data = deletion.read_tombstone(actor_id, config)
    return data


def _names(events: list[tuple[str, dict[str, Any]]]) -> list[str]:
    return [e[0] for e in events]


def _row_gone(config: Any, actor_id: str) -> bool:
    return Actor(actor_id=actor_id, config=config).id is None


class TestFirstAttempt:
    def test_wipes_fires_each_hook_once_and_starts_the_ttl(self, env: Any) -> None:
        config, hooks, events = env
        victim = create_core_actor(config, uuid_email(), auth_method="google_oauth2")
        plant_squat_state(config, victim)

        assert finish_deletion(victim, config=config, hooks=hooks, origin="delete") == 0

        assert _row_gone(config, aid(victim))
        assert not trust_module.Trusts(actor_id=aid(victim), config=config).fetch()
        assert _names(events) == ["actor_deleted", "actor_deleted_complete"]
        data = _tombstone(config, aid(victim))
        assert data is not None
        assert data["reason"] == "deleted" and data.get("finished_at")
        assert data.get("claimed_until") is None and data["hook_fired"] is True

    def test_a_pre_read_fault_writes_nothing_and_fires_nothing(self, env: Any) -> None:
        config, hooks, events = env
        victim = create_core_actor(config, uuid_email())
        with (
            patch.object(trust_module.Trusts, "fetch", side_effect=DbError("x")),
            pytest.raises(DbError),
        ):
            finish_deletion(victim, config=config, hooks=hooks, origin="delete")
        assert _tombstone(config, aid(victim)) is None
        assert events == []
        assert not _row_gone(config, aid(victim))

    def test_given_pre_reads_are_not_fetched_again(self, env: Any) -> None:
        from actingweb import subscription as subscription_module

        config, hooks, _events = env
        victim = create_core_actor(config, uuid_email())
        trusts = trust_module.Trusts(actor_id=aid(victim), config=config)
        trusts.fetch()
        subs = subscription_module.Subscriptions(actor_id=aid(victim), config=config)
        subs.fetch()
        real = trust_module.Trusts.fetch
        calls: list[Any] = []

        def counting(self: Any, *a: Any, **k: Any) -> Any:
            # A wrapper the finisher was handed answers from its cache; any
            # other Trusts would read the backend.
            if self is not trusts:
                calls.append(self)
            return real(self, *a, **k)

        with patch.object(trust_module.Trusts, "fetch", counting):
            finish_deletion(
                victim,
                config=config,
                hooks=hooks,
                origin="delete",
                pre_reads=(trusts, subs),
            )
        assert calls == []
        assert _row_gone(config, aid(victim))


class TestResume:
    def test_a_wipe_that_raised_is_finished_without_a_second_actor_deleted(
        self, env: Any
    ) -> None:
        config, hooks, events = env
        victim = create_core_actor(config, uuid_email())
        with (
            patch.object(attribute.Buckets, "delete", side_effect=DbError("x")),
            pytest.raises(DbError),
        ):
            finish_deletion(victim, config=config, hooks=hooks, origin="delete")
        assert not _row_gone(config, aid(victim))
        stalled = _tombstone(config, aid(victim))
        assert stalled is not None and stalled["hook_fired"] is True
        assert stalled.get("claimed_until") is None  # the lease was given back
        assert _names(events) == ["actor_deleted"]

        again = Actor(actor_id=aid(victim), config=config)
        assert finish_deletion(again, config=config, hooks=hooks, origin="delete") == 0
        assert _row_gone(config, aid(victim))
        assert _names(events) == ["actor_deleted", "actor_deleted_complete"]

    def test_a_re_call_of_actor_delete_is_the_resume_and_idempotent(
        self, env: Any
    ) -> None:
        config, _hooks, _events = env
        victim = create_core_actor(config, uuid_email())
        with (
            patch.object(attribute.Buckets, "delete", side_effect=DbError("x")),
            pytest.raises(DbError),
        ):
            victim.delete()
        again = Actor(actor_id=aid(victim), config=config)
        assert again.delete() is True
        assert _row_gone(config, aid(victim))
        assert again.delete() is True  # the same object, the row already gone

    def test_a_hook_db_error_runs_the_hook_again_on_the_retry(self) -> None:
        hooks = HookRegistry()
        calls: list[str] = []

        def flaky(actor: Any, **_kw: Any) -> None:
            calls.append("deleted")
            if len(calls) == 1:
                raise DbError("hook fault")

        hooks.register_lifecycle_hook("actor_deleted", flaky)
        config = make_config(hooks)
        victim = create_core_actor(config, uuid_email())
        with pytest.raises(DbError):
            finish_deletion(victim, config=config, hooks=hooks, origin="delete")
        assert not _row_gone(config, aid(victim))
        again = Actor(actor_id=aid(victim), config=config)
        assert finish_deletion(again, config=config, hooks=hooks, origin="delete") == 0
        assert calls == ["deleted", "deleted"]

    def test_a_replacement_resumed_by_a_re_call_notifies_no_peer(
        self, env: Any
    ) -> None:
        from actingweb import property as property_module

        config, hooks, _events = env
        victim = create_core_actor(config, uuid_email())
        plant_squat_state(config, victim)
        # Stops before the trusts go, so the re-call has a peer to notify.
        with (
            patch.object(
                property_module.Properties, "delete", side_effect=DbError("x")
            ),
            pytest.raises(DbError),
        ):
            finish_deletion(
                victim,
                config=config,
                hooks=hooks,
                origin="replacement",
                reason=REASON_REPLACED,
                notify_peers=False,
                hook_kwargs={"reason": REASON_REPLACED},
            )
        seen: list[bool] = []
        real = Actor.delete_reciprocal_trust

        def spy(self: Any, *a: Any, **k: Any) -> Any:
            seen.append(bool(k.get("notify_peers")))
            return real(self, *a, **k)

        with patch.object(Actor, "delete_reciprocal_trust", spy):
            # The application re-calls delete() with the default
            # notify_peers=True; the tombstone's False wins.
            assert Actor(actor_id=aid(victim), config=config).delete() is True
        assert seen and not any(seen)
        data = _tombstone(config, aid(victim))
        assert data is not None and data["reason"] == REASON_REPLACED
        assert data["notify_peers"] is False

    def test_a_resumed_hook_gets_the_recorded_kwargs(self) -> None:
        hooks = HookRegistry()
        got: list[dict[str, Any]] = []
        failing = [True]

        def hook(actor: Any, **kw: Any) -> None:
            got.append(kw)
            if failing:
                failing.clear()
                raise DbError("hook fault")

        hooks.register_lifecycle_hook("actor_deleted", hook)
        config = make_config(hooks)
        victim = create_core_actor(config, uuid_email())
        kwargs = {"reason": REASON_REPLACED, "replaced_by_identifier": "x@example.com"}
        with pytest.raises(DbError):
            finish_deletion(
                victim,
                config=config,
                hooks=hooks,
                origin="replacement",
                reason=REASON_REPLACED,
                notify_peers=False,
                hook_kwargs=kwargs,
            )
        finish_deletion(
            Actor(actor_id=aid(victim), config=config),
            config=config,
            hooks=hooks,
            origin="delete",
        )
        assert got == [kwargs, kwargs]

    def test_a_programmatic_delete_that_stalled_fires_no_hook_on_resume(
        self, env: Any
    ) -> None:
        config, hooks, events = env
        victim = create_core_actor(config, uuid_email())
        with (
            patch.object(attribute.Buckets, "delete", side_effect=DbError("x")),
            pytest.raises(DbError),
        ):
            victim.delete()  # ActorInterface.delete() runs no hooks
        data = _tombstone(config, aid(victim))
        assert data is not None and data["hook_fired"] is True
        finish_deletion(
            Actor(actor_id=aid(victim), config=config),
            config=config,
            hooks=hooks,
            origin="delete",
        )
        assert _names(events) == ["actor_deleted_complete"]

    def test_client_index_rows_go_even_after_the_buckets(self, env: Any) -> None:
        from actingweb.oauth2_server.client_registry import MCPClientRegistry

        config, hooks, _events = env
        victim = create_core_actor(config, uuid_email())
        client = MCPClientRegistry(config).register_client(
            aid(victim),
            {"client_name": "c", "redirect_uris": ["https://c.example/cb"]},
        )
        client_id = client["client_id"]
        db = get_attribute(config)
        assert db.get_attr_strict(
            actor_id=OAUTH2_SYSTEM_ACTOR, bucket=CLIENT_INDEX_BUCKET, name=client_id
        )
        # The wipe stops after the buckets (the client row among them) went.
        with (
            patch.object(
                type(victim.handle), "delete", side_effect=DbError("row delete")
            ),
            patch.object(
                type(get_attribute(config)),
                "delete_attr_conditional",
                return_value=False,
            ),
            pytest.raises(DbError),
        ):
            finish_deletion(victim, config=config, hooks=hooks, origin="delete")
        data = _tombstone(config, aid(victim))
        assert data is not None and client_id in data["client_ids"]
        finish_deletion(
            Actor(actor_id=aid(victim), config=config),
            config=config,
            hooks=hooks,
            origin="delete",
        )
        assert not db.get_attr_strict(
            actor_id=OAUTH2_SYSTEM_ACTOR, bucket=CLIENT_INDEX_BUCKET, name=client_id
        )


class TestLease:
    def test_a_live_lease_answers_in_progress(self, env: Any) -> None:
        config, hooks, events = env
        victim = create_core_actor(config, uuid_email())
        deletion.create_leased_tombstone(
            aid(victim),
            config,
            reason="deleted",
            notify_peers=True,
            hook_kwargs={},
            client_ids=[],
        )
        with pytest.raises(DeletionInProgress) as caught:
            finish_deletion(victim, config=config, hooks=hooks, origin="delete")
        assert 1 <= caught.value.retry_after <= 120
        assert events == []
        assert not _row_gone(config, aid(victim))

    def test_a_lapsed_lease_is_taken_over(self, env: Any) -> None:
        config, hooks, _events = env
        victim = create_core_actor(config, uuid_email())
        deletion.create_leased_tombstone(
            aid(victim),
            config,
            reason="deleted",
            notify_peers=True,
            hook_kwargs={},
            client_ids=[],
            now=datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1),
        )
        assert finish_deletion(victim, config=config, hooks=hooks, origin="delete") == 0
        assert _row_gone(config, aid(victim))

    def test_two_first_writers_one_wins(self, env: Any) -> None:
        config, _hooks, _events = env
        actor_id = aid(create_core_actor(config, uuid_email()))
        kwargs: dict[str, Any] = {
            "reason": "deleted",
            "notify_peers": True,
            "hook_kwargs": {},
            "client_ids": [],
        }
        deletion.create_leased_tombstone(actor_id, config, **kwargs)
        with pytest.raises(DeletionInProgress):
            deletion.create_leased_tombstone(actor_id, config, **kwargs)

    def test_an_unfinished_tombstone_has_no_ttl(self, env: Any) -> None:
        config, _hooks, _events = env
        actor_id = aid(create_core_actor(config, uuid_email()))
        deletion.create_leased_tombstone(
            actor_id,
            config,
            reason="deleted",
            notify_peers=True,
            hook_kwargs={},
            client_ids=[],
        )
        row = get_attribute(config).get_attr(
            actor_id=DELETED_ACTORS_STORE, bucket=DELETED_ACTORS_BUCKET, name=actor_id
        )
        assert row is not None
        assert not row.get("ttl_timestamp")

    def test_a_finisher_whose_lease_was_taken_stops(self, env: Any) -> None:
        """The lease is renewed after actor_deleted and fenced: a finisher
        whose lease lapsed and was taken over during a slow hook stops."""
        hooks = HookRegistry()
        config = make_config(hooks)
        victim = create_core_actor(config, uuid_email())

        def slow(actor: Any, **_kw: Any) -> None:
            # Another finisher takes the lease while this hook runs.
            _, data = deletion.read_tombstone(aid(victim), config)
            assert data is not None
            assert deletion.update_tombstone(
                aid(victim), config, data, {"lease_id": "someone-else"}
            )

        hooks.register_lifecycle_hook("actor_deleted", slow)
        with pytest.raises(DeletionInProgress):
            finish_deletion(victim, config=config, hooks=hooks, origin="delete")
        assert not _row_gone(config, aid(victim))

    def test_completion_is_announced_by_the_lease_holder_only(self, env: Any) -> None:
        config, _hooks, _events = env
        actor_id = aid(create_core_actor(config, uuid_email()))
        mine = deletion.create_leased_tombstone(
            actor_id,
            config,
            reason="deleted",
            notify_peers=True,
            hook_kwargs={},
            client_ids=[],
        )
        assert deletion.update_tombstone(actor_id, config, mine, {"lease_id": "other"})
        assert deletion.mark_finished(actor_id, config, mine) is False
        assert deletion.mark_finished(actor_id, config, {"lease_id": "other"}) is True


class TestRestamp:
    def test_keeps_what_the_first_write_recorded(self, env: Any) -> None:
        config, _hooks, _events = env
        actor_id = aid(create_core_actor(config, uuid_email()))
        first = deletion.create_leased_tombstone(
            actor_id,
            config,
            reason=REASON_REPLACED,
            notify_peers=False,
            hook_kwargs={"reason": REASON_REPLACED},
            client_ids=["c1"],
        )
        assert deletion.restamp(actor_id, config, True) is False
        data = _tombstone(config, actor_id)
        assert data is not None
        for key in ("reason", "notify_peers", "hook_kwargs", "client_ids", "lease_id"):
            assert data[key] == first[key]

    def test_without_a_tombstone_writes_a_resumable_one(self, env: Any) -> None:
        config, _hooks, _events = env
        actor_id = aid(create_core_actor(config, uuid_email()))
        assert deletion.restamp(actor_id, config, True) is True
        data = _tombstone(config, actor_id)
        assert data is not None
        assert data["reason"] == "deleted" and data["hook_fired"] is True


class TestClearOnCreate:
    def test_a_fixed_id_create_fails_when_the_clear_faults(self, env: Any) -> None:
        config, _hooks, _events = env
        actor_id = f"fixed{uuid_email().split('@')[0].replace('-', '')}"
        deletion.mark_actor_deleted(actor_id, config)
        actor = Actor(config=config)
        with (
            patch.object(
                type(get_attribute(config)),
                "get_attr_strict",
                side_effect=DbError("clear read"),
            ),
            pytest.raises(DbError),
        ):
            actor.create(
                url="https://test.example.com/",
                creator=uuid_email(),
                passphrase="p",
                actor_id=actor_id,
                auth_method="google_oauth2",
            )
        # The create failed and left no row (the clear's delete may have run
        # before its confirmation read faulted).
        assert _row_gone(config, actor_id)

    def test_a_clear_that_leaves_the_tombstone_fails_the_create(self, env: Any) -> None:
        config, _hooks, _events = env
        actor_id = f"fixed{uuid_email().split('@')[0].replace('-', '')}"
        deletion.mark_actor_deleted(actor_id, config)
        actor = Actor(config=config)
        with (
            patch.object(type(get_attribute(config)), "delete_attr", return_value=True),
            pytest.raises(DbError),
        ):
            actor.create(
                url="https://test.example.com/",
                creator=uuid_email(),
                passphrase="p",
                actor_id=actor_id,
                auth_method="google_oauth2",
            )
        assert _row_gone(config, actor_id)

    def test_a_generated_id_makes_no_strict_clear(self, env: Any) -> None:
        config, _hooks, _events = env
        with patch.object(
            deletion, "clear_actor_tombstone", wraps=deletion.clear_actor_tombstone
        ) as spy:
            create_core_actor(config, uuid_email())
        assert spy.call_args is not None
        assert spy.call_args.kwargs.get("strict", False) is False


class TestLeaseKeeper:
    """Verification 2026-11-03, issue 7: the lease was last renewed before
    Actor.delete, whose peer DELETEs can outlast it."""

    def _leased(self, config: Any) -> tuple[str, dict[str, Any]]:
        actor_id = aid(create_core_actor(config, uuid_email()))
        data = deletion.create_leased_tombstone(
            actor_id,
            config,
            reason="deleted",
            notify_peers=False,
            hook_kwargs={},
            client_ids=[],
        )
        assert data is not None
        return actor_id, data

    def test_the_keeper_renews_after_a_third_of_the_lease(self, env: Any) -> None:
        from actingweb import deletion_finish

        config, _hooks, _events = env
        actor_id, data = self._leased(config)
        before = _tombstone(config, actor_id)
        assert before is not None
        keep = deletion_finish._lease_keeper(actor_id, config, data)
        keep()  # too early: nothing written
        assert _tombstone(config, actor_id) == before
        start = deletion_finish.time.monotonic()
        with patch.object(deletion_finish.time, "monotonic", return_value=start + 60):
            keep()
        after = _tombstone(config, actor_id)
        assert after is not None
        assert after["claimed_until"] >= before["claimed_until"]
        assert after["lease_id"] == before["lease_id"]

    def test_a_slow_token_sweep_counts_against_the_lease(self, env: Any) -> None:
        """Re-verification N6: the keeper's clock started after the token and
        client sweeps, so a slow sweep was not counted and the first renewal
        came up to a third of a lease after the lease had run out."""
        from actingweb import deletion_finish

        config, hooks, _events = env
        actor = create_core_actor(config, uuid_email())
        clock = [deletion_finish.time.monotonic()]
        renewals: list[float] = []

        def slow_sweep(*args: Any, **kwargs: Any) -> int:
            clock[0] += 90  # most of the 120 s lease
            return 0

        def renew(*args: Any, **kwargs: Any) -> None:
            renewals.append(clock[0])

        with (
            patch.object(
                deletion_finish.time, "monotonic", side_effect=lambda: clock[0]
            ),
            patch("actingweb.oauth2._revoke_all_actor_tokens", slow_sweep),
            patch.object(deletion, "renew_lease", side_effect=renew),
        ):
            finish_deletion(actor, config=config, hooks=hooks, origin="delete")
        assert renewals, "the lease was not renewed after a 90 s sweep"

    def test_the_generation_is_bumped_before_the_token_sweep(self, env: Any) -> None:
        """A refresh whose consume preceded the sweep mints after it; the
        bump makes its generation guard delete what it minted (3.16)."""
        from actingweb import session_generation

        config, hooks, _events = env
        actor = create_core_actor(config, uuid_email())
        actor_id = str(actor.id)
        before = session_generation.current(actor_id, config)
        order: list[str] = []
        real_bump = session_generation.bump

        def bump(actor_id: str, cfg: Any) -> str:
            order.append("bump")
            return real_bump(actor_id, cfg)

        def sweep(*args: Any, **kwargs: Any) -> int:
            # The stamp a pre-sweep credential carries no longer matches.
            order.append("sweep")
            assert not session_generation.matches(before, actor_id, config)
            return 0

        with (
            patch.object(session_generation, "bump", bump),
            patch("actingweb.oauth2._revoke_all_actor_tokens", sweep),
        ):
            finish_deletion(actor, config=config, hooks=hooks, origin="delete")
        assert order == ["bump", "sweep"]

    def test_a_resume_with_the_actor_row_gone_writes_no_generation(
        self, env: Any
    ) -> None:
        """A wipe that stopped after the actor row went: the resume must not
        bump, since the wipe would not reach the bucket it writes
        (verification 2026-11-04, Issue 6)."""
        from actingweb import session_generation
        from actingweb.db import get_actor

        config, hooks, _events = env
        actor = create_core_actor(config, uuid_email())
        actor_id = str(actor.id)
        deletion.create_leased_tombstone(
            actor_id,
            config,
            reason="deleted",
            notify_peers=False,
            hook_kwargs={},
            client_ids=[],
        )
        db = get_actor(config)
        assert db.get(actor_id=actor_id)
        db.delete()  # the crash left the row gone, the tombstone unfinished
        _, data = deletion.read_tombstone(actor_id, config)
        assert data is not None
        deletion.release_lease(actor_id, config, data)
        with patch.object(
            session_generation, "bump", wraps=session_generation.bump
        ) as bump:
            finish_deletion(actor, config=config, hooks=hooks, origin="delete")
        bump.assert_not_called()
        assert session_generation.current(actor_id, config) is None

    def test_a_bump_fault_releases_the_lease_and_raises(self, env: Any) -> None:
        from actingweb import session_generation

        config, hooks, _events = env
        actor = create_core_actor(config, uuid_email())
        swept: list[int] = []
        with (
            patch.object(
                session_generation,
                "bump",
                side_effect=DbError("session generation write"),
            ),
            patch(
                "actingweb.oauth2._revoke_all_actor_tokens",
                lambda *a, **k: swept.append(1) or 0,
            ),
        ):
            with pytest.raises(DbError):
                finish_deletion(actor, config=config, hooks=hooks, origin="delete")
        assert swept == []
        tombstone = _tombstone(config, str(actor.id))
        assert tombstone is not None and not tombstone.get("lease_id")

    def test_a_slow_client_sweep_is_renewed_before_the_wipe(self, env: Any) -> None:
        """Re-verification 3, V10: the keeper ran between the token and the
        client sweep only, so a slow client sweep went unrenewed into the
        wipe's own steps."""
        from actingweb import deletion_finish
        from actingweb.actor import Actor

        config, hooks, _events = env
        actor = create_core_actor(config, uuid_email())
        clock = [deletion_finish.time.monotonic()]
        renewals: list[float] = []
        at_wipe: list[int] = []
        real_delete = Actor.delete

        def slow_clients(*args: Any, **kwargs: Any) -> None:
            clock[0] += 90

        def renew(*args: Any, **kwargs: Any) -> None:
            renewals.append(clock[0])

        def delete(self: Actor, *args: Any, **kwargs: Any) -> Any:
            at_wipe.append(len(renewals))
            return real_delete(self, *args, **kwargs)

        with (
            patch.object(
                deletion_finish.time, "monotonic", side_effect=lambda: clock[0]
            ),
            patch("actingweb.oauth2._delete_actor_clients", slow_clients),
            patch.object(deletion, "renew_lease", side_effect=renew),
            patch.object(Actor, "delete", delete),
        ):
            finish_deletion(actor, config=config, hooks=hooks, origin="delete")
        assert at_wipe and at_wipe[0] >= 1, "no renewal before the wipe began"

    def test_a_lease_taken_over_stops_the_wipe(self, env: Any) -> None:
        from actingweb import deletion_finish

        config, _hooks, _events = env
        actor_id, data = self._leased(config)
        current = _tombstone(config, actor_id)
        assert current is not None
        assert deletion.update_tombstone(
            actor_id, config, current, {"lease_id": "someone-else"}
        )
        keep = deletion_finish._lease_keeper(actor_id, config, data)
        start = deletion_finish.time.monotonic()
        with (
            patch.object(deletion_finish.time, "monotonic", return_value=start + 60),
            pytest.raises(DeletionInProgress),
        ):
            keep()

    def test_actor_delete_runs_the_keeper_between_steps(self, env: Any) -> None:
        config, _hooks, _events = env
        actor = create_core_actor(config, uuid_email())
        calls: list[int] = []
        assert actor.delete(_between_steps=lambda: calls.append(1)) is True
        assert len(calls) >= 2


class TestLegacyTombstoneOnDelete:
    def test_a_user_delete_fires_actor_deleted_despite_a_stray_legacy_tombstone(
        self, env: Any
    ) -> None:
        """Verification 2026-11-03, issue 16: a reason-less tombstone counted
        as hook_fired, so the application's actor_deleted cleanup never ran
        for a genuine DELETE of a live actor carrying one."""
        config, hooks, events = env
        actor = create_core_actor(config, uuid_email())
        deletion.mark_actor_deleted(aid(actor), config)  # legacy: no reason
        assert finish_deletion(actor, config=config, hooks=hooks, origin="delete") == 0
        assert _names(events) == ["actor_deleted", "actor_deleted_complete"]

    def test_the_operator_command_does_not_fire_it(self, env: Any) -> None:
        config, hooks, events = env
        actor = create_core_actor(config, uuid_email())
        deletion.mark_actor_deleted(aid(actor), config)
        finish_deletion(actor, config=config, hooks=hooks, origin="operator")
        assert "actor_deleted" not in _names(events)

    def test_an_operator_resume_records_the_deletion(self, env: Any) -> None:
        """Re-verification N13: the operator path recorded only
        ``hook_fired``, so a resume that stalled again left a tombstone that
        was still "legacy, review", with no client ids and no peers choice."""
        config, hooks, _events = env
        actor = create_core_actor(config, uuid_email())
        deletion.mark_actor_deleted(aid(actor), config)
        with (
            patch.object(Actor, "delete", side_effect=RuntimeError("stalled")),
            pytest.raises(RuntimeError),
        ):
            finish_deletion(
                actor,
                config=config,
                hooks=hooks,
                origin="operator",
                notify_peers=False,
            )
        _, data = deletion.read_tombstone(aid(actor), config)
        assert data is not None and deletion.is_resumable(data)
        assert data["notify_peers"] is False and data["hook_fired"] is True
        assert isinstance(data.get("client_ids"), list)

    def test_a_finished_tombstone_over_a_live_row_is_a_new_deletion(
        self, env: Any
    ) -> None:
        """Re-verification 4, W3: a finished tombstone whose actor id was
        re-created kept its old finish, so the resume wiped under the old
        retention TTL, the mark was refused (already finished) and
        ``actor_deleted_complete`` never fired."""
        config, hooks, events = env
        actor = create_core_actor(config, uuid_email())
        data = deletion.create_leased_tombstone(
            aid(actor),
            config,
            reason="deleted",
            notify_peers=False,
            hook_kwargs={},
            client_ids=[],
        )
        assert deletion.mark_finished(aid(actor), config, data) is True
        _, finished = deletion.read_tombstone(aid(actor), config)
        assert finished is not None and finished.get("finished_at")
        old_finish = finished["finished_at"]
        # The id is live again: its row still exists here.
        finish_deletion(
            actor, config=config, hooks=hooks, origin="delete", notify_peers=False
        )
        _, after = deletion.read_tombstone(aid(actor), config)
        assert after is not None and after.get("finished_at")
        assert after["finished_at"] != old_finish
        assert Actor(actor_id=aid(actor), config=config).id is None
        assert any(e[0] == "actor_deleted_complete" for e in events)

    def test_a_late_finisher_after_the_finish_changes_nothing(self, env: Any) -> None:
        """Re-verification 5, X1: a second finisher that loaded the actor
        before the first removed its row (a DELETE retry, a sibling two
        sign-ins sweep) reset the finished tombstone and announced the
        completion a second time."""
        config, hooks, events = env
        actor = create_core_actor(config, uuid_email())
        stale = Actor(actor_id=aid(actor), config=config)  # loaded before the wipe
        finish_deletion(
            actor, config=config, hooks=hooks, origin="delete", notify_peers=False
        )
        _, first = deletion.read_tombstone(aid(actor), config)
        assert first is not None and first.get("finished_at")
        assert _names(events).count("actor_deleted_complete") == 1
        assert (
            finish_deletion(
                stale, config=config, hooks=hooks, origin="sign_in", notify_peers=False
            )
            == 0
        )
        _, second = deletion.read_tombstone(aid(actor), config)
        assert second is not None
        assert second["finished_at"] == first["finished_at"]
        assert second.get("reason") == first.get("reason")
        assert _names(events).count("actor_deleted_complete") == 1
        assert _names(events).count("actor_deleted") == 1

    def test_a_finished_deletion_reads_nothing_else_first(self, env: Any) -> None:
        """Re-verification 6, Y4: a retry of a finished deletion answered 503
        when the trust pre-read faulted, for an actor already gone."""
        from actingweb import deletion_finish

        config, hooks, _events = env
        actor = create_core_actor(config, uuid_email())
        stale = Actor(actor_id=aid(actor), config=config)
        finish_deletion(
            actor, config=config, hooks=hooks, origin="delete", notify_peers=False
        )
        with patch.object(deletion_finish, "_pre_read", side_effect=DbError("trusts")):
            assert (
                finish_deletion(
                    stale,
                    config=config,
                    hooks=hooks,
                    origin="delete",
                    notify_peers=False,
                )
                == 0
            )

    def test_a_stalled_rewrite_keeps_no_retention_ttl(self, env: Any) -> None:
        """Re-verification N7: the legacy row carried the 30-day retention
        TTL; once rewritten as resumable it must not expire before the wipe
        it now records is confirmed."""
        import time

        config, hooks, _events = env
        actor = create_core_actor(config, uuid_email())
        deletion.mark_actor_deleted(aid(actor), config)  # legacy: no reason, TTL
        with (
            patch.object(Actor, "delete", side_effect=RuntimeError("stalled")),
            pytest.raises(RuntimeError),
        ):
            finish_deletion(actor, config=config, hooks=hooks, origin="delete")
        later = time.time() + DELETION_TOMBSTONE_TTL + 86400
        with patch("time.time", return_value=later):
            _, data = deletion.read_tombstone(aid(actor), config)
        assert data is not None and deletion.is_resumable(data)
        assert not data.get("finished_at")


class TestClearTtl:
    def test_a_conditional_update_can_remove_the_ttl(self, env: Any) -> None:
        import time

        config, _hooks, _events = env
        db = get_attribute(config)
        name = uuid_email()
        db.set_attr(
            actor_id="ttl-test", bucket="b", name=name, data={"v": 1}, ttl_seconds=60
        )
        assert db.conditional_update_attr(
            actor_id="ttl-test",
            bucket="b",
            name=name,
            old_data={"v": 1},
            new_data={"v": 2},
            clear_ttl=True,
        )
        with patch("time.time", return_value=time.time() + 7 * 86400):
            row = db.get_attr_strict(actor_id="ttl-test", bucket="b", name=name)
        assert row is not None and row["data"] == {"v": 2}

    def test_a_backend_without_the_keyword_still_writes_tombstones(
        self, env: Any
    ) -> None:
        """Re-verification 3, V4: only the legacy rewrite asks for
        ``clear_ttl``; every other tombstone write leaves it out, so a
        backend written before the keyword fails only that rewrite."""
        from actingweb import deletion

        config, _hooks, _events = env
        actor = create_core_actor(config, uuid_email())
        data = deletion.create_leased_tombstone(
            aid(actor),
            config,
            reason="deleted",
            notify_peers=False,
            hook_kwargs={},
            client_ids=[],
        )
        db = get_attribute(config)
        real = db.conditional_update_attr

        def old_backend(
            *,
            actor_id: str,
            bucket: str,
            name: str,
            old_data: Any,
            new_data: Any,
            ttl_seconds: int | None = None,
        ) -> bool:
            return real(
                actor_id=actor_id,
                bucket=bucket,
                name=name,
                old_data=old_data,
                new_data=new_data,
                ttl_seconds=ttl_seconds,
            )

        with patch.object(
            type(db), "conditional_update_attr", staticmethod(old_backend)
        ):
            with patch("actingweb.deletion.get_attribute", return_value=db):
                changed = deletion.update_tombstone(
                    aid(actor), config, data, {"hook_fired": True}
                )
        assert changed is not None and changed["hook_fired"] is True


class TestDeleteClientForADeletedActor:
    def test_only_the_index_row_goes(self, env: Any) -> None:
        """Phase 1 (planned, added at the 2026-11-03 verification):
        ``delete_client(actor_deleted=True)`` removes the global index row
        and leaves the actor's own bucket and the client trust to the wipe."""
        from actingweb.oauth2_server.client_registry import MCPClientRegistry

        config, _hooks, _events = env
        owner = create_core_actor(config, uuid_email())
        registry = MCPClientRegistry(config)
        client_id = registry.register_client(
            aid(owner),
            {"client_name": "c", "redirect_uris": ["https://c.example/cb"]},
        )["client_id"]
        trusts_before = trust_module.Trusts(actor_id=aid(owner), config=config).fetch()
        assert registry.delete_client(client_id, actor_deleted=True) is True
        db = get_attribute(config)
        assert not db.get_attr_strict(
            actor_id=OAUTH2_SYSTEM_ACTOR, bucket=CLIENT_INDEX_BUCKET, name=client_id
        )
        assert registry.list_clients_for_actor(aid(owner))  # the row stays
        assert (
            trust_module.Trusts(actor_id=aid(owner), config=config).fetch()
            == trusts_before
        )
