import logging
import os
import time
from collections.abc import Sequence

from pynamodb.attributes import (
    JSONAttribute,
    NumberAttribute,
    UnicodeAttribute,
    UTCDateTimeAttribute,
)
from pynamodb.constants import PAY_PER_REQUEST_BILLING_MODE
from pynamodb.exceptions import DoesNotExist, PutError
from pynamodb.models import Model

from actingweb.db.dynamodb._ensure import ensure_table
from actingweb.db.exceptions import DbError

# ``delete_by_chain`` scans whole token buckets; past this many rows in one
# bucket it logs a WARNING that the scan is outgrowing its budget (see the
# method's docstring).
CHAIN_SCAN_WARN_ROWS = 1000

logger = logging.getLogger(__name__)


def ttl_deadline(ttl_seconds: int) -> int:
    """The stored ``ttl_timestamp`` for a row that lives ``ttl_seconds``.

    Adds ``TTL_CLOCK_SKEW_BUFFER`` so DynamoDB's native TTL never reaps a row
    before its application-level expiry, whatever the clock skew.
    """
    from ...constants import TTL_CLOCK_SKEW_BUFFER

    return int(time.time()) + ttl_seconds + TTL_CLOCK_SKEW_BUFFER


"""
    DbAttribute handles all db operations for an attribute (internal)
    AWS DynamoDB is used as a backend.
"""


class Attribute(Model):
    """
    DynamoDB data model for a property
    """

    class Meta:  # type: ignore[misc]
        table_name = os.getenv("AWS_DB_PREFIX", "demo_actingweb") + "_attributes"
        billing_mode = PAY_PER_REQUEST_BILLING_MODE
        region = os.getenv("AWS_DEFAULT_REGION", "us-west-1")
        host = os.getenv("AWS_DB_HOST", None)

    id = UnicodeAttribute(hash_key=True)
    bucket_name = UnicodeAttribute(range_key=True)
    bucket = UnicodeAttribute()
    name = UnicodeAttribute()
    data = JSONAttribute(null=True)
    timestamp = UTCDateTimeAttribute(null=True)
    # TTL timestamp for automatic DynamoDB expiration (Unix epoch timestamp)
    # Enable DynamoDB TTL on this field for automatic cleanup
    ttl_timestamp = NumberAttribute(null=True)


def normalize_json(data):
    """Normalize JSON data by serializing with sorted keys, so that
    ``{"a": 1, "b": 2}`` and ``{"b": 2, "a": 1}`` compare equal."""
    import json

    if data is None:
        return None
    return json.loads(json.dumps(data, sort_keys=True))


