"""``actingweb-unique-creators record``: one actor's creator record
(4.0.0rc2, plans/2026-11-21-trust-request-answer-secret.md phase 5).

The consumer's case: an actor renamed from *older* to *newer*, then restored
with *older*, leaves an orphaned record *newer* → actor and no record for
*older*. ``record --actor ID --previous newer --apply`` repairs it without
a scan. Runs on the isolated store of the ``unique_creator`` group.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any
from unittest import mock

import pytest

from actingweb.maintenance import unique_creators

from ._creator_rows import DYNAMODB, raw_actor

pytestmark = pytest.mark.xdist_group(name="unique_creator")
dynamodb_only = pytest.mark.skipif(
    not DYNAMODB, reason="the creators table is DynamoDB's"
)


def _email() -> str:
    return f"{uuid.uuid4().hex[:12]}@example.com"


@pytest.fixture
def logs(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    caplog.set_level(logging.INFO, logger="unique_creators")
    return caplog


def _record_of(creator: str) -> str | None:
    from pynamodb.exceptions import DoesNotExist

    from actingweb.db.dynamodb.creator import Creator

    try:
        return str(Creator.get(creator, consistent_read=True).actor_id or "")
    except DoesNotExist:
        return None


def _orphan(creator: str, actor_id: str) -> None:
    from actingweb.db.dynamodb.creator import Creator

    Creator(creator=creator, actor_id=actor_id).save()


def _restored() -> tuple[str, str, str]:
    """An actor restored with *older*, its record still under *newer*."""
    older, newer = _email(), _email()
    actor_id = raw_actor(older)
    _orphan(newer, actor_id)
    return actor_id, older, newer


@dynamodb_only
def test_record_writes_a_missing_record(enforced_store: Any, logs: Any) -> None:
    """AC-23."""
    creator = _email()
    actor_id = raw_actor(creator)
    assert unique_creators.main(["record", "--actor", actor_id, "--apply"]) == 0
    assert _record_of(creator) == actor_id
    assert "outcome=written" in logs.text


@dynamodb_only
def test_record_releases_the_previous_address(enforced_store: Any) -> None:
    """AC-24: the consumer's restore, end to end."""
    actor_id, older, newer = _restored()
    assert unique_creators.main(["report"]) == 1
    argv = ["record", "--actor", actor_id, "--previous", newer, "--apply"]
    assert unique_creators.main(argv) == 0
    assert _record_of(older) == actor_id
    assert _record_of(newer) is None
    assert unique_creators.main(["report"]) == 0
    assert unique_creators.main(["enable", "--apply"]) == 0


@dynamodb_only
@pytest.mark.parametrize("stale", ["deleted", "renamed"])
def test_record_moves_a_stale_record(
    enforced_store: Any, logs: Any, stale: str
) -> None:
    """AC-23's other branch: the record names an actor that is gone or
    holds another creator; it moves to this actor in one step."""
    creator = _email()
    actor_id = raw_actor(creator)
    other = uuid.uuid4().hex if stale == "deleted" else raw_actor(_email())
    _orphan(creator, other)
    assert unique_creators.main(["record", "--actor", actor_id, "--apply"]) == 0
    assert "outcome=written" in logs.text
    assert _record_of(creator) == actor_id


@dynamodb_only
def test_a_dry_run_writes_nothing(enforced_store: Any, logs: Any) -> None:
    """AC-25."""
    actor_id, older, newer = _restored()
    argv = ["record", "--actor", actor_id, "--previous", newer]
    assert unique_creators.main(argv) == 0
    assert "outcome=would-write" in logs.text
    assert "outcome=would-release" in logs.text
    assert _record_of(older) is None
    assert _record_of(newer) == actor_id


@dynamodb_only
def test_a_held_address_is_reported(enforced_store: Any, logs: Any) -> None:
    """AC-26: another actor holds the address (a sign-in before the
    record)."""
    creator = _email()
    restored = raw_actor(creator)
    holder = raw_actor(creator)
    _orphan(creator, holder)
    assert unique_creators.main(["record", "--actor", restored, "--apply"]) == 1
    assert f"outcome=held-by holder={holder}" in logs.text
    assert _record_of(creator) == holder


def test_before_enable_it_is_not_enforced(fresh_store: Any, logs: Any) -> None:
    """AC-27, both backends."""
    actor_id = raw_actor(_email())
    assert unique_creators.main(["record", "--actor", actor_id, "--apply"]) == 1
    assert "outcome=not-enforced" in logs.text


@dynamodb_only
def test_capitals_are_refused(enforced_store: Any, logs: Any) -> None:
    """AC-28."""
    creator = _email()
    actor_id = raw_actor(creator.upper())
    assert unique_creators.main(["record", "--actor", actor_id, "--apply"]) == 1
    assert "outcome=refused" in logs.text
    assert _record_of(creator) is None


@pytest.mark.skipif(DYNAMODB, reason="PostgreSQL keeps no records")
def test_postgresql_checks_only(enforced_store: Any, logs: Any) -> None:
    """AC-30."""
    creator = _email()
    actor_id = raw_actor(creator)
    assert unique_creators.main(["record", "--actor", actor_id, "--apply"]) == 0
    assert "outcome=verified" in logs.text
    # A provider id keeps its case: another case is another creator.
    provider = raw_actor("apple:ABC")
    raw_actor("apple:abc")
    logs.clear()
    assert unique_creators.main(["record", "--actor", provider]) == 0
    assert "outcome=verified" in logs.text
    argv = ["record", "--actor", actor_id, "--previous", _email(), "--apply"]
    assert unique_creators.main(argv) == 0
    assert "outcome=not-kept" in logs.text
    holder = raw_actor(creator.upper())  # the index is on the raw value
    logs.clear()
    assert unique_creators.main(["record", "--actor", actor_id]) == 1
    assert f"outcome=held-by holder={holder}" in logs.text


