class attributes():
    """
        attribute is the main entity keeping an attribute.

        It needs to be initalized at object creation time.

    """

    def get_bucket(self):
        """ Retrieves the attribute bucket from the database """
        if not self.data or len(self.data) == 0:
            self.data = self.dbprop.get_bucket(actorId=self.actorId, bucket=self.bucket)
        return self.data

    def get_attr(self, name=None):
        """ Retrieves a single attribute """
        if not name:
            return None
        if not name in self.data:
            self.data[name] = self.dbprop.get_attr(actorId=self.actorId, bucket=self.bucket, name=name)
        return self.data[name]

    def set_attr(self, name=None, data=None, timestamp=None):
        """ Sets new data for this attribute """
        if not self.actorId or not self.bucket:
            return False
        if not name in data:
            self.data[name] = {}
        self.data[name]["data"] = data
        self.data[name]["timestamp"] = timestamp
        return self.dbprop.set_attr(
            actorId=self.actorId,
            bucket=self.bucket,
            name=name,
            data=data,
            timestamp=timestamp
        )

    def delete_attr(self, name=None):
        if not name:
            return False
        del self.data[name]
        return self.dbprop.delete_attr(actorId=self.actorId, bucket=self.bucket, name=name)

    def delete_bucket(self):
        """ Deletes the attribute bucket in the database """
        if not self.dbprop:
            return False
        if self.dbprop.delete_bucket(actorId=self.actorId, bucket=self.bucket):
            self.dbprop = self.config.db_attribute.db_attribute()
            self.data = {}
            return True
        else:
            return False

    def __init__(self,  actorId=None, bucket=None, config=None):
        """ A attribute must be initialised with actorId and bucket
        """
        self.config = config
        self.dbprop = self.config.db_attribute.db_attribute()
        self.bucket = bucket
        self.actorId = actorId
        self.data = {}
        if actorId and bucket and len(bucket) > 0 and config:
            self.get_bucket()


class buckets():
    """ Handles all attribute buckets of a specific actor_id

        Access the attributes
        in .props as a dictionary
    """

    def fetch(self):
        if not self.actorId:
            return False
        return self.list.fetch(actorId=self.actorId)

    def fetch_timestamps(self):
        if not self.actorId:
            return False
        return self.list.fetch_timestamps(actorId=self.actorId)

    def delete(self):
        if not self.list:
            return False
        self.list.delete(actorId=self.actorId)
        self.list = self.config.db_attribute.db_attribute_bucket_list()
        return True

    def __init__(self,  actorId=None, config=None):
        """ attributes must always be initialised with an actorId """
        self.config = config
        if not actorId:
            self.list = None
            return
        self.list = self.config.db_attribute.db_attribute_bucket_list()
        self.actorId = actorId


