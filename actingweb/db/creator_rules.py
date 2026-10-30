"""The creator-uniqueness rules, in one place.

``with_unique_creator()`` makes the database hold one actor per creator. The
same rules apply in the PostgreSQL index predicate, the DynamoDB write path and
the ``actingweb-unique-creators`` command; each of them imports them from here.

- **Exempt** values (``trustee``, ``creator``, the empty string, compared
  case-insensitively) are shared by many actors and never enforced.
- Non-exempt values compare on the stored value. Values containing ``@`` are
  lowercased before they are stored; provider ids keep their case.
- **Reserved** values begin with ``#`` (the DynamoDB ``creators`` table keeps
  its metadata under ``#meta#…``) or contain ``#dup-`` (the suffix
  ``resolve`` gives a renamed duplicate), checked on the value as stored.
  ``Actor.create``, the factory and ``PUT /<id>/trust/trustee`` refuse them.
- **System** creators (``system``, ``oauth2-system``) belong to the fixed-id
  system actors; the factory and ``PUT /<id>/trust/trustee`` refuse them, so
  nobody can take them before the system actor is bootstrapped.
"""

import hashlib

EXEMPT_CREATORS = frozenset({"trustee", "creator", ""})
DUP_MARKER = "#dup-"
RESERVED_PREFIX = "#"
BACKFILL_KEY = "#meta#backfill"
SYSTEM_CREATORS = frozenset({"system", "oauth2-system"})
UNIQUE_INDEX_NAME = "ux_actors_creator"
# The PostgreSQL partial index predicate; the literal list is EXEMPT_CREATORS.
UNIQUE_INDEX_PREDICATE = "lower(creator) NOT IN ('trustee', 'creator', '')"


def normalise_creator(creator: str | None) -> str:
    """The value as stored: ``@`` values lowercased, others unchanged."""
    value = creator or ""
    return value.lower() if "@" in value else value


def is_exempt(creator: str | None) -> bool:
    """Whether many actors may share this creator."""
    return (creator or "").lower() in EXEMPT_CREATORS


def is_reserved(creator: str | None) -> bool:
    """Whether a caller may not choose this creator: ``#…`` or ``#dup-`` in
    the value as stored (an ``@`` value is lowercased first, so ``#DUP-``
    counts)."""
    value = normalise_creator(creator)
    return value.startswith(RESERVED_PREFIX) or DUP_MARKER in value


def is_refused_from_callers(creator: str | None) -> bool:
    """What the factory and ``PUT /<id>/trust/trustee`` refuse: the reserved
    values and the system actors' creators."""
    return is_reserved(creator) or normalise_creator(creator).lower() in (
        SYSTEM_CREATORS
    )


def dup_value(creator: str, actor_id: str) -> str:
    """The creator a renamed duplicate gets: unique per actor, stable."""
    digest = hashlib.sha256(actor_id.encode("utf-8")).hexdigest()[:8]
    return f"{creator}{DUP_MARKER}{digest}"
