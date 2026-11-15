"""One timestamp form on the wire (specification 1.5, spec-1-5 Phase 3, S7)."""

import datetime
import re

from actingweb.subscription import wire_timestamp

ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")


def test_an_aware_value_is_converted_to_utc() -> None:
    oslo = datetime.timezone(datetime.timedelta(hours=1))
    value = datetime.datetime(2026, 11, 15, 11, 0, 0, 5, tzinfo=oslo)
    assert wire_timestamp(value) == "2026-11-15T10:00:00.000005Z"


def test_a_naive_value_is_taken_as_utc() -> None:
    assert wire_timestamp(datetime.datetime(2026, 1, 2, 3, 4, 5)) == (
        "2026-01-02T03:04:05.000000Z"
    )


def test_now_has_the_poll_form() -> None:
    assert ISO_Z.match(wire_timestamp(datetime.datetime.now(datetime.UTC)))


def test_text_is_passed_through() -> None:
    assert (
        wire_timestamp("2026-01-02T03:04:05.000000Z") == "2026-01-02T03:04:05.000000Z"
    )
