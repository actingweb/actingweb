"""Storage read counters shared by the tests that budget reads.

Two counters:

- :func:`count_dynamodb_operations` counts DynamoDB API calls by operation
  name, at ``botocore``'s ``_make_api_call``. A ``before-call.dynamodb``
  handler silently counts nothing under pynamodb (``docs/migration/v3.13.rst``),
  so a naive version would pass vacuously.
- :func:`count_reads` is backend-agnostic: it counts actor-row reads
  (``DbActor.get``) and subscription-list fetches (``DbSubscriptionList.fetch``)
  at the backend class of the given config, and on PostgreSQL every
  connection taken (``get_connection`` in each backend module).

A test that asserts a zero should also assert a non-zero elsewhere, so a
counter that records nothing cannot pass it.
"""

from __future__ import annotations

import collections
import importlib
import pkgutil
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from typing import Any
from unittest import mock

import pytest

from actingweb.db import get_actor, get_subscription_list


def backend_of(config: Any) -> str:
    """``"dynamodb"`` or ``"postgresql"``: the backend ``config`` resolves to."""
    return type(get_actor(config)).__module__.split(".")[2]


def count_dynamodb_operations(
    monkeypatch: pytest.MonkeyPatch,
) -> collections.Counter[str]:
    """Count DynamoDB API calls by operation name until the test ends."""
    import botocore.client

    counts: collections.Counter[str] = collections.Counter()
    original = botocore.client.BaseClient._make_api_call

    def _counting(self: Any, operation_name: str, api_params: Any) -> Any:
        if self.meta.service_model.service_name == "dynamodb":
            counts[operation_name] += 1
        return original(self, operation_name, api_params)

    monkeypatch.setattr(botocore.client.BaseClient, "_make_api_call", _counting)
    return counts


@contextmanager
def count_reads(config: Any) -> Iterator[collections.Counter[str]]:
    """Count ``actor_get``, ``subscription_list_fetch`` and, on PostgreSQL,
    ``connection`` while the block runs."""
    counts: collections.Counter[str] = collections.Counter()
    actor_cls = type(get_actor(config))
    list_cls = type(get_subscription_list(config))
    real_get = actor_cls.get
    real_fetch = list_cls.fetch

    def get(self: Any, *a: Any, **k: Any) -> Any:
        counts["actor_get"] += 1
        return real_get(self, *a, **k)

    def fetch(self: Any, *a: Any, **k: Any) -> Any:
        counts["subscription_list_fetch"] += 1
        return real_fetch(self, *a, **k)

    with ExitStack() as stack:
        stack.enter_context(mock.patch.object(actor_cls, "get", get))
        stack.enter_context(mock.patch.object(list_cls, "fetch", fetch))
        if backend_of(config) == "postgresql":
            import actingweb.db.postgresql as pg

            for info in pkgutil.iter_modules(pg.__path__):
                module = importlib.import_module(f"{pg.__name__}.{info.name}")
                real = getattr(module, "get_connection", None)
                if real is None or info.name == "connection":
                    continue

                def counted(*a: Any, _real: Any = real, **k: Any) -> Any:
                    counts["connection"] += 1
                    return _real(*a, **k)

                stack.enter_context(
                    mock.patch.object(module, "get_connection", counted)
                )
        yield counts
