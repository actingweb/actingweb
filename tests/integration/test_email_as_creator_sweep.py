"""``actingweb-unique-creators creator-to-email`` and the start-up check it
satisfies (4.0, email-as-creator Phase 3), on both backends.

The sweep moves each vouched actor whose stored email differs from its
creator to that email, conditioned on what it read; after a complete clean
``--apply`` run it writes the marker ``check_ready()`` reads under
``with_email_as_creator``. Runs on the isolated store, in the
``unique_creator`` group.
"""

from __future__ import annotations

import copy
import logging
import uuid
from types import SimpleNamespace
from typing import Any
from unittest import mock

import pytest

from actingweb.constants import READINESS_BUCKET, READINESS_STORE
from actingweb.db import get_actor, get_attribute
from actingweb.db.exceptions import DbError
from actingweb.maintenance import email_as_creator, unique_creators
from actingweb.oauth2 import VOUCHED_CREATOR

pytestmark = pytest.mark.xdist_group(name="unique_creator")

IB = "_internal"


def _email() -> str:
    return f"{uuid.uuid4().hex[:12]}@example.com"


def _pid() -> str:
    return f"github:{uuid.uuid4().int % 10**9}"


def _command(config: Any) -> Any:
    """The command's own config: uniqueness and the flag off."""
    off = copy.copy(config)
    off.unique_creator = False
    off.force_email_prop_as_creator = False
    return off


def _actor(
    config: Any,
    creator: str,
    *,
    email: str | None = None,
    auth: str | None = "google_oauth2",
    recorded: bool = True,
) -> str:
    get_attribute(config)
    actor_id = uuid.uuid4().hex
    assert get_actor(config).create(actor_id=actor_id, creator=creator, passphrase="pw")
    attrs = get_attribute(config)
    if auth:
        attrs.set_attr(actor_id, IB, "auth_method", auth)
    if recorded and auth not in (None, "factory"):
        attrs.set_attr(actor_id, IB, VOUCHED_CREATOR, creator)
    if email:
        attrs.set_attr(actor_id, IB, "email", email)
    return actor_id


def _creator(config: Any, actor_id: str) -> str | None:
    row = get_actor(config).get(actor_id=actor_id)
    return row["creator"] if row else None


def _stored(config: Any, actor_id: str, name: str) -> Any:
    row = get_attribute(config).get_attr_strict(actor_id, IB, name)
    return row.get("data") if row else None


def _marker(config: Any) -> Any:
    return email_as_creator.read_marker(config)


def _sweep(config: Any, **kw: Any) -> dict[str, int]:
    return email_as_creator.sweep(_command(config), **kw)


