"""Benchmark fixtures that create the tables they use.

``TestAttributePerformance`` calls the static ``DbAttribute.set_attr`` and
``get_attr``, which never run the constructor's ``ensure_table``. On a fresh
DynamoDB container they failed with ``ResourceNotFoundException`` until some
other test had created ``test_attributes``.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="module", autouse=True)
def _ensure_benchmark_tables() -> None:
    if os.environ.get("DATABASE_BACKEND", "dynamodb") != "dynamodb":
        return
    from actingweb.db.dynamodb._ensure import ensure_table
    from actingweb.db.dynamodb.attribute import Attribute

    ensure_table(Attribute)
