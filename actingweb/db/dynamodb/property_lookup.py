# mypy: disable-error-code="override"
"""
Reverse-lookup table for indexed properties (value -> actor_id).

v2 key design (current): a single hash key ``lookup_key`` holding the hex
SHA-256 digest of the canonical (property_name, value) encoding — see
:func:`compute_lookup_key`. This is a **permanent data format**:

    lookup_key = sha256(property_name + "\\x00" + value).hexdigest()

The NUL separator makes the encoding unambiguous for any property name.
The value is hashed verbatim as stored (no normalisation, no lowercasing)
and is **never stored** in the table — only ``actor_id`` and
``property_name`` are kept as attributes (needed for stale-row
verification tooling; not PII).

Why digests instead of the v1 ``(property_name, value)`` composite key:

- uniform partition distribution — v1 put every email under the single
  partition key ``"email"`` (per-partition throughput ceiling on login
  bursts);
- no value-size limit — v1's range key capped values at 1024 bytes while
  claiming to remove the GSI's 2048-byte limit;
- no plaintext PII in key material (note: this is pseudonymisation, not
  anonymisation — and the properties table itself still stores values);
- conditional puts turn silent cross-actor overwrites into detectable,
  logged collisions.

Reserved rows share the table: ``#meta#backfill#<name>`` (the per-name
backfill-complete marker) and ``#meta#configured`` (the indexed-name set the
last passing readiness probe saw). Real keys are 64-character hex digests,
so a reserved key cannot collide. They are written by
``actingweb-property-lookup`` and the startup readiness check (see
:mod:`actingweb.maintenance.property_lookup`) and read by
:func:`read_readiness`.
"""

import hashlib
import json
import logging
import os

from pynamodb.attributes import UnicodeAttribute
from pynamodb.constants import PAY_PER_REQUEST_BILLING_MODE
from pynamodb.exceptions import DoesNotExist, PutError
from pynamodb.models import Model

from actingweb.db.dynamodb._ensure import ensure_table
from actingweb.db.exceptions import DbError

logger = logging.getLogger(__name__)


def compute_lookup_key(property_name: str, value: str) -> str:
    """Compute the v2 lookup key: hex SHA-256 of ``name + NUL + value``.

    Permanent data format — changing this orphans every stored lookup row.
    """
    return hashlib.sha256(f"{property_name}\x00{value}".encode()).hexdigest()


class PropertyLookupV2(Model):
    """v2 lookup row: digest hash key, actor/property attributes only."""

    class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
        table_name = (
            os.getenv("AWS_DB_PREFIX", "demo_actingweb") + "_property_lookup_v2"
        )
        billing_mode = PAY_PER_REQUEST_BILLING_MODE
        region = os.getenv("AWS_DEFAULT_REGION", "us-west-1")
        host = os.getenv("AWS_DB_HOST", None)

    lookup_key = UnicodeAttribute(hash_key=True)
    actor_id = UnicodeAttribute()
    property_name = UnicodeAttribute()


def _digest_prefix(property_name: str, value: str) -> str:
    """Short digest prefix for log correlation — never log the value."""
    return compute_lookup_key(property_name, value)[:12]


def is_resource_not_found(e: BaseException) -> bool:
    """Whether a PynamoDB error says the table does not exist."""
    if getattr(e, "cause_response_code", None) == "ResourceNotFoundException":
        return True
    if type(e).__name__ == "TableDoesNotExist":
        return True
    text = str(e)
    return "ResourceNotFound" in text or "Requested resource not found" in text


LOOKUP_BACKFILL_PREFIX = "#meta#backfill#"
LOOKUP_CONFIGURED_KEY = "#meta#configured"
LOOKUP_META_ACTOR = "#meta"


def _marker_key(name: str) -> str:
    return LOOKUP_BACKFILL_PREFIX + name


def read_readiness(names: list[str]) -> tuple[set[str], set[str] | None]:
    """The names with a backfill-complete marker, and the recorded name set.

    One consistent ``BatchGetItem`` of the per-name markers and the
    configured-set row. Module-level and never creates the table: a missing
    table is reported as ``DbError("lookup table missing")`` (the startup
    check must not paper over a wrong ``AWS_DB_PREFIX`` by creating an empty
    table), and any other fault raises ``DbError`` too. The second element is
    ``None`` when no set has been recorded yet.
    """
    keys = [_marker_key(n) for n in names] + [LOOKUP_CONFIGURED_KEY]
    marked: set[str] = set()
    configured: set[str] | None = None
    try:
        for row in PropertyLookupV2.batch_get(keys, consistent_read=True):
            key = str(row.lookup_key)
            if key == LOOKUP_CONFIGURED_KEY:
                configured = set(json.loads(str(row.property_name)))
            elif key.startswith(LOOKUP_BACKFILL_PREFIX):
                marked.add(key[len(LOOKUP_BACKFILL_PREFIX) :])
    except Exception as e:
        if is_resource_not_found(e):
            raise DbError(
                f"lookup table missing: {PropertyLookupV2.Meta.table_name}"
            ) from e
        raise DbError("property lookup readiness read") from e
    return marked, configured


def mark_backfilled(names: list[str]) -> None:
    """Write the backfill-complete marker of each name (idempotent).

    A lost condition is success: two first starts racing write one row.
    """
    for name in names:
        row = PropertyLookupV2(
            lookup_key=_marker_key(name),
            actor_id=LOOKUP_META_ACTOR,
            property_name=name,
        )
        try:
            row.save(condition=PropertyLookupV2.lookup_key.does_not_exist())
        except PutError as e:
            if (
                getattr(e, "cause_response_code", None)
                == "ConditionalCheckFailedException"
            ):
                continue
            raise DbError("property lookup mark") from e
        except Exception as e:
            raise DbError("property lookup mark") from e


