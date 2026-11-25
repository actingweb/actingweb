"""A value ``json`` cannot encode is refused before the store call, as a
``ValueError`` (iteration 22; the todo
``unserialisable-value-reads-as-a-store-fault``): not a ``DbError``, which
answers 503 with ``Retry-After`` and invites a retry that can never succeed.
Runs on the configured backend (both in the Full tier)."""

from __future__ import annotations

import datetime
import os
import uuid
from collections.abc import Callable
from typing import Any

import pytest

from actingweb.db import get_attribute
from actingweb.db.exceptions import DbError, UnserialisableValue
from tests._adoption_helpers import make_config

BAD = {"when": datetime.datetime(2026, 11, 20, 12, 0)}
NON_FINITE = {"x": float("inf")}
BUCKET = "unserialisable"


def _writes(db: Any, actor: str, bad: Any = BAD) -> dict[str, Callable[[], Any]]:
    return {
        "set_attr": lambda: db.set_attr(
            actor_id=actor, bucket=BUCKET, name="a", data=bad
        ),
        "conditional_update_attr": lambda: db.conditional_update_attr(
            actor_id=actor, bucket=BUCKET, name="b", old_data={"x": 1}, new_data=bad
        ),
        "create_attr_if_absent": lambda: db.create_attr_if_absent(
            actor_id=actor, bucket=BUCKET, name="c", data=bad
        ),
        "create_attr_if_not_exists": lambda: db.create_attr_if_not_exists(
            actor, BUCKET, "d", bad
        ),
        "create_attrs_if_not_exist": lambda: db.create_attrs_if_not_exist(
            actor, BUCKET, {"e": bad}
        ),
        "set_attr_if_data_equals": lambda: db.set_attr_if_data_equals(
            actor, BUCKET, "f", '{"x": 1}', bad
        ),
        "set_attr_if_data_equals expected": lambda: db.set_attr_if_data_equals(
            actor, BUCKET, "h", bad, {"x": 1}
        ),
        "delete_attr_if_data_equals expected": lambda: db.delete_attr_if_data_equals(
            actor, BUCKET, "i", bad
        ),
        "put_attr": lambda: db.put_attr(actor, BUCKET, "g", bad),
    }


WRITES = [
    "set_attr",
    "conditional_update_attr",
    "create_attr_if_absent",
    "create_attr_if_not_exists",
    "create_attrs_if_not_exist",
    "set_attr_if_data_equals",
    "set_attr_if_data_equals expected",
    "delete_attr_if_data_equals expected",
    "put_attr",
]


@pytest.mark.parametrize("write", WRITES)
def test_an_unserialisable_value_is_refused_before_the_store(write: str) -> None:
    config = make_config(database=os.environ.get("DATABASE_BACKEND", "dynamodb"))
    db = get_attribute(config)
    actor = "unser" + uuid.uuid4().hex[:12]
    with pytest.raises(UnserialisableValue) as refused:
        _writes(db, actor)[write]()
    assert isinstance(refused.value, ValueError)
    assert isinstance(refused.value, TypeError)  # what json raised before
    assert not isinstance(refused.value, DbError)
    assert not get_attribute(config).get_bucket(actor_id=actor, bucket=BUCKET)


@pytest.mark.parametrize("write", WRITES)
def test_a_non_finite_number_is_refused_before_the_store(write: str) -> None:
    """AC-26 (plans/2026-11-25-attribute-compare-and-delete.md): ``NaN`` and
    ``Infinity`` are not JSON. DynamoDB stored them and PostgreSQL's
    ``jsonb`` raised ``DbError``; both now refuse them before the store."""
    config = make_config(database=os.environ.get("DATABASE_BACKEND", "dynamodb"))
    db = get_attribute(config)
    actor = "unser" + uuid.uuid4().hex[:12]
    with pytest.raises(UnserialisableValue) as refused:
        _writes(db, actor, NON_FINITE)[write]()
    assert not isinstance(refused.value, DbError)
    assert not get_attribute(config).get_bucket(actor_id=actor, bucket=BUCKET)


def test_a_list_item_is_not_attribute_data() -> None:
    """AC-26's boundary: a list stores each item as a string, so an item
    holding a non-finite number is stored as before on both backends."""
    import math

    from actingweb.attribute_list_store import AttributeListStore

    config = make_config(database=os.environ.get("DATABASE_BACKEND", "dynamodb"))
    actor = "unser" + uuid.uuid4().hex[:12]
    lst = AttributeListStore(actor_id=actor, bucket=BUCKET, config=config).get("l")
    try:
        lst.append({"v": float("inf")})
        assert math.isinf(lst.to_list()[0]["v"])
    finally:
        lst.delete()
