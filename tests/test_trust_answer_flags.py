"""The answers to a trust request carry its flags as JSON booleans, as a GET
of the row does (specification 1.5, spec-1-5 Phase 2, T13), and ``approved``
in a trust PUT accepts true only (T14)."""

from typing import Any

import pytest

from actingweb.handlers.trust import _approval, _trust_request_answer


def _row(approved: str) -> dict[str, Any]:
    return {
        "id": "a",
        "peerid": "b",
        "relationship": "friend",
        "approved": approved,
        "peer_approved": "true",
        "verified": "false",
        "secret": "s",
        "verification_token": "t",
    }


def test_an_unapproved_answer_has_booleans_and_no_token() -> None:
    answer = _trust_request_answer(_row("false"))
    assert answer["approved"] is False
    assert answer["peer_approved"] is True
    assert answer["verified"] is False
    assert "verification_token" not in answer
    # The secret is the requester's own, or the one generated for it (rc2).
    assert answer["secret"] == "s"


def test_an_approved_answer_has_booleans_and_its_secret() -> None:
    answer = _trust_request_answer(_row("true"))
    assert answer["approved"] is True
    assert answer["secret"] == "s"


@pytest.mark.parametrize("value", [True, "true", "TRUE", " true "])
def test_approval_accepts_true(value: Any) -> None:
    assert _approval(value) is True


@pytest.mark.parametrize("value", [False, "false", None, 1, 0, "yes", "", [], {}])
def test_approval_refuses_anything_else(value: Any) -> None:
    assert _approval(value) is None
