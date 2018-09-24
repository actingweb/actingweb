from builtins import object
import os
from pynamodb.models import Model
from pynamodb.attributes import UnicodeAttribute, JSONAttribute, UTCDateTimeAttribute

"""
    DbAttribute handles all db operations for an attribute (internal)
    AWS DynamoDB is used as a backend.
"""


class Attribute(Model):
    """
       DynamoDB data model for a property
    """
    class Meta(object):
        table_name = os.getenv('AWS_DB_PREFIX', 'demo_actingweb') + "_attributes"
        read_capacity_units = 26
        write_capacity_units = 2
        region = os.getenv('AWS_DEFAULT_REGION', 'us-west-1')
        host = os.getenv('AWS_DB_HOST', None)

    id = UnicodeAttribute(hash_key=True)
    bucket_name = UnicodeAttribute(range_key=True)
    bucket = UnicodeAttribute()
    name = UnicodeAttribute()
    data = JSONAttribute(null=True)
    timestamp = UTCDateTimeAttribute(null=True)


class DbAttribute(object):
    """
        DbProperty does all the db operations for property objects

        The actor_id must always be set. get(), set() will set a new internal handle
        that will be reused by set() (overwrite attribute) and
        delete().
    """

    @staticmethod
    def get_bucket(actor_id=None, bucket=None):
        """ Returns a dict of attributes from a bucket, each with data and timestamp """
        if not actor_id or not bucket:
            return None
        try:
            query = Attribute.query(
                actor_id,
                Attribute.bucket_name.startswith(bucket),
                consistent_read=True)
        except Attribute.DoesNotExist:
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
        """ Returns a dict of attributes from a bucket, each with data and timestamp """
        if not actor_id or not bucket or not name:
            return None
        try:
            r = Attribute.get(actor_id, bucket + ":" + name, consistent_read=True)
        except Attribute.DoesNotExist:
            return None
        return {
            "data": r.data,
            "timestamp": r.timestamp,
        }

    @staticmethod
    def set_attr(actor_id=None, bucket=None, name=None, data=None, timestamp=None):
        """ Sets a data value for a given attribute in a bucket
        """
        if not actor_id or not name or not bucket:
            return False
        if not data:
            try:
                item = Attribute.get(actor_id, bucket + ":" + name, consistent_read=True)
                item.delete()
            except Attribute.DoesNotExist:
                pass
            return True
        new = Attribute(
            id=actor_id,
            bucket_name=bucket + ":" + name,
            bucket=bucket,
            name=name,
            data=data,
            timestamp=timestamp
        )
        new.save()
        return True

    def delete_attr(self, actor_id=None, bucket=None, name=None):
        """ Deletes an attribute in a bucket
        """
        return self.set_attr(actor_id=actor_id, bucket=bucket, name=name, data=None)

    @staticmethod
    def delete_bucket(actor_id=None, bucket=None):
        """ Deletes an entire bucket
        """
        if not actor_id or not bucket:
            return False
        try:
            query = Attribute.query(
                actor_id,
                Attribute.bucket_name.startswith(bucket),
                consistent_read=True)
        except Attribute.DoesNotExist:
            return True
        for t in query:
            t.delete()
        return True

    def __init__(self):
        if not Attribute.exists():
            Attribute.create_table(wait=True)


class DbAttributeBucketList(object):
    """
        DbAttributeBucketList handles multiple buckets

        The  actor_id must always be set.
    """

    @staticmethod
    def fetch(actor_id=None):
        """ Retrieves all the attributes of an actor_id from the database """
        if not actor_id:
            return None
        try:
            query = Attribute.query(actor_id)
        except Attribute.DoesNotExist:
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
        """ Deletes all the attributes in the database """
        if not actor_id:
            return False
        try:
            query = Attribute.query(actor_id)
        except Attribute.DoesNotExist:
            return False
        for t in query:
            t.delete()
        return True

    def __init__(self):
        if not Attribute.exists():
            Attribute.create_table(wait=True)
