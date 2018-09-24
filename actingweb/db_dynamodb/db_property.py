from builtins import object
import os
from pynamodb.models import Model
from pynamodb.attributes import UnicodeAttribute
from pynamodb.indexes import GlobalSecondaryIndex, AllProjection

"""
    DbProperty handles all db operations for a property
    AWS DynamoDB is used as a backend.
"""


class PropertyIndex(GlobalSecondaryIndex):
    """
    Secondary index on property
    """
    class Meta(object):
        index_name = 'property-index'
        read_capacity_units = 2
        write_capacity_units = 1
        projection = AllProjection()

    value = UnicodeAttribute(default=0, hash_key=True)


class Property(Model):
    """
       DynamoDB data model for a property
    """
    class Meta(object):
        table_name = os.getenv('AWS_DB_PREFIX', 'demo_actingweb') + "_properties"
        read_capacity_units = 26
        write_capacity_units = 2
        region = os.getenv('AWS_DEFAULT_REGION', 'us-west-1')
        host = os.getenv('AWS_DB_HOST', None)

    id = UnicodeAttribute(hash_key=True)
    name = UnicodeAttribute(range_key=True)
    value = UnicodeAttribute()
    property_index = PropertyIndex()


class DbProperty(object):
    """
        DbProperty does all the db operations for property objects

        The actor_id must always be set. get(), set() and
        get_actor_id_from_property() will set a new internal handle
        that will be reused by set() (overwrite property) and
        delete().
    """

    def get(self,  actor_id=None, name=None):
        """ Retrieves the property from the database """
        if not actor_id or not name:
            return None
        if self.handle:
            try:
                self.handle.refresh()
            except Property.DoesNotExist:
                return None
            return self.handle.value
        try:
            self.handle = Property.get(actor_id, name, consistent_read=True)
        except Property.DoesNotExist:
            return None
        return self.handle.value

    def get_actor_id_from_property(self, name=None, value=None):
        """ Retrives an actor_id based on the value of a property.
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

    def set(self, actor_id=None, name=None, value=None):
        """ Sets a new value for the property name
        """
        if not name:
            return False
        if not value or len(value) == 0:
            if self.get(actor_id=actor_id, name=name):
                self.delete()
            return True
        if not self.handle:
            if not actor_id:
                return False
            self.handle = Property(id=actor_id, name=name,
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


class DbPropertyList(object):
    """
        DbPropertyList does all the db operations for list of property objects

        The actor_id must always be set.
    """

    def fetch(self,  actor_id=None):
        """ Retrieves the properties of an actor_id from the database """
        if not actor_id:
            return None
        self.actor_id = actor_id
        self.handle = Property.scan(Property.id == actor_id)
        if self.handle:
            self.props = {}
            for d in self.handle:
                self.props[d.name] = d.value
            return self.props
        else:
            return None

    def delete(self):
        """ Deletes all the properties in the database """
        if not self.actor_id:
            return False
        self.handle = Property.scan(Property.id == self.actor_id)
        if not self.handle:
            return False
        for p in self.handle:
            p.delete()
        self.handle = None
        return True

    def __init__(self):
        self.handle = None
        self.actor_id = None
        self.props = None
