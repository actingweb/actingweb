from builtins import object


class Attributes(object):
    """
        Attributes is the main entity keeping an attribute.

        It needs to be initalized at object creation time.

    """

    def get_bucket(self):
        """ Retrieves the attribute bucket from the database """
        if not self.data or len(self.data) == 0:
            self.data = self.dbprop.get_bucket(actor_id=self.actor_id, bucket=self.bucket)
        return self.data

    def get_attr(self, name=None):
        """ Retrieves a single attribute """
        if not name:
            return None
        if name not in self.data:
            self.data[name] = self.dbprop.get_attr(actor_id=self.actor_id, bucket=self.bucket, name=name)
        return self.data[name]

    def set_attr(self, name=None, data=None, timestamp=None):
        """ Sets new data for this attribute """
        if not self.actor_id or not self.bucket:
            return False
        if name not in data:
            self.data[name] = {}
        self.data[name]["data"] = data
        self.data[name]["timestamp"] = timestamp
        return self.dbprop.set_attr(
            actor_id=self.actor_id,
            bucket=self.bucket,
            name=name,
            data=data,
            timestamp=timestamp
        )

    def delete_attr(self, name=None):
        if not name:
            return False
        if 'name' in self.data:
            del self.data[name]
        return self.dbprop.delete_attr(actor_id=self.actor_id, bucket=self.bucket, name=name)

    def delete_bucket(self):
        """ Deletes the attribute bucket in the database """
        if not self.dbprop:
            return False
        if self.dbprop.delete_bucket(actor_id=self.actor_id, bucket=self.bucket):
            self.dbprop = self.config.DbAttribute.DbAttribute()
            self.data = {}
            return True
        else:
            return False

    def __init__(self,  actor_id=None, bucket=None, config=None):
        """ A attribute must be initialised with actor_id and bucket
        """
        self.config = config
        self.dbprop = self.config.DbAttribute.DbAttribute()
        self.bucket = bucket
        self.actor_id = actor_id
        self.data = {}
        if actor_id and bucket and len(bucket) > 0 and config:
            self.get_bucket()


class Buckets(object):
    """ Handles all attribute buckets of a specific actor_id

        Access the attributes
        in .props as a dictionary
    """

    def fetch(self):
        if not self.actor_id:
            return False
        return self.list.fetch(actor_id=self.actor_id)

    def fetch_timestamps(self):
        if not self.actor_id:
            return False
        return self.list.fetch_timestamps(actor_id=self.actor_id)

    def delete(self):
        if not self.list:
            return False
        self.list.delete(actor_id=self.actor_id)
        self.list = self.config.DbAttribute.DbAttributeBucketList()
        return True

    def __init__(self,  actor_id=None, config=None):
        """ attributes must always be initialised with an actor_id """
        self.config = config
        if not actor_id:
            self.list = None
            return
        self.list = self.config.DbAttribute.DbAttributeBucketList()
        self.actor_id = actor_id
