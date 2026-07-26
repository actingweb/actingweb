"""Deletion tombstones and the tri-state deletion check.

Structured around the acceptance list a consumer gated their release on:

1. A deleted actor is reported deleted **throughout** the wipe, not just after.
2. The tombstone outlives a 3-day provider retry window.
3. An infrastructure failure during the check is distinguishable from
   "deleted" — and does not present as "deleted".
4. A replayed webhook for a deleted actor writes zero rows.
5. A replayed webhook for a **live** actor with the tombstone store
   unreachable **still** does its work. This is the regression test that
   matters commercially: the failure mode it guards against is a paying
   customer silently never getting access.

Runs against whichever backend is configured. Tests that reach into
DynamoDB-specific internals skip elsewhere and say so.
"""

import os
import time
import uuid
from unittest import mock

import pytest

from actingweb.actor import Actor
from actingweb.config import Config
from actingweb.constants import (
    DELETED_ACTORS_BUCKET,
    DELETED_ACTORS_STORE,
    DELETION_TOMBSTONE_TTL,
)
from actingweb.db import get_attribute
from actingweb.deletion import (
    DeletionStatus,
    clear_actor_tombstone,
    get_deletion_status,
    mark_actor_deleted,
)
from actingweb.interface.actor_interface import ActorInterface


def _is_dynamodb() -> bool:
    return os.getenv("DATABASE_BACKEND", "dynamodb") == "dynamodb"


@pytest.fixture
def config():
    return Config()


@pytest.fixture
def actor_id():
    return f"tombstone-{uuid.uuid4()}"


@pytest.fixture
def tombstone_cleanup(config):
    """Remove any tombstones a test created, whatever it did to get them."""
    created: list[str] = []
    yield created
    for aid in created:
        clear_actor_tombstone(aid, config)


@pytest.fixture
def live_actor(config, tombstone_cleanup):
    """A real persisted actor with a couple of properties."""
    actor = Actor(config=config)
    actor.create(
        url="http://test.example.com",
        creator="tombstone@example.com",
        passphrase="secret",
    )
    tombstone_cleanup.append(actor.id or "")
    if actor.property:
        actor.property.first = "one"
        actor.property.second = "two"
    yield actor


class TestTombstoneLifecycle:
    def test_live_actor_reports_not_deleted(self, config, live_actor):
        assert get_deletion_status(live_actor.id, config) == DeletionStatus.NOT_DELETED

    def test_deleted_actor_reports_deleted(self, config, live_actor):
        actor_id = live_actor.id
        live_actor.delete()
        assert get_deletion_status(actor_id, config) == DeletionStatus.DELETED

    def test_unknown_actor_reports_not_deleted(self, config):
        """An id that never existed has no tombstone.

        Deliberate: the tombstone answers "was this deleted", not "does this
        exist". Conflating them would make every never-created id look deleted
        and suppress legitimate work.
        """
        assert (
            get_deletion_status(f"never-existed-{uuid.uuid4()}", config)
            == DeletionStatus.NOT_DELETED
        )

    def test_actor_interface_exposes_the_same_answer(self, config, live_actor):
        actor_id = live_actor.id
        assert (
            ActorInterface.get_deletion_status(actor_id or "", config)
            == DeletionStatus.NOT_DELETED
        )
        live_actor.delete()
        assert (
            ActorInterface.get_deletion_status(actor_id or "", config)
            == DeletionStatus.DELETED
        )

    def test_missing_arguments_report_unknown(self, config):
        """No id or no config means the question was not asked, not answered."""
        assert get_deletion_status(None, config) == DeletionStatus.UNKNOWN
        assert get_deletion_status("", config) == DeletionStatus.UNKNOWN
        assert get_deletion_status("some-id", None) == DeletionStatus.UNKNOWN


