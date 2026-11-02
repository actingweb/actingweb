"""DynamoDB list ``fetch`` with an empty ``actor_id`` answers ``[]`` (3.16).

The protocol and PostgreSQL answer an empty list; DynamoDB answered ``None``.
"""

from __future__ import annotations

import os

import pytest

from actingweb.db.dynamodb.subscription import DbSubscriptionList
from actingweb.db.dynamodb.subscription_diff import DbSubscriptionDiffList
from actingweb.db.dynamodb.trust import DbTrustList

pytestmark = pytest.mark.skipif(
    os.environ.get("DATABASE_BACKEND", "dynamodb") != "dynamodb",
    reason="DynamoDB backend only",
)


@pytest.mark.parametrize("actor_id", ["", None])
def test_trust_list_fetch(actor_id: str | None) -> None:
    assert DbTrustList().fetch(actor_id) == []


@pytest.mark.parametrize("actor_id", ["", None])
def test_subscription_list_fetch(actor_id: str | None) -> None:
    assert DbSubscriptionList().fetch(actor_id) == []


@pytest.mark.parametrize("actor_id", ["", None])
def test_subscription_diff_list_fetch(actor_id: str | None) -> None:
    assert DbSubscriptionDiffList().fetch(actor_id) == []
