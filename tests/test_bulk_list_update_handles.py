"""Phase 11 of the v2 list read cost release (thoughts/plans/2026-08-20-v2-
positional-access-cost.md): the bulk list-item update endpoint
(``POST /properties`` with ``{"items": [{"index": N, ...}, ...]}``) moves
its v2 path onto Phase 10's handles -- one ``items_with_handles()`` read
resolves the whole batch, then every update/delete is a point conditional
write instead of a positional access that cost its own whole-list query
under v2.

Uses real DynamoDB Local (no mocked storage), same convention as the
sibling ``test_v2_cost_library_callers.py``: direct ``PropertiesHandler.post()``
invocation with a mocked auth result, which is the same technique that
file uses to observe handler-level behaviour without a running HTTP server.
"""

import json
import uuid
from unittest import mock

import pytest

from actingweb.aw_web_request import AWWebObj
from actingweb.handlers.properties import PropertiesHandler, PropertyListItemsHandler
from actingweb.property import get_property
from actingweb.property_list import ListProperty


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
    return f"bulkhandle-{uuid.uuid4()}"


def _create_actor(config, actor_id):
    from actingweb.actor import Actor

    a = Actor(config=config)
    created = a.create(
        url=f"https://example.com/{actor_id}",
        creator="tester@example.com",
        passphrase="testpass",
        actor_id=actor_id,
    )
    assert created
    return a


@pytest.fixture
def myself(config, actor_id):
    a = _create_actor(config, actor_id)
    yield a
    a.delete()


@pytest.fixture
def other_myself(config):
    a = _create_actor(config, f"bulkhandle-other-{uuid.uuid4()}")
    yield a
    a.delete()


def _post_bulk(myself, config, key, items):
    body = json.dumps({key: {"items": items}})
    webobj = AWWebObj(params={}, body=body)
    handler = PropertiesHandler(webobj, config)

    auth_result = mock.Mock()
    auth_result.success = True
    auth_result.actor = myself
    auth_result.auth_obj = mock.Mock()
    auth_result.authorize = mock.Mock(return_value=True)

    with (
        mock.patch.object(handler, "authenticate_actor", return_value=auth_result),
        mock.patch.object(handler, "_check_property_permission", return_value=True),
    ):
        handler.post(myself.id, "")
    return webobj


class TestNoConcurrentWriterEverythingApplies:
    def test_k10_update_and_k10_delete_all_apply_and_none_is_reported_raced(
        self, myself, config, caplog
    ):
        lst = myself.property_lists.bulk20
        for i in range(20):
            lst.append({"n": i})

        items = [{"index": i, "n": f"upd{i}"} for i in range(10)] + [
            {"index": i} for i in range(10, 20)
        ]
        with caplog.at_level("WARNING"):
            _post_bulk(myself, config, "bulk20", items)

        assert "concurrently modified" not in caplog.text

        remaining = lst.to_list()
        assert len(remaining) == 10
        for i in range(10):
            assert remaining[i] == {"n": f"upd{i}"}


class TestConcurrentModificationMidBatchIsReportedNotFatal:
    def test_a_row_changed_between_snapshot_and_write_is_reported_others_still_apply(
        self, myself, config, caplog
    ):
        lst = myself.property_lists.raced_list
        for i in range(5):
            lst.append({"n": i})

        orig_items_with_handles = ListProperty.items_with_handles

        def racy_items_with_handles(self):
            pairs = orig_items_with_handles(self)
            # Simulate another writer changing index 2's row AFTER this
            # batch's own snapshot was taken but BEFORE its conditional
            # write for that row runs -- items_with_handles() is where the
            # snapshot is captured, so mutating storage as a side effect
            # of that same call reproduces the race window precisely.
            raced_handle = pairs[2][0]
            db = get_property(self.config)
            db.set(
                actor_id=self.actor_id,
                name=self._v2_item_name(raced_handle.rank),
                value=json.dumps({"n": "raced-by-someone-else"}),
            )
            return pairs

        with (
            mock.patch.object(
                ListProperty, "items_with_handles", racy_items_with_handles
            ),
            caplog.at_level("WARNING"),
        ):
            _post_bulk(
                myself,
                config,
                "raced_list",
                [
                    {"index": 0, "n": "upd0"},
                    {"index": 2, "n": "upd2"},  # loses the race
                    {"index": 4, "n": "upd4"},
                ],
            )

        assert "Cannot update item at index 2" in caplog.text
        assert "concurrently modified" in caplog.text

        remaining = lst.to_list()
        assert remaining[0] == {"n": "upd0"}
        assert remaining[2] == {"n": "raced-by-someone-else"}  # NOT clobbered
        assert remaining[4] == {"n": "upd4"}


