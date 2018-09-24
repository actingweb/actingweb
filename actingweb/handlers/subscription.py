from builtins import str
import json
import logging
from actingweb import auth
from actingweb.handlers import base_handler


class SubscriptionRootHandler(base_handler.BaseHandler):
    """Handles requests to /subscription"""

    def get(self, actor_id):
        if self.request.get('_method') == 'POST':
            self.post(actor_id)
            return
        (myself, check) = auth.init_actingweb(appreq=self,
                                              actor_id=actor_id,
                                              path='subscriptions',
                                              config=self.config)
        if not myself or check.response["code"] != 200:
            return
        if not check.check_authorisation(path='subscriptions', method='GET'):
            self.response.set_status(403)
            return
        peerid = self.request.get('peerid')
        target = self.request.get('target')
        subtarget = self.request.get('subtarget')
        resource = self.request.get('resource')

        subscriptions = myself.get_subscriptions(peerid=peerid, target=target, subtarget=subtarget, resource=resource)
        if not subscriptions:
            self.response.set_status(404, 'Not found')
            return
        data = {
                'id': myself.id,
                'data': subscriptions,
                }
        out = json.dumps(data)
        self.response.write(out)
        self.response.headers["Content-Type"] = "application/json"
        self.response.set_status(200, 'Ok')

    def post(self, actor_id):
        (myself, check) = auth.init_actingweb(appreq=self,
                                              actor_id=actor_id,
                                              path='subscriptions',
                                              config=self.config)
        if not myself or check.response["code"] != 200:
            return
        if not check.check_authorisation(path='subscriptions', method='POST'):
            self.response.set_status(403)
            return
        try:
            params = json.loads(self.request.body.decode('utf-8', 'ignore'))
            if 'peerid' in params:
                peerid = params['peerid']
            else:
                peerid = None
            if 'target' in params:
                target = params['target']
            else:
                target = None
            if 'subtarget' in params:
                subtarget = params['subtarget']
            else:
                subtarget = None
            if 'resource' in params:
                resource = params['resource']
            else:
                resource = None
            if 'granularity' in params:
                granularity = params['granularity']
            else:
                granularity = 'none'
        except ValueError:
            peerid = self.request.get('peerid')
            target = self.request.get('target')
            subtarget = self.request.get('subtarget')
            resource = self.request.get('resource')
            granularity = self.request.get('granularity')
        if not peerid or len(peerid) == 0:
            self.response.set_status(400, 'Missing peer URL')
            return
        if not target or len(target) == 0:
            self.response.set_status(400, 'Missing target')
            return
        remote_loc = myself.create_remote_subscription(
            peerid=peerid, target=target, subtarget=subtarget, resource=resource, granularity=granularity)
        if not remote_loc:
            self.response.set_status(408, 'Unable to create remote subscription with peer')
            return
        self.response.headers["Location"] = remote_loc
        self.response.set_status(204, 'Created')


