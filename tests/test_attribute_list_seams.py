"""The seams Phase 2 of thoughts/plans/2026-11-13-attribute-list-v2-port.md
touches around attribute lists: replica teardown with the side bucket,
``actingweb-peer-state``'s side-bucket whitelist, the callback-state cleanup
by peer segment, a list arriving where a replica holds a scalar, and the
start-up refusal of a backend without the list primitives."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from actingweb.db.exceptions import DbError
from actingweb.remote_storage import RemotePeerStore
from tests.mcp_token_double import MemoryStore, make_config

ACTOR = "a" * 32
PEER = "b" * 32


@pytest.fixture
def env() -> tuple[Any, MemoryStore]:
    return make_config()


def _actor(config: Any) -> Any:
    actor = MagicMock()
    actor.id = ACTOR
    actor.config = config
    return actor


class TestReplicaTeardown:
    def test_delete_all_leaves_no_row_in_either_bucket(self, env):
        config, store = env
        config.list_item_span_threshold = 64
        remote = RemotePeerStore(_actor(config), PEER)
        remote.set_list("notes", [{"t": "x" * 500}, {"t": "y"}])
        remote.set_value("scalar", {"v": 1})
        assert store.rows.get(f"{ACTOR}:remote:{PEER}$aux")
        remote.delete_all()
        assert not store.rows.get(f"{ACTOR}:remote:{PEER}")
        assert not store.rows.get(f"{ACTOR}:remote:{PEER}$aux")

    def test_a_side_bucket_fault_still_deletes_the_main_bucket(self, env):
        config, store = env
        remote = RemotePeerStore(_actor(config), PEER)
        remote.set_list("notes", ["a"])
        base = config.DbAttribute.DbAttribute

        class Faulty(base):  # type: ignore[misc,valid-type]
            def delete_bucket(self, actor_id: str, bucket: str) -> bool:
                if bucket.endswith("$aux"):
                    raise DbError("throttled")
                return super().delete_bucket(actor_id, bucket)

        config.DbAttribute.DbAttribute = Faulty
        with pytest.raises(DbError):
            remote.delete_all()
        assert not store.rows.get(f"{ACTOR}:remote:{PEER}")


class TestPeerStateWhitelist:
    @pytest.mark.parametrize(
        ("bucket", "peer"),
        [
            (f"remote:{PEER}", PEER),
            (f"remote:{PEER}$aux", PEER),
            ("remote:not a peer$aux", None),
            ("remote:other$aux$aux", None),
        ],
    )
    def test_the_side_bucket_is_its_peers(self, bucket, peer):
        from actingweb.maintenance.peer_state import _remote_peer

        assert _remote_peer(bucket) == peer


class TestCallbackStateByPeerSegment:
    def test_deleting_peer_b_leaves_peer_a_colon_b(self, env):
        from actingweb.callback_processor import CallbackProcessor

        config, store = env
        rows = store.bucket(ACTOR, "_callback_state")
        for name in (
            "state:b:sub1",
            "pending:b:sub1",
            "state:a:b:sub2",
            "pending:a:b:sub2",
            "state:bb:sub3",
        ):
            rows[name] = {"data": {"x": 1}}
        processor = CallbackProcessor(_actor(config))
        processor.clear_all_state_for_peer("b")
        assert set(store.names(ACTOR, "_callback_state")) == {
            "state:a:b:sub2",
            "pending:a:b:sub2",
            "state:bb:sub3",
        }


class TestListOverAStoredScalar:
    @pytest.mark.parametrize(
        "scalar",
        [
            {"action": "add", "index": 0, "value": "x"},
            {"index": 0, "value": "x"},
            {"value": "Updated 3 items"},
        ],
    )
    def test_a_list_diff_for_a_name_held_as_a_scalar_ends_in_the_list(
        self, env, scalar
    ):
        config, _ = env
        remote = RemotePeerStore(_actor(config), PEER)
        remote.set_value("notes", scalar)
        result = remote.apply_callback_data(
            {"notes": {"list": "notes", "operation": "append", "item": "first"}}
        )
        assert result["notes"]["success"] is True
        assert remote.get_list("notes") == ["first"]
        assert remote.get_value("notes") is None

    def test_reading_a_name_held_as_a_scalar_as_a_list_is_empty(self, env):
        config, _ = env
        remote = RemotePeerStore(_actor(config), PEER)
        remote.set_value("notes", {"index": 0, "value": "x"})
        assert remote.get_list("notes") == []
        assert remote.get_value("notes") == {"index": 0, "value": "x"}

    def test_a_baseline_list_for_a_name_held_as_a_scalar_ends_in_the_list(self, env):
        config, _ = env
        remote = RemotePeerStore(_actor(config), PEER)
        remote.set_value("notes", {"index": 0, "value": "x"})
        remote.set_list("notes", ["a", "b"])
        assert remote.get_list("notes") == ["a", "b"]
        assert remote.get_value("notes") is None


class TestCheckReady:
    def _app(self, config: Any) -> Any:
        from actingweb.interface.app import ActingWebApp

        app = ActingWebApp(aw_type="urn:actingweb:test:seams", fqdn="test.example.com")
        app.get_config = lambda: config  # type: ignore[method-assign]
        return app

    def test_a_backend_without_the_list_primitives_is_refused_by_name(self, env):
        from actingweb.interface.app import AttributeSchemaNotReady

        config, _ = env
        base = config.DbAttribute.DbAttribute
        lacking = type("Lacking", (base,), {"put_attr": None, "get_attr_range": None})
        config.DbAttribute.DbAttribute = lacking
        app = self._app(config)
        with pytest.raises(AttributeSchemaNotReady) as caught:
            app._check_attribute_schema_ready()  # pyright: ignore[reportPrivateUsage]
        assert "get_attr_range" in str(caught.value)
        assert "put_attr" in str(caught.value)

    def test_a_complete_backend_passes(self, env):
        config, _ = env
        app = self._app(config)
        app._check_attribute_schema_ready()  # pyright: ignore[reportPrivateUsage]
        assert app._attribute_schema_checked  # pyright: ignore[reportPrivateUsage]
