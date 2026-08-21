"""Phase 13 of the v2 list read cost release (thoughts/plans/2026-08-20-
v2-positional-access-cost.md): an orphan-row scan (``actingweb.maintenance.
verify_orphans``) that operators can trust not to misclassify live data.

Covers the four named edge cases from the plan directly:
1. an empty/failed actor-id read fails closed (exit 2), never "everything
   orphaned";
2. reserved (``_actingweb_``-prefixed) ids are reported separately, by
   prefix rather than the closed name list in constants.py;
3. (exercised in the integration suite -- consistent reads);
4. structurally, there is no code path in the module that can delete a row.
"""

import ast
from pathlib import Path

from actingweb.maintenance import verify_orphans as vo

MODULE_PATH = Path(vo.__file__)


class TestClassifyRowsLiveActors:
    def test_rows_belonging_to_a_live_actor_are_never_reported(self):
        result = vo.classify_rows(
            {"actor1", "actor2"},
            [
                ("property", "actor1", "list:foo-0"),
                ("attribute", "actor2", "bucket:name"),
                ("trust", "actor1", "peer-xyz"),
            ],
        )
        assert result["orphans"] == {"property": [], "attribute": [], "trust": []}
        assert result["counts"] == {"property": 1, "attribute": 1, "trust": 1}


class TestClassifyRowsOrphans:
    def test_rows_with_absent_actor_id_are_reported_per_row_type(self):
        result = vo.classify_rows(
            {"live1"},
            [
                ("property", "ghost1", "list:foo-0"),
                ("attribute", "ghost2", "bucket:name"),
                ("trust", "ghost3", "peer-xyz"),
                ("property", "live1", "n"),
            ],
        )
        assert result["orphans"]["property"] == [("ghost1", "list:foo-0")]
        assert result["orphans"]["attribute"] == [("ghost2", "bucket:name")]
        assert result["orphans"]["trust"] == [("ghost3", "peer-xyz")]

    def test_list_prefixed_property_rows_are_classified_like_any_other(self):
        result = vo.classify_rows(
            set(),
            [("property", "ghost", "list:mylist-meta")],
        )
        assert result["orphans"]["property"] == [("ghost", "list:mylist-meta")]


class TestClassifyRowsReservedIds:
    def test_reserved_prefixed_ids_are_reported_separately_never_as_orphans(self):
        # Deliberately an id that is NOT one of the named constants in
        # constants.py -- this must still land in "reserved", proving the
        # rule is the prefix, not the closed list of known names.
        unknown_reserved_id = "_actingweb_some_future_registry"
        result = vo.classify_rows(
            set(),  # empty live-actor set: if the prefix rule didn't apply
            # first, every one of these would fall into "orphans" instead.
            [
                ("property", unknown_reserved_id, "n"),
                ("attribute", "_actingweb_system", "bucket:name"),
                ("trust", "_actingweb_oauth2", "peer-xyz"),
            ],
        )
        assert result["orphans"] == {"property": [], "attribute": [], "trust": []}
        assert result["reserved"]["property"] == [(unknown_reserved_id, "n")]
        assert result["reserved"]["attribute"] == [("_actingweb_system", "bucket:name")]
        assert result["reserved"]["trust"] == [("_actingweb_oauth2", "peer-xyz")]

    def test_reserved_prefix_wins_even_for_an_id_that_is_also_live(self):
        # A reserved id that DOES happen to be in the actor table (e.g.
        # ACTINGWEB_SYSTEM_ACTOR is a real actor row) must still be
        # reported as reserved, not silently treated as an ordinary live
        # actor -- "reserved" is the more specific classification.
        result = vo.classify_rows(
            {"_actingweb_system"},
            [("property", "_actingweb_system", "n")],
        )
        assert result["orphans"]["property"] == []
        assert result["reserved"]["property"] == [("_actingweb_system", "n")]


