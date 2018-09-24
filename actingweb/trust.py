from builtins import object
import logging


class Trust(object):

    def get(self):
        """ Retrieve a trust relationship with either peerid or token """
        if self.trust and len(self.trust) > 0:
            return self.trust
        if not self.peerid and self.token:
            self.trust = self.handle.get(actor_id=self.actor_id,
                                         token=self.token)
        elif self.peerid and not self.token:
            self.trust = self.handle.get(actor_id=self.actor_id,
                                         peerid=self.peerid)
        else:
            self.trust = self.handle.get(actor_id=self.actor_id,
                                         peerid=self.peerid,
                                         token=self.token)
        return self.trust

    def delete(self):
        """ Delete the trust relationship """
        if not self.handle:
            return False
        self.trust = {}
        return self.handle.delete()

    def modify(self, baseuri=None, secret=None, desc=None, approved=None,
               verified=None, verification_token=None, peer_approved=None):
        if not self.handle:
            logging.debug("Attempted modifcation of trust without handle")
            return False
        if baseuri:
            self.trust["baseuri"] = baseuri
        if secret:
            self.trust["secret"] = secret
        if desc:
            self.trust["desc"] = desc
        if approved is not None:
            self.trust["approved"] = approved
        if verified is not None:
            self.trust["verified"] = verified
        if verification_token:
            self.trust["verification_token"] = verification_token
        if peer_approved is not None:
            self.trust["peer_approved"] = peer_approved
        return self.handle.modify(baseuri=baseuri, secret=secret, desc=desc, approved=approved,
                                  verified=verified, verification_token=verification_token,
                                  peer_approved=peer_approved)

    def create(self, baseuri='', peer_type='', relationship='', secret='',
               approved=False, verified=False, verification_token='',
               desc='', peer_approved=False):
        """ Create a new trust relationship """
        self.trust = {"baseuri": baseuri, "type": peer_type}
        if not relationship or len(relationship) == 0:
            self.trust["relationship"] = self.config.default_relationship
        else:
            self.trust["relationship"] = relationship
        if not secret or len(secret) == 0:
            self.trust["secret"] = self.config.new_token()
        else:
            self.trust["secret"] = secret
        # Be absolutely sure that the secret is not already used
        testhandle = self.config.DbTrust.DbTrust()
        if testhandle.is_token_in_db(actor_id=self.actor_id, token=self.trust["secret"]):
            logging.warning("Found a non-unique token where it should be unique")
            return False
        self.trust["approved"] = approved
        self.trust["peer_approved"] = peer_approved
        self.trust["verified"] = verified
        if not verification_token or len(verification_token) == 0:
            self.trust["verification_token"] = self.config.new_token()
        self.trust["desc"] = desc
        self.trust["id"] = self.actor_id
        self.trust["peerid"] = self.peerid
        return self.handle.create(actor_id=self.actor_id,
                                  peerid=self.peerid,
                                  baseuri=self.trust["baseuri"],
                                  peer_type=self.trust["type"],
                                  relationship=self.trust["relationship"],
                                  secret=self.trust["secret"],
                                  approved=self.trust["approved"],
                                  verified=self.trust["verified"],
                                  peer_approved=self.trust["peer_approved"],
                                  verification_token=self.trust["verification_token"],
                                  desc=self.trust["desc"])

    def __init__(self, actor_id=None, peerid=None, token=None, config=None):
        self.config = config
        self.handle = self.config.DbTrust.DbTrust()
        self.trust = {}
        if not actor_id or len(actor_id) == 0:
            logging.debug("No actorid set in initialisation of trust")
            return
        if not peerid and not token:
            logging.debug("Both peerid and token are not set in initialisation of trust. One must be set.")
            return
        if not token and (not peerid or len(peerid) == 0):
            logging.debug("No peerid set in initialisation of trust")
            return
        self.actor_id = actor_id
        self.peerid = peerid
        self.token = token
        self.get()


class Trusts(object):
    """ Handles all trusts of a specific actor_id

        Access the indvidual trusts in .dbtrusts and the trust data
        in .trusts as a dictionary
    """

    def fetch(self):
        if self.trusts is not None:
            return self.trusts
        if not self.list:
            self.config.DbTrust.DbTrustList()
        if not self.trusts:
            self.trusts = self.list.fetch(actor_id=self.actor_id)
        return self.trusts

    def delete(self):
        if not self.list:
            logging.debug("Already deleted list in trusts")
            return False
        self.list.delete()
        return True

    def __init__(self,  actor_id=None, config=None):
        """ Properties must always be initialised with an actor_id """
        self.config = config
        if not actor_id:
            self.list = None
            logging.debug("No actor_id in initialisation of trusts")
            return
        self.list = self.config.DbTrust.DbTrustList()
        self.actor_id = actor_id
        self.trusts = None
        self.fetch()
