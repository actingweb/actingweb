from builtins import object


class PropertyStore(object):

    def __init__(self, actor_id=None, config=None):
        self._actor_id = actor_id
        self._config = config
        self.__initialised = True

    def __getitem__(self, k):
        return self.__getattr__(k)

    def __setitem__(self, k, v):
        return self.__setattr__(k, v)

    def __setattr__(self, k, v):
        if '_PropertyStore__initialised' not in self.__dict__:
            return object.__setattr__(self, k, v)
        if v is None:
            if k in self.__dict__:
                self.__delattr__(k)
        else:
            self.__dict__[k] = v
        # Re-init property to avoid overwrite
        self.__dict__['_db'] = self.__dict__['_config'].DbProperty.DbProperty()
        # set() will retrieve an attribute and delete it if value = None
        self.__dict__['_db'].set(actor_id=self.__dict__['_actor_id'], name=k, value=v)

    def __getattr__(self, k):
        try:
            return self.__dict__[k]
        except KeyError:
            self.__dict__['_db'] = self.__dict__['_config'].DbProperty.DbProperty()
            self.__dict__[k] = self.__dict__['_db'].get(actor_id=self.__dict__['_actor_id'], name=k)
            return self.__dict__[k]


class Property(object):
    """
        property is the main entity keeping a property.

        It needs to be initalised at object creation time.

    """

    def get(self):
        """ Retrieves the property from the database """
        if not self.dbprop:
            # New property after a delete()
            self.dbprop = self.config.DbProperty.DbProperty()
            self.value = None
        self.value = self.dbprop.get(actor_id=self.actor_id, name=self.name)
        return self.value

    def set(self, value):
        """ Sets a new value for this property """
        if not self.dbprop:
            # New property after a delete()
            self.dbprop = self.config.DbProperty.DbProperty()
        if not self.actor_id or not self.name:
            return False
        # Make sure we have made a dip in db to avoid two properties
        # with same name
        db_value = self.dbprop.get(actor_id=self.actor_id, name=self.name)
        if db_value == value:
            return True
        self.value = value
        return self.dbprop.set(actor_id=self.actor_id, name=self.name, value=value)

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

    def get_actor_id(self):
        return self.actor_id

    def __init__(self, actor_id=None, name=None, value=None, config=None):
        """ A property must be initialised with actor_id and name or
            name and value (to find an actor's property of a certain value)
        """
        self.config = config
        self.dbprop = self.config.DbProperty.DbProperty()
        self.name = name
        if not actor_id and name and len(name) > 0 and value and len(value) > 0:
            self.actor_id = self.dbprop.get_actor_id_from_property(name=name,
                                                                   value=value)
            if not self.actor_id:
                return
            self.value = value
        else:
            self.actor_id = actor_id
            self.value = None
            if name and len(name) > 0:
                self.get()


class Properties(object):
    """ Handles all properties of a specific actor_id

        Access the properties
        in .props as a dictionary
    """

    def fetch(self):
        if not self.actor_id:
            return False
        if not self.list:
            return False
        if self.props is not None:
            return self.props
        self.props = self.list.fetch(actor_id=self.actor_id)
        return self.props

    def delete(self):
        if not self.list:
            self.fetch()
        if not self.list:
            return False
        self.list.delete()
        return True

    def __init__(self,  actor_id=None, config=None):
        """ Properties must always be initialised with an actor_id """
        self.config = config
        if not actor_id:
            self.list = None
            return
        self.list = self.config.DbProperty.DbPropertyList()
        self.actor_id = actor_id
        self.props = None
        self.fetch()