def unmark(names: list[str]) -> None:
    """Remove the backfill-complete marker of each name (idempotent)."""
    for name in names:
        try:
            PropertyLookupV2(
                lookup_key=_marker_key(name),
                actor_id=LOOKUP_META_ACTOR,
                property_name=name,
            ).delete()
        except Exception as e:
            raise DbError("property lookup unmark") from e


def record_configured(names: list[str]) -> None:
    """Record the configured indexed-name set (unconditional put)."""
    try:
        PropertyLookupV2(
            lookup_key=LOOKUP_CONFIGURED_KEY,
            actor_id=LOOKUP_META_ACTOR,
            property_name=json.dumps(sorted(set(names))),
        ).save()
    except Exception as e:
        raise DbError("property lookup record") from e


class DbPropertyLookup:
    """
    DbPropertyLookup handles all db operations for the property lookup table.

    Enables reverse lookups (property value -> actor_id) without any
    value-size limit. All operations recompute the digest from the caller's
    (property_name, value), so the plaintext value never touches the table.
    """

    def __init__(self) -> None:
        self.handle: PropertyLookupV2 | None = None
        ensure_table(PropertyLookupV2)

    def get(
        self,
        property_name: str | None = None,
        value: str | None = None,
        *,
        strict: bool = True,
    ) -> str | None:
        """
        Retrieve actor_id by property name and value.

        Args:
            property_name: Property name (e.g., "oauthId")
            value: Property value to lookup (exact match, verbatim)
            strict: When False, a read fault answers None instead of raising

        Returns:
            Actor ID if found, None otherwise

        Raises:
            DbError: on a read fault (unless ``strict=False``)
        """
        if not property_name or not value:
            return None

        try:
            self.handle = PropertyLookupV2.get(
                compute_lookup_key(property_name, value), consistent_read=True
            )
            return str(self.handle.actor_id) if self.handle.actor_id else None
        except DoesNotExist:
            return None
        except Exception as e:
            logger.error(
                f"LOOKUP_GET_FAILED: property={property_name} "
                f"digest={_digest_prefix(property_name, value)} error={e}"
            )
            if strict:
                raise DbError("property lookup get") from e
            return None

    def create(
        self,
        property_name: str | None = None,
        value: str | None = None,
        actor_id: str | None = None,
        overwrite: bool = False,
    ) -> bool:
        """
        Create a lookup entry.

        Uses a conditional put: an existing row for the same (name, value)
        owned by a DIFFERENT actor is a collision — logged loudly, not
        silently overwritten (pass overwrite=True for legitimate value
        moves). Re-creating an identical row is idempotent.

        Returns:
            True on success (including idempotent re-create), False on
            collision.

        Raises:
            DbError: on a write fault (a fault is not a collision).
        """
        if not property_name or not value or not actor_id:
            return False

        key = compute_lookup_key(property_name, value)
        row = PropertyLookupV2(
            lookup_key=key,
            actor_id=actor_id,
            property_name=property_name,
        )
        try:
            if overwrite:
                row.save()
            else:
                row.save(condition=PropertyLookupV2.lookup_key.does_not_exist())
            self.handle = row
            return True
        except PutError as e:
            if (
                getattr(e, "cause_response_code", None)
                == "ConditionalCheckFailedException"
            ):
                try:
                    existing = PropertyLookupV2.get(key, consistent_read=True)
                except Exception:
                    existing = None
                if existing is not None and str(existing.actor_id) == actor_id:
                    # Idempotent re-create of the same mapping
                    self.handle = existing
                    return True
                logger.error(
                    f"LOOKUP_COLLISION: property={property_name} "
                    f"digest={key[:12]} actor={actor_id} "
                    f"existing_actor={existing.actor_id if existing else 'unknown'} — "
                    "two actors share an indexed value; not overwriting"
                )
                return False
            logger.error(
                f"LOOKUP_CREATE_FAILED: property={property_name} "
                f"digest={key[:12]} actor={actor_id} error={e}"
            )
            raise DbError("property lookup create", actor_id) from e
        except Exception as e:
            logger.error(
                f"LOOKUP_CREATE_FAILED: property={property_name} "
                f"digest={key[:12]} actor={actor_id} error={e}"
            )
            raise DbError("property lookup create", actor_id) from e

    def delete(
        self, property_name: str | None = None, value: str | None = None
    ) -> bool:
        """Delete the lookup entry for (property_name, value).

        Can be called directly with the pair, or with no arguments after a
        get() (which leaves self.handle set).
        """
        if property_name and value:
            key = compute_lookup_key(property_name, value)
            try:
                row = PropertyLookupV2.get(key, consistent_read=True)
            except DoesNotExist:
                return False
            except Exception as e:
                logger.error(
                    f"LOOKUP_DELETE_FAILED: property={property_name} "
                    f"digest={key[:12]} error={e}"
                )
                return False
            try:
                row.delete()
                return True
            except Exception as e:
                logger.error(
                    f"LOOKUP_DELETE_FAILED: property={property_name} "
                    f"digest={key[:12]} error={e}"
                )
                return False

        if not self.handle:
            return False
        try:
            self.handle.delete()
            self.handle = None
            return True
        except Exception as e:
            logger.error(f"LOOKUP_DELETE_FAILED: error={e}")
            return False
