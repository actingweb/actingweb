import os
import time
from collections.abc import Sequence

from pynamodb.attributes import (
    JSONAttribute,
    NumberAttribute,
    UnicodeAttribute,
    UTCDateTimeAttribute,
)
from pynamodb.models import Model

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
        read_capacity_units = 26
        write_capacity_units = 2
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


class DbAttribute:
    """
    DbProperty does all the db operations for property objects

    The actor_id must always be set. get(), set() will set a new internal handle
    that will be reused by set() (overwrite attribute) and
    delete().
    """

    @staticmethod
    def get_bucket(actor_id=None, bucket=None):
        """Returns a dict of attributes from a bucket, each with data and timestamp"""
        if not actor_id or not bucket:
            return None
        try:
            query = Attribute.query(
                actor_id, Attribute.bucket_name.startswith(bucket), consistent_read=True
            )
        except Exception:  # PynamoDB DoesNotExist exception
            return None
        ret = {}
        for t in query:
            ret[t.name] = {
                "data": t.data,
                "timestamp": t.timestamp,
            }
        return ret

    @staticmethod
    def get_attr(actor_id=None, bucket=None, name=None):
        """Returns a dict of attributes from a bucket, each with data and timestamp"""
        if not actor_id or not bucket or not name:
            return None
        try:
            r = Attribute.get(actor_id, bucket + ":" + name, consistent_read=True)
        except Exception:  # PynamoDB DoesNotExist exception
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
        """
        if not actor_id or not name or not bucket:
            return False
        if not data:
            try:
                item = Attribute.get(
                    actor_id, bucket + ":" + name, consistent_read=True
                )
                item.delete()
            except Exception:  # PynamoDB DoesNotExist exception
                pass
            return True

        # Calculate TTL timestamp if provided
        ttl_timestamp = None
        if ttl_seconds is not None:
            from ...constants import TTL_CLOCK_SKEW_BUFFER

            # Add buffer for clock skew safety
            ttl_timestamp = int(time.time()) + ttl_seconds + TTL_CLOCK_SKEW_BUFFER

        new = Attribute(
            id=actor_id,
            bucket_name=bucket + ":" + name,
            bucket=bucket,
            name=name,
            data=data,
            timestamp=timestamp,
            ttl_timestamp=ttl_timestamp,
        )
        new.save()
        return True

    def delete_attr(self, actor_id=None, bucket=None, name=None):
        """Deletes an attribute in a bucket"""
        return self.set_attr(actor_id=actor_id, bucket=bucket, name=name, data=None)

    @staticmethod
    def conditional_update_attr(
        actor_id=None,
        bucket=None,
        name=None,
        old_data=None,
        new_data=None,
        timestamp=None,
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

        Returns:
            True if update succeeded (current matched old_data), False otherwise
        """
        import json

        if not actor_id or not bucket or not name:
            return False

        bucket_name = bucket + ":" + name

        try:
            # Get current item with consistent read
            item = Attribute.get(actor_id, bucket_name, consistent_read=True)

            # Normalize JSON for order-independent comparison
            # This ensures {"a": 1, "b": 2} == {"b": 2, "a": 1}
            def normalize_json(data):
                """Normalize JSON data by serializing with sorted keys."""
                if data is None:
                    return None
                return json.loads(json.dumps(data, sort_keys=True))

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
    def delete_bucket(actor_id=None, bucket=None):
        """Deletes an entire bucket"""
        if not actor_id or not bucket:
            return False
        try:
            query = Attribute.query(
                actor_id, Attribute.bucket_name.startswith(bucket), consistent_read=True
            )
        except Exception:  # PynamoDB DoesNotExist exception
            return True
        for t in query:
            t.delete()
        return True

    def __init__(self):
        if not Attribute.exists():
            Attribute.create_table(wait=True)


class DbAttributeBucketList:
    """
    DbAttributeBucketList handles multiple buckets

    The  actor_id must always be set.
    """

    @staticmethod
    def fetch(actor_id=None):
        """Retrieves all the attributes of an actor_id from the database"""
        if not actor_id:
            return None
        try:
            query = Attribute.query(actor_id)
        except Exception:  # PynamoDB DoesNotExist exception
            return None
        ret = {}
        for t in query:
            if t.bucket not in ret:
                ret[t.bucket] = {}
            ret[t.bucket][t.name] = {
                "data": t.data,
                "timestamp": t.timestamp,
            }
        return ret

    @staticmethod
    def delete(actor_id=None):
        """Deletes all the attributes in the database"""
        if not actor_id:
            return False
        try:
            query = Attribute.query(actor_id)
        except Exception:  # PynamoDB DoesNotExist exception
            return False
        for t in query:
            t.delete()
        return True

    def __init__(self):
        if not Attribute.exists():
            Attribute.create_table(wait=True)