class DbAttribute:
    """
    DbProperty does all the db operations for property objects

    The actor_id must always be set. get(), set() will set a new internal handle
    that will be reused by set() (overwrite attribute) and
    delete().
    """

    @staticmethod
    def get_bucket(actor_id=None, bucket=None, *, strict=True):
        """Returns a dict of attributes from a bucket, each with data and timestamp

        ``{}`` for an empty bucket. A read fault raises ``DbError``;
        ``strict=False`` answers it with None. Expired rows are returned:
        a sweep that reads a bucket to find what to delete must find them.

        ``bucket_name`` is ``bucket + ":" + name``, so ``begins_with(bucket)``
        would also match every bucket that has this one as a prefix — bucket
        ``remote:abc`` seeing ``remote:abcd``'s rows. The delimiter narrows the
        Query, and the exact ``t.bucket`` compare is what actually separates
        them, because both halves of the composite key may themselves contain
        ``:`` (bucket ``remote:{peer_id}``, name ``list:{name}:{index}``), so
        bucket ``remote:abc``/name ``x`` and bucket ``remote``/name ``abc:x``
        produce an identical ``bucket_name``. Same guard as
        ``delete_by_chain()`` below and
        ``db/dynamodb/subscription_suspension.py``'s cascade check.
        """
        if not actor_id or not bucket:
            return None
        ret = {}
        try:
            # The pages are fetched while iterating, so the try covers the
            # loop, not just the lazy query() call.
            for t in Attribute.query(
                actor_id,
                Attribute.bucket_name.startswith(bucket + ":"),
                consistent_read=True,
            ):
                if t.bucket != bucket:
                    continue
                ret[t.name] = {
                    "data": t.data,
                    "timestamp": t.timestamp,
                }
        except Exception as e:
            if strict:
                raise DbError("attribute get_bucket") from e
            logger.error(f"Error reading bucket {bucket} of {actor_id}: {e}")
            return None
        return ret

    @staticmethod
    def get_attr(actor_id=None, bucket=None, name=None, *, strict=True):
        """One attribute as ``{"data", "timestamp"}``, None when absent.

        A read fault raises ``DbError``; ``strict=False`` answers it with
        None. An expired row is returned (only ``get_attr_strict`` hides it).
        """
        if not actor_id or not bucket or not name:
            return None
        try:
            r = Attribute.get(actor_id, bucket + ":" + name, consistent_read=True)
        except DoesNotExist:
            return None
        except Exception as e:
            if strict:
                raise DbError("attribute get_attr") from e
            logger.error(f"Error reading attribute {bucket}/{name} of {actor_id}: {e}")
            return None
        # Same guard as get_bucket(): the composite key can collide across
        # buckets, and the stored ``bucket`` is what says whose row it is.
        if r.bucket != bucket:
            return None
        return {
            "data": r.data,
            "timestamp": r.timestamp,
        }

    @staticmethod
    def get_attr_strict(actor_id=None, bucket=None, name=None):
        """Point-read one attribute, distinguishing absence from failure.

        ``get_attr()`` collapses every outcome into ``None``: a missing row, a
        throttle, an expired credential and a missing table are
        indistinguishable. That is tolerable for a cache read and wrong for any
        caller whose "row is absent" branch is a decision rather than a
        fallback — the deletion tombstone read being the case in the library.

        Absence returns ``None``; a fault raises ``DbError`` so the caller can
        tell "I looked and it is not there" from "I could not look".

        An expired row reads as absent. DynamoDB's TTL sweep may lag by up to
        48 hours, and a tombstone past its window must stop suppressing writes
        on time rather than whenever the sweeper gets to it.
        """
        if not actor_id or not bucket or not name:
            return None
        try:
            r = Attribute.get(actor_id, bucket + ":" + name, consistent_read=True)
        except DoesNotExist:
            return None
        except Exception as e:
            raise DbError("attribute get_attr_strict") from e
        if r.bucket != bucket:
            return None
        if r.ttl_timestamp is not None and r.ttl_timestamp <= int(time.time()):
            return None
        return {
            "data": r.data,
            "timestamp": r.timestamp,
        }

    @staticmethod
    def set_attr(
        actor_id=None,
        bucket=None,
        name=None,
        data=None,
        timestamp=None,
        ttl_seconds=None,
    ):
        """Sets a data value for a given attribute in a bucket.

        Args:
            actor_id: The actor ID
            bucket: The bucket name
            name: The attribute name
            data: The data to store (JSON-serializable)
            timestamp: Optional timestamp
            ttl_seconds: Optional TTL in seconds from now. If provided,
                         DynamoDB will automatically delete this item after expiry.
                         Note: A 1-hour buffer is added for clock skew safety.

        A falsy ``data`` deletes the row: True when it is gone after the call
        (an absent row counts). A fault raises ``DbError``.
        """
        if not actor_id or not name or not bucket:
            return False
        if not data:
            try:
                item = Attribute.get(
                    actor_id, bucket + ":" + name, consistent_read=True
                )
                if item.bucket == bucket:
                    item.delete()
            except DoesNotExist:
                pass
            except Exception as e:
                raise DbError("attribute delete") from e
            return True

        # Calculate TTL timestamp if provided
        ttl_timestamp = None
        if ttl_seconds is not None:
            ttl_timestamp = ttl_deadline(ttl_seconds)

        # Defensive sanitization of data before storing
        from actingweb.db.utils import sanitize_json_data

        data = sanitize_json_data(data, log_source="attribute")

        new = Attribute(
            id=actor_id,
            bucket_name=bucket + ":" + name,
            bucket=bucket,
            name=name,
            data=data,
            timestamp=timestamp,
            ttl_timestamp=ttl_timestamp,
        )
        try:
            new.save()
        except Exception as e:
            raise DbError("attribute set") from e
        return True

    def delete_attr(self, actor_id=None, bucket=None, name=None):
        """Deletes an attribute in a bucket"""
        return self.set_attr(actor_id=actor_id, bucket=bucket, name=name, data=None)

    @staticmethod
    def delete_attr_conditional(actor_id=None, bucket=None, name=None):
        """Atomically delete an attribute, returning True only if THIS call
        removed an existing item.

        The DeleteItem carries a ``attribute_exists(id)`` condition, so when
        two callers race on the same attribute exactly one delete succeeds and
        the other fails its condition check (item already gone). Backs
        single-use/atomic-consume semantics (e.g. mobile-ticket redemption).

        Args:
            actor_id: The actor ID
            bucket: The bucket name
            name: The attribute name

        Returns:
            True if this call removed an existing item, False otherwise
        """
        if not actor_id or not bucket or not name:
            return False
        try:
            item = Attribute.get(actor_id, bucket + ":" + name, consistent_read=True)
        except Exception:  # PynamoDB DoesNotExist exception
            return False
        if item.bucket != bucket:
            return False
        try:
            # Condition fails (raises) if a concurrent caller already deleted it.
            item.delete(condition=Attribute.id.exists())
            return True
        except Exception:
            return False

    @staticmethod
    def conditional_update_attr(
        actor_id=None,
        bucket=None,
        name=None,
        old_data=None,
        new_data=None,
        timestamp=None,
        ttl_seconds=None,
    ):  # type: ignore[misc]
        """Conditionally update an attribute only if current data matches old_data.

        This provides atomic compare-and-swap functionality for race-free updates.

        JSON comparison is order-independent - dict key ordering does not affect equality.
        If the caller's old_data has different key ordering than stored data, we normalize
        both sides for comparison and use the stored ordering for the atomic update.

        Args:
            actor_id: The actor ID
            bucket: The bucket name
            name: The attribute name
            old_data: Expected current data value (for comparison)
            new_data: New data to set if current matches old_data
            timestamp: Optional timestamp
            ttl_seconds: When given, the same conditional update sets
                ``ttl_timestamp`` (plus the clock-skew buffer, as ``set_attr``
                does)

        Returns:
            True if update succeeded (current matched old_data), False otherwise
        """
        if not actor_id or not bucket or not name:
            return False

        bucket_name = bucket + ":" + name

        # Defensive sanitization of data before storing
        from actingweb.db.utils import sanitize_json_data

        old_data = sanitize_json_data(old_data, log_source="attribute")
        new_data = sanitize_json_data(new_data, log_source="attribute")

        try:
            # Get current item with consistent read
            item = Attribute.get(actor_id, bucket_name, consistent_read=True)
            if item.bucket != bucket:
                return False

            # Normalize JSON for order-independent comparison
            # This ensures {"a": 1, "b": 2} == {"b": 2, "a": 1}
            old_data_normalized = normalize_json(old_data)
            current_data_normalized = normalize_json(item.data)

            # Check if current data matches old_data (order-independent)
            if old_data_normalized != current_data_normalized:
                return False

            # Data matches semantically - perform atomic update
            # Use the ACTUAL stored data for DynamoDB's condition to ensure atomicity
            # This handles the case where old_data has different key ordering
            actions: Sequence[object] = [Attribute.data.set(new_data)]
            if timestamp:
                actions = list(actions) + [Attribute.timestamp.set(timestamp)]
            if ttl_seconds is not None:
                actions = list(actions) + [
                    Attribute.ttl_timestamp.set(ttl_deadline(ttl_seconds))
                ]

            item.update(
                actions=actions,  # type: ignore[arg-type]
                condition=(
                    Attribute.data == item.data
                ),  # Atomic check against current value
            )
            return True

        except Exception:
            # Item doesn't exist or condition check failed (race condition)
            return False

    @staticmethod
    def create_attr_if_absent(
        actor_id=None,
        bucket=None,
        name=None,
        data=None,
        timestamp=None,
        ttl_seconds=None,
    ):  # type: ignore[misc]
        """Create an attribute only if no live row holds its name.

        See ``DbAttributeProtocol.create_attr_if_absent`` for the contract.
        One ``PutItem`` conditioned on the key being absent, or on the stored
        row being in the same bucket with a ``ttl_timestamp`` at or before
        now (the expiry rule ``get_attr_strict`` applies). A lost condition
        is followed by one consistent read: JSON-equal stored data means the
        row is this call's own (an SDK retry of a write that landed).
        """
        if not actor_id or not bucket or not name:
            raise ValueError("create_attr_if_absent needs actor_id, bucket and name")

        from actingweb.db.utils import sanitize_json_data

        bucket_name = bucket + ":" + name
        data = sanitize_json_data(data, log_source="attribute")
        item = Attribute(
            id=actor_id,
            bucket_name=bucket_name,
            bucket=bucket,
            name=name,
            data=data,
            timestamp=timestamp,
            ttl_timestamp=(
                ttl_deadline(ttl_seconds) if ttl_seconds is not None else None
            ),
        )
        # A lost condition can be followed by the winner's row vanishing before
        # the read-back (a delete, the TTL reaper): the name is then free, so
        # the write is tried once more rather than reported as lost.
        for attempt in range(2):
            now = int(time.time())
            try:
                item.save(
                    condition=Attribute.id.does_not_exist()
                    | ((Attribute.bucket == bucket) & (Attribute.ttl_timestamp <= now))
                )
                return True
            except PutError as e:
                if e.cause_response_code != "ConditionalCheckFailedException":
                    raise DbError("attribute create", actor_id) from e
            except Exception as e:
                raise DbError("attribute create", actor_id) from e

            try:
                stored = Attribute.get(actor_id, bucket_name, consistent_read=True)
            except DoesNotExist:
                if attempt == 0:
                    continue
                return False
            except Exception as e:
                raise DbError("attribute create read-back", actor_id) from e
            if stored.bucket != bucket:
                return False
            return normalize_json(stored.data) == normalize_json(data)
        return False

    @staticmethod
    def delete_bucket(actor_id=None, bucket=None):
        """Deletes an entire bucket

        Carries ``get_bucket()``'s guard, and needs it more: without the
        delimiter and the exact ``t.bucket`` compare this deletes the rows of
        every bucket that has this one as a prefix. ``RemotePeerStore``
        deletes bucket ``remote:{peer_id}`` on trust teardown and most call
        sites build that id with ``validate_peer_id=False``, so ending trust
        with peer ``abc`` would destroy peer ``abcd``'s dataset. Same guard as
        ``delete_by_chain()`` below.
        """
        if not actor_id or not bucket:
            return False
        try:
            for t in Attribute.query(
                actor_id,
                Attribute.bucket_name.startswith(bucket + ":"),
                consistent_read=True,
            ):
                if t.bucket != bucket:
                    continue
                t.delete()
        except Exception as e:
            raise DbError("attribute delete_bucket") from e
        return True

    @staticmethod
    def delete_expired(now_epoch=None, buckets=None):  # type: ignore[misc]
        """Purge TTL-expired attributes.

        DynamoDB deletes expired items automatically when TTL is enabled on the
        ``ttl_timestamp`` attribute of the table (recommended; the field is
        written with a clock-skew buffer for exactly this purpose). A
        backend-driven purge here would require a full-table ``Scan``, which is
        intentionally avoided, so this relies on native TTL and reports 0
        deletions. Ensure DynamoDB TTL is enabled on the attributes table.

        Args:
            now_epoch: Ignored (native TTL uses the stored ttl_timestamp).
            buckets: Ignored.

        Returns:
            0 — deletion is handled asynchronously by DynamoDB TTL.
        """
        return 0

    @staticmethod
    def delete_by_chain(actor_id=None, buckets=None, chain_id=None, defer_name=None):  # type: ignore[misc]
        """Delete attributes whose stored ``data['chain_id']`` matches chain_id.

        Backs refresh-token family (chain) revocation. DynamoDB has no secondary
        index on the JSON-embedded ``chain_id``, so this queries the (shared)
        token buckets and filters in memory.

        **Cost.** Chain revocation is routine, not rare: every SPA logout and
        ``/oauth/revoke`` runs it, besides the theft response. It is acceptable
        while the two SPA token buckets together stay under about 1 MB (about
        3,000 rows, one page each; at most about 250 RCU per call). A WARNING
        is logged once per call when one bucket holds more than
        ``CHAIN_SCAN_WARN_ROWS`` rows. Beyond that budget the optimization is
        a GSI on a promoted top-level ``chain_id`` attribute.

        Args:
            actor_id: Storage partition id (the system actor the tokens live under).
            buckets: Bucket whitelist (the SPA access + refresh token buckets).
            chain_id: The refresh-token family identifier to delete.
            defer_name: A row name deleted after every other matching row, so
                a fault part-way (items are deleted one by one) leaves it in
                place for the caller to retry from.

        Returns:
            Number of items deleted.

        Raises:
            Exception: a query or delete failed. It is raised, never skipped:
                a non-zero count from one bucket would otherwise hide a
                bucket that was not swept.
        """
        if not actor_id or not chain_id or not buckets:
            return 0
        deleted = 0
        deferred = []
        for bucket in buckets:
            scanned = 0
            # ``bucket + ":"``: the row-key delimiter ``get_bucket`` and
            # ``delete_bucket`` use, so a sibling bucket sharing the prefix
            # (``spa_access_tokens_x``) is not read.
            for t in Attribute.query(
                actor_id,
                Attribute.bucket_name.startswith(bucket + ":"),
                consistent_read=True,
            ):
                scanned += 1
                data = t.data
                if (
                    t.bucket == bucket
                    and isinstance(data, dict)
                    and data.get("chain_id") == chain_id
                ):
                    if defer_name is not None and t.name == defer_name:
                        deferred.append(t)
                        continue
                    t.delete()
                    deleted += 1
            if scanned > CHAIN_SCAN_WARN_ROWS:
                logger.warning(
                    f"Chain revocation scanned {scanned} rows in bucket "
                    f"{bucket}; past {CHAIN_SCAN_WARN_ROWS} rows the per-call "
                    f"scan is outgrowing its budget. Promote chain_id to a "
                    f"top-level attribute with a GSI."
                )
        for t in deferred:
            t.delete()
            deleted += 1
        return deleted

    def __init__(self):
        ensure_table(Attribute)