# Handling requests to /subscription/*, e.g. /subscription/<peerid>
class SubscriptionRelationshipHandler(base_handler.BaseHandler):

    def get(self, actor_id, peerid):
        if self.request.get('_method') == 'POST':
            self.post(actor_id, peerid)
            return
        (myself, check) = auth.init_actingweb(appreq=self,
                                              actor_id=actor_id,
                                              path='subscriptions',
                                              config=self.config)
        if not myself or check.response["code"] != 200:
            return
        if not check.check_authorisation(path='subscriptions', method='GET', peerid=peerid):
            self.response.set_status(403)
            return
        target = self.request.get('target')
        subtarget = self.request.get('subtarget')
        resource = self.request.get('resource')

        subscriptions = myself.get_subscriptions(peerid=peerid, target=target, subtarget=subtarget, resource=resource)
        if not subscriptions:
            self.response.set_status(404, 'Not found')
            return
        data = {
                'id': myself.id,
                'peerid': peerid,
                'data': subscriptions,
                }
        out = json.dumps(data)
        self.response.write(out)
        self.response.headers["Content-Type"] = "application/json"
        self.response.set_status(200, 'Ok')

    def post(self, actor_id, peerid):
        (myself, check) = auth.init_actingweb(appreq=self,
                                              actor_id=actor_id,
                                              path='subscriptions',
                                              config=self.config)
        if not myself or check.response["code"] != 200:
            return
        if not check.check_authorisation(path='subscriptions', subpath='<id>', method='POST', peerid=peerid):
            self.response.set_status(403)
            return
        try:
            params = json.loads(self.request.body.decode('utf-8', 'ignore'))
            if 'target' in params:
                target = params['target']
            else:
                self.response.set_status(400, 'No target in request')
                return
            if 'subtarget' in params:
                subtarget = params['subtarget']
            else:
                subtarget = None
            if 'resource' in params:
                resource = params['resource']
            else:
                resource = None
            if 'granularity' in params:
                granularity = params['granularity']
            else:
                granularity = 'none'
        except ValueError:
            self.response.set_status(400, 'No json body')
            return
        if peerid != check.acl["peerid"]:
            logging.warning("Peer " + peerid +
                         " tried to create a subscription for peer " + check.acl["peerid"])
            self.response.set_status(403, 'Forbidden. Wrong peer id in request')
            return
        # We need to validate that this peer has GET rights on what it wants to subscribe to
        if not check.check_authorisation(path=target, subpath=subtarget, method='GET', peerid=peerid):
            self.response.set_status(403)
            return
        new_sub = myself.create_subscription(
            peerid=check.acl["peerid"], target=target, subtarget=subtarget, resource=resource, granularity=granularity)
        if not new_sub:
            self.response.set_status(500, 'Unable to create new subscription')
            return
        self.response.headers["Location"] = str(self.config.root + 
                                                myself.id + '/subscriptions/' + new_sub["peerid"] +
                                                '/' + new_sub["subscriptionid"])
        pair = {
            'subscriptionid': new_sub["subscriptionid"],
            'target': new_sub["target"],
            'subtarget': new_sub["subtarget"],
            'resource': new_sub["resource"],
            'granularity': new_sub["granularity"],
            'sequence': new_sub["sequence"],
        }
        out = json.dumps(pair)
        self.response.write(out)
        self.response.headers["Content-Type"] = "application/json"
        self.response.set_status(201, 'Created')

    
