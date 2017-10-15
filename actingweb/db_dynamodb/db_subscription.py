import logging
import os
from pynamodb.models import Model
from pynamodb.attributes import UnicodeAttribute, NumberAttribute, BooleanAttribute

"""
    db_subscription handles all db operations for a subscription

    db_subscription_list handles list of subscriptions
    AWS Dynamodb is used as a backend.
"""

__all__ = [
    'db_subscription',
    'db_subscription_list',
]


class Subscription(Model):
    class Meta:
        table_name = "subscriptions"
        host = os.getenv('AWS_DB_HOST', None)

    id = UnicodeAttribute(hash_key=True)
    peerid = UnicodeAttribute(range_key=True)
    subid = UnicodeAttribute()
    granularity = UnicodeAttribute()
    target = UnicodeAttribute()
    subtarget = UnicodeAttribute()
    resource = UnicodeAttribute()
    seqnr = NumberAttribute(default=1)
    callback = BooleanAttribute


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
            self.handle = Subscription.get(id=actorId,
                                           peerid=peerid,
                                           subid=subid)
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
            self.handle.peerid.set(peerid)
        if subid and len(subid) > 0:
            self.handle.subid.set(subid)
        if granularity and len(granularity) > 0:
            self.handle.granularity.set(granularity)
        if callback is not None:
            self.handle.callback.set(callback)
        if target and len(target) > 0:
            self.handle.target.set(target)
        if subtarget and len(subtarget) > 0:
            self.handle.subtarget.set(subtarget)
        if resource and len(resource) > 0:
            self.handle.resource.set(resource)
        if seqnr:
            self.handle.seqnr.set(seqnr)
        self.handle.save()
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
        self.handle.save()
        return True

    def delete(self):
        """ Deletes the subscription in the database """
        if not self.handle:
            logging.debug("Attempted delete of db_subscription with no handle set.")
            return False
        self.handle.delete()
        self.handle = None
        return True

    def __init__(self):
        self.handle = None
        if not Subscription.exists():
            Subscription.create_table(read_capacity_units=1, write_capacity_units=1, wait=True)



class db_subscription_list():
    """
        db_trust_list does all the db operations for list of trust objects

        The  actorId must always be set.
    """

    def fetch(self, actorId):
        """ Retrieves the subscriptions of an actorId from the database as an array"""
        if not actorId:
            return None
        self.handle = Subscription.query(actorId, None)
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
            p.delete()
        self.handle = None
        return True

    def __init__(self):
        self.handle = None
        self.subscriptions = []
