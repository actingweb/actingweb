"""DynamoDB's ``rename_creator``: which condition cancelled it (4.0).

The codes of a cancelled transaction come back in the order PynamoDB sends
the items, which is by kind (condition checks, deletes, puts, updates) and
not the order the code adds them in. These tests script the cancellation
with a stand-in for ``TransactWrite`` that records the calls ``build``
makes; the integration suite (``tests/integration/test_rename_creator.py``)
runs the same cases against DynamoDB Local.
"""

from typing import Any
from unittest import mock

import pytest
from pynamodb.exceptions import (
    CancellationReason,
    TransactWriteError,
    VerboseClientError,
)

from actingweb.db.creator_rename import AttrWrite, RenameOutcome
from actingweb.db.dynamodb import actor as dynamodb_actor
from actingweb.db.exceptions import AttributeKeyCollision, CreatorTaken, DbError

CCF = "ConditionalCheckFailed"
CONFLICT = "TransactionConflict"


def _cancelled(*reasons: CancellationReason | None) -> TransactWriteError:
    cause = VerboseClientError(
        {"Error": {"Code": "TransactionCanceledException", "Message": "x"}},
        "TransactWriteItems",
        cancellation_reasons=list(reasons),
    )
    return TransactWriteError("cancelled", cause)


def _r(code: str | None, bucket: str | None = None) -> CancellationReason | None:
    if code is None:
        return None
    raw = {"bucket": {"S": bucket}} if bucket else None
    return CancellationReason(code=code, raw_item=raw)


class _Recorder:
    """Stands in for ``TransactWrite``: records the kind of each item
    ``build`` adds, per attempt, and raises the next scripted error."""

    def __init__(self, errors: list[Exception | None]) -> None:
        self.errors = errors
        self.attempts: list[list[str]] = []
        self.tokens: list[str | None] = []

    def __call__(self, **kwargs: Any) -> "_Recorder":
        self.attempts.append([])
        self.tokens.append(kwargs.get("client_request_token"))
        return self

    def __enter__(self) -> "_Recorder":
        return self

    def __exit__(self, *exc: Any) -> None:
        error = self.errors.pop(0)
        if error is not None:
            raise error

    def condition_check(self, *_a: Any, **_k: Any) -> None:
        self.attempts[-1].append("check")

    def delete(self, *_a: Any, **_k: Any) -> None:
        self.attempts[-1].append("delete")

    def save(self, *_a: Any, **_k: Any) -> None:
        self.attempts[-1].append("put")

    def update(self, *_a: Any, **_k: Any) -> None:
        self.attempts[-1].append("update")


@pytest.fixture
def db() -> Any:
    with mock.patch.object(dynamodb_actor, "ensure_table"):
        handle = dynamodb_actor.DbActor(unique_creator=True)
    with (
        mock.patch.object(dynamodb_actor.DbActor, "_get_connection"),
        mock.patch.object(dynamodb_actor.time, "sleep"),
        mock.patch.object(dynamodb_actor, "_require_creators_backfill"),
        mock.patch.object(
            dynamodb_actor.DbActor, "_record_names_other", return_value=True
        ),
    ):
        yield handle


# The full call: a record claim, an email put, a pending delete and a marker
# check. Sent as: check(marker), delete(pending), put(record), put(email),
# update(row).
WRITES = (
    AttrWrite("email", "new@example.com", "equals", "old@example.com"),
    AttrWrite("vouched_creator_pending", None),
)


def _rename(db: Any, errors: list[Exception | None]) -> tuple[Any, _Recorder]:
    recorder = _Recorder(errors)
    with mock.patch.object(dynamodb_actor, "TransactWrite", recorder):
        outcome = db.rename_creator(
            "a1",
            expected="old@example.com",
            creator="new@example.com",
            internal=WRITES,
            marker="google",
        )
    return outcome, recorder


def test_items_are_added_in_the_order_pynamodb_sends_them(db: Any) -> None:
    _outcome, recorder = _rename(db, [None])
    assert recorder.attempts == [["check", "delete", "put", "put", "update"]]


@pytest.mark.parametrize(
    ("reasons", "expected"),
    [
        # check, delete, record, email, row
        ((None, None, None, None, CCF), RenameOutcome.ROW_CHANGED),
        ((CCF, None, None, None, None), RenameOutcome.MARKER_CHANGED),
        ((None, None, None, CCF, None), RenameOutcome.ATTR_CONDITION),
        # Several fail: the row is decided first.
        ((CCF, None, None, None, CCF), RenameOutcome.ROW_CHANGED),
        ((CCF, None, None, CCF, None), RenameOutcome.MARKER_CHANGED),
    ],
)
def test_the_outcome_is_read_off_the_position_of_each_kind(
    db: Any, reasons: tuple[str | None, ...], expected: RenameOutcome
) -> None:
    outcome, _ = _rename(db, [_cancelled(*(_r(c) for c in reasons))])
    assert outcome is expected