class TestSameIndexUpdateAndDeleteAppliesUpdateReportsDeleteAsRaced:
    """The CHANGED-behaviour entry: 3.13.0 deleted the updated row (the
    positional delete pass ran against whatever value happened to be at
    that index by then); 3.14 applies the update and reports the delete as
    concurrently modified, because the delete's handle pins the PRE-update
    bytes and the update pass already changed them."""

    def test_update_wins_delete_is_reported_not_applied(self, myself, config, caplog):
        lst = myself.property_lists.updel_list
        for i in range(3):
            lst.append({"n": i})

        with caplog.at_level("WARNING"):
            _post_bulk(
                myself,
                config,
                "updel_list",
                [
                    {"index": 1, "n": "updated"},
                    {"index": 1},  # delete, same index
                ],
            )

        assert "Cannot delete item at index 1" in caplog.text

        remaining = lst.to_list()
        assert len(remaining) == 3  # nothing was actually deleted
        assert remaining[1] == {"n": "updated"}


class TestOrderingSemanticsMatchV1:
    """Same scrambled batch (updates and deletes interleaved in the
    request, not pre-sorted), against a v1 list and a v2 list, must
    produce an identical final list -- the "no worse than v1, no
    different either" contract for a positional REST body regardless of
    which storage format is answering it."""

    def test_v1_and_v2_branches_produce_the_same_final_list(
        self, myself, other_myself, config
    ):
        original = [{"n": i} for i in range(6)]
        items = [
            {"index": 5},  # delete
            {"index": 0, "n": "upd0"},  # update
            {"index": 2},  # delete
            {"index": 6, "n": "appended"},  # append at length
            {"index": 3, "n": "upd3"},  # update
        ]

        v2_list = myself.property_lists.scrambled
        for item in original:
            v2_list.append(item)
        _post_bulk(myself, config, "scrambled", items)
        v2_result = v2_list.to_list()

        # Seed a genuinely v1 (dense-integer) list -- on a SEPARATE actor,
        # by writing its rows directly, bypassing ListProperty entirely
        # (the library defaults new lists to v2, so there is no public API
        # left that creates a fresh v1 list to test against).
        db = get_property(config)
        for i, item in enumerate(original):
            db.set(
                actor_id=other_myself.id,
                name="list:scrambled-" + str(i),
                value=json.dumps(item),
            )
        db.set(
            actor_id=other_myself.id,
            name="list:scrambled-meta",
            value=json.dumps(
                {
                    "format": 1,
                    "length": len(original),
                    "created_at": "2026-01-01T00:00:00",
                    "updated_at": "2026-01-01T00:00:00",
                    "item_type": "json",
                    "chunk_size": 1,
                    "version": "1.0",
                    "description": "",
                    "explanation": "",
                }
            ),
        )

        assert other_myself.property_lists.scrambled.storage_format() == 1

        _post_bulk(other_myself, config, "scrambled", items)
        # A fresh accessor, not the one used for the storage_format()
        # check above: property_lists.__getattr__ mints a new ListProperty
        # per access, and v1's __len__/to_list() trust that instance's own
        # cached metadata length -- reading through the pre-mutation
        # instance would see the pre-batch length (6) instead of the
        # post-batch one (5), which is a stale-instance test bug, not
        # something the bulk endpoint itself does (the endpoint's own
        # list_prop instance is always fetched fresh, once, per request).
        v1_result = other_myself.property_lists.scrambled.to_list()

        assert v1_result == v2_result


def _run_handler(handler_cls, myself, config, method, path_name, params=None, body=None):
    webobj = AWWebObj(params=params or {}, body=body)
    handler = handler_cls(webobj, config)

    auth_result = mock.Mock()
    auth_result.success = True
    auth_result.actor = myself
    auth_result.auth_obj = mock.Mock()
    auth_result.authorize = mock.Mock(return_value=True)

    with (
        mock.patch.object(handler, "authenticate_actor", return_value=auth_result),
        mock.patch.object(handler, "_check_property_permission", return_value=True),
    ):
        getattr(handler, method)(myself.id, path_name)
    return webobj


