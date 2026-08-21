"""
Phase 3 of the v2 list read cost release (thoughts/plans/2026-08-20-v2-
positional-access-cost.md): the library's own callers stop paying the v2
positional-access cost.

Pins the query counts for the sites Phase 3 fixed: the www.py properties
overview, the trust.py peer-sharing view, the full-state subscription
fallback, the new public list_all_with_rows(), and the bulk `{"items":
[...]}` REST endpoint. Uses real DynamoDB Local (no mocked storage) so the
counts reflect actual backend calls, not the rank-cache-reuse behaviour
that made some of the plan's own "N whole-list queries" estimates
optimistic -- see this phase's completion notes in the plan file for the
measured corrections.
"""

import json
import uuid
from unittest import mock
from unittest.mock import Mock

import pytest

from actingweb.aw_web_request import AWWebObj
from actingweb.db.dynamodb.property import DbProperty


@pytest.fixture(autouse=True)
def _require_dynamodb():
    import os

    if os.getenv("DATABASE_BACKEND", "dynamodb") != "dynamodb":
        pytest.skip("DynamoDB-only test")


@pytest.fixture
def config():
    from actingweb.config import Config

    return Config(database="dynamodb")


@pytest.fixture
def actor_id():
    return f"v2cost-{uuid.uuid4()}"


@pytest.fixture
def myself(config, actor_id):
    """A real, created Actor (Actor.get() resets self.id to None when no
    actor-table row exists, so a bare constructor call isn't enough) with 2
    plain properties and 3 list properties populated against real DynamoDB
    Local."""
    from actingweb.actor import Actor

    a = Actor(config=config)
    created = a.create(
        url=f"https://example.com/{actor_id}",
        creator="tester@example.com",
        passphrase="testpass",
        actor_id=actor_id,
    )
    assert created
    assert a.property is not None
    a.property["greeting"] = "hi"
    a.property["mood"] = "good"
    for list_name, items in (
        ("notes", ["a", "b", "c"]),
        ("todos", ["x", "y"]),
        ("tags", ["p"]),
    ):
        list_prop = getattr(a.property_lists, list_name)
        for item in items:
            list_prop.append(item)
    yield a
    a.delete()


def _count_get_range(fn):
    calls = []
    orig = DbProperty.get_range

    def spy(self, *a, **kw):
        calls.append(kw)
        return orig(self, *a, **kw)

    with mock.patch.object(DbProperty, "get_range", spy):
        result = fn()
    return result, calls


class TestListAllWithRows:
    def test_returns_names_and_raw_rows(self, myself):
        names, rows = myself.property_lists.list_all_with_rows()
        assert set(names) == {"notes", "todos", "tags"}
        assert any(k.startswith("list:notes-") for k in rows)
        assert any(k.startswith("list:todos-") for k in rows)

    def test_priming_from_the_dump_costs_zero_further_queries(self, myself):
        names, rows = myself.property_lists.list_all_with_rows()

        def prime_and_read():
            for name in names:
                lp = getattr(myself.property_lists, name)
                lp.prime_from_rows(rows)
                assert lp.to_list_from_rows(rows) == list(
                    {"notes": ["a", "b", "c"], "todos": ["x", "y"], "tags": ["p"]}[
                        name
                    ]
                )
                assert len(lp) == len(
                    {"notes": ["a", "b", "c"], "todos": ["x", "y"], "tags": ["p"]}[
                        name
                    ]
                )

        _, calls = _count_get_range(prime_and_read)
        assert calls == []

    def test_interface_layer_delegates_it(self, myself, config):
        from actingweb.interface.actor_interface import ActorInterface

        ai = ActorInterface(myself, config)
        names, rows = ai.property_lists.list_all_with_rows()
        assert set(names) == {"notes", "todos", "tags"}
        assert rows


