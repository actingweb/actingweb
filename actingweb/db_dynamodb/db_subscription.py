from google.appengine.ext import ndb
import logging

"""
    db_subscription handles all db operations for a subscription

    db_subscription_list handles list of subscriptions
    Google datastore for google is used as a backend.
"""

__all__ = [
    'db_subscription',
    'db_subscription_list',
]


class Subscription(ndb.Model):
    id = ndb.StringProperty(required=True)
    peerid = ndb.StringProperty(required=True)
    subid = ndb.StringProperty(required=True)
    granularity = ndb.StringProperty()
    target = ndb.StringProperty()
    subtarget = ndb.StringProperty()
    resource = ndb.StringProperty()
    seqnr = ndb.IntegerProperty(default=1)
    callback = ndb.BooleanProperty()


class db_subscription():
    """
        db_subscription does all the db operations for subscription objects

        The  actorId must always be set.
    """

    def get(self,  actorId=None, peerid=None, subid=None):
        """ Retrieves the subscription from the database """
        if not actorId:
            return None
        if not peerid or not subid:
            logging.debug("Attempt to get subscription without peerid or subid")
            return None
        if not self.handle:
            self.handle = Subscription.query(Subscription.id == actorId,
                                             Subscription.peerid == peerid,
                                             Subscription.subid == subid).get(use_cache=False)
        if self.handle:
            t = self.handle
            return {
                "id": t.id,
                "peerid": t.peerid,
                "subscriptionid": t.subid,
                "granularity": t.granularity,
                "target": t.target,
                "subtarget": t.subtarget,
                "resource": t.resource,
                "sequence": t.seqnr,
                "callback": t.callback,
            }
        else:
            return None

    def modify(self, actorId=None,
               peerid=None,
               subid=None,
               granularity=None,
               target=None,
               subtarget=None,
               resource=None,
               seqnr=None,
               callback=None):
        """ Modify a subscription

            If bools are none, they will not be changed.
        """
        if not self.handle:
            logging.debug("Attempted modification of db_subscription without db handle")
            return False
        if peerid and len(peerid) > 0:
            self.handle.peerid = peerid
        if subid and len(subid) > 0:
            self.handle.subid = subid
        if granularity and len(granularity) > 0:
            self.handle.granularity = granularity
        if callback is not None:
            self.handle.callback = callback
        if target and len(target) > 0:
            self.handle.target = target
        if subtarget and len(subtarget) > 0:
            self.handle.subtarget = subtarget
        if resource and len(resource) > 0:
            self.handle.resource = resource
        if seqnr:
            self.handle.seqnr = seqnr
        self.handle.put(use_cache=False)
        return True

    def create(self, actorId=None,
               peerid=None,
               subid=None,
               granularity=None,
               target=None,
               subtarget=None,
               resource=None,
               seqnr=None,
               callback=None):
        """ Create a new subscription """
        if not actorId or not peerid or not subid:
            return False
        if not granularity:
            granularity = ''
        if not target:
            target = ''
        if not subtarget:
            subtarget = ''
        if not resource:
            resource = ''
        if not seqnr:
            seqnr = 1
        if not callback:
            callback = False
        self.handle = Subscription(id=actorId,
                                   peerid=peerid,
                                   subid=subid,
                                   granularity=granularity,
                                   target=target,
                                   subtarget=subtarget,
                                   resource=resource,
                                   seqnr=seqnr,
                                   callback=callback)
        self.handle.put(use_cache=False)
        return True

    def delete(self):
        """ Deletes the subscription in the database """
        if not self.handle:
            logging.debug("Attempted delete of db_subscription with no handle set.")
            return False
        self.handle.key.delete(use_cache=False)
        self.handle = None
        return True

    def __init__(self):
        self.handle = None


class db_subscription_list():
    """
        db_trust_list does all the db operations for list of trust objects

        The  actorId must always be set.
    """

    def fetch(self, actorId):
        """ Retrieves the subscriptions of an actorId from the database as an array"""
        if not actorId:
            return None
        self.handle = Subscription.query(Subscription.id == actorId).fetch(use_cache=False)
        self.subscriptions = []
        if self.handle:
            for t in self.handle:
                self.subscriptions.append(
                {
                    "id": t.id,
                    "peerid": t.peerid,
                    "subscriptionid": t.subid,
                    "granularity": t.granularity,
                    "target": t.target,
                    "subtarget": t.subtarget,
                    "resource": t.resource,
                    "sequence": t.seqnr,
                    "callback": t.callback,
                })
            return self.subscriptions
        else:
            return []

    def delete(self):
        """ Deletes all the subscriptions for an actor in the database """
        if not self.handle:
            return False
        for p in self.handle:
            p.key.delete(use_cache=False)
        self.handle = None
        return True

    def __init__(self):
        self.handle = None
