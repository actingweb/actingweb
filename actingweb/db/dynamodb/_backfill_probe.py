"""Whether the DynamoDB ``creators`` table is backfilled (internal).

Its own module, importing the model only when called, so a test can stub
:func:`creators_backfilled` without importing the table models (whose names
freeze at import, under whatever ``AWS_DB_PREFIX`` is set then).
"""

from pynamodb.exceptions import DoesNotExist

from actingweb.db.creator_rules import BACKFILL_KEY

# Creators tables whose backfill-complete item was seen. Positive only: an
# absent item or a fault is read again on the next enforced write.
_seen: set[str] = set()


def creators_backfill_state() -> str:
    """``"table-missing"``, ``"not-backfilled"`` or ``"complete"``.

    One consistent ``GetItem`` of the backfill-complete item: a missing table
    answers ``ResourceNotFound``, so no ``DescribeTable`` is needed (the
    runtime role may not have it). Raises on any other read fault.
    """
    from actingweb.db.dynamodb.creator import Creator
    from actingweb.db.dynamodb.property_lookup import is_resource_not_found

    try:
        Creator.get(BACKFILL_KEY, consistent_read=True)
    except DoesNotExist:
        return "not-backfilled"
    except (
        Exception
    ) as e:  # folds DbError: a missing table is an answer, anything else re-raises
        if is_resource_not_found(e):
            return "table-missing"
        raise
    return "complete"


def creators_backfilled() -> bool:
    """Whether the creators table is backfilled; one read per process and
    table once it has been seen. Raises on a read fault."""
    from actingweb.db.dynamodb.creator import Creator

    table = str(Creator.Meta.table_name)
    if table in _seen:
        return True
    if creators_backfill_state() != "complete":
        return False
    _seen.add(table)
    return True


def reset_backfill_probe() -> None:
    """Forget what the probe saw (tests, ``disable``)."""
    _seen.clear()