class TestWwwPropertiesOverviewCost:
    def test_overview_issues_zero_get_range_beyond_the_partition_dump(
        self, myself, config
    ):
        from actingweb.handlers.www import WwwHandler

        webobj = AWWebObj()
        handler = WwwHandler(webobj, config)

        def render():
            with mock.patch.object(
                handler, "require_authenticated_actor", return_value=myself
            ):
                handler.get(myself.id, "properties")

        _, calls = _count_get_range(render)
        assert calls == [], f"expected zero get_range calls, got {len(calls)}"

        tv = handler.response.template_values
        assert tv["properties"]["notes"] == "[List with 3 items]"
        assert tv["properties"]["todos"] == "[List with 2 items]"
        assert tv["properties"]["tags"] == "[List with 1 items]"
        assert set(tv["list_properties"]) == {"notes", "todos", "tags"}


class TestTrustSharedPropertiesCost:
    def test_peer_sharing_view_issues_zero_get_range_beyond_the_dump(
        self, myself, config
    ):
        from actingweb.handlers.trust import TrustSharedPropertiesHandler
        from actingweb.permission_evaluator import PermissionResult

        webobj = AWWebObj()
        handler = TrustSharedPropertiesHandler(webobj, config)

        auth_result = Mock()
        auth_result.success = True
        auth_result.actor = myself
        auth_result.auth_obj = Mock()
        auth_result.auth_obj.acl = {"peerid": "peer-1"}

        def run():
            with (
                mock.patch.object(
                    handler, "authenticate_actor", return_value=auth_result
                ),
                mock.patch.object(
                    myself,
                    "get_trust_relationship",
                    return_value={
                        "peerid": "peer-1",
                        "relationship": "friend",
                        "approved": True,
                    },
                ),
                mock.patch(
                    "actingweb.handlers.trust.get_permission_evaluator"
                ) as mock_get_eval,
            ):
                mock_evaluator = Mock()
                mock_evaluator.evaluate_property_access = Mock(
                    return_value=PermissionResult.ALLOWED
                )
                mock_get_eval.return_value = mock_evaluator
                handler.get(myself.id, "friend", "peer-1")

        _, calls = _count_get_range(run)
        assert calls == [], f"expected zero get_range calls, got {len(calls)}"

        body = json.loads(handler.response.body)
        shared_by_name = {s["name"]: s for s in body["shared_properties"]}
        assert shared_by_name["notes"]["item_count"] == 3
        assert shared_by_name["todos"]["item_count"] == 2
        assert shared_by_name["tags"]["item_count"] == 1
        # Plain properties must NOT pay for a phantom list read (the
        # pre-fix bug: getattr(..., prop_name, None) succeeded for every
        # name, list or not).
        assert shared_by_name["greeting"]["item_count"] == 0


class TestFullStateSubscriptionCost:
    def test_all_properties_fallback_issues_one_partition_query_per_source(
        self, myself
    ):
        # get_properties() and list_all_with_rows() are each their own
        # whole-partition dump (one for scalars, one -- reused across all
        # lists -- for list contents); zero further per-list get_range
        # calls beyond those two.
        _, calls = _count_get_range(
            lambda: myself._get_full_state_for_subscription("properties", None)
        )
        assert calls == [], f"expected zero get_range calls, got {len(calls)}"

        result = myself._get_full_state_for_subscription("properties", None)
        assert result["greeting"] == "hi"
        assert result["notes"] == {
            "list": "notes",
            "operation": "extend",
            "items": ["a", "b", "c"],
        }
        assert result["todos"]["items"] == ["x", "y"]
        assert result["tags"]["items"] == ["p"]


