"""Attribute list rows against DynamoDB's 400 KB item cap
(thoughts/plans/2026-11-13-attribute-list-v2-port.md, Phase 2).

The backend stores the core's string as JSON, which escapes it again: a
value of quotes doubles, and a control character in the str() fallback
becomes six bytes. The attribute storage's span threshold is the row cap,
less the key overhead, over six; these write items of the worst escaping
just under and just over it, and record the growth they measure.
"""

import json
import os
import uuid
from typing import Any

import pytest

from actingweb.attribute_list import AttributeListStorage, ListAttribute
from actingweb.interface.app import ActingWebApp
from actingweb.property_list_span import encode_item

DATABASE_BACKEND = os.environ.get("DATABASE_BACKEND", "dynamodb")

pytestmark = pytest.mark.skipif(
    DATABASE_BACKEND != "dynamodb", reason="DynamoDB's item size cap"
)


@pytest.fixture
def config(docker_services, setup_database, worker_info) -> Any:  # noqa: ARG001
    return (
        ActingWebApp(
            aw_type="urn:actingweb:test:attribute_row_size",
            database="dynamodb",
            fqdn="test.example.com",
            proto="http://",
        )
        .with_unique_creator(False)
        .get_config()
    )


def _item_of(encoded_bytes: int, unit: str) -> str:
    """A string whose encoded form is ``encoded_bytes`` long, of ``unit``."""
    per = len(json.dumps(unit)) - 2
    return unit * ((encoded_bytes - 2) // per)


@pytest.mark.parametrize(
    ("unit", "growth_at_most"),
    [('"', 2.0), ("\\", 2.0), ("é", 1.2), ("\x01", 1.2), ("a", 1.0)],
)
def test_worst_escaping_under_and_over_the_threshold(config, unit, growth_at_most):
    actor = f"rowsize-{uuid.uuid4().hex}"
    bucket = "remote:" + "d" * 32
    threshold = AttributeListStorage(actor, bucket, config).span_threshold
    assert threshold is not None and threshold * 6 + 4096 <= 409_600

    under = _item_of(threshold, unit)
    over = under + unit * 4
    lst = ListAttribute(actor, bucket, "notes", config)
    lst.extend([under, over])
    assert ListAttribute(actor, bucket, "notes", config).to_list() == [under, over]

    from actingweb.db import get_attribute

    db = get_attribute(config)
    heads = db.get_attr_range(actor, bucket, "list:notes-#", "list:notes-#~")
    stored = sorted(len(json.dumps(v)) for v in heads.values())
    value = encode_item(under)
    # The backend's JSON adds two quotes and escapes the item's own two;
    # past that it grows per character by at most the factor named.
    assert len(json.dumps(value)) <= growth_at_most * len(value) + 4
    # The item under the threshold is one row; the one over it spans.
    assert len(value) <= threshold < len(encode_item(over))
    assert db.get_attr_prefix(actor, bucket + "$aux", "list:notes-$span-")
    assert stored[-1] < 409_600 - 4096