class SubscriptionHandler(base_handler.BaseHandler):
    """ Handling requests to specific subscriptions, e.g. /subscriptions/<peerid>/12f2ae53bd"""

    def get(self, actor_id, peerid, subid):
        if self.request.get('_method') == 'PUT':
            self.put(actor_id, peerid, subid)
            return
        if self.request.get('_method') == 'DELETE':
            self.delete(actor_id, peerid, subid)
            return
        (myself, check) = auth.init_actingweb(appreq=self,
                                              actor_id=actor_id,
                                              path='subscriptions',
                                              subpath=peerid + '/' + subid,
                                              config=self.config)
        if not myself or check.response["code"] != 200:
            return
        if not check.check_authorisation(path='subscriptions', subpath='<id>/<id>', method='GET', peerid=peerid):
            self.response.set_status(403)
            return
        sub = myself.get_subscription_obj(peerid=peerid, subid=subid)
        sub_data = sub.get()
        if not sub_data or len(sub_data) == 0:
            self.response.set_status(404, "Subscription does not exist")
            return
        diffs = sub.get_diffs()
        pairs = []
        for diff in diffs:
            try:
                d = json.loads(diff["diff"])
            except (TypeError, ValueError, KeyError):
                d = diff["diff"]
            pairs.append({
                'sequence': diff["sequence"],
                'timestamp': diff["timestamp"].strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                'data': d,
            })
        if len(pairs) == 0:
            self.response.set_status(404, 'No diffs available')
            return
        data = {
                'id': myself.id,
                'peerid': peerid,
                'subscriptionid': subid,
                'target': sub_data["target"],
                'subtarget': sub_data["subtarget"],
                'resource': sub_data["resource"],
                'data': pairs,
                }
        out = json.dumps(data)
        self.response.write(out)
        self.response.headers["Content-Type"] = "application/json"
        self.response.set_status(200, 'Ok')

    def put(self, actor_id, peerid, subid):
        (myself, check) = auth.init_actingweb(appreq=self,
                                              actor_id=actor_id,
                                              path='subscriptions',
                                              subpath=peerid + '/' + subid,
                                              config=self.config)
        if not myself or check.response["code"] != 200:
            return
        if not check.check_authorisation(path='subscriptions', subpath='<id>/<id>', method='GET', peerid=peerid):
            self.response.set_status(403)
            return
        try:
            params = json.loads(self.request.body.decode('utf-8', 'ignore'))
            if 'sequence' in params:
                seq = params['sequence']
            else:
                self.response.set_status(405, "Error in json body and no GET parameters")
                return
        except (TypeError, ValueError, KeyError):
            seq = self.request.get('sequence')
            if len(seq) == 0:
                self.response.set_status(405, "Error in json body and no GET parameters")
                return
        try:
            if not isinstance(seq, int):
                seqnr = int(seq)
            else:
                seqnr = seq
        except ValueError:
            self.response.set_status(405, "Sequence does not contain a number")
            return
        sub = myself.get_subscription_obj(peerid=peerid, subid=subid)
        if not sub:
            self.response.set_status(404, "Subscription does not exist")
            return
        sub.clear_diffs(seqnr=seqnr)
        self.response.set_status(204)
        return

    def delete(self, actor_id, peerid, subid):
        (myself, check) = auth.init_actingweb(appreq=self,
                                              actor_id=actor_id,
                                              path='subscriptions',
                                              subpath=peerid + '/' + subid,
                                              config=self.config)
        if not myself or check.response["code"] != 200:
            return
        if not check.check_authorisation(path='subscriptions', subpath='<id>/<id>', method='GET', peerid=peerid):
            self.response.set_status(403)
            return
        # Do not delete remote subscription if this is from our peer
        if len(check.acl['peerid']) == 0:
            myself.delete_remote_subscription(peerid=peerid, subid=subid)
        if not myself.delete_subscription(peerid=peerid, subid=subid):
            self.response.set_status(404)
            return
        self.response.set_status(204)
        return
        

class SubscriptionDiffHandler(base_handler.BaseHandler):
    """ Handling requests to specific diffs for one subscription and clears it, e.g. 
    /subscriptions/<peerid>/<subid>/112"""

    def get(self, actor_id, peerid, subid, seqnr):
        (myself, check) = auth.init_actingweb(appreq=self,
                                              actor_id=actor_id,
                                              path='subscriptions',
                                              subpath=peerid + '/' + subid + '/' + str(seqnr),
                                              config=self.config)
        if not myself or check.response["code"] != 200:
            return
        if not check.check_authorisation(path='subscriptions', subpath='<id>/<id>', method='GET', peerid=peerid):
            self.response.set_status(403)
            return
        sub = myself.get_subscription_obj(peerid=peerid, subid=subid)
        sub_data = sub.get()
        if not sub:
            self.response.set_status(404, "Subscription does not exist")
            return
        if not isinstance(seqnr, int):
            seqnr = int(seqnr)
        diff = sub.get_diff(seqnr=seqnr)
        if not diff:
            self.response.set_status(404, 'No diffs available')
            return
        try:
            d = json.loads(diff["data"])
        except (TypeError, ValueError, KeyError):
            d = diff["data"]
        pairs = {
            'id': myself.id,
            'peerid': peerid,
            'subscriptionid': subid,
            'timestamp': diff["timestamp"].strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
            'target': sub_data["target"],
            'subtarget': sub_data["subtarget"],
            'resource': sub_data["resource"],
            'sequence': seqnr,
            'data': d,
        }
        sub.clear_diff(seqnr)
        out = json.dumps(pairs)
        self.response.write(out)
        self.response.headers["Content-Type"] = "application/json"
        self.response.set_status(200, 'Ok')