class TestSingleItemPutIndexParamDetectsRaces:
    """PropertiesHandler.put() with ?index=N -- the REST single-item edit
    path. Under v2 this now writes through a handle instead of an
    unconditional __setitem__, so a concurrent modification is reported
    (503 + Retry-After, the same signal ListMetadataContentionError already
    uses) instead of silently overwritten."""

    def test_replace_at_existing_index_succeeds_with_no_race(self, myself, config):
        lst = myself.property_lists.putindex
        for item in [{"n": 0}, {"n": 1}, {"n": 2}]:
            lst.append(item)

        webobj = _run_handler(
            PropertiesHandler,
            myself,
            config,
            "put",
            "putindex",
            params={"index": "1"},
            body=json.dumps({"n": "replaced"}),
        )

        assert webobj.response.status_code == 204
        assert myself.property_lists.putindex.to_list()[1] == {"n": "replaced"}

    def test_concurrent_modification_reports_503_retry_after_not_clobbering(
        self, myself, config
    ):
        lst = myself.property_lists.putindex_raced
        for item in [{"n": 0}, {"n": 1}, {"n": 2}]:
            lst.append(item)

        orig_items_with_handles = ListProperty.items_with_handles

        def racy_items_with_handles(self):
            pairs = orig_items_with_handles(self)
            raced_handle = pairs[1][0]
            db = get_property(self.config)
            db.set(
                actor_id=self.actor_id,
                name=self._v2_item_name(raced_handle.rank),
                value=json.dumps({"n": "raced"}),
            )
            return pairs

        with mock.patch.object(
            ListProperty, "items_with_handles", racy_items_with_handles
        ):
            webobj = _run_handler(
                PropertiesHandler,
                myself,
                config,
                "put",
                "putindex_raced",
                params={"index": "1"},
                body=json.dumps({"n": "attempted"}),
            )

        assert webobj.response.status_code == 503
        assert webobj.response.headers.get("Retry-After")
        assert myself.property_lists.putindex_raced.to_list()[1] == {"n": "raced"}


class TestItemsActionEndpointDetectsRaces:
    """PropertyListItemsHandler.post() -- the "action": "update"/"delete"
    endpoint. Same handle-based write, same 503 + Retry-After mapping via
    _respond_list_metadata_contended()."""

    def test_action_update_at_existing_index_succeeds_with_no_race(
        self, myself, config
    ):
        lst = myself.property_lists.actionitems
        for item in [{"n": 0}, {"n": 1}]:
            lst.append(item)

        webobj = _run_handler(
            PropertyListItemsHandler,
            myself,
            config,
            "post",
            "actionitems",
            body=json.dumps(
                {"action": "update", "item_index": 0, "item_value": {"n": "upd"}}
            ),
        )

        assert webobj.response.status_code == 204
        assert myself.property_lists.actionitems.to_list()[0] == {"n": "upd"}

    def test_action_update_concurrent_modification_reports_503(self, myself, config):
        lst = myself.property_lists.actionitems_raced
        for item in [{"n": 0}, {"n": 1}]:
            lst.append(item)

        orig_items_with_handles = ListProperty.items_with_handles

        def racy_items_with_handles(self):
            pairs = orig_items_with_handles(self)
            raced_handle = pairs[0][0]
            db = get_property(self.config)
            db.set(
                actor_id=self.actor_id,
                name=self._v2_item_name(raced_handle.rank),
                value=json.dumps({"n": "raced"}),
            )
            return pairs

        with mock.patch.object(
            ListProperty, "items_with_handles", racy_items_with_handles
        ):
            webobj = _run_handler(
                PropertyListItemsHandler,
                myself,
                config,
                "post",
                "actionitems_raced",
                body=json.dumps(
                    {"action": "update", "item_index": 0, "item_value": {"n": "upd"}}
                ),
            )

        assert webobj.response.status_code == 503
        assert webobj.response.headers.get("Retry-After")
        assert myself.property_lists.actionitems_raced.to_list()[0] == {"n": "raced"}

    def test_action_delete_concurrent_modification_reports_503_not_deleted(
        self, myself, config
    ):
        lst = myself.property_lists.actionitems_raced_del
        for item in [{"n": 0}, {"n": 1}]:
            lst.append(item)

        orig_items_with_handles = ListProperty.items_with_handles

        def racy_items_with_handles(self):
            pairs = orig_items_with_handles(self)
            raced_handle = pairs[0][0]
            db = get_property(self.config)
            db.set(
                actor_id=self.actor_id,
                name=self._v2_item_name(raced_handle.rank),
                value=json.dumps({"n": "raced"}),
            )
            return pairs

        with mock.patch.object(
            ListProperty, "items_with_handles", racy_items_with_handles
        ):
            webobj = _run_handler(
                PropertyListItemsHandler,
                myself,
                config,
                "post",
                "actionitems_raced_del",
                body=json.dumps({"action": "delete", "item_index": 0}),
            )

        assert webobj.response.status_code == 503
        remaining = myself.property_lists.actionitems_raced_del.to_list()
        assert len(remaining) == 2  # nothing was actually deleted


