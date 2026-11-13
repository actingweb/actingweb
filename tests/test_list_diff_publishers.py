"""The publishers that emit list diffs
(thoughts/plans/2026-11-13-attribute-list-v2-port.md, Phase 4): every REST and
web-UI list edit registers a list diff (``list``, ``operation``, ``length``)
from the receiver's closed vocabulary, on the list's own subtarget.

Real DynamoDB Local, handlers invoked directly with a mocked auth result (the
technique of ``test_bulk_list_update_handles.py``)."""

import json
import uuid
from typing import Any
from unittest import mock

import pytest

from actingweb.aw_web_request import AWWebObj
from actingweb.handlers.properties import (
    BULK_LIST_DIFF_LIMIT,
    PropertiesHandler,
    PropertyListItemsHandler,
    PropertyMetadataHandler,
)
from actingweb.property_list import (
    LIST_DIFF_OPERATIONS,
    UNSET,
    build_list_diff,
)


@pytest.fixture(autouse=True)
def _require_dynamodb() -> None:
    import os

    if os.getenv("DATABASE_BACKEND", "dynamodb") != "dynamodb":
        pytest.skip("DynamoDB-only test")


@pytest.fixture
def config() -> Any:
    from actingweb.config import Config

    cfg = Config(database="dynamodb", unique_creator=False)
    cfg.ui = True
    return cfg


@pytest.fixture
def myself(config: Any) -> Any:
    from actingweb.actor import Actor

    actor_id = f"listdiff-{uuid.uuid4()}"
    a = Actor(config=config)
    assert a.create(
        url=f"https://example.com/{actor_id}",
        creator="tester@example.com",
        passphrase="testpass",
        actor_id=actor_id,
    )
    yield a
    a.delete()


class _Diffs:
    """``register_diffs`` calls, captured."""

    def __init__(self, myself: Any) -> None:
        self.calls: list[dict[str, Any]] = []
        self.resyncs: list[tuple[str, str | None]] = []
        self._patches = [
            mock.patch.object(myself, "register_diffs", side_effect=self._record),
            mock.patch.object(
                myself,
                "request_resync",
                side_effect=lambda t, s=None: self.resyncs.append((t, s)) or 0,
            ),
        ]

    def _record(self, target=None, subtarget=None, resource=None, blob=None) -> None:
        self.calls.append(
            {
                "target": target,
                "subtarget": subtarget,
                "resource": resource,
                "blob": blob,
            }
        )

    def __enter__(self) -> "_Diffs":
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        for p in self._patches:
            p.stop()

    def list_diffs(self, name: str) -> list[dict[str, Any]]:
        out = []
        for call in self.calls:
            if call["subtarget"] == name:
                diff = json.loads(call["blob"])
                assert diff["list"] == name
                assert diff["operation"] in LIST_DIFF_OPERATIONS
                assert isinstance(diff["length"], int)
                out.append(diff)
        return out


def _auth(myself: Any) -> Any:
    auth_result = mock.Mock()
    auth_result.success = True
    auth_result.actor = myself
    auth_result.auth_obj = mock.Mock()
    auth_result.authorize = mock.Mock(return_value=True)
    return auth_result


def _run(
    handler_cls: Any, myself: Any, config: Any, method: str, *args: Any, **kw: Any
) -> Any:
    webobj = AWWebObj(**kw)
    handler = handler_cls(webobj, config)
    with (
        mock.patch.object(handler, "authenticate_actor", return_value=_auth(myself)),
        mock.patch.object(handler, "_check_property_permission", return_value=True),
    ):
        getattr(handler, method)(myself.id, *args)
    return handler


def _www(myself: Any, config: Any, path: str, params: dict[str, Any]) -> Any:
    from actingweb.handlers.www import WwwHandler

    handler = WwwHandler(AWWebObj(params=params), config)
    with (
        mock.patch.object(handler, "require_authenticated_actor", return_value=myself),
        mock.patch.object(handler, "_refuse_cross_site", return_value=False),
    ):
        handler.post(myself.id, path)
    return handler