class TestBulkItemsEndpointCost:
    def test_k_updates_and_deletes_issue_bounded_get_range_calls(
        self, myself, config
    ):
        """k=3 updates + 2 deletes against a fresh 10-item list. The plan's
        stated baseline ("~2k+2") does not hold against the current code,
        which already tracks a projected length across the validation
        pass -- see the phase notes in the plan for the corrected
        measurement. This pins the CURRENT count (1 initial length read +
        one forced reload per positional write, no post-hook read since no
        hooks are registered here) so a regression is caught even though
        it isn't the literal "k+2" figure the plan describes for the
        hook-registered case."""
        from actingweb.handlers.properties import PropertiesHandler

        big = myself.property_lists.bulk_list
        for i in range(10):
            big.append(f"orig{i}")

        body = json.dumps(
            {
                "bulk_list": {
                    "items": [
                        {"index": 0, "value": "upd0"},
                        {"index": 1, "value": "upd1"},
                        {"index": 2, "value": "upd2"},
                        {"index": 8},
                        {"index": 9},
                    ]
                }
            }
        )
        webobj = AWWebObj(params={}, body=body)
        handler = PropertiesHandler(webobj, config)

        auth_result = Mock()
        auth_result.success = True
        auth_result.actor = myself
        auth_result.auth_obj = Mock()
        auth_result.authorize = Mock(return_value=True)

        def run():
            with (
                mock.patch.object(
                    handler, "authenticate_actor", return_value=auth_result
                ),
                mock.patch.object(
                    handler, "_check_property_permission", return_value=True
                ),
            ):
                handler.post(myself.id, "")

        _, calls = _count_get_range(run)
        # 1 (projected_length) + 5 (one forced reload per positional
        # write: 3 updates + 2 deletes) = 6. No post-hook read: self.hooks
        # is None on this handler.
        assert len(calls) == 6, f"expected 6 get_range calls, got {len(calls)}"

        remaining = big.to_list()
        # item_spec minus "index" becomes the stored item, per post()'s
        # documented bulk semantics -- so {"index": 0, "value": "upd0"}
        # stores {"value": "upd0"}, not the bare string.
        assert remaining[0] == {"value": "upd0"}
        assert remaining[1] == {"value": "upd1"}
        assert remaining[2] == {"value": "upd2"}
        assert len(remaining) == 8  # 10 - 2 deletes
        big.delete()


class TestNotifiedAppendQueryCount:
    def test_append_with_diff_registration_issues_zero_get_range(
        self, config, actor_id
    ):
        """Confirms the corrected baseline (see phase notes): a notified
        append already issued exactly one get_range call before this
        phase's cleanup, because _v2_append's first attempt reuses an
        already-warm rank cache (force=False) -- the "duplicate len()"
        this phase removes was already a cache hit, not a second query.

        Phase 9B (thoughts/plans/2026-08-20-v2-positional-access-cost.md)
        changes the baseline itself: append() stops using the rank cache
        (and its whole-list get_range()) to find its own insertion point
        at all, replacing it with one get_last_in_range() call -- a
        single-row read. get_range() calls drop from 1 to 0; the new cost
        is one get_last_in_range() instead.
        """
        from actingweb.interface.property_store import NotifyingListProperty
        from actingweb.property_list import ListProperty

        core = ListProperty(actor_id, "notes2", config)

        class FakeActor:
            def __init__(self):
                self.diffs = []

            def register_diffs(self, **kw):
                self.diffs.append(kw)

        fake_actor = FakeActor()
        wrapped = NotifyingListProperty(core, "notes2", fake_actor)  # type: ignore[arg-type]

        orig_last_in_range = DbProperty.get_last_in_range
        last_in_range_calls = []

        def spy_last_in_range(self, *a, **kw):
            last_in_range_calls.append(kw)
            return orig_last_in_range(self, *a, **kw)

        with mock.patch.object(DbProperty, "get_last_in_range", spy_last_in_range):
            _, calls = _count_get_range(lambda: wrapped.append("hello"))
        assert len(calls) == 0
        assert len(last_in_range_calls) == 1

        diff = json.loads(fake_actor.diffs[0]["blob"])
        assert diff["operation"] == "append"
        assert diff["index"] == 0
        assert diff["item"] == "hello"

        core.delete()


class TestBoundsCheckRegressionsMapToIndexError:
    def test_www_update_out_of_range_returns_400(self, myself, config):
        from actingweb.handlers.www import WwwHandler

        webobj = AWWebObj(
            params={"action": "update", "item_index": "99", "item_value": '"x"'}
        )
        handler = WwwHandler(webobj, config)
        with mock.patch.object(
            handler, "require_authenticated_actor", return_value=myself
        ):
            handler.post(myself.id, "properties/notes/items")
        assert handler.response.status_code == 400

    def test_www_delete_out_of_range_returns_400(self, myself, config):
        from actingweb.handlers.www import WwwHandler

        webobj = AWWebObj(params={"action": "delete", "item_index": "99"})
        handler = WwwHandler(webobj, config)
        with mock.patch.object(
            handler, "require_authenticated_actor", return_value=myself
        ):
            handler.post(myself.id, "properties/notes/items")
        assert handler.response.status_code == 400
