"""Restrict a maintenance sweep's actor list to one actor (test helper).

The sweeps (``verify_property_lists``, ``migrate_property_lists``) walk every
actor in the table, but the test database is shared with whatever other tests
are running (xdist workers included), so their exit codes and checkpoint
contents would otherwise depend on unrelated actors' lists. Patching the actor
listing keeps argparse, the sweep loop and the checkpoint lifecycle while
making the outcome deterministic.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest


def only_this_actor(
    monkeypatch: pytest.MonkeyPatch, actor_id: str, *, fault_after: bool = False
) -> None:
    """Make ``get_actor_list`` list ``actor_id`` alone; with ``fault_after``,
    the streamed listing raises ``DbError`` after yielding it."""

    class _OneActor:
        def fetch(self) -> list[dict[str, Any]]:
            return [{"id": actor_id}]

        def iter_rows(self, **_kwargs: Any) -> Iterator[dict[str, Any]]:
            yield {"id": actor_id, "creator": "x@example.com"}
            if fault_after:
                from actingweb.db.exceptions import DbError

                raise DbError("actor list scan")

    monkeypatch.setattr("actingweb.db.get_actor_list", lambda config: _OneActor())
