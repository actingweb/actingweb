"""Whether the DynamoDB ``creators`` table is backfilled (internal).

A small module of its own so the probe and its per-process cache sit in one
place that tests can stub by attribute (``cached_backfill_state``). It does
not avoid importing the table models: importing anything under
``actingweb.db.dynamodb`` runs the package ``__init__``, which imports every
model and freezes its table name under the current ``AWS_DB_PREFIX``. That
is why the test stub is function-scoped.
"""

from pynamodb.exceptions import DoesNotExist

from actingweb.db.creator_rules import BACKFILL_KEY

# Creators tables whose backfill-complete item was seen. Positive only: an
# absent item or a fault is read again on the next enforced write.
_seen: set[str] = set()


def _table() -> str:
    from actingweb.db.dynamodb.creator import Creator

    return str(Creator.Meta.table_name)


def creators_backfill_state() -> str:
    """``"table-missing"``, ``"not-backfilled"`` or ``"complete"``.

    One consistent ``GetItem`` of the backfill-complete item: a missing table
    answers ``ResourceNotFound``, so no ``DescribeTable`` is needed (the
    runtime role may not have it). Raises on any other read fault. A
    ``"complete"`` answer is remembered, so the startup check
    (``check_ready()``) also spares the first enforced write its read.
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
    _seen.add(_table())
    return "complete"


def cached_backfill_state() -> str:
    """:func:`creators_backfill_state`, without a read once ``"complete"``
    has been seen for this table in this process. Raises on a read fault."""
    if _table() in _seen:
        return "complete"
    return creators_backfill_state()


def reset_backfill_probe() -> None:
    """Forget what the probe saw (tests, ``disable``)."""
    _seen.clear()