class TestAcceptance1ReportedThroughoutTheWipe:
    """The window that made an absence-based guard impossible to write."""

    def test_actor_still_resolves_mid_wipe(self, config, live_actor):
        """Documents *why* the tombstone exists, and pins the ordering.

        The actor row is removed last, so get_by_id() answers "live" while the
        data is being erased. If this ever starts failing because the ordering
        changed, the tombstone contract below is what consumers rely on and
        must keep holding.
        """
        from actingweb import property as property_module

        actor_id = live_actor.id
        observed = {}

        real_delete = property_module.Properties.delete

        def spy(self, *args, **kwargs):
            observed["resolves_mid_wipe"] = (
                ActorInterface.get_by_id(actor_id or "", config) is not None
            )
            return real_delete(self, *args, **kwargs)

        with mock.patch.object(property_module.Properties, "delete", spy):
            live_actor.delete()

        assert observed["resolves_mid_wipe"] is True

    def test_tombstone_is_readable_before_any_data_is_removed(self, config, live_actor):
        """Acceptance #1: DELETED throughout, not merely afterwards.

        Sampled at the *first* wipe step, which is where a provider callback
        triggered from the actor_deleted hook lands.
        """
        actor_id = live_actor.id
        observed = {}

        real_delete_peer_trustee = type(live_actor).delete_peer_trustee

        def spy(self, *args, **kwargs):
            observed["status"] = get_deletion_status(actor_id, config)
            return real_delete_peer_trustee(self, *args, **kwargs)

        with mock.patch.object(type(live_actor), "delete_peer_trustee", spy):
            live_actor.delete()

        assert observed["status"] == DeletionStatus.DELETED

    def test_tombstone_is_readable_at_the_last_wipe_step(self, config, live_actor):
        """The other end of the window: after buckets are wiped.

        A marker stored in the actor's own attribute bucket would be gone by
        here — that is the pattern this replaces.
        """
        from actingweb import attribute

        actor_id = live_actor.id
        observed = {}

        real_buckets_delete = attribute.Buckets.delete

        def spy(self, *args, **kwargs):
            result = real_buckets_delete(self, *args, **kwargs)
            observed["status"] = get_deletion_status(actor_id, config)
            return result

        with mock.patch.object(attribute.Buckets, "delete", spy):
            live_actor.delete()

        assert observed["status"] == DeletionStatus.DELETED


class TestAcceptance2TombstoneOutlivesRetryWindows:
    def test_default_ttl_exceeds_three_days(self):
        """Stripe retries a failed webhook for up to 3 days."""
        assert DELETION_TOMBSTONE_TTL > 3 * 86400

    @pytest.mark.skipif(not _is_dynamodb(), reason="reads the raw DynamoDB row")
    def test_stored_ttl_timestamp_is_far_enough_out(
        self, config, actor_id, tombstone_cleanup
    ):
        from actingweb.db.dynamodb.attribute import Attribute

        tombstone_cleanup.append(actor_id)
        assert mark_actor_deleted(actor_id, config) is True

        row = Attribute.get(
            DELETED_ACTORS_STORE,
            f"{DELETED_ACTORS_BUCKET}:{actor_id}",
            consistent_read=True,
        )
        assert row.ttl_timestamp is not None
        assert row.ttl_timestamp > int(time.time()) + 3 * 86400
        assert row.data["actor_id"] == actor_id
        assert row.data["deleted_at"]

    def test_expired_tombstone_reads_as_absent(
        self, config, actor_id, tombstone_cleanup
    ):
        """TTL must mean the same thing on both backends.

        DynamoDB's sweeper can lag 48 hours and PostgreSQL only reclaims on an
        explicit sweep, so an expired row is filtered at read time rather than
        left to suppress writes until someone collects it.
        """
        tombstone_cleanup.append(actor_id)
        # set_attr adds TTL_CLOCK_SKEW_BUFFER (1h), so this lands in the past.
        mark_actor_deleted(actor_id, config, ttl_seconds=-7200)
        assert get_deletion_status(actor_id, config) == DeletionStatus.NOT_DELETED


