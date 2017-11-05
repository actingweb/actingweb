class property():
    """
        property is the main entity keeping a property.

        It needs to be initalised at object creation time.

    """

    def get(self):
        """ Retrieves the property from the database """
        if not self.dbprop:
            # New property after a delete()
            self.dbprop = self.config.db_property.db_property()
            self.value=None
        self.value = self.dbprop.get(actorId=self.actorId, name=self.name)
        return self.value

    def set(self, value):
        """ Sets a new value for this property """
        if not self.dbprop:
            # New property after a delete()
            self.dbprop = self.config.db_property.db_property()
        if not self.actorId or not self.name:
            return False
        # Make sure we have made a dip in db to avoid two properties
        # with same name
        db_value = self.dbprop.get(actorId=self.actorId, name=self.name)
        if db_value == value:
            return True
        self.value = value
        return self.dbprop.set(actorId=self.actorId, name=self.name, value=value)

    def delete(self):
        """ Deletes the property in the database """
        if not self.dbprop:
            return
        if self.dbprop.delete():
            self.value = None
            self.dbprop = None
            return True
        else:
            return False

    def getActorId(self):
        return self.actorId

    def __init__(self,  actorId=None, name=None, value=None, config=None):
        """ A property must be initialised with actorId and name or
            name and value (to find an actor's property of a certain value)
        """
        self.config = config
        self.dbprop = self.config.db_property.db_property()
        self.name = name
        if not actorId and name and len(name) > 0 and value and len(value) > 0:
            self.actorId = self.dbprop.get_actorId_from_property(name=name,
                                                                 value=value)
            if not self.actorId:
                return
            self.value = value
        else:
            self.actorId = actorId
            self.value = None
            if name and len(name) > 0:
                self.get()


class properties():
    """ Handles all properties of a specific actor_id

        Access the properties
        in .props as a dictionary
    """

    def fetch(self):
        if not self.actorId:
            return False
        if not self.list:
            return False
        if self.props is not None:
            return self.props
        self.props = self.list.fetch(actorId=self.actorId)
        return self.props

    def delete(self):
        if not self.list:
            self.fetch()
        if not self.list:
            return False
        self.list.delete()
        return True

    def __init__(self,  actorId=None, config=None):
        """ Properties must always be initialised with an actorId """
        self.config = config
        if not actorId:
            self.list = None
            return False
        self.list = self.config.db_property.db_property_list()
        self.actorId = actorId
        self.props = None
        self.fetch()


