import os
from pynamodb.models import Model
from pynamodb.attributes import UnicodeAttribute, JSONAttribute, UTCDateTimeAttribute

"""
    db_attribute handles all db operations for an attribute (internal)
    AWS DynamoDB is used as a backend.
"""

class Attribute(Model):
    """
       DynamoDB data model for a property
    """
    class Meta:
        table_name = "attributes"
        read_capacity_units = 26
        write_capacity_units = 2
        host = os.getenv('AWS_DB_HOST', None)

    id = UnicodeAttribute(hash_key=True)
    bucket_name = UnicodeAttribute(range_key=True)
    bucket = UnicodeAttribute()
    name = UnicodeAttribute()
    data = JSONAttribute(null=True)
    timestamp = UTCDateTimeAttribute(null=True)


class db_attribute():
    """
        db_property does all the db operations for property objects

        The actorId must always be set. get(), set() will set a new internal handle
        that will be reused by set() (overwrite attribute) and
        delete().
    """

    def get_bucket(self,  actorId=None, bucket=None):
        """ Returns a dict of attributes from a bucket, each with data and timestamp """
        if not actorId or not bucket:
            return None
        try:
            query = Attribute.query(
                actorId,
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

    def get_attr(self,  actorId=None, bucket=None, name=None):
        """ Returns a dict of attributes from a bucket, each with data and timestamp """
        if not actorId or not bucket or not name:
            return None
        try:
            r = Attribute.get(actorId, bucket + ":" + name, consistent_read=True)
        except Attribute.DoesNotExist:
            return None
        return {
            "data": r.data,
            "timestamp": r.timestamp,
        }

    def set_attr(self, actorId=None, bucket=None, name=None, data=None, timestamp=None):
        """ Sets a data value for a given attribute in a bucket
        """
        if not actorId or not name or not bucket:
            return False
        if not data or len(data) == 0:
            try:
                item = Attribute.get(actorId, bucket + ":" + name, consistent_read=True)
                item.delete()
            except Attribute.DoesNotExist:
                pass
            return True
        new = Attribute(
            id=actorId,
            bucket_name=bucket + ":" + name,
            bucket=bucket,
            name=name,
            data=data,
            timestamp=timestamp
        )
        new.save()
        return True

    def delete_attr(self, actorId=None, bucket=None, name=None):
        """ Deletes an attribute in a bucket
        """
        return self.set_attr(actorId=actorId, bucket=bucket, name=name, data=None)

    def delete_bucket(self, actorId=None, bucket=None):
        """ Deletes an entire bucket
        """
        if not actorId or not bucket:
            return False
        try:
            query = Attribute.query(
                actorId,
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


class db_attribute_bucket_list():
    """
        db_attribute_bucket_list handles multiple buckets

        The  actorId must always be set.
    """

    def fetch(self,  actorId=None):
        """ Retrieves all the attributes of an actorId from the database """
        if not actorId:
            return None
        try:
            query = Attribute.query(actorId)
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

    def delete(self, actorId=None):
        """ Deletes all the attributes in the database """
        if not actorId:
            return False
        try:
            query = Attribute.query(actorId)
        except Attribute.DoesNotExist:
            return False
        for t in query:
            t.delete()
        return True

    def __init__(self):
        if not Attribute.exists():
            Attribute.create_table(wait=True)