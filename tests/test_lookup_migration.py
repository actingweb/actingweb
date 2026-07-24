"""
Upgrade-path tests for the lookup-table default flip (v3.13).

Two upgrading cohorts must keep resolving reverse lookups between the
upgrade and the backfill:
(a) legacy-GSI deployments (populated GSI, no lookup tables) — served by
    the GSI fallback tier;
(b) v1-lookup deployments (populated v1 table, typically NO GSI — the
    measured production shape) — served by the v1 fallback tier.
Both fallbacks log deprecation warnings; after the backfill, lookups
resolve from v2 with no fallback. The startup check warns loudly for the
un-backfilled state.
"""

import uuid
from unittest import mock

import pytest


@pytest.fixture(autouse=True)
def _require_dynamodb():
    import os

    if os.getenv("DATABASE_BACKEND", "dynamodb") != "dynamodb":
        pytest.skip("DynamoDB-only test")


@pytest.fixture
def actor_id():
    return f"migration-{uuid.uuid4()}"


def _lookup_mode_prop(indexed):
    from actingweb.db.dynamodb.property import DbProperty

    return DbProperty(use_lookup_table=True, indexed_properties=list(indexed))


class TestV1CohortFallback:
    """Cohort (b): populated v1 table, empty v2, no GSI needed."""

    def test_v1_fallback_serves_and_warns(self, actor_id, caplog):
        from actingweb.db.dynamodb.property import Property
        from actingweb.db.dynamodb.property_lookup import (
            DbPropertyLookup,
            PropertyLookup,
        )

        value = f"v1cohort-{uuid.uuid4()}"
        # Simulate pre-upgrade state: property row + v1 lookup row only
        # (write via the models directly — the current writers would
        # populate v2, which this cohort does not have yet).
        Property(id=actor_id, name="email", value=value).save()
        if not PropertyLookup.exists():
            PropertyLookup.create_table(wait=True)
        PropertyLookup(property_name="email", value=value, actor_id=actor_id).save()

        try:
            reader = _lookup_mode_prop(["email"])
            with caplog.at_level("WARNING", logger="actingweb.db.dynamodb.property"):
                found = reader.get_actor_id_from_property(name="email", value=value)
            assert found == actor_id
            assert any(
                "v1 lookup table" in r.message and "DEPRECATED" in r.message
                for r in caplog.records
            )
            # v2 still empty for this value — fallback did not write through
            assert DbPropertyLookup().get("email", value) is None
        finally:
            Property.get(actor_id, "email").delete()
            PropertyLookup.get("email", value).delete()


