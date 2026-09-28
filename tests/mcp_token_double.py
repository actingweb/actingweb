"""In-memory attribute store for MCP OAuth2 server and token-manager tests.

Copied from the SPA rotation double (``test_oauth2_spa_refresh_rotation.py``)
and extended so it behaves like a real backend where the MCP code depends on
it:

- ``get_attr`` and ``get_bucket`` return **deep copies**, so a caller mutating
  what it loaded never changes storage (the real backends deserialise);
- ``conditional_update_attr`` compares against the stored value, and a test
  can force the next one to lose (``store.cas_hook``);
- ``set_attr(ttl_seconds=)`` is recorded (not enforced) in ``store.ttls``;
- ``delete_by_chain`` and ``delete_expired`` are implemented; the latter is
  recorded in ``store.purges`` and deletes nothing, like DynamoDB;
- ``get_attr_strict`` is implemented, and a bucket named in
  ``store.faulty_buckets`` faults: ``get_bucket`` returns None (a caught
  backend fault, the PostgreSQL shape) and ``get_attr_strict`` raises;
- a bucket named in ``store.raising_buckets`` makes ``get_bucket`` raise
  (the DynamoDB shape: a throttle mid-page propagates);
- ``store.chain_delete_fault`` makes ``delete_by_chain`` return 0 without
  deleting (``"zero"``, the PostgreSQL shape), raise (``"raise"``, the
  DynamoDB shape), or delete every row but the last and then raise
  (``"partial"``, a DynamoDB fault part-way through its row-by-row delete;
  ``defer_name`` puts that row last, so it is the one that survives);
- ``store.cas_fault`` makes ``conditional_update_attr`` answer False without
  writing, the shape both backends give a throttle or a dropped connection;
  ``store.cas_lost_response`` makes it write and still answer False (the
  write landed, the response was lost);
  ``conditional_update_attr(ttl_seconds=)`` is recorded in ``store.ttls``;
- ``store.delete_faults`` names ``(actor_id, bucket, name)`` rows whose
  deletes fail: ``delete_attr_conditional`` answers False and ``delete_attr``
  answers True (DynamoDB swallows a failed delete), and the row stays.

``make_config()`` returns a real :class:`~actingweb.config.Config` whose
``DbAttribute`` module is swapped for the double, so everything that reaches
storage through ``actingweb.attribute.Attributes`` or ``get_attribute`` lands
here.
"""

import copy
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

from actingweb.config import Config
from actingweb.constants import OAUTH2_SYSTEM_ACTOR


