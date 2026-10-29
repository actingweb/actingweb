"""Follow-ups from the review of PR #160: which PostgreSQL errors count as
permanent, and no resync for a subscription that is gone."""

from __future__ import annotations

from typing import Any
from unittest import mock

import pytest

from actingweb.db.exceptions import DbError


def _wrapped(cause: BaseException) -> DbError:
    try:
        raise DbError("simulated") from cause
    except DbError as fault:
        return fault


class TestPostgresPermanentClassification:
    """A retry fixes a lost or closed connection and a pool timeout (503);
    it cannot fix bad SQL or a constraint (500)."""

    @pytest.mark.parametrize(
        "name",
        ["OperationalError", "InterfaceError", "InFailedSqlTransaction"],
    )
    def test_connection_trouble_is_transient(self, name: str) -> None:
        errors = pytest.importorskip("psycopg.errors")
        from actingweb.interface.integrations._errors import db_error_answer

        status, headers, _ = db_error_answer(
            _wrapped(getattr(errors, name)("the connection is closed"))
        )
        assert status == 503 and headers.get("Retry-After") == "5"

    def test_a_pool_timeout_is_transient(self) -> None:
        pool = pytest.importorskip("psycopg_pool")
        from actingweb.interface.integrations._errors import db_error_answer

        status, _, _ = db_error_answer(_wrapped(pool.PoolTimeout("no connection")))
        assert status == 503

    @pytest.mark.parametrize(
        "name",
        ["ProgrammingError", "UndefinedTable", "IntegrityError", "DataError"],
    )
    def test_sql_and_constraint_errors_are_permanent(self, name: str) -> None:
        errors = pytest.importorskip("psycopg.errors")
        from actingweb.interface.integrations._errors import db_error_answer

        status, headers, _ = db_error_answer(_wrapped(getattr(errors, name)("bad")))
        assert status == 500 and "Retry-After" not in headers


class TestResyncForAGoneSubscription:
    def test_no_resync_and_no_reused_number(self) -> None:
        """At 4275401 a missing row answered sequence 1, which repeats a
        number the subscriber already has."""
        from tests._adoption_helpers import create_core_actor, make_config, uuid_email

        config = make_config()
        actor = create_core_actor(config, uuid_email())
        assert actor._increment_subscription_sequence("p-gone", "s-gone") == 0

        trust = mock.Mock()
        trust.get.return_value = {"baseuri": "https://peer.example.com", "secret": "s"}
        sent: list[Any] = []
        with (
            mock.patch("actingweb.trust.Trust", return_value=trust),
            mock.patch.object(
                actor, "_send_resync_callback_sync", lambda *a, **k: sent.append(a)
            ),
            mock.patch.object(
                actor, "_send_resync_callback_async", lambda *a, **k: sent.append(a)
            ),
        ):
            assert (
                actor._callback_subscription_resync(
                    {
                        "peerid": "p-gone",
                        "subscriptionid": "s-gone",
                        "target": "properties",
                    }
                )
                is False
            )
        assert sent == []