class TestAcceptance3InfrastructureFailureIsNotDeleted:
    def test_unreadable_store_reports_unknown(self, config, actor_id, caplog):
        """The whole point: UNKNOWN, never DELETED, and never silent."""
        db = get_attribute(config)
        with mock.patch.object(
            type(db),
            "get_attr_strict",
            side_effect=RuntimeError("ProvisionedThroughputExceededException"),
        ):
            with caplog.at_level("ERROR"):
                status = get_deletion_status(actor_id, config)

        assert status == DeletionStatus.UNKNOWN
        assert status != DeletionStatus.DELETED
        assert any(
            "Could not read deletion tombstone" in r.message for r in caplog.records
        )

    @pytest.mark.skipif(not _is_dynamodb(), reason="patches the pynamodb model")
    def test_strict_read_propagates_infrastructure_errors(self):
        """get_attr_strict must not repeat get_attr's collapse.

        Building the tombstone read on get_attr() would have reintroduced the
        exact bug it fixes: a throttle returning None, read as "no tombstone",
        read as "not deleted".
        """
        from actingweb.db.dynamodb.attribute import Attribute, DbAttribute

        with mock.patch.object(Attribute, "get", side_effect=RuntimeError("throttled")):
            # The lenient read swallows it...
            assert DbAttribute.get_attr(actor_id="a", bucket="b", name="c") is None
            # ...the strict one does not.
            with pytest.raises(RuntimeError):
                DbAttribute.get_attr_strict(actor_id="a", bucket="b", name="c")

    @pytest.mark.skipif(not _is_dynamodb(), reason="patches the pynamodb model")
    def test_strict_read_returns_none_for_genuine_absence(self):
        from actingweb.db.dynamodb.attribute import DbAttribute

        assert (
            DbAttribute.get_attr_strict(
                actor_id=DELETED_ACTORS_STORE,
                bucket=DELETED_ACTORS_BUCKET,
                name=f"absent-{uuid.uuid4()}",
            )
            is None
        )

    @pytest.mark.skipif(not _is_dynamodb(), reason="DynamoDB accessor")
    def test_failed_actor_read_is_logged(self, caplog):
        """DEL2's minimum: a swallowed infrastructure fault must leave a trace.

        DbActor.get() still returns None (raising would turn every throttle
        across auth, OAuth2 and MCP into a 500 on a validated release), so the
        ERROR is the only signal that an existence check just answered "no" for
        an infrastructure reason.
        """
        from actingweb.db.dynamodb.actor import Actor as ActorModel
        from actingweb.db.dynamodb.actor import DbActor

        with mock.patch.object(
            ActorModel, "get", side_effect=RuntimeError("throttled")
        ):
            with caplog.at_level("ERROR"):
                result = DbActor().get(actor_id="some-actor")

        assert result is None
        assert any("Failed to read actor" in r.message for r in caplog.records)

    @pytest.mark.skipif(not _is_dynamodb(), reason="DynamoDB accessor")
    def test_missing_actor_is_not_logged_as_an_error(self, caplog):
        """A genuine absence is not an error; only real faults should alert."""
        from actingweb.db.dynamodb.actor import DbActor

        with caplog.at_level("ERROR"):
            result = DbActor().get(actor_id=f"absent-{uuid.uuid4()}")

        assert result is None
        assert not [r for r in caplog.records if "Failed to read actor" in r.message]


class TestAcceptance4And5TheGuardAConsumerWrites:
    """The guard the library is telling consumers to write, both ways round."""

    @staticmethod
    def _webhook(actor_id, config):
        """Stand-in for a provider webhook that writes actor-scoped state."""
        from actingweb import attribute

        if (
            ActorInterface.get_deletion_status(actor_id, config)
            == DeletionStatus.DELETED
        ):
            return False
        attrs = attribute.Attributes(
            actor_id=actor_id, bucket="subscription", config=config
        )
        attrs.set_attr(name="metadata", data={"status": "active"})
        return True

    def test_replay_for_deleted_actor_writes_nothing(self, config, live_actor):
        """Acceptance #4."""
        from actingweb import attribute

        actor_id = live_actor.id or ""
        live_actor.delete()

        assert self._webhook(actor_id, config) is False

        bucket = attribute.Attributes(
            actor_id=actor_id, bucket="subscription", config=config
        ).get_bucket()
        assert not bucket

    def test_replay_for_live_actor_with_store_unreachable_still_writes(
        self, config, live_actor
    ):
        """Acceptance #5 — the commercially important one.

        A tombstone store that cannot be read must not cost a paying customer
        their entitlement.
        """
        from actingweb import attribute

        actor_id = live_actor.id or ""
        db = get_attribute(config)
        with mock.patch.object(
            type(db),
            "get_attr_strict",
            side_effect=RuntimeError("ProvisionedThroughputExceededException"),
        ):
            assert self._webhook(actor_id, config) is True

        bucket = attribute.Attributes(
            actor_id=actor_id, bucket="subscription", config=config
        ).get_bucket()
        assert bucket is not None
        assert bucket["metadata"]["data"] == {"status": "active"}