@dynamodb_only
def test_a_changed_row_is_not_recorded(enforced_store: Any, logs: Any) -> None:
    """AC-31: the actor is renamed between the read and the write."""
    from actingweb.db.dynamodb import actor as dynamo_actor

    creator = _email()
    actor_id = raw_actor(creator)
    real = dynamo_actor.record_for_actor_as_read

    def renamed_meanwhile(key: str, row: Any, **kw: Any) -> bool:
        model = dynamo_actor.Actor.get(actor_id, consistent_read=True)
        model.creator = _email()
        model.save()
        return real(key, row, **kw)

    with mock.patch.object(
        dynamo_actor, "record_for_actor_as_read", side_effect=renamed_meanwhile
    ):
        assert unique_creators.main(["record", "--actor", actor_id, "--apply"]) == 1
    assert "outcome=changed" in logs.text
    assert _record_of(creator) is None


@dynamodb_only
@pytest.mark.parametrize(
    "case", ["current", "reserved", "capitals", "absent", "another-actor"]
)
def test_previous_is_checked(enforced_store: Any, logs: Any, case: str) -> None:
    """AC-38."""
    actor_id, older, newer = _restored()
    expected = {
        "current": (older, 1, "previous outcome=refused"),
        "reserved": ("#meta#backfill", 1, "previous outcome=refused"),
        "capitals": (newer.upper(), 0, "previous outcome=released"),
        "absent": (_email(), 0, "previous outcome=absent"),
        "another-actor": (None, 1, "previous outcome=not-this-actor"),
    }
    previous, code, line = expected[case]
    if previous is None:
        previous = _email()
        _orphan(previous, raw_actor(previous))
    argv = ["record", "--actor", actor_id, "--previous", previous, "--apply"]
    assert unique_creators.main(argv) == code
    assert line in logs.text
    if case in ("current", "reserved"):
        # Refused before anything is written.
        assert _record_of(older) is None
    if case == "another-actor":
        assert _record_of(previous) not in (None, actor_id)


@dynamodb_only
def test_previous_is_kept_when_the_record_step_fails(
    enforced_store: Any, logs: Any
) -> None:
    """AC-39."""
    actor_id, older, newer = _restored()
    holder = raw_actor(older)
    _orphan(older, holder)
    argv = ["record", "--actor", actor_id, "--previous", newer, "--apply"]
    assert unique_creators.main(argv) == 1
    assert "previous outcome=skipped" in logs.text
    assert _record_of(newer) == actor_id


@dynamodb_only
@pytest.mark.parametrize("creator", ["#meta#backfill", "#imported-legacy"])
def test_enable_never_records_a_reserved_creator(
    fresh_store: Any, logs: Any, creator: str
) -> None:
    """rc2 iteration: a legacy row with a reserved creator is listed, never
    recorded (``#meta#backfill`` is the key of the backfill-complete item),
    and it does not keep ``report`` or ``enable`` from finishing."""
    actor_id = raw_actor(creator)
    raw_actor(_email())
    assert unique_creators.main(["report"]) == 0
    assert f"reserved creator id={actor_id} creator={creator!r}" in logs.text
    assert unique_creators.main(["enable", "--apply"]) == 0
    assert unique_creators.backfill_complete()
    if creator != "#meta#backfill":
        assert _record_of(creator) is None
    else:
        from actingweb.db.dynamodb.creator import Creator

        marker = Creator.get(creator, consistent_read=True)
        assert not marker.actor_id
    logs.clear()
    assert unique_creators.main(["report"]) == 0
    assert "unrecorded actor" not in logs.text


@dynamodb_only
def test_resolve_never_records_a_reserved_creator(
    enforced_store: Any, logs: Any
) -> None:
    """rc2 verification, issue 1: two legacy rows sharing
    ``#meta#backfill`` are listed, not grouped, so ``resolve --apply``
    neither renames them nor moves the backfill-complete item to one."""
    first, second = raw_actor("#meta#backfill"), raw_actor("#meta#backfill")
    assert unique_creators.main(["report"]) == 0
    for actor_id in (first, second):
        assert f"reserved creator id={actor_id}" in logs.text
    assert "exact_groups=0" in logs.text
    assert unique_creators.main(["resolve", "--apply"]) == 0
    assert "groups=0" in logs.text
    from actingweb.db.dynamodb.actor import Actor
    from actingweb.db.dynamodb.creator import Creator

    assert not Creator.get("#meta#backfill", consistent_read=True).actor_id
    assert unique_creators.backfill_complete()
    for actor_id in (first, second):
        assert Actor.get(actor_id, consistent_read=True).creator == "#meta#backfill"


@dynamodb_only
@pytest.mark.parametrize("ours", [True, False])
def test_previous_is_released_for_an_exempt_creator(
    enforced_store: Any, logs: Any, ours: bool
) -> None:
    """rc2 verification, issue 3: an actor whose creator is now exempt
    still gets ``--previous`` released, and a release it cannot do fails
    the command."""
    actor_id = raw_actor("trustee")
    previous = _email()
    _orphan(previous, actor_id if ours else raw_actor(previous))
    argv = ["record", "--actor", actor_id, "--previous", previous, "--apply"]
    assert unique_creators.main(argv) == (0 if ours else 1)
    assert "outcome=exempt" in logs.text
    if ours:
        assert "previous outcome=released" in logs.text
        assert _record_of(previous) is None
    else:
        assert "previous outcome=not-this-actor" in logs.text
