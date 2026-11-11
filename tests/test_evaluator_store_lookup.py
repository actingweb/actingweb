"""The evaluator reads the live permission store (3.16, plan
grant-enforcement-per-route, Phase 4 finding).

The store is a singleton rebuilt when another application's config asks for
it. An evaluator that kept the store it was built with read that store's
cache while writes went to the rebuilt one, so a narrowed grant was not
seen in a process serving two applications (found by the integration suite:
an old subscription to a list excluded later still delivered it).
"""

from __future__ import annotations

from actingweb.permission_evaluator import (
    get_permission_evaluator,
    initialize_permission_evaluator,
)
from actingweb.trust_permissions import get_trust_permission_store
from tests._adoption_helpers import make_config


def test_a_rebuilt_store_is_the_one_the_evaluator_reads() -> None:
    a, b = make_config(), make_config()
    initialize_permission_evaluator(a)
    evaluator = get_permission_evaluator(a)
    first = get_trust_permission_store(a)
    get_trust_permission_store(b)  # another app: the singleton is rebuilt
    current = get_trust_permission_store(a)  # and rebuilt again for A
    assert current is not first
    assert get_permission_evaluator(a) is evaluator
    assert evaluator.permission_store is current


def test_an_assigned_store_is_used_as_given() -> None:
    evaluator = get_permission_evaluator(make_config())
    sentinel = object()
    evaluator.permission_store = sentinel
    assert evaluator.permission_store is sentinel