class TestTombstoneDoesNotOutliveItsActor:
    def test_recreating_a_supplied_id_clears_the_tombstone(
        self, config, actor_id, tombstone_cleanup
    ):
        """Without this, a reused id is DELETED for the whole retention window.

        Generated ids are never reused, but create(actor_id=...) accepts one
        from the caller.
        """
        tombstone_cleanup.append(actor_id)
        mark_actor_deleted(actor_id, config)
        assert get_deletion_status(actor_id, config) == DeletionStatus.DELETED

        actor = Actor(config=config)
        actor.create(
            url="http://test.example.com",
            creator="recreate@example.com",
            passphrase="secret",
            actor_id=actor_id,
        )
        try:
            assert get_deletion_status(actor_id, config) == DeletionStatus.NOT_DELETED
        finally:
            actor.delete()

    def test_tombstones_are_not_stored_under_a_real_system_actor(self):
        """Tombstones live under an id that is never itself an actor.

        ``ACTINGWEB_SYSTEM_ACTOR`` and ``OAUTH2_SYSTEM_ACTOR`` exist as real
        actors, and deleting an actor wipes every attribute bucket it owns — so
        tombstones kept under either could be destroyed by the very mechanism
        they describe.

        Asserted on the constants rather than by wiping a system actor: that
        actor also holds the shared trust-type and trust-permission registries
        (``TRUST_TYPES_BUCKET``, ``TRUST_PERMISSIONS_BUCKET``), and deleting its
        buckets would pull global table state out from under any concurrently
        running xdist worker. ``test_tombstone_is_readable_at_the_last_wipe_step``
        covers the real behaviour, wiping only the actor being deleted.
        """
        from actingweb.constants import ACTINGWEB_SYSTEM_ACTOR, OAUTH2_SYSTEM_ACTOR

        assert DELETED_ACTORS_STORE not in (
            ACTINGWEB_SYSTEM_ACTOR,
            OAUTH2_SYSTEM_ACTOR,
        )
        # Still reserved, so an orphan sweep excludes it.
        assert DELETED_ACTORS_STORE.startswith("_actingweb_")

    def test_a_failed_create_does_not_clear_the_tombstone(
        self, config, actor_id, tombstone_cleanup
    ):
        """Clearing is conditional on the row actually being persisted.

        ``DbActor.create()`` returns False when the id is already taken — which
        includes an actor **mid-deletion**, since its row survives until the
        wipe's last step. An unconditional clear would strip the marker off a
        deletion still in progress and reopen the race it guards. A backend
        insert failure is the same shape: nothing created, nothing to clear.
        """
        tombstone_cleanup.append(actor_id)
        mark_actor_deleted(actor_id, config)

        actor = Actor(config=config)
        # Pre-set the handle so create() uses this one rather than building a
        # real accessor; a backend that refuses the insert returns False.
        actor.handle = mock.Mock(create=mock.Mock(return_value=False))

        actor.create(
            url="http://test.example.com",
            creator="failed-create@example.com",
            passphrase="secret",
            actor_id=actor_id,
        )

        assert actor.handle.create.called, "test did not exercise the create path"
        assert get_deletion_status(actor_id, config) == DeletionStatus.DELETED

    def test_creating_over_an_id_still_being_wiped_keeps_the_tombstone(
        self, config, live_actor, tombstone_cleanup
    ):
        """The concurrent case, end to end against the real backend.

        Mimics "actor X is mid-deletion (tombstone written, row not yet
        removed) and a create races it on the same id": the real backend
        refuses the insert because the row is still there, so the in-flight
        deletion must keep its tombstone.
        """
        actor_id = live_actor.id or ""
        mark_actor_deleted(actor_id, config)

        racer = Actor(config=config)
        racer.create(
            url="http://test.example.com",
            creator="racer@example.com",
            passphrase="secret",
            actor_id=actor_id,
        )

        assert get_deletion_status(actor_id, config) == DeletionStatus.DELETED

    def test_a_normal_actors_wipe_leaves_other_tombstones_alone(
        self, config, actor_id, tombstone_cleanup, live_actor
    ):
        """One actor's deletion must not disturb another's tombstone."""
        tombstone_cleanup.append(actor_id)
        mark_actor_deleted(actor_id, config)

        live_actor.delete()

        assert get_deletion_status(actor_id, config) == DeletionStatus.DELETED


