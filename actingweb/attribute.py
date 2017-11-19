class attributes():
    """
        attribute is the main entity keeping an attribute.

        It needs to be initalized at object creation time.

    """

    def get(self):
        """ Retrieves the attribute bucket from the database """
        return self.dbprop.get(actorId=self.actorId, bucket=self.bucket)

    def set(self, name=None, value=None):
        """ Sets a new value for this attribute """
        if not self.actorId or not self.bucket:
            return False
        return self.dbprop.set(actorId=self.actorId, bucket=self.bucket, name=name, value=value)

    def unset(self, name=None):
        if not name:
            return False
        return self.dbprop.delete(actorId=self.actorId, bucket=self.bucket, name=name)

    def delete(self):
        """ Deletes the attribute bucket in the database """
        if not self.dbprop:
            return False
        if self.dbprop.delete_bucket(actorId=self.actorId, bucket=self.bucket):
            self.dbprop = self.config.db_attribute.db_attribute()
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
        if actorId and bucket and len(bucket) > 0:
            self.get()


class buckets():
    """ Handles all attribute buckets of a specific actor_id

        Access the attributes
        in .props as a dictionary
    """

    def fetch(self):
        if not self.actorId:
            return False
        return self.list.fetch(actorId=self.actorId)

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


