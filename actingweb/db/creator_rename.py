"""The types of ``DbActor.rename_creator``, shared by both backends.

One backend operation moves an actor's creator together with writes to its
``_internal`` attributes: the actor row (conditioned on the creator the
caller read), the new uniqueness record, the attribute writes (each with its
own condition) and a check that the vouch marker is unchanged. Any failed
condition cancels all of it, and the caller is told which one failed.
"""

from collections.abc import Sequence
from enum import Enum
from typing import Any, Literal, NamedTuple

INTERNAL_BUCKET = "_internal"
MARKER_NAME = "auth_method"
# A DynamoDB transaction holds at most 100 items; the actor row, the record
# and the marker check take three.
MAX_WRITES = 97


class AttrWrite(NamedTuple):
    """One write to the ``_internal`` bucket inside a rename.

    ``value`` None deletes the attribute (``when`` must then be
    ``"always"``); any other value, a falsy one included, is stored (where
    ``set_attr`` deletes on a falsy value). ``when`` is ``"always"`` (an
    upsert), ``"absent"`` (only when no live row holds the name, the rule
    ``create_attr_if_absent`` applies, the one condition that consults a
    row's TTL) or ``"equals"``
    (only when the stored value equals ``expected``, a string; a row's TTL
    is not consulted, as for the marker).
    """

    name: str
    value: Any | None
    when: Literal["always", "absent", "equals"] = "always"
    expected: str | None = None


class RenameOutcome(Enum):
    """What a rename that did not fault answered."""

    APPLIED = "applied"
    # The stored creator was not ``expected`` (or the actor is gone).
    ROW_CHANGED = "row-changed"
    # ``auth_method`` did not hold ``marker`` (or is gone).
    MARKER_CHANGED = "marker-changed"
    # An ``"absent"`` or ``"equals"`` attribute write lost its condition.
    ATTR_CONDITION = "attr-condition"


def validate_rename_writes(internal: Sequence[AttrWrite], marker: str | None) -> None:
    """Refuse, before any backend call, what a backend cannot run as one
    operation: a name written twice, a write of the marker the operation
    also checks (DynamoDB refuses a transaction naming one row twice), a
    conditional delete, and an ``"equals"`` without a string to compare.

    Raises:
        ValueError: on any of these
    """
    if len(internal) > MAX_WRITES:
        raise ValueError(f"rename_creator: at most {MAX_WRITES} attribute writes")
    seen: set[str] = set()
    for w in internal:
        if not w.name:
            raise ValueError("rename_creator: an attribute write needs a name")
        if w.name in seen:
            raise ValueError(f"rename_creator: {w.name!r} is written twice")
        seen.add(w.name)
        if w.when not in ("always", "absent", "equals"):
            raise ValueError(f"rename_creator: unknown condition {w.when!r}")
        if w.value is None and w.when != "always":
            raise ValueError("rename_creator: a delete is unconditional")
        if w.when == "equals" and not isinstance(w.expected, str):
            raise ValueError("rename_creator: 'equals' compares with a string")
    if marker is not None and MARKER_NAME in seen:
        raise ValueError(
            f"rename_creator: {MARKER_NAME!r} cannot be written while it is checked"
        )