@pytest.mark.skipif(not _is_dynamodb(), reason="counts DynamoDB API calls")
class TestOperationProfile:
    """The read must be one point read — a consumer budgeted for exactly that.

    Counted rather than asserted from the code, using the recipe in
    ``docs/migration/v3.13.rst``: a ``before-call.dynamodb`` handler silently
    counts nothing under pynamodb, so a naive version of this test would pass
    vacuously.
    """

    @staticmethod
    def _counter(monkeypatch):
        import collections

        import botocore.client

        counts = collections.Counter()
        original = botocore.client.BaseClient._make_api_call

        def _counting(self, operation_name, api_params):
            if self.meta.service_model.service_name == "dynamodb":
                counts[operation_name] += 1
            return original(self, operation_name, api_params)

        monkeypatch.setattr(botocore.client.BaseClient, "_make_api_call", _counting)
        return counts

    def test_status_check_is_a_single_get_item(self, config, actor_id, monkeypatch):
        counts = self._counter(monkeypatch)
        status = get_deletion_status(actor_id, config)
        assert status == DeletionStatus.NOT_DELETED
        # The live-counter check: a zero elsewhere is only meaningful if the
        # counter records something.
        assert counts["GetItem"] == 1
        assert counts.total() == 1, f"expected one GetItem, got {dict(counts)}"

    def test_status_check_for_a_deleted_actor_is_also_one_get_item(
        self, config, actor_id, tombstone_cleanup, monkeypatch
    ):
        tombstone_cleanup.append(actor_id)
        mark_actor_deleted(actor_id, config)

        counts = self._counter(monkeypatch)
        assert get_deletion_status(actor_id, config) == DeletionStatus.DELETED
        assert counts["GetItem"] == 1
        assert counts.total() == 1, f"expected one GetItem, got {dict(counts)}"

    def test_deletion_adds_one_put_item(self, config, live_actor, monkeypatch):
        """The cost the tombstone adds to a deletion: one write."""
        counts = self._counter(monkeypatch)
        live_actor.delete()
        assert counts["PutItem"] >= 1
        assert counts["Scan"] == 0


