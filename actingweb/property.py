from typing import Any

from .property_list import ListProperty


class PropertyListStore:
    """
    Explicit interface for managing list properties.

    Used when the application knows it's working with list data.
    """

    def __init__(self, actor_id: str | None = None, config: Any | None = None) -> None:
        self._actor_id = actor_id
        self._config = config
        self.__initialised = True

    def exists(self, name: str) -> bool:
        """Check if a list property exists without creating it."""
        try:
            if self._config:
                db = self._config.DbProperty.DbProperty()
                meta = db.get(actor_id=self._actor_id, name=f"list:{name}-meta")
                return meta is not None
        except Exception:
            pass
        return False

    def list_all(self) -> list[str]:
        """List all existing list property names."""
        list_names = []
        try:
            if self._config:
                db_list = self._config.DbProperty.DbPropertyList()
                all_props = (
                    db_list.fetch_all_including_lists(actor_id=self._actor_id) or {}
                )
                for prop_name in all_props.keys():
                    if prop_name.startswith("list:") and prop_name.endswith("-meta"):
                        # Extract list name: "list:name-meta" -> "name"
                        list_name = prop_name[
                            5:-5
                        ]  # Remove 'list:' prefix and '-meta' suffix
                        list_names.append(list_name)
        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Error in list_all(): {e}")
        return list_names

    def __getattr__(self, k: str) -> ListProperty:
        """Return a ListProperty for the requested list name."""
        if k.startswith("_"):
            raise AttributeError(
                f"'{self.__class__.__name__}' object has no attribute '{k}'"
            )

        # Validate actor_id is not None before creating ListProperty
        if self._actor_id is None:
            raise RuntimeError("Cannot create ListProperty without a valid actor_id")

        # Return a ListProperty - don't add "list:" prefix here, ListProperty will handle it
        return ListProperty(self._actor_id, k, self._config)


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

    def get_all(self) -> dict[str, Any]:
        """Fetch all properties from the database and return as dictionary."""
        if not self._actor_id or not self._config:
            return {}
        db_list = self._config.DbProperty.DbPropertyList()
        props = db_list.fetch(actor_id=self._actor_id)
        if isinstance(props, dict):
            return props
        return {}


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

    def __init__(
        self,
        actor_id: str | None = None,
        name: str | None = None,
        value: Any | None = None,
        config: Any | None = None,
    ) -> None:
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
