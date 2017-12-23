from google.appengine.ext import ndb
import logging

"""
    DbTrust handles all db operations for a trust
    Google datastore for google is used as a backend.
"""

__all__ = [
    'DbTrust',
    'DbTrustList',
]


class Trust(ndb.Model):
    """ Data model for a trust relationship """
    id = ndb.StringProperty(required=True)
    peerid = ndb.StringProperty(required=True)
    baseuri = ndb.StringProperty(required=True)
    type = ndb.StringProperty(required=True)
    relationship = ndb.StringProperty(required=True)
    secret = ndb.StringProperty(required=True)
    desc = ndb.TextProperty()
    approved = ndb.BooleanProperty()
    peer_approved = ndb.BooleanProperty()
    verified = ndb.BooleanProperty()
    verification_token = ndb.StringProperty()


class DbTrust():
    """
        DbTrust does all the db operations for trust objects

        The  actor_id must always be set.
    """

    def get(self,  actor_id=None, peerid=None, token=None):
        """ Retrieves the property from the database

            Either peerid or token must be set.
            If peerid is set, token will be ignored.
        """
        if not actor_id:
            return None
        if not self.handle and peerid:
            self.handle = Trust.query(Trust.id == actor_id,
                                      Trust.peerid == peerid).get(use_cache=False)
        elif not self.handle and token:
            self.handle = Trust.query(Trust.id == actor_id,
                                      Trust.secret == token).get(use_cache=False)
        if self.handle:
            t = self.handle
            return {
                "id": t.id,
                "peerid": t.peerid,
                "baseuri": t.baseuri,
                "type": t.type,
                "relationship": t.relationship,
                "secret": t.secret,
                "desc": t.desc,
                "approved": t.approved,
                "peer_approved": t.peer_approved,
                "verified": t.verified,
                "verification_token": t.verification_token,
            }
        else:
            return None

    def modify(self, baseuri=None,
               secret=None,
               desc=None,
               approved=None,
               verified=None,
               verification_token=None,
               peer_approved=None):
        """ Modify a trust 
        
            If bools are none, they will not be changed.
        """
        if not self.handle:
            logging.debug("Attempted modification of DbTrust without db handle")
            return False
        if baseuri and len(baseuri) > 0:
            self.handle.baseuri = baseuri
        if secret and len(secret) > 0:
            self.handle.secret = secret
        if desc and len(desc) > 0:
            self.handle.desc = desc
        if approved is not None:
            self.handle.approved = approved
        if verified is not None:
            self.handle.verified = verified
        if verification_token and len(verification_token) > 0:
            self.handle.verification_token = verification_token
        if peer_approved is not None:
            self.handle.peer_approved = peer_approved
        self.handle.put(use_cache=False)
        return True

    def create(self, actor_id=None, peerid=None,
               baseuri='', peer_type='', relationship='',
               secret='', approved='', verified=False,
               peer_approved=False, verification_token='',
               desc=''):
        """ Create a new trust """
        if not actor_id or not peerid:
            return False
        self.handle = Trust(id=actor_id,
                            peerid=peerid,
                            baseuri=baseuri,
                            type=peer_type,
                            relationship=relationship,
                            secret=secret,
                            approved=approved,
                            verified=verified,
                            peer_approved=peer_approved,
                            verification_token=verification_token,
                            desc=desc)
        self.handle.put(use_cache=False)
        return True

    def delete(self):
        """ Deletes the property in the database """
        if not self.handle:
            return False
        self.handle.key.delete(use_cache=False)
        self.handle = None
        return True

    def is_token_in_db(self, actor_id=None, token=None):
        """ Returns True if token is found in db """
        if not actor_id or len(actor_id) == 0:
            return False
        if not token or len(token) == 0:
            return False
        res = Trust.query(Trust.id == actor_id, 
                          Trust.secret == token).get(use_cache=False)
        if res:
            return True
        return False

    def __init__(self):
        self.handle = None


class DbTrustList():
    """
        DbTrustList does all the db operations for list of trust objects

        The  actor_id must always be set. 
    """

    def fetch(self,  actor_id):
        """ Retrieves the trusts of an actor_id from the database as an array"""
        if not actor_id:
            return None
        self.handle = Trust.query(Trust.id == actor_id).fetch(use_cache=False)
        self.trusts = []
        if self.handle:
            for t in self.handle:
                self.trusts.append(
                {
                    "id": t.id,
                    "peerid": t.peerid,
                    "baseuri": t.baseuri,
                    "type": t.type,
                    "relationship": t.relationship,
                    "secret": t.secret,
                    "desc": t.desc,
                    "approved": t.approved,
                    "peer_approved": t.peer_approved,
                    "verified": t.verified,
                    "verification_token": t.verification_token,
                })
            return self.trusts
        else:
            return []

    def delete(self):
        """ Deletes all the properties in the database """
        if not self.handle:
            return False
        for p in self.handle:
            p.key.delete(use_cache=False)
        self.handle = None
        return True

    def __init__(self):
        self.handle = None
