"""
v2 (fractional rank key) list-property storage format -- Phase 4 of
thoughts/plans/2026-08-08-property-list-index-integrity.md.

Runs against real DynamoDB/PostgreSQL (parametrized via DATABASE_BACKEND,
same convention as the sibling integration test files) -- running this file
once per backend is the "cross-backend ordering" pin: the same operation
sequence must yield the same order on both.
"""

import os

import pytest

from actingweb.interface.actor_interface import ActorInterface
from actingweb.interface.app import ActingWebApp
from actingweb.property_list import ListProperty

DATABASE_BACKEND = os.environ.get("DATABASE_BACKEND", "dynamodb")


@pytest.fixture
def aw_app(docker_services, setup_database, worker_info):  # noqa: ARG001
    if DATABASE_BACKEND == "postgresql":
        os.environ["PG_DB_HOST"] = os.environ.get("PG_DB_HOST", "localhost")
        os.environ["PG_DB_PORT"] = os.environ.get("PG_DB_PORT", "5433")
        os.environ["PG_DB_NAME"] = os.environ.get("PG_DB_NAME", "actingweb_test")
        os.environ["PG_DB_USER"] = os.environ.get("PG_DB_USER", "actingweb")
        os.environ["PG_DB_PASSWORD"] = os.environ.get("PG_DB_PASSWORD", "testpassword")
        os.environ["PG_DB_PREFIX"] = worker_info["db_prefix"]
        os.environ["PG_DB_SCHEMA"] = "public"

    return ActingWebApp(
        aw_type="urn:actingweb:test:property_list_v2",
        database=DATABASE_BACKEND,
        fqdn="test.example.com",
        proto="http://",
    )


@pytest.fixture
def test_actor(aw_app):
    config = aw_app.get_config()
    actor = ActorInterface.create(creator="test@example.com", config=config)
    yield actor
    try:
        actor.delete()
    except Exception:
        pass


class TestV2BehavioralParity:
    """A v2 list must behave exactly like a Python list for every operation
    ListProperty exposes -- same contract v1 already had to meet."""

    def test_full_operation_sequence(self, test_actor):
        lst = test_actor.property_lists.parity_list
        reference: list = []

        lst.append("a")
        reference.append("a")
        lst.append("b")
        reference.append("b")
        lst.extend(["c", "d"])
        reference.extend(["c", "d"])
        assert lst.to_list() == reference == ["a", "b", "c", "d"]
        assert len(lst) == len(reference)

        lst.insert(1, "x")
        reference.insert(1, "x")
        assert lst.to_list() == reference == ["a", "x", "b", "c", "d"]

        lst[0] = "A"
        reference[0] = "A"
        assert lst[0] == reference[0] == "A"
        assert lst.to_list() == reference

        del lst[2]
        del reference[2]
        assert lst.to_list() == reference == ["A", "x", "c", "d"]

        assert lst.index("c") == reference.index("c")
        assert lst.count("c") == reference.count("c") == 1
        assert list(iter(lst)) == reference
        assert lst.slice(1, 3) == reference[1:3]

        popped = lst.pop()
        ref_popped = reference.pop()
        assert popped == ref_popped == "d"
        assert lst.to_list() == reference

        popped0 = lst.pop(0)
        ref_popped0 = reference.pop(0)
        assert popped0 == ref_popped0 == "A"
        assert lst.to_list() == reference

        lst.remove("c")
        reference.remove("c")
        assert lst.to_list() == reference == ["x"]

        assert lst.to_indexed_list() == list(enumerate(reference))

        lst.set_description("desc")
        lst.set_explanation("expl")
        assert lst.get_description() == "desc"
        assert lst.get_explanation() == "expl"

        lst.clear()
        reference.clear()
        assert lst.to_list() == reference == []
        assert len(lst) == 0

        lst.append("after-clear")
        assert lst.to_list() == ["after-clear"]

        lst.delete()
        assert not test_actor.property_lists.exists("parity_list")

    def test_negative_index_access(self, test_actor):
        lst = test_actor.property_lists.negidx_list
        for item in ["a", "b", "c"]:
            lst.append(item)

        assert lst[-1] == "c"
        assert lst.slice(-2, 3) == ["b", "c"]

        lst[-1] = "C"
        assert lst.to_list() == ["a", "b", "C"]

        del lst[-1]
        assert lst.to_list() == ["a", "b"]

    def test_verify_reports_healthy_and_length(self, test_actor):
        lst = test_actor.property_lists.verify_list
        for item in ["a", "b", "c"]:
            lst.append(item)

        report = lst.verify()
        assert report["format"] == 2
        assert report["length"] == 3
        assert report["healthy"] is True
        assert report["adjacent_duplicates"] == []