class DbAttributeBucketList:
    """
    DbAttributeBucketList handles multiple buckets

    The  actor_id must always be set.
    """

    @staticmethod
    def fetch(actor_id=None, *, strict=True):
        """Retrieves all the attributes of an actor_id from the database.

        A read fault raises ``DbError``; ``strict=False`` answers it with None.
        """
        if not actor_id:
            return None
        ret = {}
        try:
            for t in Attribute.query(actor_id):
                if t.bucket not in ret:
                    ret[t.bucket] = {}
                ret[t.bucket][t.name] = {
                    "data": t.data,
                    "timestamp": t.timestamp,
                }
        except Exception as e:
            if strict:
                raise DbError("attribute bucket list fetch") from e
            logger.error(f"Error reading the attributes of {actor_id}: {e}")
            return None
        return ret

    @staticmethod
    def fetch_timestamps(actor_id=None, *, strict=True):
        """Retrieves timestamps for all buckets of an actor_id.

        A read fault raises ``DbError``; ``strict=False`` answers it with None.
        """
        if not actor_id:
            return None
        ret = {}
        try:
            for t in Attribute.query(actor_id):
                if t.bucket not in ret:
                    ret[t.bucket] = t.timestamp
        except Exception as e:
            if strict:
                raise DbError("attribute bucket list fetch_timestamps") from e
            logger.error(f"Error reading the attribute timestamps of {actor_id}: {e}")
            return None
        return ret

    @staticmethod
    def delete(actor_id=None):
        """Deletes all the attributes of an actor. A fault raises ``DbError``."""
        if not actor_id:
            return False
        try:
            for t in Attribute.query(actor_id):
                t.delete()
        except Exception as e:
            raise DbError("attribute bucket list delete") from e
        return True

    def __init__(self):
        ensure_table(Attribute)
