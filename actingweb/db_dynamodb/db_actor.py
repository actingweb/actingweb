import os
from pynamodb.models import Model
from pynamodb.attributes import UnicodeAttribute
from pynamodb.indexes import GlobalSecondaryIndex, AllProjection
import logging

"""
    db_actor handles all db operations for an actor
    Google datastore for google is used as a backend.
"""

__all__ = [
    'db_actor',
    'db_actor_list',
]


class CreatorIndex(GlobalSecondaryIndex):
    """
    Secondary index on actor
    """
    class Meta:
        index_name = 'creator-index'
        read_capacity_units = 2
        write_capacity_units = 1
        projection = AllProjection()

    creator = UnicodeAttribute(hash_key=True)


class Actor(Model):
    """
       DynamoDB data model for an actor
    """
    class Meta:
        table_name = "actors"
        read_capacity_units = 6
        write_capacity_units = 2
        region = os.getenv('AWS_DEFAULT_REGION', 'us-west-1')
        host = os.getenv('AWS_DB_HOST', None)

    id = UnicodeAttribute(hash_key=True)
    creator = UnicodeAttribute()
    passphrase = UnicodeAttribute()
    creator_index = CreatorIndex()


class db_actor():
    """
        db_actor does all the db operations for actor objects

    """

    def get(self,  actorId=None):
        """ Retrieves the actor from the database """
        if not actorId:
            return None
        try:
            if self.handle:
                self.handle.refresh()
            else:
                self.handle = Actor.get(actorId, consistent_read=True)
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

    def getByCreator(self, creator=None):
        """ Retrieves the actor from db based on creator field

            Returns None if none was found. If one is found, that one is
            loaded in the object. If more, all are returned.
        """
        if not creator:
            return None
        self.handle = Actor.creator_index.query(creator)
        if not self.handle or len(self.handle) == 0:
            return None
        ret = []
        if len(self.handle) == 1:
            ret.append(self.get(actorId=self.handle[0].id))
            return ret
        logging.warn("Found multiple actors with creator(" + creator + "):")
        for c in self.handle:
            logging.warn("    id (" + c.id + ")")
            ret.append(self.get(actorId=c.id))
        return ret

    def modify(self, creator=None, passphrase=None):
        """ Modify an actor """
        if not self.handle:
            logging.debug("Attempted modification of db_actor without db handle")
            return False
        if creator and len(creator) > 0:
            self.handle.creator = creator
        if passphrase and len(passphrase) > 0:
            self.handle.passphrase = passphrase
        self.handle.save()
        return True

    def create(self, actorId=None, creator=None,
               passphrase=None):
        """ Create a new actor """
        if not actorId:
            return False
        if not creator:
            creator = ''
        if not passphrase:
            passphrase = ''
        if self.get(actorId=actorId):
            logging.warn("Trying to create actor that exists(" + actorId + ")")
            return False
        self.handle = Actor(id=actorId,
                            creator=creator,
                            passphrase=passphrase)
        self.handle.save()
        return True

    def delete(self):
        """ Deletes the actor in the database """
        if not self.handle:
            logging.debug("Attempted delete of db_actor without db handle")
            return False
        self.handle.delete()
        self.handle = None
        return True

    def __init__(self):
        self.handle = None
        if not Actor.exists():
            Actor.create_table(wait=True)


class db_actor_list():
    """
        db_actor_list does all the db operations for list of actor objects
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
