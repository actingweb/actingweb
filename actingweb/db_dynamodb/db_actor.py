from builtins import object
import os
from pynamodb.models import Model
from pynamodb.attributes import UnicodeAttribute
from pynamodb.indexes import GlobalSecondaryIndex, AllProjection
import logging

"""
    DbActor handles all db operations for an actor
    Google datastore for google is used as a backend.
"""


class CreatorIndex(GlobalSecondaryIndex):
    """
    Secondary index on actor
    """
    class Meta(object):
        index_name = 'creator-index'
        read_capacity_units = 2
        write_capacity_units = 1
        projection = AllProjection()

    creator = UnicodeAttribute(hash_key=True)


class Actor(Model):
    """
       DynamoDB data model for an actor
    """
    class Meta(object):
        table_name = os.getenv('AWS_DB_PREFIX', 'demo_actingweb') + "_actors"
        read_capacity_units = 6
        write_capacity_units = 2
        region = os.getenv('AWS_DEFAULT_REGION', 'us-west-1')
        host = os.getenv('AWS_DB_HOST', None)

    id = UnicodeAttribute(hash_key=True)
    creator = UnicodeAttribute()
    passphrase = UnicodeAttribute()
    creator_index = CreatorIndex()


class DbActor(object):
    """
        DbActor does all the db operations for actor objects

    """

    def get(self,  actor_id=None):
        """ Retrieves the actor from the database """
        if not actor_id:
            return None
        try:
            self.handle = Actor.get(actor_id, consistent_read=True)
        except Actor.DoesNotExist:
            return None
        if self.handle:
            t = self.handle
            return {
                "id": t.id,
                "creator": t.creator,
                "passphrase": t.passphrase,
            }
        else:
            return None

    def get_by_creator(self, creator=None):
        """ Retrieves the actor from db based on creator field

            Returns None if none was found. If one is found, that one is
            loaded in the object. If more, all are returned.
        """
        if not creator:
            return None
        self.handle = Actor.creator_index.query(creator)
        ret = []
        for c in self.handle:
            logging.warning("    id (" + c.id + ")")
            ret.append(self.get(actor_id=c.id))
        return ret

    def modify(self, creator=None, passphrase=None):
        """ Modify an actor """
        if not self.handle:
            logging.debug("Attempted modification of DbActor without db handle")
            return False
        if creator and len(creator) > 0:
            self.handle.creator = creator
        if passphrase and len(passphrase) > 0:
            self.handle.passphrase = passphrase.decode('utf-8')
        self.handle.save()
        return True

    def create(self, actor_id=None, creator=None,
               passphrase=None):
        """ Create a new actor """
        if not actor_id:
            return False
        if not creator:
            creator = ''
        if not passphrase:
            passphrase = ''
        if self.get(actor_id=actor_id):
            logging.warning("Trying to create actor that exists(" + actor_id + ")")
            return False
        self.handle = Actor(id=actor_id,
                            creator=creator,
                            passphrase=passphrase)
        self.handle.save()
        return True

    def delete(self):
        """ Deletes the actor in the database """
        if not self.handle:
            logging.debug("Attempted delete of DbActor without db handle")
            return False
        self.handle.delete()
        self.handle = None
        return True

    def __init__(self):
        self.handle = None
        if not Actor.exists():
            Actor.create_table(wait=True)


class DbActorList(object):
    """
        DbActorList does all the db operations for list of actor objects
    """

    def fetch(self):
        """ Retrieves the actors in the database """
        self.handle = Actor.scan()
        if self.handle:
            ret = []
            for t in self.handle:
                ret.append({
                    "id": t.id,
                    "creator": t.creator,
                    })
            return ret
        else:
            return False

    def __init__(self):
        self.handle = None