class TestWwwActionEndpointDetectsRaces:
    """WwwHandler.post() for properties/{name}/items -- the web-UI form
    action endpoint. Same handle-based write as the REST paths above, but
    responds with a bare 503 + Retry-After (no JSON body, matching the
    web-UI's other error responses) rather than
    _respond_list_metadata_contended()'s structured body."""

    def test_action_update_concurrent_modification_reports_503(self, myself, config):
        from actingweb.handlers.www import WwwHandler

        lst = myself.property_lists.wwwitems_raced
        for item in [{"n": 0}, {"n": 1}]:
            lst.append(item)

        orig_items_with_handles = ListProperty.items_with_handles

        def racy_items_with_handles(self):
            pairs = orig_items_with_handles(self)
            raced_handle = pairs[0][0]
            db = get_property(self.config)
            db.set(
                actor_id=self.actor_id,
                name=self._v2_item_name(raced_handle.rank),
                value=json.dumps({"n": "raced"}),
            )
            return pairs

        webobj = AWWebObj(
            params={
                "action": "update",
                "item_index": "0",
                "item_value": json.dumps({"n": "upd"}),
            }
        )
        handler = WwwHandler(webobj, config)

        with (
            mock.patch.object(
                handler, "require_authenticated_actor", return_value=myself
            ),
            mock.patch.object(
                ListProperty, "items_with_handles", racy_items_with_handles
            ),
        ):
            handler.post(myself.id, "properties/wwwitems_raced/items")

        assert webobj.response.status_code == 503
        assert webobj.response.headers.get("Retry-After")
        assert myself.property_lists.wwwitems_raced.to_list()[0] == {"n": "raced"}