class TestBuildListDiff:
    def test_every_operation_carries_list_operation_and_length(self) -> None:
        for op in LIST_DIFF_OPERATIONS:
            diff = build_list_diff("n", op, length=3, config=None)
            assert diff == {"list": "n", "operation": op, "length": 3}

    def test_none_is_a_legal_item_and_old_item(self) -> None:
        diff = build_list_diff(
            "n", "update", length=1, config=None, item=None, old_item=None, index=0
        )
        assert diff["item"] is None and diff["old_item"] is None
        assert "item" not in build_list_diff(
            "n", "pop", length=0, config=None, item=UNSET
        )

    def test_an_unknown_operation_raises(self) -> None:
        with pytest.raises(ValueError):
            build_list_diff("n", "add", length=0, config=None)

    def test_over_the_threshold_it_is_a_reference(self) -> None:
        cfg = mock.Mock(list_item_span_threshold=100)
        diff = build_list_diff("n", "append", length=1, config=cfg, item="x" * 500)
        assert diff["spanned"] is True and "item" not in diff

    def test_a_spanned_item_not_read_is_a_reference(self) -> None:
        cfg = mock.Mock(list_item_span_threshold=100)
        diff = build_list_diff("n", "remove", length=0, config=cfg, spanned_bytes=900)
        assert diff["spanned"] is True and diff["bytes"] >= 900


class TestRestRows:
    def test_put_index_at_length_is_an_append(self, myself, config) -> None:
        myself.property_lists.notes.extend(["a"])
        with _Diffs(myself) as d:
            _run(
                PropertiesHandler,
                myself,
                config,
                "put",
                "notes",
                params={"index": "1"},
                body='"b"',
            )
        assert d.list_diffs("notes") == [
            {
                "list": "notes",
                "operation": "append",
                "item": "b",
                "index": 1,
                "length": 2,
            }
        ]

    def test_put_index_inside_is_an_update_with_old_item(self, myself, config) -> None:
        myself.property_lists.notes.extend(["a", "b"])
        with _Diffs(myself) as d:
            _run(
                PropertiesHandler,
                myself,
                config,
                "put",
                "notes",
                params={"index": "0"},
                body='"z"',
            )
        assert d.list_diffs("notes") == [
            {
                "list": "notes",
                "operation": "update",
                "item": "z",
                "index": 0,
                "old_item": "a",
                "length": 2,
            }
        ]

    def test_items_add_update_delete(self, myself, config) -> None:
        myself.property_lists.notes.extend(["a", "b"])
        with _Diffs(myself) as d:
            for body in (
                {"action": "add", "item_value": "c"},
                {"action": "update", "item_index": 0, "item_value": "z"},
                {"action": "delete", "item_index": 1},
            ):
                _run(
                    PropertyListItemsHandler,
                    myself,
                    config,
                    "post",
                    "notes",
                    body=json.dumps(body),
                )
        add, update, delete = d.list_diffs("notes")
        assert add == {
            "list": "notes",
            "operation": "append",
            "item": "c",
            "index": 2,
            "length": 3,
        }
        assert update["operation"] == "update" and update["old_item"] == "a"
        assert update["item"] == "z" and update["index"] == 0
        assert delete == {
            "list": "notes",
            "operation": "delete",
            "index": 1,
            "old_item": "b",
            "length": 2,
        }
        assert myself.property_lists.notes.to_list() == ["z", "c"]

    def test_metadata_put(self, myself, config) -> None:
        myself.property_lists.notes.extend(["a"])
        with _Diffs(myself) as d:
            _run(
                PropertyMetadataHandler,
                myself,
                config,
                "put",
                "notes",
                body=json.dumps({"description": "d"}),
            )
        assert d.list_diffs("notes") == [
            {"list": "notes", "operation": "metadata", "length": 1}
        ]

    def test_list_delete(self, myself, config) -> None:
        myself.property_lists.notes.extend(["a"])
        with _Diffs(myself) as d:
            _run(PropertiesHandler, myself, config, "delete", "notes")
        assert d.list_diffs("notes") == [
            {"list": "notes", "operation": "delete_all", "length": 0}
        ]

    def test_empty_list_creation_json_and_form(self, myself, config) -> None:
        with _Diffs(myself) as d:
            _run(
                PropertiesHandler,
                myself,
                config,
                "post",
                "",
                body=json.dumps({"fresh": {"_type": "list", "description": "x"}}),
            )
            _run(
                PropertiesHandler,
                myself,
                config,
                "post",
                "",
                params={"property": "form_list", "property_type": "list"},
            )
        assert d.list_diffs("fresh") == [
            {"list": "fresh", "operation": "extend", "items": [], "length": 0}
        ]
        assert d.list_diffs("form_list") == [
            {"list": "form_list", "operation": "extend", "items": [], "length": 0}
        ]
        # A form without a description stores the list (it created nothing).
        assert myself.property_lists.exists("form_list")
        # No scalar diff carries the text marker any more.
        assert not [c for c in d.calls if c["subtarget"] is None]