def test_a_failed_record_is_creator_taken(db: Any) -> None:
    with pytest.raises(CreatorTaken):
        _rename(db, [_cancelled(None, None, _r(CCF), None, None)])


def test_a_failed_put_over_another_buckets_row_is_a_collision(db: Any) -> None:
    with pytest.raises(AttributeKeyCollision):
        _rename(db, [_cancelled(None, None, None, _r(CCF, "_internal:x"), None)])


def test_a_failed_put_over_this_buckets_row_is_a_lost_condition(db: Any) -> None:
    outcome, _ = _rename(db, [_cancelled(None, None, None, _r(CCF, "_internal"), None)])
    assert outcome is RenameOutcome.ATTR_CONDITION


def test_a_failed_delete_is_a_collision(db: Any) -> None:
    with pytest.raises(AttributeKeyCollision):
        _rename(db, [_cancelled(None, _r(CCF), None, None, None)])


def test_a_conflict_on_the_deciding_item_is_not_a_failed_condition(
    db: Any,
) -> None:
    """On the last attempt ``_run_transaction`` returns the codes once any
    item failed a condition; an item reported with ``TransactionConflict``
    was not evaluated, and no counted item failed here."""
    last = _cancelled(_r(CONFLICT), None, None, None, _r(CONFLICT))
    with pytest.raises(DbError):
        _rename(db, [_cancelled(_r(CONFLICT)), _cancelled(_r(CONFLICT)), last])


def test_a_conflict_then_a_failed_condition_answers_that_condition(
    db: Any,
) -> None:
    outcome, recorder = _rename(
        db,
        [_cancelled(_r(CONFLICT)), _cancelled(None, None, None, None, _r(CCF))],
    )
    assert outcome is RenameOutcome.ROW_CHANGED
    # Each attempt replays the same items: nothing accumulates.
    assert recorder.attempts == [["check", "delete", "put", "put", "update"]] * 2


def test_a_conflict_is_retried_with_the_same_token_and_applies(db: Any) -> None:
    outcome, recorder = _rename(db, [_cancelled(_r(CONFLICT)), None])
    assert outcome is RenameOutcome.APPLIED
    assert len(recorder.tokens) == 2
    assert recorder.tokens[0] and recorder.tokens[0] == recorder.tokens[1]


def test_codes_that_do_not_match_the_items_raise(db: Any) -> None:
    with pytest.raises(DbError):
        _rename(db, [_cancelled(_r(CCF), None)])


@pytest.mark.parametrize(
    ("internal", "marker"),
    [
        ((AttrWrite("email", "a"), AttrWrite("email", "b")), None),
        ((AttrWrite("auth_method", "google"),), "google"),
        ((AttrWrite("email", None, "absent"),), None),
        ((AttrWrite("email", "a", "equals", None),), None),
        ((AttrWrite("email", "a", "equals", {"x": 1}),), None),  # type: ignore[arg-type]
    ],
)
def test_a_call_it_cannot_run_raises_before_any_backend_call(
    db: Any, internal: tuple[AttrWrite, ...], marker: str | None
) -> None:
    recorder = _Recorder([])
    with mock.patch.object(dynamodb_actor, "TransactWrite", recorder):
        with pytest.raises(ValueError):
            db.rename_creator(
                "a1",
                expected="old@example.com",
                creator="new@example.com",
                internal=internal,
                marker=marker,
            )
    assert recorder.attempts == []


def test_pynamodb_sends_the_items_in_this_order(db: Any) -> None:
    """The positions above assume PynamoDB flattens a transaction as
    condition checks, deletes, puts, updates; a release that changes it
    fails here. The real ``TransactWrite`` and ``Connection`` build the
    request; only its dispatch is captured."""
    from pynamodb.connection import Connection

    sent: list[dict[str, Any]] = []

    def capture(self: Any, operation: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        sent.append(kwargs)
        return {}

    connection = Connection(region="us-west-1", host="http://localhost:1")
    with (
        mock.patch.object(
            dynamodb_actor.DbActor, "_get_connection", return_value=connection
        ),
        mock.patch.object(Connection, "dispatch", capture),
    ):
        outcome = db.rename_creator(
            "a1",
            expected="old@example.com",
            creator="new@example.com",
            internal=WRITES,
            marker="google",
        )
    assert outcome is RenameOutcome.APPLIED
    items = sent[0]["TransactItems"]
    assert [next(iter(i)) for i in items] == [
        "ConditionCheck",
        "Delete",
        "Put",
        "Put",
        "Update",
    ]
    assert items[4]["Update"]["TableName"].endswith("_actors")
    assert items[2]["Put"]["TableName"].endswith("_creators")
