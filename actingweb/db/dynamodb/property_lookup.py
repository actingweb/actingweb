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

The v1 model below is retained read-only for the migration fallback and
is never auto-created. Migration: run scripts/backfill_property_lookup.py
(rebuilds v2 from the properties table — the source of truth), verify,
then drop the v1 table.
"""

import hashlib
import logging
import os

from pynamodb.attributes import UnicodeAttribute
from pynamodb.constants import PAY_PER_REQUEST_BILLING_MODE
from pynamodb.exceptions import DoesNotExist, PutError
from pynamodb.models import Model

from actingweb.db.dynamodb._ensure import ensure_table

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


class PropertyLookup(Model):
    """DEPRECATED v1 lookup row — read-only migration fallback.

    Never auto-created; a missing table is a normal state handled by the
    fallback read path. Removed (with the table) in the next major release.
    """

    class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
        table_name = os.getenv("AWS_DB_PREFIX", "demo_actingweb") + "_property_lookup"
        billing_mode = PAY_PER_REQUEST_BILLING_MODE
        region = os.getenv("AWS_DEFAULT_REGION", "us-west-1")
        host = os.getenv("AWS_DB_HOST", None)

    property_name = UnicodeAttribute(hash_key=True)
    value = UnicodeAttribute(range_key=True)
    actor_id = UnicodeAttribute()


def _digest_prefix(property_name: str, value: str) -> str:
    """Short digest prefix for log correlation — never log the value."""
    return compute_lookup_key(property_name, value)[:12]


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
        self, property_name: str | None = None, value: str | None = None
    ) -> str | None:
        """
        Retrieve actor_id by property name and value.

        Args:
            property_name: Property name (e.g., "oauthId")
            value: Property value to lookup (exact match, verbatim)

        Returns:
            Actor ID if found, None otherwise
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
            return None

    def get_v1(
        self, property_name: str | None = None, value: str | None = None
    ) -> str | None:
        """Read-only fallback against the deprecated v1 table.

        Returns None when the v1 table does not exist (normal for fresh
        deployments) or holds no row. A hit means the deployment has not
        run the v2 backfill yet.
        """
        if not property_name or not value:
            return None
        try:
            row = PropertyLookup.get(property_name, value, consistent_read=True)
            return str(row.actor_id) if row.actor_id else None
        except Exception:
            # DoesNotExist and missing-table errors alike mean "no v1 answer"
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
            collision or write failure.
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
            if "ConditionalCheckFailed" in str(e):
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
            return False
        except Exception as e:
            logger.error(
                f"LOOKUP_CREATE_FAILED: property={property_name} "
                f"digest={key[:12]} actor={actor_id} error={e}"
            )
            return False

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
