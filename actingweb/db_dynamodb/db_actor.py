from google.appengine.ext import ndb
import logging

"""
    db_actor handles all db operations for an actor
    Google datastore for google is used as a backend.
"""

__all__ = [
    'db_actor',
    'db_actor_list',
]


class Actor(ndb.Model):
    """
       NDB data model for an actor
    """
    id = ndb.StringProperty(required=True)
    creator = ndb.StringProperty()
    passphrase = ndb.StringProperty()


class db_actor():
    """
        db_actor does all the db operations for actor objects

    """

    def get(self,  actorId=None):
        """ Retrieves the actor from the database """
        if not actorId:
            return None
        self.handle = Actor.query(Actor.id == actorId).get(use_cache=False)
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
            loaded in the object. If more, the last one found is loaded.
        """
        if not creator:
            return None
        self.handle = Actor.query(Actor.creator == creator).fetch(use_cache=False)
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
        self.handle.put(use_cache=False)
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
        self.handle = Actor(id=actorId,
                            creator=creator,
                            passphrase=passphrase)
        self.handle.put(use_cache=False)
        return True

    def delete(self):
        """ Deletes the actor in the database """
        if not self.handle:
            logging.debug("Attempted delete of db_actor without db handle")
            return False
        self.handle.key.delete(use_cache=False)
        self.handle = None
        return True

    def __init__(self):
        self.handle = None


class db_actor_list():
    """
        db_actor_list does all the db operations for list of actor objects
    """

    def fetch(self):
        """ Retrieves the actors in the database """
        self.handle = Actor.query().fetch(use_cache=False)
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
