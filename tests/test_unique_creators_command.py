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
