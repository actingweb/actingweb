"""The creators record against the actor row, state by state (3.16, PR 2).

thoughts/research/2026-10-30-creator-record-invariant-audit.md lists the
states in which a DynamoDB ``creators`` record and the actor row disagree:
G1 (a rename's old record lingers), G2 (the swap: the squatter's row still
has the creator), G3 (a delete's record lingers) and G4 (two scans of
``report`` disagree). Each test seeds one state directly and checks what a
reader (the sign-in lookup, ``report``, ``enable``, ``resolve``) does with
it. ``unique_creator`` xdist group; an isolated store per module.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any
from unittest import mock

import pytest

from actingweb import oauth2 as oauth2_module
from actingweb.actor import Actor
from actingweb.db import get_actor
from actingweb.db.exceptions import CreatorTaken, DbError
from actingweb.interface.actor_interface import ActorInterface
from actingweb.maintenance import unique_creators
from actingweb.oauth2 import OAuth2Authenticator, OAuth2Provider

from .conftest import DATABASE_BACKEND

pytestmark = pytest.mark.xdist_group(name="unique_creator")

DYNAMODB = DATABASE_BACKEND == "dynamodb"
dynamodb_only = pytest.mark.skipif(
    not DYNAMODB, reason="the creators table is DynamoDB's"
)


def _email() -> str:
    return f"{uuid.uuid4().hex[:12]}@example.com"


def _id() -> str:
    return uuid.uuid4().hex


def _auth(config: Any) -> OAuth2Authenticator:
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
    return OAuth2Authenticator(config, provider)


def _actor(config: Any, creator: str, auth_method: str = "factory") -> Actor:
    actor = Actor(config=config)
    assert actor.create(
        url="https://test.example.com/",
        creator=creator,
        passphrase="pw",
        auth_method=auth_method,
    )
    return actor


def _holder(config: Any, creator: str) -> str | None:
    return get_actor(config).get_creator_holder(creator)


def _raw_row(actor_id: str, creator: str) -> None:
    from actingweb.db.dynamodb.actor import Actor as ActorModel

    ActorModel(id=actor_id, creator=creator, passphrase="pw").save()


def _raw_rename(actor_id: str, creator: str) -> None:
    from actingweb.db.dynamodb.actor import Actor as ActorModel

    row = ActorModel.get(actor_id, consistent_read=True)
    row.update(actions=[ActorModel.creator.set(creator)])


def _raw_record(creator: str, actor_id: str) -> None:
    from actingweb.db.dynamodb.creator import Creator

    Creator(creator=creator, actor_id=actor_id).save()


def _record(creator: str) -> str | None:
    from pynamodb.exceptions import DoesNotExist

    from actingweb.db.dynamodb.creator import Creator

    try:
        return Creator.get(creator, consistent_read=True).actor_id
    except DoesNotExist:
        return None


@dynamodb_only
class TestLookup:
    """R1: ``get_from_creator`` under the flag."""

    def test_a_true_record_loads_its_actor(self, enforced_store: Any) -> None:
        creator = _email()
        owner = _actor(enforced_store, creator)
        found = Actor(config=enforced_store)
        assert found.get_from_creator(creator) and found.id == owner.id

    def test_g3_a_record_whose_actor_is_gone_is_removed(
        self, enforced_store: Any
    ) -> None:
        creator = _email()
        _raw_record(creator, "gone-actor")
        assert not Actor(config=enforced_store).get_from_creator(creator)
        assert _record(creator) is None

    def test_g1_a_record_whose_actor_was_renamed_is_removed(
        self, enforced_store: Any
    ) -> None:
        old, new = _email(), _email()
        actor = _actor(enforced_store, old)
        assert actor.id
        _raw_rename(actor.id, new)
        assert not Actor(config=enforced_store).get_from_creator(old)
        assert _record(old) is None
        row = get_actor(enforced_store).get(actor_id=actor.id)
        assert row is not None and row["creator"] == new

    def test_g2_mid_swap_the_lookup_finds_the_successor(
        self, enforced_store: Any
    ) -> None:
        creator = _email()
        squatter = _actor(enforced_store, creator)
        successor = _id()
        assert squatter.id
        assert get_actor(enforced_store).create(
            actor_id=successor,
            creator=creator,
            passphrase="pw",
            replace_holder=squatter.id,
        )
        found = Actor(config=enforced_store)
        assert found.get_from_creator(creator) and found.id == successor

    def test_the_force_email_rewrite_does_not_run_inside_the_lookup(
        self, enforced_store: Any
    ) -> None:
        # G8: a provider-id creator whose stored email differs.
        creator = f"google:{_id()}"
        owner = _actor(enforced_store, creator, auth_method="google_oauth2")
        assert owner.store is not None and owner.id
        owner.store.email = _email()
        forced = enforced_store
        with mock.patch.object(forced, "force_email_prop_as_creator", True):
            found = Actor(config=forced)
            assert found.get_from_creator(creator)
        assert found.id == owner.id and found.creator == creator
        assert _holder(enforced_store, creator) == owner.id


@dynamodb_only
class TestReportAndResolveUnderLiveTraffic:
    """R3 and W8: G4, scan skew, is not damage."""

    def test_an_actor_created_between_the_two_scans_is_not_an_orphan(
        self, enforced_store: Any
    ) -> None:
        real = unique_creators._dynamodb_actor_rows
        late: list[str] = []

        def rows_then_a_sign_up(**kwargs: Any) -> Any:
            rows = list(real(**kwargs))
            # A flag-on sign-up after the actor scan, before the record scan.
            created = _actor(enforced_store, _email())
            late.append(created.id or "")
            return iter(rows)

        with mock.patch.object(
            unique_creators, "_dynamodb_actor_rows", rows_then_a_sign_up
        ):
            report = unique_creators.collect(enforced_store)
            assert not report.orphans
            counts = unique_creators.resolve(enforced_store, report, apply=True)
        assert counts["errors"] == 0
        row = get_actor(enforced_store).get(actor_id=late[0])
        assert row is not None
        assert _record(row["creator"]) == late[0]

    def test_a_stale_record_is_listed_and_repaired(self, enforced_store: Any) -> None:
        creator = _email()
        _raw_record(creator, "gone-actor")
        report = unique_creators.collect(enforced_store)
        assert (creator, "gone-actor", "missing") in report.orphans
        unique_creators.resolve(enforced_store, report, apply=True)
        assert _record(creator) is None


@dynamodb_only
class TestEnable:
    """R4: a record naming another actor that holds the creator too."""

    def test_g2_is_listed_and_the_run_goes_on_without_the_marker(
        self, fresh_store: Any
    ) -> None:
        from actingweb.db.dynamodb.creator import Creator

        # Sorted so the collision comes first: the run must go on past it.
        creator, other = f"a{_email()}", f"z{_email()}"
        squatter, successor, other_id = _id(), _id(), _id()
        _raw_row(squatter, creator)
        _raw_row(successor, creator)
        _raw_row(other_id, other)
        Creator.create_table(wait=True)
        _raw_record(creator, successor)
        report = unique_creators.Report(creators={squatter: creator, other_id: other})
        assert unique_creators.enable(fresh_store, report, apply=True) == "collision"
        assert _record(other) == other_id  # the run went on
        assert not unique_creators.backfill_complete()

    def test_creator_is_refused_for_enable_and_disable(self, fresh_store: Any) -> None:
        for command in ("enable", "disable"):
            with pytest.raises(SystemExit) as exc:
                unique_creators.main([command, "--apply", "--creator", _email()])
            assert exc.value.code == 2

    def test_disable_finishes_a_partial_run(self, fresh_store: Any) -> None:
        from actingweb.db.dynamodb.creator import Creator

        creator = _email()
        _actor(fresh_store, creator)
        assert unique_creators.main(["enable", "--apply"]) == 0
        Creator(creator="#meta#backfill").delete()  # a run that stopped here
        assert unique_creators.main(["disable", "--apply"]) == 0
        assert list(Creator.scan()) == []


@dynamodb_only
class TestWriters:
    def test_a8_a_case_only_rename_keeps_the_record_it_claimed(
        self, enforced_store: Any
    ) -> None:
        creator = _email()
        actor_id = _id()
        _raw_row(actor_id, creator.upper())
        _raw_record(creator, actor_id)
        db = get_actor(enforced_store)
        assert db.get(actor_id=actor_id)
        assert db.modify(creator=creator) is True
        assert _record(creator) == actor_id

    def test_a9_a_password_change_through_a_stale_handle_writes_nothing(
        self, enforced_store: Any
    ) -> None:
        # Rule 8: the whole-row save would write the old creator back over
        # the rename, leaving it without a record.
        old, new = _email(), _email()
        actor = _actor(enforced_store, old)
        assert actor.id
        stale = get_actor(enforced_store)
        assert stale.get(actor_id=actor.id)
        renamer = get_actor(enforced_store)
        assert renamer.get(actor_id=actor.id)
        assert renamer.modify(creator=new) is True
        assert stale.modify(passphrase=b"rotated") is False
        row = get_actor(enforced_store).get(actor_id=actor.id)
        assert row is not None and row["creator"] == new
        assert _record(new) == actor.id and _record(old) is None

    def test_a_stale_handles_rename_does_not_undo_a_rotation(
        self, fresh_store: Any
    ) -> None:
        import copy

        off = copy.copy(fresh_store)
        off.unique_creator = False
        actor_id = _id()
        _raw_row(actor_id, _email())
        stale = get_actor(off)
        assert stale.get(actor_id=actor_id)
        rotator = get_actor(off)
        assert rotator.get(actor_id=actor_id)
        assert rotator.modify(passphrase=b"rotated")
        assert stale.modify(creator=_email()) is False
        row = get_actor(off).get(actor_id=actor_id)
        assert row is not None and row["passphrase"] == "rotated"

    def test_a9_a_stale_handle_does_not_re_create_a_deleted_actor(
        self, enforced_store: Any
    ) -> None:
        actor = _actor(enforced_store, _email())
        assert actor.id
        stale = get_actor(enforced_store)
        assert stale.get(actor_id=actor.id)
        doomed = get_actor(enforced_store)
        assert doomed.get(actor_id=actor.id) and doomed.delete()
        assert stale.modify(passphrase=b"rotated") is False
        assert get_actor(enforced_store).get(actor_id=actor.id) is None


@dynamodb_only
class TestWritesCheckTheActorRow:
    """Rule 9: a record write that depends on the actor row commits only
    while the row is as read."""

    def test_e9_a_rename_back_between_the_read_and_the_delete_keeps_the_record(
        self, enforced_store: Any
    ) -> None:
        from actingweb.db.dynamodb import actor as dynamodb_actor

        creator = _email()
        actor_id = _id()
        _raw_row(actor_id, _email())  # renamed away: the record is stale
        _raw_record(creator, actor_id)
        stale = dynamodb_actor.Actor.get(actor_id, consistent_read=True)
        _raw_rename(actor_id, creator)  # back, after the helper's read
        with mock.patch.object(dynamodb_actor.Actor, "get", return_value=stale):
            assert dynamodb_actor.release_stale_record(creator, actor_id) is False
        assert _record(creator) == actor_id

    def test_f9_g9_a_rename_after_the_read_writes_no_record(
        self, enforced_store: Any
    ) -> None:
        from actingweb.db.dynamodb import actor as dynamodb_actor

        creator = _email()
        actor_id = _id()
        _raw_row(actor_id, creator)
        row = dynamodb_actor.Actor.get(actor_id, consistent_read=True)
        _raw_rename(actor_id, _email())
        assert dynamodb_actor.record_for_actor_as_read(creator, row) is False
        assert _record(creator) is None

    def test_d9_a_rename_between_the_check_and_the_load_is_not_loaded(
        self, enforced_store: Any
    ) -> None:
        creator = _email()
        owner = _actor(enforced_store, creator)
        assert owner.id
        real_get = Actor.get

        def renamed_first(self: Actor, actor_id: Any = None, **kwargs: Any) -> Any:
            _raw_rename(owner.id or "", _email())
            return real_get(self, actor_id, **kwargs)

        found = Actor(config=enforced_store)
        with mock.patch.object(Actor, "get", renamed_first):
            assert not found.get_from_creator(creator)
        assert found.id is None and found.store is None


@dynamodb_only
class TestResolveUnderSignIn:
    def test_b9_a_sign_in_during_the_renames_lands_on_the_kept_actor(
        self, enforced_store: Any
    ) -> None:
        # Amended rule 2: the record names the kept actor before any rename.
        creator = _email()
        loser, kept = _id(), _id()
        _raw_row(loser, creator)
        _raw_record(creator, loser)
        _raw_row(kept, creator)  # an old process, no record
        real_rename = unique_creators._rename
        signed_in: list[str | None] = []

        def rename_then_sign_in(config: Any, actor_id: str, target: str) -> bool:
            done = real_rename(config, actor_id, target)
            found = Actor(config=enforced_store)
            signed_in.append(found.id if found.get_from_creator(creator) else None)
            return done

        with mock.patch.object(unique_creators, "_rename", rename_then_sign_in):
            assert unique_creators.main(["resolve", "--apply", "--keep", kept]) == 0
        assert signed_in == [kept]
        assert _record(creator) == kept


class TestRetryAdoptsOnlyAMarkedWinner:
    def test_c9_an_unmarked_winner_is_not_cleaned(self, enforced_store: Any) -> None:
        # Rule 10: the winner's marker is written after its row and record.
        creator = _email()
        winners: list[Actor] = []

        def other_tab_mid_create(*args: Any, **kwargs: Any) -> Any:
            winner = Actor(config=enforced_store)
            assert winner.create(
                url="https://test.example.com/",
                creator=creator,
                passphrase="pw",
                auth_method="",  # its marker not written yet
            )
            assert winner.property is not None
            winner.property["kept"] = "yes"
            winners.append(winner)
            raise CreatorTaken(creator)

        with mock.patch.object(
            oauth2_module, "_create_actor_for_identifier", other_tab_mid_create
        ):
            with pytest.raises(CreatorTaken):
                _auth(enforced_store).lookup_or_create_actor_by_identifier(creator)
        winner = Actor(config=enforced_store)
        assert winner.get(actor_id=winners[0].id) and winner.property is not None
        assert winner.property["kept"] == "yes"
        assert winner.passphrase == "pw"


class TestMarkerBeforeRow:
    """Invariant M, widened (entry 66): an actor a sign-in can find carries
    its marker, so the first lookup never takes a brand-new actor for a
    legacy one."""

    def test_a10_the_row_is_never_visible_without_its_marker(
        self, enforced_store: Any
    ) -> None:
        from actingweb.attribute import InternalStore

        backend = type(get_actor(enforced_store))
        real_create = backend.create
        seen: list[Any] = []

        def create_then_look(self: Any, *args: Any, **kwargs: Any) -> Any:
            done = real_create(self, *args, **kwargs)
            store = InternalStore(actor_id=kwargs["actor_id"], config=enforced_store)
            seen.append(store.auth_method)
            return done

        with mock.patch.object(backend, "create", create_then_look):
            _actor(enforced_store, _email(), auth_method="google_oauth2")
        assert seen == ["google_oauth2"]

    def test_a10_a_refused_create_leaves_no_marker(self, enforced_store: Any) -> None:
        from actingweb.attribute import InternalStore

        creator = _email()
        _actor(enforced_store, creator)
        fixed = _id()
        with mock.patch.object(enforced_store, "new_uuid", return_value=fixed):
            with pytest.raises(CreatorTaken):
                _actor(enforced_store, creator)
        assert InternalStore(actor_id=fixed, config=enforced_store).auth_method is None

    def test_a11_creates_in_the_same_microsecond_get_their_own_ids(
        self, enforced_store: Any
    ) -> None:
        import datetime as real_datetime

        from actingweb import actor as actor_module

        frozen = mock.Mock(wraps=real_datetime)
        frozen.UTC = real_datetime.UTC
        frozen.datetime.now.return_value = real_datetime.datetime(
            2026, 10, 30, tzinfo=real_datetime.UTC
        )
        with mock.patch.object(actor_module, "datetime", frozen):
            first = _actor(enforced_store, _email(), auth_method="google_oauth2")
            second = _actor(enforced_store, _email(), auth_method="factory")
        assert first.id and second.id and first.id != second.id
        assert first.store is not None and second.store is not None
        mine = Actor(config=enforced_store)
        assert mine.get(actor_id=first.id) and mine.store is not None
        assert mine.store.auth_method == "google_oauth2"

    def test_b11_a_create_that_committed_before_its_fault_keeps_its_marker(
        self, enforced_store: Any
    ) -> None:
        from actingweb.attribute import InternalStore

        backend = type(get_actor(enforced_store))
        real_create = backend.create
        made: list[str] = []

        def commit_then_fault(self: Any, *args: Any, **kwargs: Any) -> Any:
            real_create(self, *args, **kwargs)
            made.append(kwargs["actor_id"])
            raise DbError("the answer was lost")

        with mock.patch.object(backend, "create", commit_then_fault):
            with pytest.raises(DbError):
                _actor(enforced_store, _email(), auth_method="google_oauth2")
        store = InternalStore(actor_id=made[0], config=enforced_store)
        assert store.auth_method == "google_oauth2"

    def test_e10_an_unreadable_marker_is_a_fault_not_a_conflict(self) -> None:
        winner = mock.Mock()
        winner.store.auth_method = None
        winner.store.loaded = False
        with pytest.raises(DbError):
            oauth2_module._winner_is_marked(winner)


@dynamodb_only
class TestResolveOutsideRecords:
    def test_b10_a_stale_record_naming_another_actor_moves_to_the_kept_one(
        self, enforced_store: Any
    ) -> None:
        creator = _email()
        loser, kept, elsewhere = _id(), _id(), _id()
        _raw_row(loser, creator)
        _raw_row(kept, creator)
        _raw_row(elsewhere, _email())  # renamed away: its record is stale
        _raw_record(creator, elsewhere)
        assert unique_creators.main(["resolve", "--apply", "--keep", kept]) == 0
        assert _record(creator) == kept

    def test_c11_the_outside_record_is_never_absent_during_the_move(
        self, enforced_store: Any
    ) -> None:
        from actingweb.db.dynamodb.actor import DbActor

        creator = _email()
        loser, kept, elsewhere = _id(), _id(), _id()
        _raw_row(loser, creator)
        _raw_row(kept, creator)
        _raw_row(elsewhere, _email())
        _raw_record(creator, elsewhere)
        real = DbActor._run_transaction.__func__  # type: ignore[attr-defined]
        seen: list[str | None] = []

        def observed(cls: Any, build: Any, *, op: str) -> Any:
            seen.append(_record(creator))
            return real(cls, build, op=op)

        with mock.patch.object(DbActor, "_run_transaction", classmethod(observed)):
            assert unique_creators.main(["resolve", "--apply", "--keep", kept]) == 0
        assert seen and None not in seen
        assert _record(creator) == kept

    def test_d11_a_holder_the_index_has_not_caught_up_with_is_recorded(
        self, enforced_store: Any
    ) -> None:
        from actingweb.db.dynamodb.actor import DbActor as Backend

        creator = _email()
        holder = _id()
        _raw_row(holder, creator.upper())  # lowercased by this run
        _raw_record(creator, "gone-actor")
        with mock.patch.object(Backend, "get_by_creator", return_value=[]):
            assert unique_creators.main(["resolve", "--apply"]) == 0
        assert _record(creator) == holder

    def test_b12_a_failed_holder_write_is_reported_as_such(
        self, enforced_store: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        creator = _email()
        _raw_record(creator, "gone-actor")
        with mock.patch.object(
            unique_creators, "_record_lone_holder", side_effect=DbError("throttled")
        ):
            with caplog.at_level(logging.ERROR):
                assert unique_creators.main(["resolve", "--apply"]) == 1
        assert _record(creator) is None
        assert "its holder's record could not be written" in caplog.text
        assert "could not be removed" not in caplog.text

    def test_b10_an_orphan_repair_records_the_lone_holder(
        self, enforced_store: Any
    ) -> None:
        creator = _email()
        holder = _id()
        _raw_row(holder, creator)  # an old process: no record
        _raw_record(creator, "gone-actor")
        assert unique_creators.main(["resolve", "--apply"]) == 0
        assert _record(creator) == holder


@dynamodb_only
class TestCreatorValues:
    """The missing creator in the conditions (D10). The empty one (C10)
    cannot be stored: it is the creator index's key."""

    def test_d10_an_actor_without_a_creator_can_be_renamed_and_deleted(
        self, enforced_store: Any
    ) -> None:
        from actingweb.db.dynamodb.actor import Actor as ActorModel

        actor_id, new = _id(), _email()
        _raw_row(actor_id, "x")
        ActorModel.get(actor_id, consistent_read=True).update(
            actions=[ActorModel.creator.remove()]
        )
        db = get_actor(enforced_store)
        assert db.get(actor_id=actor_id)
        assert db.modify(creator=new) is True
        assert _record(new) == actor_id
        doomed = get_actor(enforced_store)
        assert doomed.get(actor_id=actor_id)
        ActorModel.get(actor_id, consistent_read=True).update(
            actions=[ActorModel.creator.remove()]
        )
        doomed_handle = get_actor(enforced_store)
        assert doomed_handle.get(actor_id=actor_id) and doomed_handle.delete()
        assert get_actor(enforced_store).get(actor_id=actor_id) is None


