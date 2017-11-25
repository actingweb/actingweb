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
    value = JSONAttribute(null=True)
    timestamp = UTCDateTimeAttribute(null=True)


class db_attribute():
    """
        db_property does all the db operations for property objects

        The actorId must always be set. get(), set() will set a new internal handle
        that will be reused by set() (overwrite attribute) and
        delete().
    """

    def get(self,  actorId=None, bucket=None):
        """ Retrieves the attributes from bucket from the database """
        if not actorId or not bucket:
            return None
        if len(self.value) > 0:
            return self.value
        if self.bucket and self.bucket != bucket:
            return None
        self.bucket = bucket
        try:
            query = Attribute.query(
                actorId,
                Attribute.bucket_name.startswith(bucket),
                consistent_read=True)
        except Attribute.DoesNotExist:
            return None
        self.value = {}
        self.timestamp = {}
        for t in query:
            self.value[t.name] = t.value
            self.timestamp[t.name] = t.timestamp
        return self.value

    def get_timestamps(self):
        if len(self.timestamp)> 0:
            return self.timestamp
        return None

    def set(self, actorId=None, bucket=None, name=None, value=None, timestamp=None):
        """ Sets a new value for the bucket and attribute name
        """
        if not name or not bucket:
            return False
        self.value[name] = value
        self.timestamp[name] = timestamp
        if not value or len(value) == 0:
            try:
                item = Attribute.get(actorId, bucket + ":" + name)
                item.delete()
            except Attribute.DoesNotExist:
                pass
            return True
        new = Attribute(
            id=actorId,
            bucket_name=bucket + ":" + name,
            bucket=bucket,
            name=name,
            value=value,
            timestamp=timestamp
        )
        new.save()
        return True

    def delete(self, actorId=None, bucket=None, name=None):
        """ Deletes an attribute in a bucket
        """
        del self.value[name]
        return self.set(actorId=actorId, bucket=bucket, name=name, value=None)

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
        self.value = {}
        self.timestamp = {}
        return True

    def __init__(self):
        self.bucket = None
        self.value = {}
        self.timestamp = {}
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
            ret[t.bucket][t.name] = t.value
        return ret

    def fetch_timestamps(self,  actorId=None):
        """ Retrieves all the timestamps of attributes of an actorId from the database """
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
            ret[t.bucket][t.name] = t.timestamp
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