class TestTheSweep:
    def test_a_mixed_store(self, enforced_store: Any) -> None:
        cfg = enforced_store
        old_creator: dict[str, str] = {}
        moved_to = {
            "address": (_actor(cfg, _email(), email=(a := _email())), a),
            "default": (_actor(cfg, "creator", email=(b := _email())), b),
            "provider": (_actor(cfg, _pid(), email=(c := _email())), c),
        }
        for aid, _t in moved_to.values():
            old_creator[aid] = _creator(cfg, aid) or ""
        same = _email()
        equal = _actor(cfg, same, email=same)
        unvouched = _actor(cfg, _email(), email=_email(), auth="factory")
        trustee = _actor(cfg, "trustee", email=_email())
        squat_addr, held_addr, typed_addr = _email(), _email(), _email()
        _actor(cfg, squat_addr, auth="factory")
        squatted = _actor(cfg, _pid(), email=squat_addr)
        # An unvouched holder of another kind (a typed address, a trustee
        # handoff) does not block either.
        _actor(cfg, typed_addr, auth="email_unverified")
        squatted_too = _actor(cfg, _pid(), email=typed_addr)
        held_by = _actor(cfg, held_addr)
        held = _actor(cfg, _pid(), email=held_addr)
        fixed = {
            aid: _creator(cfg, aid)
            for aid in (equal, unvouched, trustee, squatted, squatted_too, held)
        }

        dry = _sweep(cfg)
        assert dry["moved"] == 3 and dry["held"] == 1 and dry["squatted"] == 2
        for aid, _target in moved_to.values():
            assert _creator(cfg, aid) != _target
        assert _marker(cfg) is None

        done = _sweep(cfg, apply=True)
        assert done["moved"] == 3 and done["held"] == 1 and done["errors"] == 0
        for name, (aid, target) in moved_to.items():
            assert _creator(cfg, aid) == target
            assert get_actor(cfg).get_creator_holder(target) == aid
            assert _stored(cfg, aid, VOUCHED_CREATOR) == target
            assert _stored(cfg, aid, "email") == target
            if name != "default":
                assert get_actor(cfg).get_creator_holder(old_creator[aid]) is None
        for aid, creator in fixed.items():
            assert _creator(cfg, aid) == creator
        assert get_actor(cfg).get_creator_holder(held_addr) == held_by
        # A vouched holder keeps the marker back.
        assert _marker(cfg) is None

        cleared = _sweep(cfg, apply=True, clear_held_email=True)
        assert cleared["cleared"] == 1 and cleared["held"] == 0
        assert _stored(cfg, held, "email") is None
        assert (_marker(cfg) or {}).get("state") == "synced"

    def test_a_deliberate_rename_is_not_moved_back(self, enforced_store: Any) -> None:
        """Actor.modify(creator=X) leaves the recorded address and the stored
        email on the old one: the actor reads unvouched for X, out of scope."""
        old, x = _email(), _email()
        aid = _actor(enforced_store, old, email=old)
        db = get_actor(enforced_store)
        db.get(actor_id=aid)
        assert db.modify(creator=x)
        counts = _sweep(enforced_store, apply=True)
        assert counts["moved"] == 0
        assert _creator(enforced_store, aid) == x

    def test_a_stale_holder_does_not_block(self, enforced_store: Any) -> None:
        addr = _email()
        gone = _actor(enforced_store, addr)
        # Renamed away without releasing its record (an old process, a
        # faulted release): the record, or a lagging index, still names it.
        stale = get_actor(_command(enforced_store))
        stale.get(actor_id=gone)
        assert stale.modify(creator=_email())
        aid = _actor(enforced_store, _pid(), email=addr)
        recorded = get_actor(enforced_store).get_creator_holder(addr)
        _sweep(enforced_store)
        # A dry run changes nothing, the stale record included.
        assert get_actor(enforced_store).get_creator_holder(addr) == recorded
        counts = _sweep(enforced_store, apply=True)
        assert counts["moved"] == 1 and counts["held"] == 0
        assert _creator(enforced_store, aid) == addr
        assert get_actor(enforced_store).get_creator_holder(addr) == aid

    def test_a_held_email_is_cleared_only_for_a_vouched_holder(
        self, enforced_store: Any
    ) -> None:
        addr = _email()
        _actor(enforced_store, addr, auth="creator_changed")
        aid = _actor(enforced_store, _pid(), email=addr)
        counts = _sweep(enforced_store, apply=True, clear_held_email=True)
        assert counts["squatted"] == 1 and counts["cleared"] == 0
        assert _stored(enforced_store, aid, "email") == addr
        assert _marker(enforced_store) is not None

    def test_a_marker_that_cannot_be_written_exits_two(
        self, enforced_store: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            unique_creators, "make_config", lambda: _command(enforced_store)
        )
        _actor(enforced_store, _pid(), email=_email())
        with mock.patch.object(
            email_as_creator, "write_marker", side_effect=DbError("throttled")
        ):
            assert unique_creators.main(["creator-to-email", "--apply"]) == 2

    def test_without_enforcement_the_rename_still_moves_the_creator(
        self, fresh_store: Any
    ) -> None:
        cfg = _command(fresh_store)
        target = _email()
        aid = _actor(cfg, _pid(), email=target)
        assert _sweep(fresh_store, apply=True)["moved"] == 1
        assert _creator(cfg, aid) == target

    @pytest.mark.parametrize("limit", ["only", "start_after"])
    def test_a_partial_run_writes_no_marker(
        self, enforced_store: Any, limit: str
    ) -> None:
        aid = _actor(enforced_store, _pid(), email=_email())
        kw = (
            {"only": _creator(enforced_store, aid)}
            if limit == "only"
            else {"start_after": "0"}
        )
        assert _sweep(enforced_store, apply=True, **kw)["moved"] == 1
        assert _marker(enforced_store) is None
        assert _sweep(enforced_store, apply=True)["moved"] == 0
        assert _marker(enforced_store) is not None

    def test_a_fault_mid_run_writes_no_marker_and_a_rerun_does(
        self, enforced_store: Any
    ) -> None:
        a = _actor(enforced_store, _pid(), email=_email())
        _actor(enforced_store, _pid(), email=_email())
        cls = type(get_actor(enforced_store))
        real = cls.rename_creator

        def flaky(self: Any, actor_id: str, **k: Any) -> Any:
            if actor_id == a:
                raise DbError("throttled")
            return real(self, actor_id, **k)

        with mock.patch.object(cls, "rename_creator", flaky):
            counts = _sweep(enforced_store, apply=True)
        assert counts["errors"] == 1 and counts["moved"] == 1
        assert _marker(enforced_store) is None
        again = _sweep(enforced_store, apply=True)
        assert again["moved"] == 1 and again["errors"] == 0
        assert _marker(enforced_store) is not None

    def test_a_change_under_traffic_is_not_overridden(
        self, enforced_store: Any
    ) -> None:
        """A sign-in resets the email between the sweep's read and its
        commit, each time: the rename loses its condition twice, the creator
        stays, the actor counts as changed and the marker is withheld."""
        creator = _pid()
        aid = _actor(enforced_store, creator, email=_email())
        cls = type(get_actor(enforced_store))
        real = cls.rename_creator

        def reset_first(self: Any, actor_id: str, **k: Any) -> Any:
            get_attribute(enforced_store).set_attr(actor_id, IB, "email", _email())
            return real(self, actor_id, **k)

        with mock.patch.object(cls, "rename_creator", reset_first):
            counts = _sweep(enforced_store, apply=True)
        assert counts["changed"] == 1 and counts["moved"] == 0
        assert _creator(enforced_store, aid) == creator
        assert _marker(enforced_store) is None

    def test_a_sign_in_unvouching_mid_run_wins(self, enforced_store: Any) -> None:
        creator = _pid()
        aid = _actor(enforced_store, creator, email=_email())
        cls = type(get_actor(enforced_store))
        real = cls.rename_creator

        def unvouch(self: Any, actor_id: str, **k: Any) -> Any:
            get_attribute(enforced_store).set_attr(
                actor_id, IB, "auth_method", "creator_changed"
            )
            return real(self, actor_id, **k)

        with mock.patch.object(cls, "rename_creator", unvouch):
            counts = _sweep(enforced_store, apply=True)
        # The second read finds it unvouched, out of scope.
        assert counts["moved"] == 0 and counts["changed"] == 0
        assert _creator(enforced_store, aid) == creator

    def test_no_address_is_printed_unless_asked(
        self, enforced_store: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        target = _email()
        _actor(enforced_store, _pid(), email=target)
        caplog.set_level(logging.INFO, logger="unique_creators")
        _sweep(enforced_store)
        assert target not in caplog.text
        caplog.clear()
        _sweep(enforced_store, show_addresses=True)
        assert target in caplog.text

    def test_the_cli_runs_dry_then_apply_then_unmark(
        self, enforced_store: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            unique_creators, "make_config", lambda: _command(enforced_store)
        )
        _actor(enforced_store, _pid(), email=_email())
        assert unique_creators.main(["creator-to-email"]) == 1
        assert unique_creators.main(["creator-to-email", "--apply"]) == 0
        assert _marker(enforced_store) is not None
        assert unique_creators.main(["creator-to-email"]) == 0
        assert unique_creators.main(["creator-to-email", "--unmark"]) == 0
        assert _marker(enforced_store) is not None
        assert unique_creators.main(["creator-to-email", "--unmark", "--apply"]) == 0
        assert _marker(enforced_store) is None


def _forced(config: Any) -> Any:
    on = copy.copy(config)
    on.force_email_prop_as_creator = True
    return on


@pytest.mark.usefixtures("real_email_probe")
class TestTheStartupCheck:
    def _app(self, config: Any) -> Any:
        from actingweb.interface.app import ActingWebApp

        app = ActingWebApp(aw_type="urn:actingweb:test:email", fqdn="test.example.com")
        app.get_config = lambda: config  # type: ignore[method-assign]
        return app

    def test_a_store_with_actors_and_no_marker_is_refused(
        self, enforced_store: Any
    ) -> None:
        from actingweb.interface.app import EmailAsCreatorNotReady

        _actor(enforced_store, _email())
        with pytest.raises(EmailAsCreatorNotReady) as refused:
            self._app(_forced(enforced_store))._check_email_as_creator_ready()  # pyright: ignore[reportPrivateUsage]
        assert "creator-to-email" in str(refused.value)

    def test_an_empty_store_passes_and_writes_the_marker(
        self, enforced_store: Any
    ) -> None:
        get_attribute(enforced_store)
        self._app(_forced(enforced_store))._check_email_as_creator_ready()  # pyright: ignore[reportPrivateUsage]
        assert (_marker(enforced_store) or {}).get("state") == "synced"
        email_as_creator.reset_probe()
        # A second start (another process) finds it and writes nothing new.
        assert email_as_creator.settle(_forced(enforced_store)) is None

    def test_two_starts_at_once_write_one_marker(self, enforced_store: Any) -> None:
        import threading

        get_attribute(enforced_store)
        forced = _forced(enforced_store)
        barrier = threading.Barrier(2)
        answers: list[Any] = []

        def start() -> None:
            barrier.wait()
            answers.append(email_as_creator.settle(forced))

        threads = [threading.Thread(target=start) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert answers == [None, None]
        bucket = get_attribute(enforced_store).get_bucket(
            READINESS_STORE, READINESS_BUCKET
        )
        assert bucket and list(bucket) == ["email_as_creator"]

    def test_a_synced_marker_passes_with_one_read_then_none(
        self, enforced_store: Any
    ) -> None:
        _actor(enforced_store, _email())
        email_as_creator.write_marker(enforced_store)
        forced = _forced(enforced_store)
        assert email_as_creator.settle(forced) is None
        with mock.patch.object(
            email_as_creator, "read_marker", side_effect=AssertionError
        ):
            assert email_as_creator.settle(forced) is None

    def test_with_the_flag_off_nothing_is_read_or_written(
        self, enforced_store: Any
    ) -> None:
        _actor(enforced_store, _email())
        with (
            mock.patch.object(
                email_as_creator, "read_marker", side_effect=AssertionError
            ),
            mock.patch.object(
                email_as_creator, "write_marker", side_effect=AssertionError
            ),
        ):
            self._app(enforced_store)._check_email_as_creator_ready()  # pyright: ignore[reportPrivateUsage]
        assert _marker(enforced_store) is None

    def test_a_flag_off_start_leaves_a_synced_marker(self, enforced_store: Any) -> None:
        email_as_creator.write_marker(enforced_store)
        before = _marker(enforced_store)
        self._app(enforced_store)._check_email_as_creator_ready()  # pyright: ignore[reportPrivateUsage]
        assert _marker(enforced_store) == before

    def test_a_read_fault_refuses(self, enforced_store: Any) -> None:
        from actingweb.interface.app import EmailAsCreatorNotReady

        with mock.patch.object(
            email_as_creator, "read_marker", side_effect=DbError("throttled")
        ):
            with pytest.raises(EmailAsCreatorNotReady):
                self._app(_forced(enforced_store))._check_email_as_creator_ready()  # pyright: ignore[reportPrivateUsage]

    @pytest.mark.parametrize("flag", [True, False])
    def test_a_backend_without_rename_creator_is_refused(
        self, enforced_store: Any, flag: bool
    ) -> None:
        from actingweb.interface.app import EmailAsCreatorNotReady

        config = _forced(enforced_store) if flag else copy.copy(enforced_store)
        base = config.DbActor.DbActor
        lacking = type("Lacking", (base,), {"rename_creator": None})
        config.DbActor = SimpleNamespace(DbActor=lacking)
        with pytest.raises(EmailAsCreatorNotReady) as refused:
            self._app(config)._check_email_as_creator_ready()  # pyright: ignore[reportPrivateUsage]
        assert "rename_creator" in str(refused.value)

    def test_unmark_makes_the_next_start_refuse(self, enforced_store: Any) -> None:
        _actor(enforced_store, _email())
        email_as_creator.write_marker(enforced_store)
        forced = _forced(enforced_store)
        assert email_as_creator.settle(forced) is None
        email_as_creator.delete_marker(enforced_store)
        email_as_creator.reset_probe()
        assert email_as_creator.settle(forced) is not None

    def test_the_marker_lives_under_the_reserved_id(self, enforced_store: Any) -> None:
        email_as_creator.write_marker(enforced_store)
        bucket = get_attribute(enforced_store).get_bucket(
            READINESS_STORE, READINESS_BUCKET
        )
        assert bucket and "email_as_creator" in bucket
