"""AC-11: ``actingweb-check-ready``: each start-up gate reported as ready,
ready at first start (an empty store), or refused with its fix line, from
the configuration the command assumed; writes nothing and creates no table;
exit 0, 1 (a gate refuses) or 2 (the store could not be read).

The gates' probes are patched where the command calls them.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest import mock

import pytest

from actingweb.db.exceptions import DbError
from actingweb.maintenance import check_ready as command

P = "actingweb.maintenance.check_ready"


@pytest.fixture(autouse=True)
def _dynamodb(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_BACKEND", "dynamodb")
    monkeypatch.setenv("AWS_DB_PREFIX", "checkready")
    monkeypatch.delenv("INDEXED_PROPERTIES", raising=False)


@contextmanager
def _gates(
    *,
    lookup: Any = (),
    unique: Any = None,
    actors: Any = False,
    schema: Any = (),
    email: Any = None,
    synced: bool = True,
) -> Iterator[dict[str, mock.MagicMock]]:
    """Patch the five probes; a ``BaseException`` value is raised."""

    def answer(value: Any) -> mock.MagicMock:
        if isinstance(value, BaseException):
            return mock.MagicMock(side_effect=value)
        return mock.MagicMock(return_value=value)

    mocks = {
        "_lookup_attention": answer(
            list(lookup) if isinstance(lookup, tuple | list) else lookup
        ),
        "_uniqueness_missing": answer(unique),
        "_store_empty": answer(
            actors if isinstance(actors, BaseException) else not actors
        ),
        "_schema_problems": answer(
            list(schema) if isinstance(schema, tuple | list) else schema
        ),
        "_email_marker": answer(
            email if email is not None or not synced else {"state": "synced"}
        ),
    }
    with mock.patch.multiple(P, **mocks):
        yield mocks


def test_each_gate_is_reported_with_its_fix(capsys: pytest.CaptureFixture[str]) -> None:
    with _gates(
        lookup=["email"],
        unique="the DynamoDB table x_creators is not backfilled",
        actors=True,
    ):
        status = command.main(["--properties", "email"])
    out = capsys.readouterr().out
    assert status == 1
    assert "reverse lookup: REFUSED" in out
    assert "actingweb-property-lookup backfill --apply --properties email" in out
    assert "creator uniqueness: REFUSED" in out
    assert "actingweb-unique-creators report" in out
    assert "attribute lists: ready" in out


def test_assumed_configuration_is_printed(capsys: pytest.CaptureFixture[str]) -> None:
    with _gates():
        assert command.main(["--properties", "a,b", "--no-unique-creator"]) == 0
    out = capsys.readouterr().out
    assert "indexed properties: a, b (from --properties)" in out
    assert "creator uniqueness: off (--no-unique-creator)" in out
    assert "email as creator: off" in out


def test_email_gate_needs_its_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with _gates(synced=False, actors=True) as patched:
        assert command.main(["--properties", "", "--no-unique-creator"]) == 0
        patched["_email_marker"].assert_not_called()
        status = command.main(
            ["--properties", "", "--no-unique-creator", "--email-as-creator"]
        )
    out = capsys.readouterr().out
    assert status == 1
    assert "email as creator: REFUSED" in out
    assert "creator-to-email" in out


def test_an_empty_store_is_ready_at_first_start(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with _gates(
        lookup=["email"],
        unique="the DynamoDB table x_creators does not exist",
        actors=False,
        synced=False,
    ):
        status = command.main(["--properties", "email", "--email-as-creator"])
    out = capsys.readouterr().out
    assert status == 0
    assert "reverse lookup: ready at first start" in out
    assert "creator uniqueness: ready at first start" in out
    assert "email as creator: ready at first start" in out


def test_the_default_prefix_is_not_ready_at_first_start(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AWS_DB_PREFIX", raising=False)
    with _gates(unique="the DynamoDB table x_creators does not exist", actors=False):
        assert command.main(["--properties", ""]) == 1
    assert "AWS_DB_PREFIX" in capsys.readouterr().out


def test_it_writes_nothing_and_creates_no_table() -> None:
    """No write path of either backend is reached, and no table is made."""
    with (
        _gates(unique="missing", actors=False),
        mock.patch("pynamodb.models.Model.create_table") as create_table,
        mock.patch("pynamodb.models.Model.save") as save,
        mock.patch("actingweb.db.dynamodb._ensure.ensure_table") as ensure,
        mock.patch("actingweb.interface.app.ActingWebApp.check_ready") as check_ready,
    ):
        command.main(["--properties", "email", "--email-as-creator"])
    create_table.assert_not_called()
    save.assert_not_called()
    ensure.assert_not_called()
    check_ready.assert_not_called()


def test_a_store_fault_is_exit_2(capsys: pytest.CaptureFixture[str]) -> None:
    with _gates(unique=DbError("throttled")):
        assert command.main(["--properties", ""]) == 2
    assert "could not be read" in capsys.readouterr().out


def test_a_missing_lookup_table_is_not_a_fault() -> None:
    """A fresh store has no lookup table: no name is marked yet."""
    from actingweb.db.exceptions import DbError

    with mock.patch(
        "actingweb.maintenance.property_lookup.read_readiness",
        side_effect=DbError("lookup table missing: x_property_lookup_v2"),
    ):
        assert command._lookup_attention("dynamodb", ["email"]) == ["email"]  # pyright: ignore[reportPrivateUsage]
