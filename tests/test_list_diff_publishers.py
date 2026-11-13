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
            "operation": "remove",
            "item": "b",
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
        assert ops == ["update", "append", "remove"]
        assert d.list_diffs("notes")[-1]["item"] == {"n": 1}
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
        assert ops == ["append", "update", "remove", "metadata"]
        assert d.list_diffs("notes")[1]["old_item"] == "a"
        assert d.list_diffs("fresh") == [
            {"list": "fresh", "operation": "extend", "items": [], "length": 0}
        ]
        assert [c["blob"] for c in d.calls if c["subtarget"] == "color"] == ["red"]
        assert myself.property_lists.exists("fresh")