class TestMainFailsClosedOnBadActorRead:
    def test_empty_actor_set_yields_exit_2_and_no_sweep(self, monkeypatch, tmp_path):
        monkeypatch.setattr(vo, "_read_actor_ids", lambda backend: set())
        sweep_called = []
        monkeypatch.setattr(
            vo,
            "_rows_for",
            lambda backend, table, limiter: sweep_called.append(table) or iter([]),
        )
        checkpoint_file = tmp_path / "ckpt.json"
        monkeypatch.setattr(
            "sys.argv",
            ["verify_orphans", "--checkpoint-file", str(checkpoint_file)],
        )
        rc = vo.main()
        assert rc == 2
        assert sweep_called == []  # never even attempted a table sweep

    def test_failed_actor_read_yields_exit_2(self, monkeypatch, tmp_path):
        def _boom(backend):
            raise RuntimeError("connection refused")

        monkeypatch.setattr(vo, "_read_actor_ids", _boom)
        checkpoint_file = tmp_path / "ckpt.json"
        monkeypatch.setattr(
            "sys.argv",
            ["verify_orphans", "--checkpoint-file", str(checkpoint_file)],
        )
        rc = vo.main()
        assert rc == 2


class TestMainReportsOrphansAndReserved:
    def test_a_clean_sweep_with_orphans_present_exits_1_and_reports_them(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(vo, "_read_actor_ids", lambda backend: {"live1"})

        def _rows(backend, table, limiter):
            if table == "property":
                return iter([("property", "ghost", "n")])
            return iter([])

        monkeypatch.setattr(vo, "_rows_for", _rows)
        checkpoint_file = tmp_path / "ckpt.json"
        monkeypatch.setattr(
            "sys.argv",
            ["verify_orphans", "--checkpoint-file", str(checkpoint_file)],
        )
        rc = vo.main()
        assert rc == 1
        # Orphans found: checkpoint is kept (nothing to clean up mid-review).
        assert checkpoint_file.exists()

    def test_a_clean_sweep_with_nothing_orphaned_exits_0_and_clears_checkpoint(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(vo, "_read_actor_ids", lambda backend: {"live1"})
        monkeypatch.setattr(vo, "_rows_for", lambda backend, table, limiter: iter([]))
        checkpoint_file = tmp_path / "ckpt.json"
        monkeypatch.setattr(
            "sys.argv",
            ["verify_orphans", "--checkpoint-file", str(checkpoint_file)],
        )
        rc = vo.main()
        assert rc == 0
        assert not checkpoint_file.exists()


class TestCheckpointResume:
    def test_a_completed_table_is_skipped_on_the_next_run(self, monkeypatch, tmp_path):
        monkeypatch.setattr(vo, "_read_actor_ids", lambda backend: {"live1"})
        swept_tables = []
        attribute_calls = {"n": 0}

        def _rows(backend, table, limiter):
            swept_tables.append(table)
            if table == "attribute":
                attribute_calls["n"] += 1
                if attribute_calls["n"] == 1:
                    raise RuntimeError("simulated interruption")
            return iter([])

        monkeypatch.setattr(vo, "_rows_for", _rows)
        checkpoint_file = tmp_path / "ckpt.json"
        monkeypatch.setattr(
            "sys.argv",
            ["verify_orphans", "--checkpoint-file", str(checkpoint_file)],
        )
        rc = vo.main()
        assert rc == 1  # attribute sweep errored this run
        assert swept_tables == ["property", "attribute", "trust"]

        # Resume: property and trust (already done) must not be re-swept --
        # only the table that errored gets attempted again.
        swept_tables.clear()
        rc = vo.main()
        assert swept_tables == ["attribute"]
        assert rc == 0

    def test_checkpoint_round_trips_orphans_across_resume(self, tmp_path):
        path = tmp_path / "ckpt.json"
        cp = vo.Checkpoint(str(path))
        result = vo.classify_rows({"live1"}, [("property", "ghost", "n")])
        cp.mark_table_done("property", result)

        cp2 = vo.Checkpoint(str(path))
        assert cp2.is_table_done("property")
        assert cp2.merged()["orphans"]["property"] == [("ghost", "n")]

    def test_a_run_that_scans_nothing_is_labelled_a_replay_and_exits_3(
        self, monkeypatch, tmp_path, caplog
    ):
        """An operator who removed the reported rows and re-ran used to get
        the ORIGINAL orphan report reprinted -- same counts, exit 1, zero
        rows scanned -- indistinguishable from a fresh scan. A run where
        every table is already checkpoint-complete must say so loudly and
        exit distinctly (3), and must not clear or re-scan anything."""
        import logging

        monkeypatch.setattr(vo, "_read_actor_ids", lambda backend: {"live1"})
        scan_attempts = []

        def _rows(backend, table, limiter):
            scan_attempts.append(table)
            if table == "property":
                return iter([("property", "ghost", "n")])
            return iter([])

        monkeypatch.setattr(vo, "_rows_for", _rows)
        checkpoint_file = tmp_path / "ckpt.json"
        monkeypatch.setattr(
            "sys.argv",
            ["verify_orphans", "--checkpoint-file", str(checkpoint_file)],
        )

        # First run: a real scan, orphan found, checkpoint kept.
        assert vo.main() == 1
        assert checkpoint_file.exists()
        assert len(scan_attempts) == 3

        # Second run: every table already complete -- nothing is scanned.
        scan_attempts.clear()
        with caplog.at_level(
            logging.WARNING, logger="actingweb.maintenance.verify_orphans"
        ):
            rc = vo.main()

        assert rc == 3  # distinct from 0 (clean), 1 (orphans), 2 (refused)
        assert scan_attempts == []  # nothing re-swept
        assert checkpoint_file.exists()  # replay never clears the file
        replay_warnings = [
            r for r in caplog.records if "REPLAYED FROM CHECKPOINT" in r.getMessage()
        ]
        assert len(replay_warnings) == 1
        assert "delete" in replay_warnings[0].getMessage()  # names the remedy


class TestRateLimiter:
    def test_zero_rps_never_sleeps(self):
        limiter = vo.RateLimiter(0)
        for _ in range(1000):
            limiter.wait()  # would take unreasonably long if this slept


class TestNoDeleteCodePath:
    """Structural: parse the module's own source so a later 'helpful'
    addition (someone wiring in a repair/delete flag) fails the suite
    instead of silently shipping."""

    FORBIDDEN_CALL_ATTRS = {
        "delete",
        "batch_delete",
        "delete_if_value_equals",
        "delete_item",
        "remove",
        "clear_actor",
        # Write primitives too, not just delete-named ones: this
        # codebase's own idiom for removing a property row is
        # db.set(..., value=None), which the delete-named set above would
        # wave through. A report-only tool has no business calling ANY
        # of these.
        "set",
        "put",
        "put_item",
        "batch_write",
        "save",
        "set_if_value_equals",
    }

    def _tree(self):
        return ast.parse(MODULE_PATH.read_text())

    def test_no_call_targets_a_backend_delete_primitive(self):
        offenders = [
            node.func.attr
            for node in ast.walk(self._tree())
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in self.FORBIDDEN_CALL_ATTRS
        ]
        assert offenders == []

    def test_no_sql_string_literal_is_a_mutating_statement(self):
        offenders = []
        for node in ast.walk(self._tree()):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                stripped = node.value.strip().upper()
                if stripped.startswith(
                    ("DELETE", "INSERT", "UPDATE", "DROP", "TRUNCATE")
                ):
                    offenders.append(node.value)
        assert offenders == []

    def test_argparse_defines_no_delete_flag(self):
        for node in ast.walk(self._tree()):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"
            ):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        assert "delete" not in arg.value.lower()


class TestPostgresqlTableMap:
    def test_every_row_type_maps_to_a_table_and_column(self):
        assert set(vo._POSTGRESQL_TABLES) == set(vo.ROW_TYPES)
        for table, column in vo._POSTGRESQL_TABLES.values():
            assert table and column


def test_maintenance_package_init_stays_docstring_only():
    """``actingweb/maintenance/__init__.py`` must not import
    verify_orphans (or anything else) at package scope -- see its own
    docstring and thoughts/plans/2026-08-08-dynamodb-known-next.md item 6.
    A bare ``import actingweb.maintenance`` must never bind a backend
    model just by existing."""
    import actingweb.maintenance as pkg

    init_source = Path(pkg.__file__).read_text()
    body_after_docstring = init_source.split('"""', 2)[-1]
    assert body_after_docstring.strip() == ""
