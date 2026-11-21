"""``actingweb-unique-creators creator-to-email``: the summary (4.0.0rc1
adoption findings)."""

from __future__ import annotations

import argparse
import logging
from typing import Any
from unittest import mock

import pytest

from actingweb.maintenance import email_as_creator, unique_creators


def _args(**kw: Any) -> argparse.Namespace:
    base = {
        "unmark": False,
        "apply": False,
        "creator": None,
        "start_after": None,
        "rate_limit": None,
        "clear_held_email": False,
        "show_addresses": False,
    }
    base.update(kw)
    return argparse.Namespace(**base)


def _counts(**kw: int) -> dict[str, int]:
    counts: dict[str, int] = dict.fromkeys(
        (
            "scanned",
            "moved",
            "held",
            "squatted",
            "cleared",
            "changed",
            "unvouched",
            "errors",
        ),
        0,
    )
    counts.update(kw)
    return counts


def test_creator_to_email_summary_names_the_order(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="unique_creators")
    with mock.patch.object(
        email_as_creator, "sweep", return_value=_counts(scanned=3, unvouched=2)
    ):
        unique_creators._run_creator_to_email(_args(), object())  # pyright: ignore[reportPrivateUsage]
    assert "unvouched=2" in caplog.text
    assert "actingweb-mark-actors-vouched" in caplog.text
    caplog.clear()
    with mock.patch.object(email_as_creator, "sweep", return_value=_counts(scanned=3)):
        unique_creators._run_creator_to_email(_args(), object())  # pyright: ignore[reportPrivateUsage]
    assert "actingweb-mark-actors-vouched" not in caplog.text


# ---------------------------------------------------------------------------
# record (4.0.0rc2, plans/2026-11-21-trust-request-answer-secret.md phase 5)
# ---------------------------------------------------------------------------


def _record_args(**kw: Any) -> argparse.Namespace:
    base = {"command": "record", "actor": "actor-1", "previous": None, "apply": True}
    base.update(kw)
    return argparse.Namespace(**base)


def _config(database: str = "dynamodb") -> Any:
    return mock.Mock(database=database)


@pytest.mark.parametrize(
    ("actor_id", "creator", "expected"),
    [
        ("actor-1", "#imported", "refused"),
        ("actor-1", "system", "refused"),
        ("actor-1", "oauth2-system", "refused"),
        ("actor-1", "Mixed@Example.com", "refused"),
        # The system actors at their fixed ids are not refused.
        ("_actingweb_system", "system", "not-enforced"),
        ("_actingweb_oauth2", "oauth2-system", "not-enforced"),
    ],
)
def test_record_refuses_reserved_and_system_creators(
    actor_id: str, creator: str, expected: str, caplog: pytest.LogCaptureFixture
) -> None:
    """AC-29 (and AC-28's rule): exit 1, nothing written."""
    from actingweb.constants import ACTINGWEB_SYSTEM_ACTOR, OAUTH2_SYSTEM_ACTOR

    assert (ACTINGWEB_SYSTEM_ACTOR, OAUTH2_SYSTEM_ACTOR) == (
        "_actingweb_system",
        "_actingweb_oauth2",
    )
    caplog.set_level(logging.INFO, logger="unique_creators")
    with (
        mock.patch.object(
            unique_creators, "_read_actor_creator", return_value=(True, creator)
        ),
        mock.patch.object(unique_creators, "_uniqueness_enforced", return_value=False),
        mock.patch.object(unique_creators, "_dynamodb_record_step") as write,
    ):
        code = unique_creators._run(  # pyright: ignore[reportPrivateUsage]
            _record_args(actor=actor_id), argparse.ArgumentParser(), _config()
        )
    assert code == 1
    assert f"outcome={expected}" in caplog.text
    write.assert_not_called()


def test_record_missing_and_exempt(caplog: pytest.LogCaptureFixture) -> None:
    """AC-37."""
    caplog.set_level(logging.INFO, logger="unique_creators")
    parser = argparse.ArgumentParser()
    with mock.patch.object(
        unique_creators, "_read_actor_creator", return_value=(False, None)
    ):
        assert unique_creators._run(_record_args(), parser, _config()) == 1  # pyright: ignore[reportPrivateUsage]
    assert "outcome=missing" in caplog.text
    for exempt in ("trustee", "creator", "", "a@b.example#dup-0123"):
        caplog.clear()
        with mock.patch.object(
            unique_creators, "_read_actor_creator", return_value=(True, exempt)
        ):
            assert unique_creators._run(_record_args(), parser, _config()) == 0  # pyright: ignore[reportPrivateUsage]
        assert "outcome=exempt" in caplog.text


@pytest.mark.parametrize("where", ["read", "write"])
def test_record_store_fault_exits_2(
    where: str, caplog: pytest.LogCaptureFixture
) -> None:
    """AC-40: a helper's DbError, on the actor read or on the record write,
    is a store fault: exit 2, and the fault is printed."""
    from actingweb.db.exceptions import DbError

    caplog.set_level(logging.INFO, logger="unique_creators")
    patches = (
        [
            mock.patch.object(
                unique_creators,
                "_read_actor_creator",
                side_effect=DbError("actor get"),
            )
        ]
        if where == "read"
        else [
            mock.patch.object(
                unique_creators,
                "_read_actor_creator",
                return_value=(True, "someone@example.com"),
            ),
            mock.patch.object(
                unique_creators, "_uniqueness_enforced", return_value=True
            ),
            mock.patch.object(
                unique_creators,
                "_dynamodb_record_step",
                side_effect=DbError("creator record write"),
            ),
        ]
    )
    with patches[0]:
        if where == "read":
            code = unique_creators._run(  # pyright: ignore[reportPrivateUsage]
                _record_args(), argparse.ArgumentParser(), _config()
            )
        else:
            with patches[1], patches[2]:
                code = unique_creators._run(  # pyright: ignore[reportPrivateUsage]
                    _record_args(), argparse.ArgumentParser(), _config()
                )
    assert code == 2
    assert "re-run when the database answers" in caplog.text
