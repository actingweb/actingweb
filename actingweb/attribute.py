from typing import Any


class InternalStore:
    """Access to internal attributes using .prop notation"""

    def __init__(
        self,
        actor_id: str | None = None,
        config: Any | None = None,
        bucket: str | None = None,
    ) -> None:
        if not bucket:
            bucket = "_internal"
        self._db = Attributes(actor_id=actor_id, bucket=bucket, config=config)
        d = self._db.get_bucket()
        if d:
            for k, v in d.items():
                self.__setattr__(k, v.get("data"))
        self.__initialised = True

    def __getitem__(self, k: str) -> Any:
        return self.__getattr__(k)

    def __setitem__(self, k: str, v: Any) -> None:
        return self.__setattr__(k, v)

    def __setattr__(self, k: str, v: Any) -> None:
        if "_InternalStore__initialised" not in self.__dict__:
            return object.__setattr__(self, k, v)
        if k is None:
            raise ValueError
        if v is None:
            self.__dict__["_db"].delete_attr(name=k)
            if k in self.__dict__:
                self.__delattr__(k)
        else:
            self.__dict__[k] = v
            self.__dict__["_db"].set_attr(name=k, data=v)

    def __getattr__(self, k: str) -> Any:
        try:
            return self.__dict__[k]
        except KeyError:
            return None


class Attributes:
    """
    Attributes is the main entity keeping an attribute.

    It needs to be initalized at object creation time.

    """

    def get_bucket(self) -> dict[str, Any] | None:
        """Retrieves the attribute bucket from the database"""
        if not self.data or len(self.data) == 0:
            if self.dbprop:
                self.data = self.dbprop.get_bucket(
                    actor_id=self.actor_id, bucket=self.bucket
                )
            else:
                self.data = {}
        return self.data

    def get_attr(self, name: str | None = None) -> dict[str, Any] | None:
        """Retrieves a single attribute"""
        if not name:
            return None
        if name not in self.data:
            if self.dbprop:
                self.data[name] = self.dbprop.get_attr(
                    actor_id=self.actor_id, bucket=self.bucket, name=name
                )
            else:
                self.data[name] = None
        return self.data[name]

    def set_attr(
        self,
        name: str | None = None,
        data: Any | None = None,
        timestamp: Any | None = None,
    ) -> bool:
        """Sets new data for this attribute"""
        if not self.actor_id or not self.bucket:
            return False
        if name not in self.data or self.data[name] is None:
            self.data[name] = {}
        self.data[name]["data"] = data
        self.data[name]["timestamp"] = timestamp
        if self.dbprop:
            return self.dbprop.set_attr(
                actor_id=self.actor_id,
                bucket=self.bucket,
                name=name,
                data=data,
                timestamp=timestamp,
            )
        return False

    def delete_attr(self, name: str | None = None) -> bool:
        if not name:
            return False
        if "name" in self.data:
            del self.data[name]
        if self.dbprop:
            return self.dbprop.delete_attr(
                actor_id=self.actor_id, bucket=self.bucket, name=name
            )
        return False

    def delete_bucket(self) -> bool:
        """Deletes the attribute bucket in the database"""
        if not self.dbprop:
            return False
        if self.dbprop.delete_bucket(actor_id=self.actor_id, bucket=self.bucket):
            if self.config:
                self.dbprop = self.config.DbAttribute.DbAttribute()
            else:
                self.dbprop = None
            self.data = {}
            return True
        else:
            return False

    def __init__(
        self,
        actor_id: str | None = None,
        bucket: str | None = None,
        config: Any | None = None,
    ) -> None:
        """A attribute must be initialised with actor_id and bucket"""
        self.config = config
        if self.config:
            self.dbprop = self.config.DbAttribute.DbAttribute()
        else:
            self.dbprop = None
        self.bucket = bucket
        self.actor_id = actor_id
        self.data = {}
        if actor_id and bucket and len(bucket) > 0 and config:
            self.get_bucket()


class Buckets:
    """Handles all attribute buckets of a specific actor_id

    Access the attributes
    in .props as a dictionary
    """

    def fetch(self) -> dict[str, Any] | bool:
        if not self.actor_id:
            return False
        if self.list:
            return self.list.fetch(actor_id=self.actor_id)
        return False

    def fetch_timestamps(self) -> dict[str, Any] | bool:
        if not self.actor_id:
            return False
        if self.list:
            return self.list.fetch_timestamps(actor_id=self.actor_id)
        return False

    def delete(self) -> bool:
        if not self.list:
            return False
        self.list.delete(actor_id=self.actor_id)
        if self.config:
            self.list = self.config.DbAttribute.DbAttributeBucketList()
        else:
            self.list = None
        return True

    def __init__(self, actor_id: str | None = None, config: Any | None = None) -> None:
        """attributes must always be initialised with an actor_id"""
        self.config = config
        if not actor_id:
            self.list = None
            return
        if self.config:
            self.list = self.config.DbAttribute.DbAttributeBucketList()
        else:
            self.list = None
        self.actor_id = actor_id
