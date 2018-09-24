from builtins import object
import os
import logging
from pynamodb.models import Model
from pynamodb.attributes import UnicodeAttribute

"""
    DbPeerTrustee handles all db operations for a peer we are a trustee for.
    Google datastore for google is used as a backend.
"""


class PeerTrustee(Model):

    class Meta(object):
        table_name = os.getenv('AWS_DB_PREFIX', 'demo_actingweb') + "_peertrustees"
        read_capacity_units = 1
        write_capacity_units = 1
        region = os.getenv('AWS_DEFAULT_REGION', 'us-west-1')
        host = os.getenv('AWS_DB_HOST', None)

    id = UnicodeAttribute(hash_key=True)
    peerid = UnicodeAttribute(range_key=True)
    baseuri = UnicodeAttribute()
    type = UnicodeAttribute()
    passphrase = UnicodeAttribute()


class DbPeerTrustee(object):
    """
        DbPeerTrustee does all the db operations for property objects

        The actor_id must always be set.
    """

    def get(self,  actor_id=None, peer_type=None, peerid=None):
        """ Retrieves the peertrustee from the database """
        if not actor_id:
            return None
        if not peerid and not peer_type:
            logging.debug("Attempt to get DbPeerTrustee without peerid or type")
            return None
        try:
            if not self.handle and peerid:
                self.handle = PeerTrustee.get(actor_id, peerid, consistent_read=True)
            elif not self.handle and peer_type:
                if PeerTrustee.count(actor_id, PeerTrustee.type == peer_type) > 1:
                    logging.error('Found more than one peer of this peer trustee type(' +
                                  peer_type + '). Unable to determine which, need peerid lookup.')
                    return False
                for h in PeerTrustee.query(actor_id, PeerTrustee.type == peer_type):
                    self.handle = h
        except PeerTrustee.DoesNotExist:
            self.handle = None
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

    def create(self, actor_id=None,
               peerid=None,
               peer_type=None,
               baseuri=None,
               passphrase=None):
        """ Create a new peertrustee """
        if not actor_id or not peerid or not peer_type:
            logging.debug("actor_id, peerid, and type are mandatory when creating peertrustee in db")
            return False
        if not baseuri:
            baseuri = ''
        if not passphrase:
            passphrase = ''
        self.handle = PeerTrustee(id=actor_id,
                                  peerid=peerid,
                                  type=peer_type,
                                  baseuri=baseuri,
                                  passphrase=passphrase)
        self.handle.save()
        return True

    def modify(self,
               peer_type=None,
               baseuri=None,
               passphrase=None):
        """ Modify a peertrustee

            If bools are none, they will not be changed.
        """
        if not self.handle:
            logging.debug("Attempted modification of DbPeerTrustee without db handle")
            return False
        if baseuri and len(baseuri) > 0:
            self.handle.baseuri = baseuri
        if passphrase and len(passphrase) > 0:
            self.handle.passphrase = passphrase
        if type and len(peer_type) > 0:
            self.handle.type = peer_type
        self.handle.save()
        return True

    def delete(self):
        """ Deletes the peertrustee in the database after a get() """
        if not self.handle:
            return False
        self.handle.delete()
        self.handle = None
        return True

    def __init__(self):
        self.handle = None
        if not PeerTrustee.exists():
            PeerTrustee.create_table(wait=True)


class DbPeerTrusteeList(object):
    """
        DbPeerTrusteeList does all the db operations for list of peertrustee objects

        The  actor_id must always be set.
    """

    def fetch(self,  actor_id=None):
        """ Retrieves the peer trustees of an actor_id from the database """
        if not actor_id:
            return None
        self.actor_id = actor_id
        self.peertrustees = []
        self.handle = PeerTrustee.scan(PeerTrustee.actor_id == self.actor_id)
        if self.handle:
            for t in self.handle:
                self.peertrustees.append({
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
        self.handle = PeerTrustee.scan(PeerTrustee.actor_id == self.actor_id)
        if not self.handle:
            return False
        for p in self.handle:
            p.delete()
        self.handle = None
        return True

    def __init__(self):
        self.handle = None
        self.actor_id = None
        self.peertrustees = None
