"""``DbAttribute.delete_by_chain`` on PostgreSQL raises on an error.

It used to answer 0, which a revocation cannot tell from "nothing matched": a
failed delete whose anchor row then expired read as "already revoked". The
real backend is covered by
``tests/integration/test_spa_chain_revocation_backend.py``.
"""

from unittest import mock

import pytest

pytest.importorskip("psycopg")

from actingweb.db.postgresql import attribute as pg  # noqa: E402


def test_a_failed_delete_raises_instead_of_answering_zero() -> None:
    with mock.patch.object(pg, "get_connection", side_effect=RuntimeError("down")):
        with pytest.raises(RuntimeError):
            pg.DbAttribute.delete_by_chain(
                actor_id="_actingweb_oauth2",
                buckets=["spa_access_tokens"],
                chain_id="c1",
            )


def test_missing_arguments_still_answer_zero() -> None:
    assert (
        pg.DbAttribute.delete_by_chain(actor_id=None, buckets=["b"], chain_id="c") == 0
    )
