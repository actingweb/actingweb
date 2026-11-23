"""``actingweb.faults``: the public classification of a store fault
(4.0.0rc3), and the HTTP mapping derived from it."""

from __future__ import annotations

from typing import Any

import pytest

from actingweb.constants import ERROR_CODE_HEADER
from actingweb.db.exceptions import (
    AttributeKeyCollision,
    CreatorTaken,
    DbError,
    DbErrorAfterWrite,
    DeletionInProgress,
)
from actingweb.faults import Fault, FaultClass, classify_fault
from actingweb.interface.integrations._errors import db_error_answer


class _BackendError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.cause_response_code = code


def _caused(code: str) -> DbError:
    try:
        raise _BackendError(code)
    except _BackendError as cause:
        try:
            raise DbError("property write", "actor-1") from cause
        except DbError as fault:
            return fault


def _stored_from(cause: DbError) -> DbErrorAfterWrite:
    try:
        raise cause
    except DbError as c:
        try:
            raise DbErrorAfterWrite("diff registration") from c
        except DbErrorAfterWrite as fault:
            return fault


class TestPrecedence:
    """Each subclass is tested before permanence: the order is behaviour."""

    def test_a_stored_fault_with_a_permanent_cause_is_stored(self) -> None:
        fault = classify_fault(_stored_from(_caused("ValidationException")))
        assert fault is not None and fault.kind is FaultClass.STORED
        assert _answer(fault.error)[0] == 503

    def test_is_permanent_does_not_know_a_collision(self) -> None:
        """``is_permanent`` reads the backend cause only: the resync loop
        branches on it, and a collision there is not a missed subscriber."""
        from actingweb.faults import is_permanent

        assert is_permanent(AttributeKeyCollision("a", "b:c")) is False

    def test_the_public_names(self) -> None:
        import actingweb.faults as faults

        assert sorted(faults.__all__) == ["Fault", "FaultClass", "classify_fault"]


class TestClassifyFault:
    @pytest.mark.parametrize(
        ("exc", "kind", "retry_after"),
        [
            (DbError("property read"), FaultClass.RETRYABLE, 5),
            (
                _caused("ProvisionedThroughputExceededException"),
                FaultClass.RETRYABLE,
                5,
            ),
            (DeletionInProgress("actor-1", 17), FaultClass.RETRYABLE, 17),
            (DbErrorAfterWrite("diff registration"), FaultClass.STORED, None),
            (_caused("ValidationException"), FaultClass.PERMANENT, None),
            (AttributeKeyCollision("a", "b:c", "actor-1"), FaultClass.PERMANENT, None),
            (CreatorTaken("someone@example.com"), FaultClass.CONFLICT, None),
        ],
        ids=[
            "transient",
            "throttle",
            "deleting",
            "stored",
            "permanent",
            "collision",
            "conflict",
        ],
    )
    def test_each_class(
        self, exc: DbError, kind: FaultClass, retry_after: int | None
    ) -> None:
        fault = classify_fault(exc)
        assert isinstance(fault, Fault)
        assert fault.kind is kind
        assert fault.retry_after == retry_after
        assert fault.error is exc

    def test_a_wrapped_fault_is_found(self) -> None:
        inner = DbErrorAfterWrite("diff registration")
        try:
            try:
                raise inner
            except DbError as e:
                raise RuntimeError("the app's own wrapper") from e
        except RuntimeError as wrapped:
            fault = classify_fault(wrapped)
        assert fault is not None
        assert fault.kind is FaultClass.STORED
        assert fault.error is inner

    def test_a_fault_reached_only_through_context_is_not_found(self) -> None:
        try:
            try:
                raise DbError("property read")
            except DbError:
                raise KeyError("a bug while handling it")  # noqa: B904
        except KeyError as bug:
            assert classify_fault(bug) is None

    def test_not_a_fault_is_none(self) -> None:
        assert classify_fault(ValueError("nope")) is None

    def test_the_class_is_a_string(self) -> None:
        assert FaultClass.RETRYABLE == "retryable"
        assert f"{FaultClass.STORED}" == "stored"


def _answer(exc: DbError) -> tuple[int, dict[str, str], str]:
    status, headers, body = db_error_answer(exc)
    assert body["code"] == body["error"] == headers[ERROR_CODE_HEADER]
    return (
        status,
        {k: v for k, v in headers.items() if k != ERROR_CODE_HEADER},
        body["error"],
    )


class TestHttpMapping:
    """What rc2 answered for each class, pinned as a table: the mapping is
    rebuilt on the classifier and must not move."""

    @pytest.mark.parametrize(
        ("exc", "expected"),
        [
            (
                DbError("property read"),
                (503, {"Retry-After": "5"}, "temporarily_unavailable"),
            ),
            (
                DeletionInProgress("actor-1", 17),
                (503, {"Retry-After": "17"}, "temporarily_unavailable"),
            ),
            (DbErrorAfterWrite("diff registration"), (503, {}, "stored_not_notified")),
            (_caused("ValidationException"), (500, {}, "internal_error")),
            (CreatorTaken("someone@example.com"), (409, {}, "conflict")),
        ],
        ids=["transient", "deleting", "stored", "permanent", "conflict"],
    )
    def test_the_http_mapping_is_unchanged_from_rc2(
        self, exc: DbError, expected: tuple[int, dict[str, str], str]
    ) -> None:
        assert _answer(exc) == expected

    def test_a_key_collision_is_permanent(self) -> None:
        """It answered 503 with ``Retry-After: 5`` in rc2, though a retry
        meets the same row."""
        assert _answer(AttributeKeyCollision("a", "b:c", "actor-1")) == (
            500,
            {},
            "internal_error",
        )

    def test_anything_else_is_refused(self) -> None:
        wrapped: Any = RuntimeError("wraps nothing")
        with pytest.raises(TypeError):
            db_error_answer(wrapped)