class MemoryStore:
    """Rows keyed ``"{actor_id}:{bucket}" -> {name: {"data": ...}}``."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, dict[str, Any]]] = {}
        self.ttls: dict[tuple[str, str, str], int | None] = {}
        self.purges: list[list[str] | None] = []
        # Called as cas_hook(actor_id, bucket, name) before a compare-and-swap;
        # returning False makes that CAS lose.
        self.cas_hook: Callable[[str, str, str], bool] | None = None
        # Buckets whose reads fault: get_bucket returns None (a caught backend
        # fault) and get_attr_strict raises.
        self.faulty_buckets: set[str] = set()
        # Buckets whose get_bucket raises (DynamoDB mid-page throttle).
        self.raising_buckets: set[str] = set()
        # "zero", "raise" or "partial": how delete_by_chain faults, when set.
        self.chain_delete_fault: str | None = None
        # When True, a compare-and-swap answers False without writing.
        self.cas_fault = False
        # When True, a compare-and-swap writes and then answers False.
        self.cas_lost_response = False
        # Rows whose deletes fail (the row stays).
        self.delete_faults: set[tuple[str, str, str]] = set()
        # Buckets whose set_attr answers False without writing.
        self.write_faults: set[str] = set()

    def bucket(self, actor_id: str, bucket: str) -> dict[str, dict[str, Any]]:
        return self.rows.setdefault(f"{actor_id}:{bucket}", {})

    def data(self, actor_id: str, bucket: str, name: str) -> Any:
        row = self.rows.get(f"{actor_id}:{bucket}", {}).get(name)
        return None if row is None else row.get("data")

    def names(self, actor_id: str, bucket: str) -> set[str]:
        return set(self.rows.get(f"{actor_id}:{bucket}", {}))


def make_config() -> tuple[Config, MemoryStore]:
    """A real Config whose attribute storage is an in-memory MemoryStore."""
    store = MemoryStore()

    class MockDbAttribute:
        def get_bucket(self, actor_id: str, bucket: str) -> dict[str, Any] | None:
            if bucket in store.raising_buckets:
                raise RuntimeError(f"throttled reading {bucket}")
            if bucket in store.faulty_buckets:
                return None
            return copy.deepcopy(store.rows.get(f"{actor_id}:{bucket}", {}))

        def get_attr_strict(self, actor_id: str, bucket: str, name: str) -> Any:
            if bucket in store.faulty_buckets:
                raise RuntimeError(f"backend fault reading {bucket}")
            return copy.deepcopy(store.rows.get(f"{actor_id}:{bucket}", {}).get(name))

        def get_attr(self, actor_id: str, bucket: str, name: str) -> Any:
            return copy.deepcopy(store.rows.get(f"{actor_id}:{bucket}", {}).get(name))

        def set_attr(
            self,
            actor_id: str,
            bucket: str,
            name: str,
            data: Any,
            timestamp: Any = None,
            ttl_seconds: int | None = None,
        ) -> bool:
            if bucket in store.write_faults:
                return False
            if not data:
                store.rows.get(f"{actor_id}:{bucket}", {}).pop(name, None)
                return True
            store.bucket(actor_id, bucket)[name] = {"data": copy.deepcopy(data)}
            store.ttls[(actor_id, bucket, name)] = ttl_seconds
            return True

        def delete_attr(self, actor_id: str, bucket: str, name: str) -> bool:
            if (actor_id, bucket, name) in store.delete_faults:
                return True
            store.rows.get(f"{actor_id}:{bucket}", {}).pop(name, None)
            return True

        def delete_attr_conditional(
            self, actor_id: str, bucket: str, name: str
        ) -> bool:
            if (actor_id, bucket, name) in store.delete_faults:
                return False
            return (
                store.rows.get(f"{actor_id}:{bucket}", {}).pop(name, None) is not None
            )

        def conditional_update_attr(
            self,
            actor_id: str,
            bucket: str,
            name: str,
            old_data: Any,
            new_data: Any,
            timestamp: Any = None,
            ttl_seconds: int | None = None,
        ) -> bool:
            if store.cas_fault:
                return False
            if store.cas_hook is not None and not store.cas_hook(
                actor_id, bucket, name
            ):
                return False
            current = store.rows.get(f"{actor_id}:{bucket}", {}).get(name)
            if current is None or current.get("data") != old_data:
                return False
            store.bucket(actor_id, bucket)[name] = {"data": copy.deepcopy(new_data)}
            if ttl_seconds is not None:
                store.ttls[(actor_id, bucket, name)] = ttl_seconds
            return not store.cas_lost_response

        def delete_bucket(self, actor_id: str, bucket: str) -> bool:
            return store.rows.pop(f"{actor_id}:{bucket}", None) is not None

        def delete_by_chain(
            self,
            actor_id: str | None = None,
            buckets: list[str] | None = None,
            chain_id: str | None = None,
            defer_name: str | None = None,
        ) -> int:
            if store.chain_delete_fault == "raise":
                raise RuntimeError("throttled deleting chain")
            if store.chain_delete_fault == "zero":
                return 0
            if not actor_id or not chain_id or not buckets:
                return 0
            matches: list[tuple[dict[str, Any], str]] = []
            deferred: list[tuple[dict[str, Any], str]] = []
            for bucket in buckets:
                items = store.rows.get(f"{actor_id}:{bucket}", {})
                for name, rec in list(items.items()):
                    data = rec.get("data") or {}
                    if isinstance(data, dict) and data.get("chain_id") == chain_id:
                        (deferred if name == defer_name else matches).append(
                            (items, name)
                        )
            deleted = 0
            ordered = matches + deferred
            for i, (items, name) in enumerate(ordered):
                if store.chain_delete_fault == "partial" and i == len(ordered) - 1:
                    raise RuntimeError("throttled part-way through the chain")
                del items[name]
                deleted += 1
            return deleted

        def delete_expired(
            self, now_epoch: int | None = None, buckets: list[str] | None = None
        ) -> int:
            store.purges.append(list(buckets) if buckets else None)
            return 0

    db_mod = MagicMock()
    db_mod.DbAttribute = MockDbAttribute
    config = Config(fqdn="test.example.com", proto="https://", database="dynamodb")
    config.DbAttribute = db_mod
    return config, store


def index_actor(store: MemoryStore, bucket: str, name: str) -> Any:
    """The actor id a global index row points at, or None."""
    return store.data(OAUTH2_SYSTEM_ACTOR, bucket, name)