class TestVouchBoundToItsAddress:
    """The clean-in-place race (round 7): a rename landing while a sign-in
    cleans the actor must not leave it vouched under the new address."""

    def test_a_rename_during_the_clean_leaves_the_new_address_unvouched(
        self, enforced_store: Any
    ) -> None:
        from actingweb.attribute import InternalStore

        proven, other = _email(), _email()
        squatter = _actor(enforced_store, proven, auth_method="creator_changed")
        assert squatter.id
        real = InternalStore.set_confirmed
        renamed: list[bool] = []

        def rename_before_the_vouch(self: Any, name: str, value: Any, **kw: Any) -> Any:
            if name == "auth_method" and value == "google_oauth2" and not renamed:
                renamed.append(True)
                mover = Actor(actor_id=squatter.id, config=enforced_store)
                assert mover.modify(creator=other)
            return real(self, name, value, **kw)

        with mock.patch.object(InternalStore, "set_confirmed", rename_before_the_vouch):
            _auth(enforced_store).lookup_or_create_actor_by_identifier(proven)
        assert renamed
        after = Actor(actor_id=squatter.id, config=enforced_store)
        assert after.creator == other
        assert not oauth2_module.is_vouched_actor(after)
        assert oauth2_module.classify_marker(enforced_store, squatter.id, other) != (
            "vouched"
        )


