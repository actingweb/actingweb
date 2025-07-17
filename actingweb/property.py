from typing import Any


class PropertyStore:

    def __init__(self, actor_id: str | None = None, config: Any | None = None) -> None:
        self._actor_id = actor_id
        self._config = config
        self.__initialised = True

    def __getitem__(self, k: str) -> Any:
        return self.__getattr__(k)

    def __setitem__(self, k: str, v: Any) -> None:
        return self.__setattr__(k, v)

    def __setattr__(self, k: str, v: Any) -> None:
        if "_PropertyStore__initialised" not in self.__dict__:
            return object.__setattr__(self, k, v)
        if v is None:
            if k in self.__dict__:
                self.__delattr__(k)
        else:
            self.__dict__[k] = v
        # Re-init property to avoid overwrite
        self.__dict__["_db"] = self.__dict__["_config"].DbProperty.DbProperty()
        # set() will retrieve an attribute and delete it if value = None
        self.__dict__["_db"].set(actor_id=self.__dict__["_actor_id"], name=k, value=v)

    def __getattr__(self, k: str) -> Any:
        try:
            return self.__dict__[k]
        except KeyError:
            self.__dict__["_db"] = self.__dict__["_config"].DbProperty.DbProperty()
            self.__dict__[k] = self.__dict__["_db"].get(
                actor_id=self.__dict__["_actor_id"], name=k
            )
            return self.__dict__[k]


class Property:
    """
    property is the main entity keeping a property.

    It needs to be initalised at object creation time.

    """

    def get(self) -> Any:
        """Retrieves the property from the database"""
        if not self.dbprop:
            # New property after a delete()
            if self.config:
                self.dbprop = self.config.DbProperty.DbProperty()
            else:
                self.dbprop = None
            self.value = None
        if self.dbprop:
            self.value = self.dbprop.get(actor_id=self.actor_id, name=self.name)
        else:
            self.value = None
        return self.value

    def set(self, value: Any) -> bool:
        """Sets a new value for this property"""
        if not self.dbprop:
            # New property after a delete()
            if self.config:
                self.dbprop = self.config.DbProperty.DbProperty()
            else:
                self.dbprop = None
        if not self.actor_id or not self.name:
            return False
        # Make sure we have made a dip in db to avoid two properties
        # with same name
        if self.dbprop:
            db_value = self.dbprop.get(actor_id=self.actor_id, name=self.name)
        else:
            db_value = None
        if db_value == value:
            return True
        self.value = value
        if self.dbprop:
            return self.dbprop.set(actor_id=self.actor_id, name=self.name, value=value)
        return False

    def delete(self) -> bool | None:
        """Deletes the property in the database"""
        if not self.dbprop:
            return
        if self.dbprop.delete():
            self.value = None
            self.dbprop = None
            return True
        else:
            return False

    def get_actor_id(self) -> str | None:
        return self.actor_id

    def __init__(self, actor_id: str | None = None, name: str | None = None, value: Any | None = None, config: Any | None = None) -> None:
        """A property must be initialised with actor_id and name or
        name and value (to find an actor's property of a certain value)
        """
        self.config = config
        if self.config:
            self.dbprop = self.config.DbProperty.DbProperty()
        else:
            self.dbprop = None
        self.name = name
        if not actor_id and name and len(name) > 0 and value and len(value) > 0:
            if self.dbprop:
                self.actor_id = self.dbprop.get_actor_id_from_property(
                    name=name, value=value
                )
            else:
                self.actor_id = None
            if not self.actor_id:
                return
            self.value = value
        else:
            self.actor_id = actor_id
            self.value = None
            if name and len(name) > 0:
                self.get()


class Properties:
    """Handles all properties of a specific actor_id

    Access the properties
    in .props as a dictionary
    """

    def fetch(self) -> dict[str, Any] | bool:
        if not self.actor_id:
            return False
        if not self.list:
            return False
        if self.props is not None:
            return self.props
        self.props = self.list.fetch(actor_id=self.actor_id)
        return self.props

    def delete(self) -> bool:
        if not self.list:
            self.fetch()
        if not self.list:
            return False
        self.list.delete()
        return True

    def __init__(self, actor_id: str | None = None, config: Any | None = None) -> None:
        """Properties must always be initialised with an actor_id"""
        self.config = config
        if not actor_id:
            self.list = None
            return
        if self.config:
            self.list = self.config.DbProperty.DbPropertyList()
        else:
            self.list = None
        self.actor_id = actor_id
        self.props = None
        self.fetch()
