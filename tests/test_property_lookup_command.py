"""``actingweb-property-lookup``: report, backfill, mark-complete, unmark.

Runs against whichever backend ``DATABASE_BACKEND`` selects, with unique
indexed-property names per test so the shared tables are left as found.
"""

from __future__ import annotations

import importlib
import os
import tempfile
import uuid
from collections.abc import Iterator
from typing import Any
from unittest import mock

import pytest

from actingweb.maintenance import property_lookup as command

# The recorded name set is one shared row per store: these tests write it, so
# they run in one xdist group (parallel workers share the unit-test store).
pytestmark = pytest.mark.xdist_group(name="property_lookup_markers")

BACKEND = os.getenv("DATABASE_BACKEND", "dynamodb")


def _lookup_module() -> Any:
    return importlib.import_module(f"actingweb.db.{BACKEND}.property_lookup")


class Store:
    """Seed and clean property rows, backend-neutral."""

    def __init__(self) -> None:
        self.rows: list[tuple[str, str]] = []
        self.actors: list[str] = []
        self.lookup_values: list[tuple[str, str]] = []
        self.names: list[str] = []

    def name(self) -> str:
        name = f"cmd{uuid.uuid4().hex[:10]}"
        self.names.append(name)
        return name

    def actor(self) -> str:
        actor_id = f"cmd-{uuid.uuid4()}"
        if BACKEND == "postgresql":
            from actingweb.db.postgresql.actor import DbActor

            DbActor().create(
                actor_id=actor_id, creator=f"{actor_id}@x.test", passphrase=""
            )
        else:
            from actingweb.db.dynamodb.actor import Actor

            Actor(id=actor_id, creator=f"{actor_id}@x.test", passphrase="").save()
        self.actors.append(actor_id)
        return actor_id

    def seed(self, actor_id: str, name: str, value: str) -> None:
        """A property row with no lookup row, as pre-3.16 data looks."""
        if BACKEND == "postgresql":
            from actingweb.db.postgresql.connection import get_connection

            with get_connection() as conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO properties (id, name, value) VALUES (%s, %s, %s)",
                    (actor_id, name, value),
                )
                conn.commit()
        else:
            from actingweb.db.dynamodb.property import Property

            Property(id=actor_id, name=name, value=value).save()
        self.rows.append((actor_id, name))
        self.lookup_values.append((name, value))

    def cleanup(self) -> None:
        lookup = _lookup_module()
        if BACKEND == "postgresql":
            from actingweb.db.postgresql.connection import get_connection

            with get_connection() as conn, conn.cursor() as cur:
                for actor_id, name in self.rows:
                    cur.execute(
                        "DELETE FROM properties WHERE id = %s AND name = %s",
                        (actor_id, name),
                    )
                for name in self.names:
                    cur.execute(
                        "DELETE FROM property_lookup WHERE property_name = %s", (name,)
                    )
                for actor_id in self.actors:
                    cur.execute("DELETE FROM actors WHERE id = %s", (actor_id,))
                conn.commit()
        else:
            from actingweb.db.dynamodb.actor import Actor
            from actingweb.db.dynamodb.property import Property

            for actor_id, name in self.rows:
                try:
                    Property.get(actor_id, name).delete()
                except Exception:  # noqa: BLE001
                    pass

            for actor_id in self.actors:
                try:
                    Actor.get(actor_id).delete()
                except Exception:  # noqa: BLE001
                    pass
            for actor_id in self.actors:
                try:
                    Actor.get(actor_id).delete()
                except Exception:  # noqa: BLE001
                    pass
            for name, value in self.lookup_values:
                lookup.DbPropertyLookup().delete(name, value)
        lookup.unmark(self.names)


@pytest.fixture
def store() -> Iterator[Store]:
    if BACKEND == "dynamodb":
        from actingweb.db.dynamodb.property_lookup import DbPropertyLookup

        DbPropertyLookup()  # ensure the v2 table
    s = Store()
    saved = _lookup_module().read_readiness([])[1]
    yield s
    s.cleanup()
    lookup = _lookup_module()
    now = lookup.read_readiness([])[1]
    if saved is None and now is not None:
        # The command recorded a set in a store that had none; drop it.
        _drop_recorded_set()
    elif saved is not None and now != saved:
        lookup.record_configured(sorted(saved))


def _drop_recorded_set() -> None:
    if BACKEND == "postgresql":
        from actingweb.db.postgresql.connection import get_connection

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM property_lookup_backfill WHERE kind = 'configured'"
            )
            conn.commit()
    else:
        from actingweb.db.dynamodb.property_lookup import (
            LOOKUP_CONFIGURED_KEY,
            PropertyLookupV2,
        )

        try:
            PropertyLookupV2.get(LOOKUP_CONFIGURED_KEY).delete()
        except Exception:  # noqa: BLE001
            pass