class TestSwapRaces:
    def test_f8_a_concurrent_swap_ends_on_the_winners_successor(
        self, enforced_store: Any
    ) -> None:
        creator = _email()
        squatter = _actor(enforced_store, creator)
        real = oauth2_module._create_actor_for_identifier
        winners: list[str] = []

        def other_tab_swaps_first(*args: Any, **kwargs: Any) -> Any:
            if kwargs.get("replace_holder") and not winners:
                with mock.patch.object(
                    oauth2_module, "_create_actor_for_identifier", real
                ):
                    first = _auth(enforced_store).lookup_or_create_actor_by_identifier(
                        creator
                    )
                assert first is not None and first.id
                winners.append(first.id)
            return real(*args, **kwargs)

        real_remove = oauth2_module._remove_for_replacement
        removals: list[str] = []

        def counted_remove(existing: Any, **kwargs: Any) -> Any:
            removals.append(existing.id or "")
            return real_remove(existing, **kwargs)

        with (
            mock.patch.object(
                oauth2_module, "_create_actor_for_identifier", other_tab_swaps_first
            ),
            mock.patch.object(oauth2_module, "_remove_for_replacement", counted_remove),
        ):
            result = _auth(enforced_store).lookup_or_create_actor_by_identifier(creator)

        # Only the tab whose swap won removes the squatter.
        assert removals == [squatter.id]
        assert result is not None and result.id == winners[0]
        assert _holder(enforced_store, creator) == winners[0]
        assert get_actor(enforced_store).get(actor_id=squatter.id or "") is None

    def test_h8_an_unreadable_holder_after_a_failed_create_leaves_the_squatter(
        self, enforced_store: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        from actingweb.attribute import InternalStore

        creator = _email()
        squatter = _actor(enforced_store, creator)
        assert squatter.id
        real_set = InternalStore.set_confirmed
        db_class = type(get_actor(enforced_store))
        real_holder = db_class.get_creator_holder
        calls: list[int] = []

        def marker_faults(self: Any, name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "auth_method" and self._db.actor_id != squatter.id:
                raise DbError("throttled")
            return real_set(self, name, *args, **kwargs)

        def holder_faults_second(self: Any, *args: Any, **kwargs: Any) -> Any:
            calls.append(1)
            if len(calls) > 1:
                raise DbError("throttled")
            return real_holder(self, *args, **kwargs)

        with (
            mock.patch.object(InternalStore, "set_confirmed", marker_faults),
            mock.patch.object(db_class, "get_creator_holder", holder_faults_second),
            caplog.at_level(logging.ERROR),
        ):
            with pytest.raises(DbError):
                _auth(enforced_store).lookup_or_create_actor_by_identifier(creator)
        assert "the squatter may still be live" in caplog.text
        assert get_actor(enforced_store).get(actor_id=squatter.id) is not None


class TestReservedThroughTheSdk:
    """I8: ``ActorInterface.modify_creator`` refuses reserved values."""

    @pytest.mark.parametrize("unvouch", [False, True])
    def test_dup_values_are_refused(self, enforced_store: Any, unvouch: bool) -> None:
        creator = _email()
        actor = _actor(enforced_store, creator, auth_method="google_oauth2")
        assert actor.id
        iface = ActorInterface(actor)
        assert not iface.modify_creator(f"{creator}#DUP-1A2B3C4D", unvouch=unvouch)
        row = get_actor(enforced_store).get(actor_id=actor.id)
        assert row is not None and row["creator"] == creator

    def test_system_is_refused_for_user_input(self, enforced_store: Any) -> None:
        actor = _actor(enforced_store, _email(), auth_method="google_oauth2")
        assert not ActorInterface(actor).modify_creator("system", unvouch=True)


class TestStaleHandleRename:
    """Both backends: a rename from a handle loaded before another rename
    answers False and leaves the other rename in place."""

    def test_a_stale_handle_rename_answers_false(self, enforced_store: Any) -> None:
        old, first, second = _email(), _email(), _email()
        actor_id = _id()
        assert get_actor(enforced_store).create(
            actor_id=actor_id, creator=old, passphrase="pw"
        )
        stale = get_actor(enforced_store)
        assert stale.get(actor_id=actor_id)
        fresh = get_actor(enforced_store)
        assert fresh.get(actor_id=actor_id)
        assert fresh.modify(creator=first) is True
        assert stale.modify(creator=second) is False
        row = get_actor(enforced_store).get(actor_id=actor_id)
        assert row is not None and row["creator"] == first