class TestSameBatchDuplicateIndices:
    """Regression pins for the post-PR-#134 fix (plan's Post-Verification
    item 3): the v2 branch resolves ONE final value per targeted index
    before writing anything, so duplicate indices in one batch cannot
    double-append, a same-batch create-then-delete is a net no-op, and a
    second update at a pre-existing index does not fail against the handle
    the first update just invalidated. Each expected result below is the
    v1 branch's live-length semantics, hand-traced -- the contract is
    "same accepted batch, same final list, regardless of storage format".
    """

    def test_two_updates_at_the_same_append_index_produce_one_row_later_wins(
        self, myself, config, caplog
    ):
        lst = myself.property_lists.dup_append
        for i in range(3):
            lst.append({"n": i})

        with caplog.at_level("WARNING"):
            _post_bulk(
                myself,
                config,
                "dup_append",
                [{"index": 3, "n": "first"}, {"index": 3, "n": "second"}],
            )

        assert "concurrently modified" not in caplog.text
        result = lst.to_list()
        assert len(result) == 4  # ONE appended row, not two
        assert result[3] == {"n": "second"}  # later duplicate wins

    def test_two_updates_at_the_same_pre_existing_index_apply_later_wins(
        self, myself, config, caplog
    ):
        """The incidental half of the fix: before it, the second update
        hit a handle the first update's own write had just invalidated
        and was misreported as 'concurrently modified' -- not a real
        concurrent writer, just this batch's earlier entry."""
        lst = myself.property_lists.dup_existing
        for i in range(3):
            lst.append({"n": i})

        with caplog.at_level("WARNING"):
            _post_bulk(
                myself,
                config,
                "dup_existing",
                [{"index": 1, "n": "first"}, {"index": 1, "n": "second"}],
            )

        assert "concurrently modified" not in caplog.text
        result = lst.to_list()
        assert len(result) == 3
        assert result[1] == {"n": "second"}

    def test_create_then_delete_at_the_append_index_is_a_net_noop(
        self, myself, config, caplog
    ):
        lst = myself.property_lists.create_del
        for i in range(3):
            lst.append({"n": i})

        with caplog.at_level("WARNING"):
            _post_bulk(
                myself,
                config,
                "create_del",
                [{"index": 3, "n": "ephemeral"}, {"index": 3}],
            )

        assert "out of range" not in caplog.text
        result = lst.to_list()
        assert result == [{"n": 0}, {"n": 1}, {"n": 2}]  # nothing appended

    def test_update_then_delete_at_an_interior_new_index_keeps_the_survivor(
        self, myself, config
    ):
        """[append at 3, append at 4, delete 3] -- v1 appends both then
        deletes index 3, ending [0..2, appended-at-4]. The v2 branch's
        net-effect resolution must land in the same place."""
        lst = myself.property_lists.interior_del
        for i in range(3):
            lst.append({"n": i})

        _post_bulk(
            myself,
            config,
            "interior_del",
            [{"index": 3, "n": "a"}, {"index": 4, "n": "b"}, {"index": 3}],
        )

        result = lst.to_list()
        assert result == [{"n": 0}, {"n": 1}, {"n": 2}, {"n": "b"}]

    def test_duplicate_delete_of_the_same_pre_existing_index_deletes_one_row(
        self, myself, config, caplog
    ):
        """Deliberate v2 divergence from v1, pinned: v1's live-length
        delete pass shifts positions between the two deletes, so the
        second `del lst[2]` removes the NEXT row too (two rows gone) --
        the positional-skew class this release exists to kill. Under v2
        the second delete presents a handle the first delete already
        consumed, is reported as a conflict, and exactly one row is gone.
        """
        lst = myself.property_lists.dup_delete
        for i in range(6):
            lst.append({"n": i})

        with caplog.at_level("WARNING"):
            _post_bulk(myself, config, "dup_delete", [{"index": 2}, {"index": 2}])

        assert "concurrently modified" in caplog.text  # the second delete
        result = lst.to_list()
        assert result == [{"n": 0}, {"n": 1}, {"n": 3}, {"n": 4}, {"n": 5}]


class TestItemsActionEndpointContract:
    """Two Phase 3 verification gaps: the de-bounds-checked action
    endpoint must map an out-of-range index to 400 (same message the old
    pre-read produced), and the "add" action's 201 body must carry the
    new item's index."""

    def test_action_update_out_of_range_returns_400(self, myself, config):
        lst = myself.property_lists.action_oob
        lst.append({"n": 0})

        webobj = _run_handler(
            PropertyListItemsHandler,
            myself,
            config,
            "post",
            "action_oob",
            body=json.dumps(
                {"action": "update", "item_index": 7, "item_value": {"n": "x"}}
            ),
        )

        assert webobj.response.status_code == 400
        assert myself.property_lists.action_oob.to_list() == [{"n": 0}]

    def test_action_delete_out_of_range_returns_400(self, myself, config):
        lst = myself.property_lists.action_oob_del
        lst.append({"n": 0})

        webobj = _run_handler(
            PropertyListItemsHandler,
            myself,
            config,
            "post",
            "action_oob_del",
            body=json.dumps({"action": "delete", "item_index": 7}),
        )

        assert webobj.response.status_code == 400
        assert len(myself.property_lists.action_oob_del.to_list()) == 1

    def test_action_add_201_body_carries_the_new_index(self, myself, config):
        lst = myself.property_lists.action_add
        for i in range(2):
            lst.append({"n": i})

        webobj = _run_handler(
            PropertyListItemsHandler,
            myself,
            config,
            "post",
            "action_add",
            body=json.dumps({"action": "add", "item_value": {"n": "new"}}),
        )

        assert webobj.response.status_code == 201
        body = json.loads(webobj.response.body)
        assert body["success"] is True
        assert body["index"] == 2
        assert myself.property_lists.action_add.to_list()[2] == {"n": "new"}