class TestBulk:
    def _bulk(self, myself, config, items: list[dict[str, Any]], **extra: Any) -> Any:
        return _run(
            PropertiesHandler,
            myself,
            config,
            "post",
            "",
            body=json.dumps({"notes": {"items": items}, **extra}),
        )

    def test_a_run_of_appends_is_one_extend(self, myself, config) -> None:
        myself.property_lists.notes.extend(["a"])
        with _Diffs(myself) as d:
            self._bulk(myself, config, [{"index": 1, "v": 1}, {"index": 2, "v": 2}])
        assert d.list_diffs("notes") == [
            {
                "list": "notes",
                "operation": "extend",
                "items": [{"v": 1}, {"v": 2}],
                "length": 3,
            }
        ]

    def test_a_mixed_batch_keeps_order_and_the_response(self, myself, config) -> None:
        lst = myself.property_lists.notes
        lst.extend([{"n": 0}, {"n": 1}, {"n": 2}])
        with _Diffs(myself) as d:
            h = self._bulk(
                myself,
                config,
                [{"index": 0, "n": "u"}, {"index": 3, "n": "new"}, {"index": 1}],
                color={"v": 1},
            )
        ops = [x["operation"] for x in d.list_diffs("notes")]
        assert ops == ["update", "append", "delete"]
        assert d.list_diffs("notes")[-1]["old_item"] == {"n": 1}
        assert d.list_diffs("notes")[-1]["index"] == 1
        scalars = [c for c in d.calls if c["subtarget"] is None]
        assert [json.loads(c["blob"]) for c in scalars] == [{"color": {"v": 1}}]
        body = json.loads(h.response.body)
        assert body["notes"].startswith("[Bulk update:")
        assert lst.to_list() == [{"n": "u"}, {"n": 2}, {"n": "new"}]

    @pytest.mark.parametrize("count", [BULK_LIST_DIFF_LIMIT, BULK_LIST_DIFF_LIMIT + 1])
    def test_the_threshold(self, myself, config, count) -> None:
        lst = myself.property_lists.notes
        lst.extend([{"n": i} for i in range(count)])
        with _Diffs(myself) as d:
            self._bulk(
                myself, config, [{"index": i, "n": f"u{i}"} for i in range(count)]
            )
        if count <= BULK_LIST_DIFF_LIMIT:
            assert len(d.list_diffs("notes")) == count and d.resyncs == []
        else:
            assert d.list_diffs("notes") == []
            assert d.resyncs == [("properties", "notes")]
        # No suspension row either way.
        assert myself.is_subscription_suspended("properties", "notes") is False

    def test_a_hook_rejected_batch_still_announces_what_landed(
        self, myself, config
    ) -> None:
        lst = myself.property_lists.notes
        lst.extend(["a"])
        hooks = mock.Mock()
        hooks.execute_property_hooks.return_value = None
        webobj = AWWebObj(body=json.dumps({"notes": {"items": [{"index": 1, "v": 1}]}}))
        handler = PropertiesHandler(webobj, config, hooks=hooks)
        with (
            _Diffs(myself) as d,
            mock.patch.object(
                handler, "authenticate_actor", return_value=_auth(myself)
            ),
            mock.patch.object(handler, "_check_property_permission", return_value=True),
            mock.patch.object(
                handler, "_get_actor_interface", return_value=mock.Mock()
            ),
        ):
            handler.post(myself.id, "")
        assert handler.response.status_code == 403
        assert [x["operation"] for x in d.list_diffs("notes")] == ["append"]


