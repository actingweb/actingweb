"""AC-16, AC-17: a start-up check that faults is tried three times in all
before the start is refused; a "not ready" answer is not retried; and the
raised ``StoreNotReady`` says whether the store did not answer
(``unavailable``) or answered "not ready".

The probes are patched where the checks call them; ``time.sleep`` is
patched so the back-off costs nothing.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest import mock

import pytest

from actingweb.db.exceptions import DbError
from actingweb.interface import ActingWebApp, StoreNotReady, UniqueCreatorNotReady

MISSING = "the DynamoDB table x_creators is not backfilled"

pytestmark = pytest.mark.usefixtures("real_unique_probe")


def _app() -> ActingWebApp:
    return ActingWebApp(
        aw_type="urn:actingweb:test:retry", fqdn="x.example.com", database="dynamodb"
    ).with_indexed_properties([])


@pytest.fixture(autouse=True)
def _no_wait() -> Iterator[None]:
    with (
        mock.patch.object(ActingWebApp, "_prewarm_dynamodb_tables"),
        mock.patch("actingweb.interface.app.time.sleep"),
        # Only the uniqueness check is under test here.
        mock.patch.object(ActingWebApp, "_check_attribute_schema_ready"),
        mock.patch.object(ActingWebApp, "_check_email_as_creator_ready"),
    ):
        yield


def _fault() -> DbError:
    return DbError("simulated throttle")


def _missing_table() -> DbError:
    class _Cause(Exception):
        response = {"Error": {"Code": "ResourceNotFoundException"}}

    error = DbError("creators read")
    error.__cause__ = _Cause()
    return error


def _probe(**kw: Any) -> Any:
    return mock.patch("actingweb.maintenance.unique_creators.missing_enforcement", **kw)


def test_a_faulting_check_is_tried_three_times() -> None:
    with _probe(side_effect=_fault()) as probe:
        with pytest.raises(UniqueCreatorNotReady) as raised:
            _app().check_ready()
    assert probe.call_count == 3
    assert raised.value.unavailable is True


def test_a_check_that_recovers_lets_the_app_start() -> None:
    with _probe(side_effect=[_fault(), _fault(), None]) as probe:
        _app().check_ready()
    assert probe.call_count == 3


def test_a_not_ready_answer_is_not_retried() -> None:
    with (
        _probe(return_value=MISSING) as probe,
        mock.patch(
            "actingweb.maintenance.unique_creators.no_actors", return_value=False
        ),
    ):
        with pytest.raises(UniqueCreatorNotReady) as raised:
            _app().check_ready()
    assert probe.call_count == 1
    assert raised.value.unavailable is False


def test_unavailable_is_true_only_for_a_fault() -> None:
    with _probe(side_effect=_fault()):
        with pytest.raises(StoreNotReady) as faulted:
            _app().check_ready()
    with (
        _probe(return_value=MISSING),
        mock.patch(
            "actingweb.maintenance.unique_creators.no_actors", return_value=False
        ),
    ):
        with pytest.raises(StoreNotReady) as answered:
            _app().check_ready()
    assert faulted.value.unavailable is True
    assert answered.value.unavailable is False


def test_a_missing_table_is_not_unavailable() -> None:
    with _probe(side_effect=_missing_table()) as probe:
        with pytest.raises(UniqueCreatorNotReady) as raised:
            _app().check_ready()
    assert probe.call_count == 1
    assert raised.value.unavailable is False


def test_a_fault_while_counting_actors_is_unavailable() -> None:
    with (
        _probe(return_value=MISSING),
        mock.patch(
            "actingweb.maintenance.unique_creators.no_actors", side_effect=_fault()
        ) as counting,
    ):
        with pytest.raises(UniqueCreatorNotReady) as raised:
            _app().check_ready()
    assert counting.call_count == 3
    assert raised.value.unavailable is True


def test_the_combined_refusal() -> None:
    from actingweb.interface.app import EmailAsCreatorNotReady

    def answered() -> None:
        raise EmailAsCreatorNotReady("not ready", unavailable=False)

    def faulted() -> None:
        raise EmailAsCreatorNotReady("no answer", unavailable=True)

    with _probe(side_effect=_fault()):
        with mock.patch.object(
            ActingWebApp, "_check_email_as_creator_ready", side_effect=answered
        ):
            with pytest.raises(StoreNotReady) as mixed:
                _app().check_ready()
        with mock.patch.object(
            ActingWebApp, "_check_email_as_creator_ready", side_effect=faulted
        ):
            with pytest.raises(StoreNotReady) as both:
                _app().check_ready()
    assert type(mixed.value) is StoreNotReady and mixed.value.unavailable is False
    assert type(both.value) is StoreNotReady and both.value.unavailable is True
