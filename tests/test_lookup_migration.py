"""
Backfill command tests (``actingweb-property-lookup backfill``, DynamoDB).

The legacy-cohort fallbacks (v1 table, property-index GSI), the startup
warning and the default-flip tests were removed with the legacy lookup in
3.16; what remains is the backfill itself, now a packaged command.
"""

import uuid

import pytest

pytestmark = pytest.mark.xdist_group(name="property_lookup_markers")


@pytest.fixture(autouse=True)
def _require_dynamodb():
    import os

    if os.getenv("DATABASE_BACKEND", "dynamodb") != "dynamodb":
        pytest.skip("DynamoDB-only test")


@pytest.fixture
def actor_id():
    """An actor with a row of its own (the backfill skips orphaned rows)."""
    from actingweb.db.dynamodb.actor import Actor

    actor = f"migration-{uuid.uuid4()}"
    Actor(id=actor, creator=f"{actor}@x.test", passphrase="").save()
    yield actor
    Actor.get(actor).delete()


def _lookup_mode_prop(indexed):
    from actingweb.db.dynamodb.property import DbProperty

    return DbProperty(indexed_properties=list(indexed))


class TestBackfillCommand:
    def _run_backfill(self, argv):
        from actingweb.maintenance import property_lookup

        translated = ["backfill"]
        if "--dry-run" in argv:
            argv = [a for a in argv if a != "--dry-run"]
        else:
            translated.append("--apply")
        return property_lookup.main([*translated, *argv])

    @pytest.fixture
    def prop_name(self):
        # Unique indexed-property name per test so the backfill scan of the
        # SHARED table matches only this test's rows.
        from actingweb.db.dynamodb import property_lookup as pl

        name = f"bfprop{uuid.uuid4().hex[:10]}"
        yield name
        # The command marks the name and records it in the configured set;
        # leave the shared table as found.
        pl.unmark([name])
        _marked, recorded = pl.read_readiness([name])
        if recorded is not None and name in recorded:
            pl.record_configured(sorted(recorded - {name}))

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

    def test_backfill_then_lookup_without_fallback(self, actor_id, prop_name, tmp_path):
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

            # Reverse lookup resolves from the lookup table, and the command
            # marked the name backfill-complete.
            reader = _lookup_mode_prop([prop_name])
            assert (
                reader.get_actor_id_from_property(name=prop_name, value=value)
                == actor_id
            )
            from actingweb.db.dynamodb import property_lookup as pl

            marked, recorded = pl.read_readiness([prop_name])
            assert prop_name in marked
            assert recorded is not None and prop_name in recorded

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
        from actingweb.db.dynamodb.actor import Actor

        actor_a = f"bf-a-{uuid.uuid4()}"
        actor_b = f"bf-b-{uuid.uuid4()}"
        for actor in (actor_a, actor_b):
            Actor(id=actor, creator=f"{actor}@x.test", passphrase="").save()
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
            Actor.get(actor_a).delete()
            Actor.get(actor_b).delete()