class TestGsiCohortFallback:
    """Cohort (a): legacy GSI populated, no lookup tables."""

    def test_gsi_fallback_serves_and_warns(self, actor_id, caplog):
        from actingweb.db.dynamodb.property import Property, PropertyLegacy

        # Requires the shared table to carry the GSI (see
        # test_conditional_gsi_schema for shape coverage)
        try:
            desc = PropertyLegacy._get_connection().describe_table()
        except Exception:
            desc = None
        if not (desc and desc.get("GlobalSecondaryIndexes")):
            pytest.skip("shared properties table has the lookup-mode shape")

        value = f"gsicohort-{uuid.uuid4()}"
        Property(id=actor_id, name="email", value=value).save()
        try:
            reader = _lookup_mode_prop(["email"])
            with caplog.at_level("WARNING", logger="actingweb.db.dynamodb.property"):
                found = reader.get_actor_id_from_property(name="email", value=value)
            assert found == actor_id
            assert any(
                "property-index GSI" in r.message and "DEPRECATED" in r.message
                for r in caplog.records
            )
        finally:
            Property.get(actor_id, "email").delete()

    def test_gsi_fallback_warns_mocked(self, actor_id, caplog):
        """Shape-independent coverage of the tier-2 hit path."""
        from actingweb.db.dynamodb import property as prop_mod

        fake_row = mock.MagicMock()
        fake_row.id = actor_id
        reader = _lookup_mode_prop(["email"])
        with (
            mock.patch.object(
                prop_mod.PropertyLegacy.property_index,
                "query",
                return_value=iter([fake_row]),
            ),
            mock.patch.object(prop_mod.Property, "get", return_value=fake_row),
            caplog.at_level("WARNING", logger="actingweb.db.dynamodb.property"),
        ):
            found = reader.get_actor_id_from_property(
                name="email", value=f"mocked-{uuid.uuid4()}"
            )
        assert found == actor_id
        assert any(
            "property-index GSI" in r.message and "DEPRECATED" in r.message
            for r in caplog.records
        )

    def test_missing_gsi_fallback_is_none_not_crash(self, actor_id):
        """On a GSI-less table the tier-2 fallback must swallow the missing
        index and return None — never surface the backend exception."""
        from actingweb.db.dynamodb import property as prop_mod

        reader = _lookup_mode_prop(["email"])
        with mock.patch.object(
            prop_mod.PropertyLegacy.property_index,
            "query",
            side_effect=Exception(
                "ValidationException: The table does not have the specified index"
            ),
        ):
            assert (
                reader.get_actor_id_from_property(
                    name="email", value=f"missing-{uuid.uuid4()}"
                )
                is None
            )


class TestBackfillScript:
    def _run_backfill(self, argv):
        import sys

        sys.path.insert(0, "scripts")
        try:
            import backfill_property_lookup  # type: ignore[import-not-found]

            with mock.patch.object(sys, "argv", ["backfill_property_lookup.py", *argv]):
                return backfill_property_lookup.main()
        finally:
            sys.path.remove("scripts")

    @pytest.fixture
    def prop_name(self):
        # Unique indexed-property name per test so the backfill scan of the
        # SHARED table matches only this test's rows.
        return f"bfprop{uuid.uuid4().hex[:10]}"

    def test_dry_run_counts_without_writing(self, actor_id, prop_name, tmp_path):
        from actingweb.db.dynamodb.property import Property
        from actingweb.db.dynamodb.property_lookup import DbPropertyLookup

        value = f"dry-{uuid.uuid4()}"
        Property(id=actor_id, name=prop_name, value=value).save()
        try:
            rc = self._run_backfill(
                [
                    "--dry-run",
                    "--rps",
                    "0",
                    "--segments",
                    "2",
                    "--properties",
                    prop_name,
                ]
            )
            assert rc == 0
            assert DbPropertyLookup().get(prop_name, value) is None
        finally:
            Property.get(actor_id, prop_name).delete()

    def test_backfill_then_lookup_without_fallback(
        self, actor_id, prop_name, tmp_path, caplog
    ):
        from actingweb.db.dynamodb.property import Property
        from actingweb.db.dynamodb.property_lookup import DbPropertyLookup

        value = f"real-{uuid.uuid4()}"
        Property(id=actor_id, name=prop_name, value=value).save()
        try:
            checkpoint = str(tmp_path / "ckpt.json")
            rc = self._run_backfill(
                [
                    "--rps",
                    "0",
                    "--segments",
                    "2",
                    "--properties",
                    prop_name,
                    "--checkpoint-file",
                    checkpoint,
                ]
            )
            assert rc == 0
            assert DbPropertyLookup().get(prop_name, value) == actor_id

            # Reverse lookup now resolves from v2 — no deprecation warnings
            reader = _lookup_mode_prop([prop_name])
            with caplog.at_level("WARNING", logger="actingweb.db.dynamodb.property"):
                assert (
                    reader.get_actor_id_from_property(name=prop_name, value=value)
                    == actor_id
                )
            assert not any("DEPRECATED" in r.message for r in caplog.records)

            # Idempotent re-run
            rc2 = self._run_backfill(
                [
                    "--rps",
                    "0",
                    "--segments",
                    "2",
                    "--properties",
                    prop_name,
                    "--checkpoint-file",
                    checkpoint,
                ]
            )
            assert rc2 == 0
        finally:
            Property.get(actor_id, prop_name).delete()
            DbPropertyLookup().delete(prop_name, value)

    def test_collision_reported_not_overwritten(self, prop_name, tmp_path):
        from actingweb.db.dynamodb.property import Property
        from actingweb.db.dynamodb.property_lookup import DbPropertyLookup

        value = f"shared-{uuid.uuid4()}"
        actor_a = f"bf-a-{uuid.uuid4()}"
        actor_b = f"bf-b-{uuid.uuid4()}"
        Property(id=actor_a, name=prop_name, value=value).save()
        Property(id=actor_b, name=prop_name, value=value).save()
        try:
            rc = self._run_backfill(
                [
                    "--rps",
                    "0",
                    "--segments",
                    "1",
                    "--properties",
                    prop_name,
                    "--checkpoint-file",
                    str(tmp_path / "c.json"),
                ]
            )
            assert rc == 1  # collision -> non-zero exit
            winner = DbPropertyLookup().get(prop_name, value)
            assert winner in (actor_a, actor_b)  # one row kept, not clobbered
        finally:
            Property.get(actor_a, prop_name).delete()
            Property.get(actor_b, prop_name).delete()
            DbPropertyLookup().delete(prop_name, value)