def _run(*argv: str) -> int:
    args = list(argv)
    if args[0] == "backfill" and "--checkpoint-file" not in args:
        # The default checkpoint file is relative to the working directory,
        # which parallel test workers share.
        args += ["--checkpoint-file", os.path.join(tempfile.mkdtemp(), "ckpt.json")]
    return command.main(args)


def _marked(name: str) -> bool:
    return name in _lookup_module().read_readiness([name])[0]


def _lookup(name: str, value: str) -> str | None:
    return _lookup_module().DbPropertyLookup().get(name, value)


class TestReport:
    def test_unmarked_name_with_data_exits_one_and_is_listed(
        self,
        store: Store,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        name = store.name()
        monkeypatch.setenv("INDEXED_PROPERTIES", name)
        store.seed(store.actor(), name, f"v-{uuid.uuid4()}")
        assert _run("report", "--properties", name) == 1
        out = capsys.readouterr().out
        assert name in out and "UNMARKED" in out
        assert "backfill --apply" in out

    def test_a_subset_never_reads_as_a_pass(
        self,
        store: Store,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """--properties narrows the printout, not the verdict."""
        marked, other = store.name(), store.name()
        monkeypatch.setenv("INDEXED_PROPERTIES", f"{marked},{other}")
        store.seed(store.actor(), other, f"v-{uuid.uuid4()}")
        _lookup_module().mark_backfilled([marked])
        _lookup_module().record_configured([marked, other])
        assert _run("report", "--properties", marked) == 1
        assert other in capsys.readouterr().out

    def test_counts_exclude_the_meta_rows(self, store: Store) -> None:
        name = store.name()
        actor = store.actor()
        value = f"v-{uuid.uuid4()}"
        store.seed(actor, name, value)
        _lookup_module().mark_backfilled([name])  # writes a #meta row on DynamoDB
        counts = command.count_rows(BACKEND, [name])
        assert counts[name].properties == 1
        assert counts[name].lookups == 0  # the marker is not a lookup row

    def test_a_marked_name_exits_zero(
        self, store: Store, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        name = store.name()
        monkeypatch.setenv("INDEXED_PROPERTIES", name)
        store.seed(store.actor(), name, f"v-{uuid.uuid4()}")
        assert _run("backfill", "--apply", "--properties", name, "--segments", "2") == 0
        assert _run("report", "--properties", name) == 0

    def test_a_name_absent_from_the_recorded_set_is_flagged(
        self,
        store: Store,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        name = store.name()
        monkeypatch.setenv("INDEXED_PROPERTIES", name)
        store.seed(store.actor(), name, f"v-{uuid.uuid4()}")
        lookup = _lookup_module()
        lookup.mark_backfilled([name])
        lookup.record_configured(["somethingelse"])
        assert _run("report", "--properties", name) == 1
        assert "absent from the recorded set" in capsys.readouterr().out


class TestBackfill:
    def test_dry_run_writes_neither_rows_nor_markers(self, store: Store) -> None:
        name = store.name()
        value = f"v-{uuid.uuid4()}"
        store.seed(store.actor(), name, value)
        assert _run("backfill", "--properties", name, "--segments", "2") == 0
        assert _lookup(name, value) is None
        assert not _marked(name)

    def test_apply_writes_rows_then_the_marker_then_the_set(self, store: Store) -> None:
        name = store.name()
        actor = store.actor()
        value = f"v-{uuid.uuid4()}"
        store.seed(actor, name, value)
        assert _run("backfill", "--apply", "--properties", name, "--segments", "2") == 0
        assert _lookup(name, value) == actor
        marked, recorded = _lookup_module().read_readiness([name])
        assert name in marked
        assert recorded is not None and name in recorded

    def test_a_second_run_is_idempotent(self, store: Store) -> None:
        name = store.name()
        actor = store.actor()
        value = f"v-{uuid.uuid4()}"
        store.seed(actor, name, value)
        args = ("backfill", "--apply", "--properties", name, "--segments", "2")
        assert _run(*args) == 0
        assert _run(*args) == 0
        assert _lookup(name, value) == actor

    def test_a_collision_leaves_that_name_unmarked_and_marks_the_others(
        self, store: Store
    ) -> None:
        clash, fine = store.name(), store.name()
        shared = f"shared-{uuid.uuid4()}"
        first, second = store.actor(), store.actor()
        store.seed(first, clash, shared)
        store.seed(second, clash, shared)
        store.seed(first, fine, f"v-{uuid.uuid4()}")
        rc = _run(
            "backfill",
            "--apply",
            "--properties",
            f"{clash},{fine}",
            "--segments",
            "1",
            "--rps",
            "0",
        )
        assert rc == 1
        assert _lookup(clash, shared) in (first, second)  # one row kept
        assert not _marked(clash)
        assert _marked(fine)

    def test_properties_restricts_the_names_marked(self, store: Store) -> None:
        one, two = store.name(), store.name()
        store.seed(store.actor(), one, f"v-{uuid.uuid4()}")
        store.seed(store.actor(), two, f"v-{uuid.uuid4()}")
        assert _run("backfill", "--apply", "--properties", one, "--segments", "2") == 0
        assert _marked(one)
        assert not _marked(two)

    def test_a_missing_properties_table_refuses(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with mock.patch.object(
            command,
            "_require_tables",
            side_effect=command.StoreUnavailable(
                "the table x_properties does not exist"
            ),
        ):
            assert _run("backfill", "--apply", "--properties", "email") == 2
        assert "does not exist" in capsys.readouterr().err

    @pytest.mark.skipif(BACKEND != "dynamodb", reason="DynamoDB throttling")
    def test_a_write_fault_is_not_a_collision_and_marks_nothing(
        self, store: Store, tmp_path: Any
    ) -> None:
        from actingweb.db.dynamodb.property_lookup import PropertyLookupV2

        name = store.name()
        store.seed(store.actor(), name, f"v-{uuid.uuid4()}")
        checkpoint = str(tmp_path / "ckpt.json")
        with mock.patch.object(
            PropertyLookupV2,
            "save",
            side_effect=RuntimeError("ProvisionedThroughputExceededException"),
        ):
            stats = command.backfill_dynamodb(
                [name], apply=True, rps=0, segments=1, checkpoint_file=checkpoint
            )
        assert stats.faults >= 1
        assert stats.collisions == {}
        assert stats.completed_names([name]) == []
        # The segment is not checkpointed "done", so a re-run retries it.
        assert command.Checkpoint(checkpoint, 1).get(0) != "done"
        assert not _marked(name)

    @pytest.mark.skipif(BACKEND != "postgresql", reason="PostgreSQL batches")
    def test_orphaned_property_rows_are_skipped_and_reported(
        self, store: Store, capsys: pytest.CaptureFixture[str]
    ) -> None:
        name = store.name()
        store.seed("no-such-actor-" + uuid.uuid4().hex, name, f"v-{uuid.uuid4()}")
        kept = store.actor()
        value = f"v-{uuid.uuid4()}"
        store.seed(kept, name, value)
        assert _run("backfill", "--apply", "--properties", name) == 0
        assert _lookup(name, value) == kept
        assert "no longer exist" in capsys.readouterr().out

    @pytest.mark.skipif(BACKEND != "postgresql", reason="PostgreSQL batches")
    def test_batches_commit_independently(self, store: Store) -> None:
        name = store.name()
        actors = sorted(store.actor() for _ in range(3))
        values = {a: f"v-{uuid.uuid4()}" for a in actors}
        for a in actors:
            store.seed(a, name, values[a])
        real = command._pg_batches_conn  # pyright: ignore[reportPrivateUsage]
        calls = {"n": 0}

        from actingweb.db.postgresql import connection as pg

        original_get = pg.get_connection

        def faulty(conn: Any, names: list[str], size: int) -> Any:
            for item in real(conn, names, size):
                calls["n"] += 1
                if calls["n"] == 3:
                    raise RuntimeError("boom in batch 3")
                yield item

        with mock.patch.object(command, "_pg_batches_conn", faulty):
            stats = command.backfill_postgresql([name], apply=True, batch_size=1)
        assert original_get is pg.get_connection
        assert stats.faults == 1
        # Batches 1 and 2 committed; the name is not marked.
        assert _lookup(name, values[actors[0]]) == actors[0]
        assert _lookup(name, values[actors[1]]) == actors[1]
        assert _lookup(name, values[actors[2]]) is None
        assert not _marked(name)


class TestBackfillDynamoDbSafety:
    @pytest.mark.skipif(BACKEND != "dynamodb", reason="DynamoDB backfill")
    def test_an_orphaned_property_row_is_skipped_and_counted(
        self, store: Store
    ) -> None:
        name = store.name()
        store.seed("no-such-actor-" + uuid.uuid4().hex, name, f"v-{uuid.uuid4()}")
        kept = store.actor()
        value = f"v-{uuid.uuid4()}"
        store.seed(kept, name, value)
        stats = command.backfill_dynamodb(
            [name], apply=True, rps=0, segments=1, checkpoint_file=None
        )
        assert stats.orphans == 1 and stats.collisions == {}
        assert _lookup(name, value) == kept

    @pytest.mark.skipif(BACKEND != "dynamodb", reason="DynamoDB backfill")
    def test_a_collision_run_leaves_no_checkpoint_to_skip_rows_next_time(
        self, store: Store, tmp_path: Any
    ) -> None:
        name = store.name()
        shared = f"shared-{uuid.uuid4()}"
        store.seed(store.actor(), name, shared)
        store.seed(store.actor(), name, shared)
        checkpoint = tmp_path / "ckpt.json"
        stats = command.backfill_dynamodb(
            [name], apply=True, rps=0, segments=1, checkpoint_file=str(checkpoint)
        )
        assert stats.collisions
        assert not checkpoint.exists()

    def test_a_checkpoint_for_other_names_is_not_resumed(self, tmp_path: Any) -> None:
        path = str(tmp_path / "ckpt.json")
        first = command.Checkpoint(path, 1, "table|email")
        first.set(0, None)  # segment 0 done
        assert command.Checkpoint(path, 1, "table|email").get(0) == "done"
        assert command.Checkpoint(path, 1, "table|oauthId").get(0) is None


class TestMarkComplete:
    def test_refuses_a_name_with_rows_and_no_lookup_rows(
        self, store: Store, capsys: pytest.CaptureFixture[str]
    ) -> None:
        name = store.name()
        store.seed(store.actor(), name, f"v-{uuid.uuid4()}")
        assert _run("mark-complete", "--apply", "--properties", name) == 1
        assert not _marked(name)
        assert "backfill --apply" in capsys.readouterr().err

    def test_force_marks_it_and_is_idempotent(self, store: Store) -> None:
        name = store.name()
        store.seed(store.actor(), name, f"v-{uuid.uuid4()}")
        args = ("mark-complete", "--apply", "--force", "--properties", name)
        assert _run(*args) == 0
        assert _run(*args) == 0
        assert _marked(name)

    def test_a_name_with_lookup_rows_is_marked_without_force(
        self, store: Store
    ) -> None:
        name = store.name()
        actor = store.actor()
        value = f"v-{uuid.uuid4()}"
        store.seed(actor, name, value)
        _lookup_module().DbPropertyLookup().create(name, value, actor)
        assert _run("mark-complete", "--apply", "--properties", name) == 0
        assert _marked(name)

    def test_dry_run_marks_nothing(self, store: Store) -> None:
        name = store.name()
        assert _run("mark-complete", "--properties", name) == 0
        assert not _marked(name)


class TestUnmark:
    def test_unmark_removes_the_marker_and_the_probe_refuses(
        self, store: Store
    ) -> None:
        name = store.name()
        store.seed(store.actor(), name, f"v-{uuid.uuid4()}")
        assert _run("backfill", "--apply", "--properties", name, "--segments", "2") == 0
        assert _marked(name)
        assert _run("unmark", "--apply", "--properties", name) == 0
        assert not _marked(name)
        assert _run("report", "--properties", name) == 1

    def test_dry_run_unmarks_nothing(self, store: Store) -> None:
        name = store.name()
        _lookup_module().mark_backfilled([name])
        assert _run("unmark", "--properties", name) == 0
        assert _marked(name)


class TestShim:
    """``scripts/backfill_property_lookup.py`` maps its old flags."""

    def _translate(self, argv: list[str]) -> list[str]:
        import importlib.util
        import pathlib

        path = (
            pathlib.Path(__file__).resolve().parent.parent
            / "scripts"
            / ("backfill_property_lookup.py")
        )
        spec = importlib.util.spec_from_file_location("backfill_shim", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.translate(argv)

    def test_dry_run_becomes_the_commands_default(self) -> None:
        assert self._translate(["--dry-run"]) == ["backfill"]

    def test_no_dry_run_becomes_apply(self) -> None:
        assert self._translate([]) == ["backfill", "--apply"]

    def test_flags_map_one_to_one(self) -> None:
        out = self._translate(
            [
                "--rps",
                "5",
                "--segments",
                "2",
                "--checkpoint-file",
                "c.json",
                "--properties",
                "email",
            ]
        )
        assert out == [
            "backfill",
            "--apply",
            "--rps",
            "5",
            "--segments",
            "2",
            "--checkpoint-file",
            "c.json",
            "--properties",
            "email",
        ]
