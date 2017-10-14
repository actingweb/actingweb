from google.appengine.ext import ndb

"""
    db_peertrustee handles all db operations for a peer we are a trustee for.
    Google datastore for google is used as a backend.
"""

__all__ = [
    'db_peertrustee',
    'db_peertrustee_list',
]


class PeerTrustee(ndb.Model):
    id = ndb.StringProperty(required=True)
    peerid = ndb.StringProperty(required=True)
    baseuri = ndb.StringProperty(required=True)
    type = ndb.StringProperty(required=True)
    passphrase = ndb.StringProperty(required=True)


class db_peertrustee():
    """
        db_peertrustee does all the db operations for property objects

        The actorId must always be set.
    """

    def get(self,  actorId=None, type=None, peerid=None):
        """ Retrieves the peertrustee from the database """
        if not actorId:
            return None
        if not peerid and not type:
            logging.debug("Attempt to get db_peertrustee without peerid or type")
            return None
        if not self.handle and peerid:
            self.handle = PeerTrustee.query(PeerTrustee.id == actorId,
                                            PeerTrustee.peerid == peerid).get(use_cache=False)
        elif not self.handle and type:
            self.handle = PeerTrustee.query(PeerTrustee.id == actorId,
                                            PeerTrustee.type == type).fetch(use_cache=False)
            if len(self.handle) > 1:
                logging.error('Found more than one peer of this peer trustee type(' + 
                              shorttype + '). Unable to determine which, need peerid lookup.')
                return False
            if len(self.handle) == 1:
                self.handle = self.handle[0]
        if self.handle:
            t = self.handle
            return {
                "id": t.id,
                "peerid": t.peerid,
                "baseuri": t.baseuri,
                "type": t.type,
                "passphrase": t.passphrase,
            }
        else:
            return None

    def create(self, actorId=None,
               peerid=None,
               type=None,
               baseuri=None,
               passphrase=None):
        """ Create a new peertrustee """
        if not actorId or not peerid or not type:
            logging.debug("actorId, peerid, and type are mandatory when creating peertrustee in db")
            return False
        if not baseuri:
            baseuri = ''
        if not passphrase:
            passphrase = ''
        self.handle = PeerTrustee(id=actorId,
                                  peerid=peerid,
                                  type=type,
                                  baseuri=baseuri,
                                  passphrase=passphrase)
        self.handle.put(use_cache=False)
        return True

    def modify(self,
               type=None,
               baseuri=None,
               passphrase=None):
        """ Modify a peertrustee

            If bools are none, they will not be changed.
        """
        if not self.handle:
            logging.debug("Attempted modification of db_peertrustee without db handle")
            return False
        if baseuri and len(baseuri) > 0:
            self.handle.baseuri = baseuri
        if passphrase and len(passphrase) > 0:
            self.handle.passphrase = passphrase
        if type and len(type) > 0:
            self.handle.type = type
        self.handle.put(use_cache=False)
        return True

    def delete(self):
        """ Deletes the peertrustee in the database after a get() """
        if not self.handle:
            return False
        self.handle.key.delete(use_cache=False)
        self.handle = None
        return True

    def __init__(self):
        self.handle = None


class db_peertrustee_list():
    """
        db_peertrustee_list does all the db operations for list of peertrustee objects

        The  actorId must always be set.
    """

    def fetch(self,  actorId=None):
        """ Retrieves the peer trustees of an actorId from the database """
        if not actorId:
            return None
        self.handle = PeerTrustee.query(PeerTrustee.id == actorId).fetch(use_cache=False)
        self.peertrustees = []
        if self.handle:
            for t in self.handle:
                self.peertrustees.append(
                {
                  "id": t.id,
                  "peerid": t.peerid,
                  "baseuri": t.baseuri,
                  "type": t.type,
                  "passphrase": t.passphrase,
                })
            return self.peertrustees
        else:
            return []

    def delete(self):
        """ Deletes all the peertrustees in the database """
        if not self.handle:
            return False
        for p in self.handle:
            p.key.delete(use_cache=False)
        self.handle = None
        return True

    def __init__(self):
        self.handle = None
