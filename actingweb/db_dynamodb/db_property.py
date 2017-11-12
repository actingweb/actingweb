import os
from pynamodb.models import Model
from pynamodb.attributes import UnicodeAttribute
from pynamodb.indexes import GlobalSecondaryIndex, AllProjection

"""
    db_property handles all db operations for a property
    AWS DynamoDB is used as a backend.
"""

__all__ = [
    'db_property',
    'db_property_list',
]

class PropertyIndex(GlobalSecondaryIndex):
    """
    Secondary index on property
    """
    class Meta:
        index_name = 'property-index'
        read_capacity_units = 2
        write_capacity_units = 1
        region = os.getenv('AWS_DEFAULT_REGION', 'us-west-1')
        projection = AllProjection()

    value = UnicodeAttribute(default=0, hash_key=True)

class Property(Model):
    """
       DynamoDB data model for a property
    """
    class Meta:
        table_name = "properties"
        read_capacity_units = 26
        write_capacity_units = 2
        host = os.getenv('AWS_DB_HOST', None)

    id = UnicodeAttribute(hash_key=True)
    name = UnicodeAttribute(range_key=True)
    value = UnicodeAttribute()
    property_index = PropertyIndex()


class db_property():
    """
        db_property does all the db operations for property objects

        The actorId must always be set. get(), set() and
        get_actorId_from_property() will set a new internal handle
        that will be reused by set() (overwrite property) and
        delete().
    """

    def get(self,  actorId=None, name=None):
        """ Retrieves the property from the database """
        if not actorId or not name:
            return None
        if self.handle:
            try:
                self.handle.refresh()
            except Property.DoesNotExist:
                return None
            return self.handle.value
        try:
            self.handle = Property.get(actorId, name, consistent_read=True)
        except Property.DoesNotExist:
            return None
        return self.handle.value

    def get_actorId_from_property(self, name=None, value=None):
        """ Retrives an actorId based on the value of a property.
        """
        if not name or not value:
            return None
        results = Property.property_index.query(value)
        self.handle = None
        for res in results:
            self.handle = res
            break
        if not self.handle:
            return None
        return self.handle.id

    def set(self, actorId=None, name=None, value=None):
        """ Sets a new value for the property name
        """
        if not name:
            return False
        if not value or len(value) == 0:
            if self.get(actorId=actorId, name=name):
                self.delete()
            return True
        if not self.handle:
            if not actorId:
                return False
            self.handle = Property(id=actorId, name=name,
                                   value=value)
        else:
            self.handle.value = value
        self.handle.save()
        return True

    def delete(self):
        """ Deletes the property in the database after a get() """
        if not self.handle:
            return False
        self.handle.delete()
        self.handle = None
        return True

    def __init__(self):
        self.handle = None
        if not Property.exists():
            Property.create_table(wait=True)


class db_property_list():
    """
        db_property does all the db operations for list of property objects

        The  actorId must always be set.
    """

    def fetch(self,  actorId=None):
        """ Retrieves the properties of an actorId from the database """
        if not actorId:
            return None
        self.actorId = actorId
        self.handle = Property.scan(Property.id == actorId)
        if self.handle:
            self.props = {}
            for d in self.handle:
                self.props[d.name] = d.value
            return self.props
        else:
            return None

    def delete(self):
        """ Deletes all the properties in the database """
        if not self.actorId:
            return False
        self.handle = Property.scan(Property.id == self.actorId)
        if not self.handle:
            return False
        for p in self.handle:
            p.delete()
        self.handle = None
        return True

    def __init__(self):
        self.handle = None
        self.actorId = None