class TestStartupCheck:
    def _app(self):
        from actingweb.interface import ActingWebApp

        return ActingWebApp(
            aw_type="urn:actingweb:test:startup",
            database="dynamodb",
            fqdn="test.example.com",
        )

    def _run_check(self, v2_rows, prop_rows, v1_rows, caplog):
        from actingweb.db.dynamodb import property as prop_mod
        from actingweb.db.dynamodb import property_lookup as pl

        app = self._app()
        with (
            mock.patch.object(pl.PropertyLookupV2, "scan", return_value=iter(v2_rows)),
            mock.patch.object(prop_mod.Property, "scan", return_value=iter(prop_rows)),
            mock.patch.object(pl.PropertyLookup, "scan", return_value=iter(v1_rows)),
            caplog.at_level("ERROR", logger="actingweb.interface.app"),
        ):
            app._check_lookup_backfill_needed()
        return [r.message for r in caplog.records if r.levelname == "ERROR"]

    def test_fires_when_backfill_needed(self, caplog):
        errors = self._run_check([], ["prop"], [], caplog)
        assert any("lookup table is empty" in m for m in errors)

    def test_v1_variant_message(self, caplog):
        errors = self._run_check([], ["prop"], ["v1row"], caplog)
        assert any("needs migration" in m for m in errors)

    def test_silent_when_v2_populated(self, caplog):
        assert self._run_check(["v2row"], ["prop"], [], caplog) == []

    def test_silent_on_fresh_deployment(self, caplog):
        assert self._run_check([], [], [], caplog) == []

    def test_silent_in_legacy_mode(self, caplog):
        app = self._app().with_legacy_property_index(enable=True)
        from actingweb.db.dynamodb import property_lookup as pl

        with (
            mock.patch.object(pl.PropertyLookupV2, "scan") as scan_spy,
            caplog.at_level("ERROR", logger="actingweb.interface.app"),
        ):
            app._check_lookup_backfill_needed()
        scan_spy.assert_not_called()


class TestDefaultFlip:
    def test_config_default_is_lookup_mode(self):
        from actingweb.config import Config

        assert Config(database="dynamodb").use_lookup_table is True

    def test_env_rollback_still_works(self, monkeypatch):
        """The documented rollback: USE_PROPERTY_LOOKUP_TABLE=false."""
        from actingweb.config import Config

        monkeypatch.setenv("USE_PROPERTY_LOOKUP_TABLE", "false")
        assert Config(database="dynamodb").use_lookup_table is False
