"""``actingweb-deletions``: report, resume and clear unfinished deletions.

Plan: thoughts/plans/2026-11-02-3-16-adoption-fault-followups.md, Phase 1.
"""

from __future__ import annotations

import datetime
from typing import Any
from unittest.mock import patch

import pytest

from actingweb import deletion
from actingweb.actor import Actor
from actingweb.db import get_attribute
from actingweb.db.exceptions import DbError
from actingweb.maintenance import deletions as command
from tests._adoption_helpers import aid, create_core_actor, make_config, uuid_email

_PAST = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1)


@pytest.fixture
def config() -> Any:
    return make_config()


@pytest.fixture(autouse=True)
def _same_backend(config: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    # The command builds its own Config from the environment, as an operator
    # would run it; point it at the suite's backend and keep the suite's
    # uniqueness setting through --no-unique-creator.
    monkeypatch.setenv("DATABASE_BACKEND", config.database)


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    code = command.main([*argv[:1], *argv[1:], "--no-unique-creator"])
    return code, capsys.readouterr().out


def _stalled(config: Any, *, leased: bool = False) -> str:
    actor_id = aid(create_core_actor(config, uuid_email()))
    deletion.create_leased_tombstone(
        actor_id,
        config,
        reason="deleted",
        notify_peers=True,
        hook_kwargs={},
        client_ids=[],
        now=None if leased else _PAST,
    )
    return actor_id


class TestReport:
    def test_classifies_one_actor(self, config: Any, capsys: Any) -> None:
        stalled = _stalled(config)
        code, out = _run(capsys, "report", stalled)
        assert code == 1 and f"{stalled}\tstalled" in out

    def test_an_in_progress_one_is_not_an_error(self, config: Any, capsys: Any) -> None:
        leased = _stalled(config, leased=True)
        code, out = _run(capsys, "report", leased)
        assert code == 0 and "in progress" in out

    def test_a_legacy_tombstone_needs_review(self, config: Any, capsys: Any) -> None:
        actor_id = aid(create_core_actor(config, uuid_email()))
        deletion.mark_actor_deleted(actor_id, config)
        try:
            code, out = _run(capsys, "report", actor_id)
            assert code == 1 and "legacy, review" in out
        finally:
            deletion.clear_actor_tombstone(actor_id, config)

    def test_a_finished_wipe_is_not_listed(self, config: Any, capsys: Any) -> None:
        from actingweb.deletion_finish import finish_deletion

        victim = create_core_actor(config, uuid_email())
        finish_deletion(victim, config=config, hooks=None, origin="delete")
        code, out = _run(capsys, "report", aid(victim))
        assert code == 0 and "No unfinished deletions" in out

    def test_an_unreadable_store_exits_2(self, config: Any, capsys: Any) -> None:
        with patch.object(
            type(get_attribute(config)), "get_bucket", side_effect=DbError("x")
        ):
            code = command.main(["report", "--no-unique-creator"])
        assert code == 2


class TestResume:
    def test_a_dry_run_changes_nothing(self, config: Any, capsys: Any) -> None:
        stalled = _stalled(config)
        code, out = _run(capsys, "resume", stalled)
        assert code == 1 and f"would finish {stalled}" in out
        assert Actor(actor_id=stalled, config=config).id == stalled

    def test_apply_finishes_and_prints_the_ids(self, config: Any, capsys: Any) -> None:
        stalled = _stalled(config)
        code, out = _run(capsys, "resume", stalled, "--apply")
        assert code == 0, out
        assert f"{stalled}: finished" in out and "actor_deleted_complete" in out
        assert Actor(actor_id=stalled, config=config).id is None

    def test_a_legacy_one_is_resumed_only_when_named(
        self, config: Any, capsys: Any
    ) -> None:
        actor_id = aid(create_core_actor(config, uuid_email()))
        deletion.mark_actor_deleted(actor_id, config)
        try:
            with patch.object(command, "scan", wraps=command.scan) as scanned:
                command.main(["resume", "--apply", "--no-unique-creator"])
            assert scanned.called
            assert Actor(actor_id=actor_id, config=config).id == actor_id
            code, _out = _run(capsys, "resume", actor_id, "--apply")
            assert code == 0
            assert Actor(actor_id=actor_id, config=config).id is None
        finally:
            deletion.clear_actor_tombstone(actor_id, config)


class TestClear:
    def test_dry_run_then_apply(self, config: Any, capsys: Any) -> None:
        actor_id = aid(create_core_actor(config, uuid_email()))
        deletion.mark_actor_deleted(actor_id, config)
        code, out = _run(capsys, "clear", actor_id)
        assert code == 1 and "would clear" in out
        code, out = _run(capsys, "clear", actor_id, "--apply")
        assert code == 0 and "cleared" in out
        assert deletion.get_deletion_status(actor_id, config) == (
            deletion.DeletionStatus.NOT_DELETED
        )
        assert Actor(actor_id=actor_id, config=config).id == actor_id

    def test_clear_sees_a_finished_tombstone_on_a_live_actor(
        self, config: Any, capsys: Any
    ) -> None:
        actor_id = aid(create_core_actor(config, uuid_email()))
        deletion.mark_actor_deleted(actor_id, config, reason="deleted", hook_fired=True)
        deletion.mark_finished(actor_id, config, None)
        code, out = _run(capsys, "clear", actor_id, "--apply")
        assert code == 0 and "cleared" in out


class TestProgrammaticDelete:
    def test_a_programmatic_delete_leaves_a_finished_tombstone(
        self, config: Any, capsys: Any
    ) -> None:
        """Verification 2026-11-03, issue 5: Actor.delete() wrote a resumable
        tombstone that only the finisher ever marked finished, so it stayed
        for ever (no TTL) and report listed it as unfinished."""
        actor = create_core_actor(config, uuid_email())
        actor_id = aid(actor)
        assert actor.delete() is True
        _, data = deletion.read_tombstone(actor_id, config)
        assert data is not None and data.get("finished_at")
        code, out = _run(capsys, "report", actor_id)
        assert code == 0 and actor_id not in out

    def test_a_tombstone_under_a_live_lease_is_left_to_its_finisher(
        self, config: Any
    ) -> None:
        actor_id = _stalled(config, leased=True)
        Actor(actor_id=actor_id, config=config).delete()
        _, data = deletion.read_tombstone(actor_id, config)
        assert data is not None and not data.get("finished_at")


class TestCommandRobustness:
    def test_resume_does_not_print_finished_when_the_mark_fails(
        self, config: Any, capsys: Any
    ) -> None:
        """Verification 2026-11-03, issue 11: mark_finished folds a fault, and
        resume printed "finished" for a tombstone the next report lists."""
        stalled = _stalled(config)
        with patch.object(deletion, "mark_finished", return_value=True):
            code, out = _run(capsys, "resume", stalled, "--apply")
        assert code == 1
        assert f"{stalled}: failed" in out and f"{stalled}: finished" not in out

    def test_report_skips_an_expired_tombstone(self, config: Any, capsys: Any) -> None:
        actor_id = aid(create_core_actor(config, uuid_email()))
        deletion.mark_actor_deleted(actor_id, config)  # legacy, with a TTL
        with patch.object(deletion, "read_tombstone", return_value=(None, None)):
            _code, out = _run(capsys, "report")
        assert actor_id not in out


class TestALiveLeaseIsInProgress:
    """Re-verification N5 and N12: a wipe whose row is gone but whose
    finisher has not yet marked it finished belongs to that finisher."""

    def test_mark_finished_without_a_lease_leaves_a_leased_tombstone(
        self, config: Any
    ) -> None:
        actor_id = _stalled(config, leased=True)
        assert deletion.mark_finished(actor_id, config, None) is False
        _, data = deletion.read_tombstone(actor_id, config)
        assert data is not None and not data.get("finished_at")
        assert data.get("lease_id")  # the finisher's lease is untouched

    def test_report_lists_a_row_gone_under_a_lease_as_in_progress(
        self, config: Any, capsys: Any
    ) -> None:
        from actingweb.db import get_actor

        actor_id = _stalled(config, leased=True)
        # The finisher has removed the actor row and not yet marked the end.
        with patch.object(type(get_actor(config)), "get", return_value=None):
            code, out = _run(capsys, "report", actor_id)
        assert f"{actor_id}\tin progress" in out and code == 0

    def test_resume_reports_a_lease_taken_meanwhile_as_in_progress(
        self, config: Any, capsys: Any
    ) -> None:
        """The row is gone and the lease lapsed (unfinished); while the
        command marks the end, a finisher takes the lease and finishes it."""
        from actingweb.db import get_actor

        unfinished = _stalled(config)

        def another_finisher_took_it(actor_id: str, config: Any, data: Any) -> bool:
            _, current = deletion.read_tombstone(actor_id, config)
            assert current is not None
            deletion.update_tombstone(
                actor_id, config, current, {**deletion.lease_fields(), "lease_id": "x"}
            )
            return False

        with (
            patch.object(type(get_actor(config)), "get", return_value=None),
            patch.object(deletion, "mark_finished", another_finisher_took_it),
        ):
            _code, out = _run(capsys, "resume", unfinished, "--apply")
        assert f"{unfinished}: in progress" in out
        assert f"{unfinished}: failed" not in out

    def test_a_finish_whose_lease_was_taken_over_is_in_progress(
        self, config: Any, capsys: Any
    ) -> None:
        """Re-verification 3, V8: the command's own finisher wipes a stalled
        actor, its lease lapses meanwhile and another finisher takes it, so
        the command's mark is refused. In progress, not failed."""
        stalled = _stalled(config)

        def another_finisher_took_it(actor_id: str, config: Any, data: Any) -> bool:
            _, current = deletion.read_tombstone(actor_id, config)
            assert current is not None
            deletion.update_tombstone(
                actor_id, config, current, {**deletion.lease_fields(), "lease_id": "x"}
            )
            return False

        with patch.object(deletion, "mark_finished", another_finisher_took_it):
            _code, out = _run(capsys, "resume", stalled, "--apply")
        assert f"{stalled}: in progress" in out
        assert f"{stalled}: failed" not in out

    def test_a_finish_whose_own_mark_faulted_is_a_failure(
        self, config: Any, capsys: Any
    ) -> None:
        """V8, the other side: the live lease is the command's own (its mark
        folded a fault), so the run reports a failure, not in progress."""
        stalled = _stalled(config)
        with patch.object(deletion, "mark_finished", return_value=True):
            code, out = _run(capsys, "resume", stalled, "--apply")
        assert f"{stalled}: failed" in out and code != 0