class TestWebUiRows:
    def test_add_update_delete_metadata_create_and_simple(self, myself, config) -> None:
        myself.property_lists.notes.extend(["a", "b"])
        with _Diffs(myself) as d:
            _www(
                myself,
                config,
                "properties/notes/items",
                {"action": "add", "item_value": '"c"'},
            )
            _www(
                myself,
                config,
                "properties/notes/items",
                {"action": "update", "item_index": "0", "item_value": '"z"'},
            )
            _www(
                myself,
                config,
                "properties/notes/items",
                {"action": "delete", "item_index": "1"},
            )
            _www(
                myself,
                config,
                "properties/notes/metadata",
                {"action": "update", "description": "d"},
            )
            _www(
                myself,
                config,
                "properties",
                {"property_name": "fresh", "property_type": "list"},
            )
            _www(
                myself,
                config,
                "properties",
                {"property_name": "color", "property_value": "red"},
            )
        ops = [x["operation"] for x in d.list_diffs("notes")]
        assert ops == ["append", "update", "delete", "metadata"]
        assert d.list_diffs("notes")[1]["old_item"] == "a"
        assert d.list_diffs("fresh") == [
            {"list": "fresh", "operation": "extend", "items": [], "length": 0}
        ]
        assert [c["blob"] for c in d.calls if c["subtarget"] == "color"] == ["red"]
        assert myself.property_lists.exists("fresh")


