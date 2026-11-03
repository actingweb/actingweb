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
