import logging
import os
from pynamodb.models import Model
from pynamodb.attributes import UnicodeAttribute, BooleanAttribute
from pynamodb.indexes import GlobalSecondaryIndex, AllProjection

"""
    db_trust handles all db operations for a trust
    Google datastore for google is used as a backend.
"""

__all__ = [
    'db_trust',
    'db_trust_list',
]


class SecretIndex(GlobalSecondaryIndex):
    """
    Secondary index on trust
    """
    class Meta:
        index_name = 'secret-index'
        read_capacity_units = 2
        write_capacity_units = 1
        projection = AllProjection()

    secret = UnicodeAttribute(hash_key=True)


class Trust(Model):
    """ Data model for a trust relationship """
    class Meta:
        table_name = "trusts"
        read_capacity_units = 5
        write_capacity_units = 2
        region = os.getenv('AWS_DEFAULT_REGION', 'us-west-1')
        host = os.getenv('AWS_DB_HOST', None)

    id = UnicodeAttribute(hash_key=True)
    peerid = UnicodeAttribute(range_key=True)
    baseuri = UnicodeAttribute()
    type = UnicodeAttribute()
    relationship = UnicodeAttribute()
    secret = UnicodeAttribute()
    desc = UnicodeAttribute()
    approved = BooleanAttribute()
    peer_approved = BooleanAttribute()
    verified = BooleanAttribute()
    verificationToken = UnicodeAttribute()
    secret_index = SecretIndex()


class db_trust():
    """
        db_trust does all the db operations for trust objects

        The  actorId must always be set.
    """

    def get(self,  actorId=None, peerid=None, token=None):
        """ Retrieves the trust from the database

            Either peerid or token must be set.
            If peerid is set, token will be ignored.
        """
        if not actorId:
            return None
        try:
            if not self.handle and peerid:
                logging.debug('    Retrieving trust from db based on peerid(' + peerid + ')')
                self.handle = Trust.get(actorId, peerid, consistent_read=True)
            elif not self.handle and token:
                logging.debug('    Retrieving trust from db based on token(' + token + ')')
                res = Trust.secret_index.query(token)
                for h in res:
                    if actorId == h.id:
                        self.handle = h
                        break
        except Trust.DoesNotExist:
            return None
        if not self.handle:
            return None
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
            "verificationToken": t.verificationToken,
        }


    def modify(self, baseuri=None,
               secret=None,
               desc=None,
               approved=None,
               verified=None,
               verificationToken=None,
               peer_approved=None):
        """ Modify a trust 
        
            If bools are none, they will not be changed.
        """
        if not self.handle:
            logging.debug("Attempted modification of db_trust without db handle")
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
        if verificationToken and len(verificationToken) > 0:
            self.handle.verificationToken = verificationToken
        if peer_approved is not None:
            self.handle.peer_approved = peer_approved
        self.handle.save()
        return True

    def create(self, actorId=None, peerid=None,
               baseuri='', type='', relationship='',
               secret='', approved='', verified=False,
               peer_approved=False, verificationToken='',
               desc=''):
        """ Create a new trust """
        if not actorId or not peerid:
            return False
        self.handle = Trust(id=actorId,
                            peerid=peerid,
                            baseuri=baseuri,
                            type=type,
                            relationship=relationship,
                            secret=secret,
                            approved=approved,
                            verified=verified,
                            peer_approved=peer_approved,
                            verificationToken=verificationToken,
                            desc=desc)
        self.handle.save()
        return True

    def delete(self):
        """ Deletes the property in the database """
        if not self.handle:
            return False
        self.handle.delete()
        self.handle = None
        return True

    def isTokenInDB(self, actorId=None, token=None):
        """ Returns True if token is found in db """
        if not actorId or len(actorId) == 0:
            return False
        if not token or len(token) == 0:
            return False
        for r in Trust.secret_index.query(token):
            if r.id != actorId:
                continue
            else:
                return True
        return False

    def __init__(self):
        self.handle = None
        if not Trust.exists():
            Trust.create_table(wait=True)



class db_trust_list():
    """
        db_trust_list does all the db operations for list of trust objects

        The  actorId must always be set. 
    """

    def fetch(self,  actorId):
        """ Retrieves the trusts of an actorId from the database as an array"""
        if not actorId:
            return None
        self.actorId = actorId
        self.handle = Trust.scan(Trust.id == self.actorId, consistent_read=True)
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
                    "verificationToken": t.verificationToken,
                })
            return self.trusts
        else:
            return []

    def delete(self):
        """ Deletes all the properties in the database """
        self.handle = Trust.scan(Trust.id == self.actorId, consistent_read=True)
        if not self.handle:
            return False
        for p in self.handle:
            p.delete()
        self.handle = None
        return True

    def __init__(self):
        self.handle = None
        self.actorId = None
        self.trusts = []
        if not Trust.exists():
            Trust.create_table(wait=True)

