"""DynamoDB's creator transactions: bounded retries on a conflict (3.16, PR 2).

DynamoDB Local never raises ``TransactionConflict``, so the retry is pinned
with a mocked transaction.
"""

from typing import Any
from unittest import mock

import pytest
from pynamodb.exceptions import (
    CancellationReason,
    TransactWriteError,
    VerboseClientError,
)

from actingweb.db.dynamodb import actor as dynamodb_actor
from actingweb.db.exceptions import DbError


def _cancelled(*codes: str | None) -> TransactWriteError:
    cause = VerboseClientError(
        {"Error": {"Code": "TransactionCanceledException", "Message": "x"}},
        "TransactWriteItems",
        cancellation_reasons=[CancellationReason(code=c) if c else None for c in codes],
    )
    return TransactWriteError("cancelled", cause)


def _conflict() -> TransactWriteError:
    return _cancelled("TransactionConflict", None)


class _Recorder:
    """Stands in for ``TransactWrite``: records each client request token and
    raises the next scripted error on commit."""

    def __init__(self, errors: list[Exception | None]) -> None:
        self.errors = errors
        self.tokens: list[str | None] = []

    def __call__(self, **kwargs: Any) -> "_Recorder":
        self.tokens.append(kwargs.get("client_request_token"))
        return self

    def __enter__(self) -> "_Recorder":
        return self

    def __exit__(self, *exc: Any) -> None:
        error = self.errors.pop(0)
        if error is not None:
            raise error


@pytest.fixture
def db() -> Any:
    with mock.patch.object(dynamodb_actor, "ensure_table"):
        handle = dynamodb_actor.DbActor(unique_creator=True)
    with mock.patch.object(dynamodb_actor.DbActor, "_get_connection"):
        with mock.patch.object(dynamodb_actor.time, "sleep"):
            yield handle


def test_a_conflict_is_retried_with_the_same_token(db: Any) -> None:
    recorder = _Recorder([_conflict(), None])
    with mock.patch.object(dynamodb_actor, "TransactWrite", recorder):
        assert db._run_transaction(lambda t: None, op="actor create") is None
    assert len(recorder.tokens) == 2
    assert recorder.tokens[0] and recorder.tokens[0] == recorder.tokens[1]


def test_conflicts_past_two_retries_raise_db_error(db: Any) -> None:
    recorder = _Recorder([_conflict(), _conflict(), _conflict()])
    with mock.patch.object(dynamodb_actor, "TransactWrite", recorder):
        with pytest.raises(DbError):
            db._run_transaction(lambda t: None, op="actor create")
    assert len(recorder.tokens) == 3
    assert len(set(recorder.tokens)) == 1


def test_a_condition_failure_on_the_last_attempt_wins_over_a_conflict(
    db: Any,
) -> None:
    # H9: a real CreatorTaken is not reported as an outage.
    both = ["TransactionConflict", "ConditionalCheckFailed"]
    recorder = _Recorder([_cancelled(*both), _cancelled(*both), _cancelled(*both)])
    with mock.patch.object(dynamodb_actor, "TransactWrite", recorder):
        codes = db._run_transaction(lambda t: None, op="actor create")
    assert codes == both
    assert len(recorder.tokens) == 3


def test_a_condition_failure_answers_the_codes_without_a_retry(db: Any) -> None:
    recorder = _Recorder([_cancelled(None, "ConditionalCheckFailed")])
    with mock.patch.object(dynamodb_actor, "TransactWrite", recorder):
        codes = db._run_transaction(lambda t: None, op="actor create")
    assert codes == [None, "ConditionalCheckFailed"]
    assert len(recorder.tokens) == 1