class TestPostWipeLifecycleHook:
    """``actor_deleted_complete``: somewhere to put "the actor is definitely gone".

    Without it, the only hook is ``actor_deleted``, which runs *before* the
    wipe. That is the right place to read the actor's data but the wrong place
    to act on it: an external API call made there triggers a provider callback
    that races the wipe and lands while the actor still resolves.
    """

    def _handler(self, config, hooks):
        from actingweb.aw_web_request import AWWebObj
        from actingweb.handlers.root import RootHandler

        return RootHandler(
            AWWebObj(url="http://test.example.com/"), config, hooks=hooks
        )

    def _auth_result(self, actor):
        auth_result = mock.Mock()
        auth_result.success = True
        auth_result.authorize.return_value = True
        auth_result.actor = actor
        return auth_result

    def test_registered_as_a_lifecycle_event(self):
        from actingweb.interface.hooks import LifecycleEvent

        assert LifecycleEvent.ACTOR_DELETED_COMPLETE.value == "actor_deleted_complete"

    def test_no_async_delete_variant_bypasses_the_hook(self):
        """Both integrations must reach the one ``delete()`` that fires the hook.

        The FastAPI integration prefers a ``<method>_async`` handler variant
        when one exists and only falls back to the sync method in a thread
        pool. ``RootHandler`` has no ``delete_async`` today, so both Flask and
        FastAPI run the same code — but adding one later without mirroring the
        hook call would silently stop ``actor_deleted_complete`` (and
        ``actor_deleted``) firing on FastAPI, which is the deployment shape that
        asked for this hook. Fail here rather than in production.
        """
        from actingweb.handlers.root import RootHandler

        assert not hasattr(RootHandler, "delete_async"), (
            "RootHandler gained a delete_async variant: mirror the "
            "actor_deleted / actor_deleted_complete hook calls into it "
            "(via execute_lifecycle_hooks_async) or FastAPI will skip them."
        )

    def test_fires_after_the_wipe_with_the_actor_id(self, config, live_actor):
        from actingweb.interface.hooks import HookRegistry

        actor_id = live_actor.id
        calls = []
        hooks = HookRegistry()

        def before(actor, **kwargs):
            calls.append(("actor_deleted", actor.id, kwargs.get("actor_id")))

        def after(actor, **kwargs):
            calls.append(
                (
                    "actor_deleted_complete",
                    actor,
                    kwargs.get("actor_id"),
                    ActorInterface.get_by_id(kwargs.get("actor_id") or "", config),
                    get_deletion_status(kwargs.get("actor_id"), config),
                )
            )

        hooks.register_lifecycle_hook("actor_deleted", before)
        hooks.register_lifecycle_hook("actor_deleted_complete", after)

        handler = self._handler(config, hooks)
        with mock.patch.object(
            handler, "authenticate_actor", return_value=self._auth_result(live_actor)
        ):
            handler.delete(actor_id)

        assert [c[0] for c in calls] == ["actor_deleted", "actor_deleted_complete"]

        # The pre-wipe hook still gets a live ActorInterface.
        assert calls[0][1] == actor_id

        _, actor_arg, passed_id, resolved, status = calls[1]
        # No ActorInterface — deliberately. There is no actor left to hand over.
        assert actor_arg is None
        assert passed_id == actor_id
        # And by this point the actor really is gone, and reported gone.
        assert resolved is None
        assert status == DeletionStatus.DELETED

    def test_tombstone_exists_while_the_pre_delete_hook_runs(self, config, live_actor):
        """The window that actually produced the reported orphan rows.

        The production sequence was: ``actor_deleted`` calls the payment
        provider to cancel, and the provider's webhook arrives *in response to
        that call* — potentially while it is still in flight, i.e. before
        ``Actor.delete()`` has started and written its own tombstone. Marking
        only at the start of the wipe leaves precisely the motivating case
        uncovered, so the HTTP path marks before running the hook.
        """
        from actingweb.interface.hooks import HookRegistry

        observed = {}
        hooks = HookRegistry()

        def during(actor, **kwargs):
            # Stands in for the provider callback landing mid-cancellation.
            observed["actor_id"] = actor.id
            observed["status"] = get_deletion_status(actor.id, config)

        hooks.register_lifecycle_hook("actor_deleted", during)

        handler = self._handler(config, hooks)
        with mock.patch.object(
            handler, "authenticate_actor", return_value=self._auth_result(live_actor)
        ):
            handler.delete(live_actor.id)

        # Guards against a vacuous pass: a falsy id would make
        # mark_actor_deleted() a silent no-op and the status read meaningless.
        assert observed["actor_id"]
        assert observed["status"] == DeletionStatus.DELETED

    def test_the_two_marks_collapse_to_one_tombstone_row(self, config, live_actor):
        """The HTTP path marks twice; that must be an overwrite, not a duplicate.

        Keeping both marks (pre-hook in the handler, start-of-wipe in
        ``Actor.delete()`` for programmatic deletion) is justified by them being
        idempotent, so pin it rather than assert it in prose: one row, still
        readable, carrying a usable ``deleted_at``.
        """
        from actingweb import attribute

        actor_id = live_actor.id
        handler = self._handler(config, None)
        with mock.patch.object(
            handler, "authenticate_actor", return_value=self._auth_result(live_actor)
        ):
            handler.delete(actor_id)

        bucket = attribute.Attributes(
            actor_id=DELETED_ACTORS_STORE,
            bucket=DELETED_ACTORS_BUCKET,
            config=config,
        ).get_bucket()
        rows = [k for k in (bucket or {}) if k == actor_id]
        assert rows == [actor_id], f"expected exactly one tombstone row, got {rows}"
        assert (bucket or {})[actor_id]["data"]["deleted_at"]
        assert get_deletion_status(actor_id, config) == DeletionStatus.DELETED

    def test_delete_still_returns_204_when_the_hook_raises(self, config, live_actor):
        from actingweb.interface.hooks import HookRegistry

        hooks = HookRegistry()

        def boom(actor, **kwargs):
            raise RuntimeError("external cleanup failed")

        hooks.register_lifecycle_hook("actor_deleted_complete", boom)

        handler = self._handler(config, hooks)
        with mock.patch.object(
            handler, "authenticate_actor", return_value=self._auth_result(live_actor)
        ):
            handler.delete(live_actor.id)

        assert handler.response.status_code == 204


class TestDeletionProceedsWhenTombstoneWriteFails:
    def test_failed_tombstone_write_does_not_block_deletion(
        self, config, live_actor, caplog
    ):
        """A user asking to delete their account must not be blocked.

        The ERROR is the compensating control: it says the race is open for
        this actor.
        """
        actor_id = live_actor.id
        db = get_attribute(config)
        with mock.patch.object(
            type(db), "set_attr", side_effect=RuntimeError("table missing")
        ):
            with caplog.at_level("ERROR"):
                assert mark_actor_deleted(actor_id, config) is False

        assert any(
            "Failed to write deletion tombstone" in r.message for r in caplog.records
        )
        # And the actor really does delete.
        live_actor.delete()
        assert ActorInterface.get_by_id(actor_id or "", config) is None
