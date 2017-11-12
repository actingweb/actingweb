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
        read_capacity_units = 2
        write_capacity_units = 1
        region = os.getenv('AWS_DEFAULT_REGION', 'us-west-1')
        host = os.getenv('AWS_DB_HOST', None)

    id = UnicodeAttribute(hash_key=True)
    peer_sub_id = UnicodeAttribute(range_key=True)
    peerid = UnicodeAttribute()
    subid = UnicodeAttribute()
    granularity = UnicodeAttribute(null=True)
    target = UnicodeAttribute(null=True)
    subtarget = UnicodeAttribute(null=True)
    resource = UnicodeAttribute(null=True)
    seqnr = NumberAttribute(default=1)
    callback = BooleanAttribute()


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
        try:
            # We only expect one
            for t in Subscription.query(actorId,
                                        Subscription.peer_sub_id == peerid + ":" + subid,
                                        consistent_read=True):
                self.handle = t
                return {
                    "id": t.id,
                    "peerid": t.peerid,
                    "subscriptionid": t.subid,
                    "granularity": (t.granularity or ''),
                    "target": (t.target or ''),
                    "subtarget": (t.subtarget or ''),
                    "resource": (t.resource or ''),
                    "sequence": t.seqnr,
                    "callback": t.callback,
                }
        except Subscription.DoesNotExist:
            pass
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
        self.handle.save()
        return True

    def create(self, actorId=None,
               peerid=None,
               subid=None,
               granularity=None,
               target=None,
               subtarget=None,
               resource=None,
               seqnr=1,
               callback=False):
        """ Create a new subscription """
        if not actorId or not peerid or not subid:
            return False
        if self.get(actorId=actorId, peerid=peerid, subid=subid):
            return False
        self.handle = Subscription(id=actorId,
                                   peer_sub_id=peerid + ":" + subid,
                                   peerid=peerid,
                                   subid=subid,
                                   seqnr=seqnr,
                                   callback=callback)
        if granularity and len(granularity) > 0:
            self.handle.granularity = granularity
        if target and len(target) > 0:
            self.handle.target = target
        if subtarget and len(subtarget) > 0:
            self.handle.subtarget = subtarget
        if resource and len(resource) > 0:
            self.handle.resource = resource
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
            Subscription.create_table(wait=True)



class db_subscription_list():
    """
        db_trust_list does all the db operations for list of trust objects

        The  actorId must always be set.
    """

    def fetch(self, actorId):
        """ Retrieves the subscriptions of an actorId from the database as an array"""
        if not actorId:
            return None
        self.actorId = actorId
        self.handle = Subscription.query(self.actorId, consistent_read=True)
        self.subscriptions = []
        if self.handle:
            for t in self.handle:
                self.subscriptions.append(
                {
                    "id": t.id,
                    "peerid": t.peerid,
                    "subscriptionid": t.subid,
                    "granularity": (t.granularity or ''),
                    "target": (t.target or ''),
                    "subtarget": (t.subtarget or ''),
                    "resource": (t.resource or ''),
                    "sequence": t.seqnr,
                    "callback": t.callback,
                })
            return self.subscriptions
        else:
            return []

    def delete(self):
        """ Deletes all the subscriptions for an actor in the database """
        if not self.actorId:
            return False
        self.handle = Subscription.query(self.actorId, consistent_read=True)
        if not self.handle:
            return False
        for p in self.handle:
            p.delete()
        self.handle = None
        return True

    def __init__(self):
        self.handle = None
        self.actorId = None
        self.subscriptions = []
        if not Subscription.exists():
            Subscription.create_table(wait=True)