class TestVerificationFindings:
    """Verification 2026-11-13 (outside voice 1, 2, 5, 6, 7)."""

    def test_a_move_to_top_batch_leaves_the_replica_equal(self, myself, config) -> None:
        from actingweb.remote_storage import RemotePeerStore
        from tests.mcp_token_double import make_config

        lst = myself.property_lists.notes
        lst.extend([{"v": "A"}, {"v": "B"}, {"v": "C"}])
        before = lst.to_list()
        with _Diffs(myself) as d:
            _run(
                PropertiesHandler,
                myself,
                config,
                "post",
                "",
                body=json.dumps(
                    {"notes": {"items": [{"index": 0, "v": "C"}, {"index": 2}]}}
                ),
            )
        core = mock.MagicMock()
        core.id = "a" * 32
        core.config, _ = make_config()
        replica = RemotePeerStore(core, "b" * 32)
        replica.set_list("notes", before)
        for diff in d.list_diffs("notes"):
            assert replica.apply_callback_data({"notes": diff}).out_of_step is None
        assert replica.get_list("notes") == lst.to_list() == [{"v": "C"}, {"v": "B"}]

    def _flaky_append(self, fail_on: int) -> Any:
        from actingweb.property_list import ListProperty

        real = ListProperty.append
        calls = {"n": 0}

        def flaky(self: Any, item: Any) -> None:
            calls["n"] += 1
            if calls["n"] == fail_on:
                raise ValueError("contended")
            real(self, item)

        return mock.patch.object(ListProperty, "append", flaky)

    def test_a_batch_stopped_part_way_announces_what_landed(
        self, myself, config
    ) -> None:
        myself.property_lists.notes.extend(["a"])
        items = [{"index": 0, "v": "u"}, {"index": 1, "v": 1}, {"index": 2, "v": 2}]
        with _Diffs(myself) as d, self._flaky_append(2):
            h = _run(
                PropertiesHandler,
                myself,
                config,
                "post",
                "",
                body=json.dumps({"notes": {"items": items}}),
            )
        assert h.response.status_code >= 500  # stopped part way
        assert [x["operation"] for x in d.list_diffs("notes")] == ["update", "append"]

    def test_a_large_batch_stopped_part_way_still_resyncs(self, myself, config) -> None:
        count = BULK_LIST_DIFF_LIMIT + 5
        myself.property_lists.notes.extend(["a"])
        items = [{"index": i, "v": i} for i in range(count)]
        with _Diffs(myself) as d, self._flaky_append(3):
            _run(
                PropertiesHandler,
                myself,
                config,
                "post",
                "",
                body=json.dumps({"notes": {"items": items}}),
            )
        assert d.resyncs == [("properties", "notes")]

    def test_a_resync_fault_does_not_fail_a_committed_batch(
        self, myself, config
    ) -> None:
        from actingweb.db.exceptions import DbError

        count = BULK_LIST_DIFF_LIMIT + 1
        myself.property_lists.notes.extend([{"n": i} for i in range(count)])
        items = [{"index": i, "n": "u"} for i in range(count)]
        with (
            _Diffs(myself),
            mock.patch.object(
                myself, "request_resync", side_effect=DbError("throttled")
            ),
        ):
            h = _run(
                PropertiesHandler,
                myself,
                config,
                "post",
                "",
                body=json.dumps({"notes": {"items": items}}),
            )
        assert h.response.status_code == 201

    def test_a_rank_addressed_web_edit_carries_the_position(
        self, myself, config
    ) -> None:
        lst = myself.property_lists.notes
        lst.extend(["dup", "dup", "z"])
        second = lst.items_with_handles(resolve=False)[1][0]
        with _Diffs(myself) as d:
            _www(
                myself,
                config,
                "properties/notes/items",
                {"action": "update", "item_rank": second.rank, "item_value": '"new"'},
            )
        (diff,) = d.list_diffs("notes")
        assert diff["index"] == 1 and diff["old_item"] == "dup"
        third = lst.items_with_handles(resolve=False)[2][0]
        with _Diffs(myself) as d:
            _www(
                myself,
                config,
                "properties/notes/items",
                {"action": "delete", "item_rank": third.rank},
            )
        (diff,) = d.list_diffs("notes")
        assert diff == {
            "list": "notes",
            "operation": "delete",
            "index": 2,
            "old_item": "z",
            "length": 2,
        }

    @pytest.mark.parametrize("route", ["json", "form", "www"])
    def test_a_list_the_post_hook_refuses_is_not_created(
        self, myself, config, route
    ) -> None:
        hooks = mock.Mock()
        hooks.execute_property_hooks.return_value = None
        if route == "www":
            from actingweb.handlers.www import WwwHandler

            handler: Any = WwwHandler(
                AWWebObj(params={"property_name": "refused", "property_type": "list"}),
                config,
                hooks=hooks,
            )
            with (
                mock.patch.object(
                    handler, "require_authenticated_actor", return_value=myself
                ),
                mock.patch.object(handler, "_refuse_cross_site", return_value=False),
                mock.patch.object(
                    handler, "_get_actor_interface", return_value=mock.Mock()
                ),
            ):
                handler.post(myself.id, "properties")
        else:
            kw: dict[str, Any] = (
                {"body": json.dumps({"refused": {"_type": "list"}})}
                if route == "json"
                else {"params": {"property": "refused", "property_type": "list"}}
            )
            handler = PropertiesHandler(AWWebObj(**kw), config, hooks=hooks)
            with (
                mock.patch.object(
                    handler, "authenticate_actor", return_value=_auth(myself)
                ),
                mock.patch.object(
                    handler, "_check_property_permission", return_value=True
                ),
                mock.patch.object(
                    handler, "_get_actor_interface", return_value=mock.Mock()
                ),
            ):
                handler.post(myself.id, "")
        assert not myself.property_lists.exists("refused")
