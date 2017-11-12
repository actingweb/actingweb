import logging

class trust():

    def get(self):
        """ Retrieve a trust relationship with either peerid or token """
        if self.trust and len(self.trust) > 0:
            return self.trust
        if not self.peerid and self.token:
            self.trust = self.handle.get(actorId=self.actorId,
                                         token=self.token)
        elif self.peerid and not self.token:
            self.trust = self.handle.get(actorId=self.actorId,
                                         peerid=self.peerid)
        else:
            self.trust = self.handle.get(actorId=self.actorId,
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
               verified=None, verificationToken=None, peer_approved=None):
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
        if verificationToken:
            self.trust["verificationToken"] = verificationToken
        if peer_approved is not None:
            self.trust["peer_approved"] = peer_approved
        return self.handle.modify(baseuri=baseuri, secret=secret, desc=desc, approved=approved,
                                  verified=verified, verificationToken=verificationToken,
                                  peer_approved=peer_approved)

    def create(self, baseuri='', type='', relationship='', secret='',
               approved=False, verified=False, verificationToken='',
               desc='', peer_approved=False):
        """ Create a new trust relationship """
        self.trust = {}
        self.trust["baseuri"] = baseuri
        self.trust["type"] = type
        if not relationship or len(relationship) == 0:
            self.trust["relationship"] = self.config.default_relationship
        else:
            self.trust["relationship"] = relationship
        if not secret or len(secret) == 0:
            self.trust["secret"] = self.config.newToken()
        else:
            self.trust["secret"] = secret
        # Be absolutely sure that the secret is not already used
        testhandle = self.config.db_trust.db_trust()
        if testhandle.isTokenInDB(actorId=self.actorId, token=self.trust["secret"]):
            logging.warn("Found a non-unique token where it should be unique")
            return False
        self.trust["approved"] = approved
        self.trust["peer_approved"] = peer_approved
        self.trust["verified"] = verified
        if not verificationToken or len(verificationToken) == 0:
            self.trust["verificationToken"] = self.config.newToken()
        self.trust["desc"] = desc
        self.trust["id"] = self.actorId
        self.trust["peerid"] = self.peerid
        return self.handle.create(actorId=self.actorId,
                                  peerid=self.peerid,
                                  baseuri=self.trust["baseuri"],
                                  type=self.trust["type"],
                                  relationship=self.trust["relationship"],
                                  secret=self.trust["secret"],
                                  approved=self.trust["approved"],
                                  verified=self.trust["verified"],
                                  peer_approved=self.trust["peer_approved"],
                                  verificationToken=self.trust["verificationToken"],
                                  desc=self.trust["desc"])

    def __init__(self, actorId=None, peerid=None, token=None, config=None):
        self.config = config
        self.handle = self.config.db_trust.db_trust()
        self.trust = {}
        if not actorId or len(actorId) == 0:
            logging.debug("No actorid set in initialisation of trust")
            return
        if not peerid and not token:
            logging.debug("Both peerid and token are not set in initialisation of trust. One must be set.")
            return
        if not token and (not peerid or len(peerid) == 0):
            logging.debug("No peerid set in initialisation of trust")
            return
        self.actorId = actorId
        self.peerid = peerid
        self.token = token
        self.get()


class trusts():
    """ Handles all trusts of a specific actor_id

        Access the indvidual trusts in .dbtrusts and the trust data
        in .trusts as a dictionary
    """

    def fetch(self):
        if self.trusts is not None:
            return self.trusts
        if not self.list:
            self.config.db_trust.db_trust_list()
        if not self.trusts:
            self.trusts = self.list.fetch(actorId=self.actorId)
        return self.trusts

    def delete(self):
        if not self.list:
            logging.debug("Already deleted list in trusts")
            return False
        self.list.delete()
        return True

    def __init__(self,  actorId=None, config=None):
        """ Properties must always be initialised with an actorId """
        self.config = config
        if not actorId:
            self.list = None
            logging.debug("No actorId in initialisation of trusts")
            return
        self.list = self.config.db_trust.db_trust_list()
        self.actorId = actorId
        self.trusts = None
        self.fetch()