class TestV2NameValidationLibrary:
    def test_hash_in_new_list_name_raises(self, test_actor):
        bad = getattr(test_actor.property_lists, "bad#name")
        with pytest.raises(ValueError, match="cannot contain"):
            bad.append("x")

    def test_no_partial_write_after_name_rejection(self, test_actor):
        bad = getattr(test_actor.property_lists, "bad#name2")
        with pytest.raises(ValueError):
            bad.append("x")
        assert not test_actor.property_lists.exists("bad#name2")


class TestV2InterleavedMutationStaleCache:
    """Two independent ListProperty instances (as two request handlers on
    different processes would hold) -- one mutates, the other's cached
    rank-key list goes stale. A stale-cache read must return correct
    content, not raise ListCorruptionError -- see the review's stale-cache
    scenario, now under v2."""

    def test_stale_reader_sees_correct_content_after_writer_deletes(self, test_actor):
        writer = ListProperty(test_actor.id, "interleaved", test_actor.config)
        for item in ["a", "b", "c"]:
            writer.append(item)

        reader = ListProperty(test_actor.id, "interleaved", test_actor.config)
        # Warm the reader's cache BEFORE the writer mutates.
        assert reader.to_list() == ["a", "b", "c"]
        assert len(reader) == 3

        # Writer deletes "b" (index 1) through a completely separate
        # instance -- reader's cache is now stale.
        del writer[1]
        assert writer.to_list() == ["a", "c"]

        # Reader's per-position __getitem__ must self-heal via one cache
        # reload rather than raising ListCorruptionError.
        assert reader[1] == "c"
        assert len(reader) == 2

    def test_stale_reader_append_still_lands_correctly(self, test_actor):
        writer_a = ListProperty(test_actor.id, "interleaved2", test_actor.config)
        writer_a.append("a")

        writer_b = ListProperty(test_actor.id, "interleaved2", test_actor.config)
        # writer_b has never loaded its rank cache -- first operation is a
        # write that must see writer_a's committed state, not a stale
        # in-memory None.
        writer_b.append("b")

        fresh = ListProperty(test_actor.id, "interleaved2", test_actor.config)
        assert fresh.to_list() == ["a", "b"]


class TestV2RankRebalanceIntegration:
    def test_compact_after_many_inserts_shrinks_ranks(self, test_actor):
        lst = test_actor.property_lists.rebalance_list
        lst.append("left")
        lst.append("right")

        # Repeatedly insert at the same position -- bisection between the
        # same two neighbours, growing rank-key length each time.
        for i in range(60):
            lst.insert(1, f"mid-{i}")

        before = lst.verify()
        assert before["length"] == 62
        assert before["max_rank_length"] > 10

        lst.compact()

        after_fresh = test_actor.property_lists.rebalance_list
        after = after_fresh.verify()
        assert after["length"] == 62
        assert after["max_rank_length"] < 10
        # Order preserved through the rebalance.
        assert after_fresh.to_list()[0] == "left"
        assert after_fresh.to_list()[-1] == "right"
