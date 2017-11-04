import json
import logging
from actingweb import auth, aw_web_request
from actingweb.handlers import base_handler


class subscription_root_handler(base_handler.base_handler):
    """Handles requests to /subscription"""

    def get(self, id):
        if self.request.get('_method') == 'POST':
            self.post(id)
            return
        (myself, check) = auth.init_actingweb(appreq=self,
                                              id=id,
                                              path='subscriptions',
                                              config=self.config)
        if not myself or check.response["code"] != 200:
            return
        if not check.checkAuthorisation(path='subscriptions', method='GET'):
            self.response.set_status(403)
            return
        peerid = self.request.get('peerid')
        target = self.request.get('target')
        subtarget = self.request.get('subtarget')
        resource = self.request.get('resource')

        subscriptions = myself.getSubscriptions(peerid=peerid, target=target, subtarget=subtarget, resource=resource)
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

    def post(self, id):
        (myself, check) = auth.init_actingweb(appreq=self,
                                              id=id,
                                              path='subscriptions',
                                              config=self.config)
        if not myself or check.response["code"] != 200:
            return
        if not check.checkAuthorisation(path='subscriptions', method='POST'):
            self.response.set_status(403)
            return
        try:
            params = json.loads(self.request.body.decode('utf-8', 'ignore'))
            if 'peerid' in params:
                peerid = params['peerid']
            if 'target' in params:
                target = params['target']
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
        remoteLoc = myself.createRemoteSubscription(
            peerid=peerid, target=target, subtarget=subtarget, resource=resource, granularity=granularity)
        if not remoteLoc:
            self.response.set_status(408, 'Unable to create remote subscription with peer')
            return
        self.response.headers["Location"] = remoteLoc
        self.response.set_status(204, 'Created')


# Handling requests to /subscription/*, e.g. /subscription/<peerid>
class subscription_relationship_handler(base_handler.base_handler):

    def get(self, id, peerid):
        peerid = peerid.decode("utf-8")
        if self.request.get('_method') == 'POST':
            self.post(id, peerid)
            return
        (myself, check) = auth.init_actingweb(appreq=self,
                                              id=id,
                                              path='subscriptions',
                                              config=self.config)
        if not myself or check.response["code"] != 200:
            return
        if not check.checkAuthorisation(path='subscriptions', method='GET', peerid=peerid):
            self.response.set_status(403)
            return
        target = self.request.get('target')
        subtarget = self.request.get('subtarget')
        resource = self.request.get('resource')

        subscriptions = myself.getSubscriptions(peerid=peerid, target=target, subtarget=subtarget, resource=resource)
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

    def post(self, id, peerid):
        peerid = peerid.decode("utf-8")
        (myself, check) = auth.init_actingweb(appreq=self,
                                              id=id,
                                              path='subscriptions',
                                              config=self.config)
        if not myself or check.response["code"] != 200:
            return
        if not check.checkAuthorisation(path='subscriptions', subpath='<id>', method='POST', peerid=peerid):
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
            logging.warn("Peer " + peerid +
                         " tried to create a subscription for peer " + check.acl["peerid"])
            self.response.set_status(403, 'Forbidden. Wrong peer id in request')
            return
        # We need to validate that this peer has GET rights on what it wants to subscribe to
        if not check.checkAuthorisation(path=target, subpath=subtarget, method='GET', peerid=peerid):
            self.response.set_status(403)
            return
        new_sub = myself.createSubscription(
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

        

class subscription_handler(base_handler.base_handler):
    """ Handling requests to specific subscriptions, e.g. /subscriptions/<peerid>/12f2ae53bd"""

    def get(self, id, peerid, subid):
        peerid = peerid.decode("utf-8")
        subid = subid.decode("utf-8")
        if self.request.get('_method') == 'PUT':
            self.put(id, peerid, subid)
            return
        if self.request.get('_method') == 'DELETE':
            self.delete(id, peerid, subid)
            return
        (myself, check) = auth.init_actingweb(appreq=self,
                                              id=id,
                                              path='subscriptions',
                                              subpath=peerid + '/' + subid,
                                              config=self.config)
        if not myself or check.response["code"] != 200:
            return
        if not check.checkAuthorisation(path='subscriptions', subpath='<id>/<id>', method='GET', peerid=peerid):
            self.response.set_status(403)
            return
        sub = myself.getSubscriptionObj(peerid=peerid, subid=subid)
        subData = sub.get()
        if not subData or len(subData) == 0:
            self.response.set_status(404, "Subscription does not exist")
            return
        diffs = sub.getDiffs()
        pairs = []
        for diff in diffs:
            try:
                d = json.loads(diff["diff"])
            except:
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
                'target': subData["target"],
                'subtarget': subData["subtarget"],
                'resource': subData["resource"],
                'data': pairs,
                }
        out = json.dumps(data)
        self.response.write(out)
        self.response.headers["Content-Type"] = "application/json"
        self.response.set_status(200, 'Ok')

    def put(self, id, peerid, subid):
        peerid = peerid.decode("utf-8")
        subid = subid.decode("utf-8")
        (myself, check) = auth.init_actingweb(appreq=self,
                                              id=id,
                                              path='subscriptions',
                                              subpath=peerid + '/' + subid,
                                              config=self.config)
        if not myself or check.response["code"] != 200:
            return
        if not check.checkAuthorisation(path='subscriptions', subpath='<id>/<id>', method='GET', peerid=peerid):
            self.response.set_status(403)
            return
        try:
            params = json.loads(self.request.body.decode('utf-8', 'ignore'))
            if 'sequence' in params:
                seq = params['sequence']
            else:
                self.response.set_status(405, "Error in json body and no GET parameters")
                return
        except:
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
        sub = myself.getSubscriptionObj(peerid=peerid, subid=subid)
        if not sub:
            self.response.set_status(404, "Subscription does not exist")
            return
        sub.clearDiffs(seqnr=seqnr)
        self.response.set_status(204)
        return

    def delete(self, id, peerid, subid):
        peerid = peerid.decode("utf-8")
        subid = subid.decode("utf-8")
        (myself, check) = auth.init_actingweb(appreq=self,
                                              id=id,
                                              path='subscriptions',
                                              subpath=peerid + '/' + subid,
                                              config=self.config)
        if not myself or check.response["code"] != 200:
            return
        if not check.checkAuthorisation(path='subscriptions', subpath='<id>/<id>', method='GET', peerid=peerid):
            self.response.set_status(403)
            return
        # Do not delete remote subscription if this is from our peer
        if len(check.acl['peerid']) == 0:
            myself.deleteRemoteSubscription(peerid=peerid, subid=subid)
        if not myself.deleteSubscription(peerid=peerid, subid=subid):
            self.response.set_status(404)
            return
        self.response.set_status(204)
        return
        

class subscription_diff_handler(base_handler.base_handler):
    """ Handling requests to specific diffs for one subscription and clears it, e.g. /subscriptions/<peerid>/<subid>/112"""

    def get(self, id, peerid, subid, seqnr):
        peerid = peerid.decode("utf-8")
        subid = subid.decode("utf-8")
        seqnr = seqnr.decode("utf-8")
        (myself, check) = auth.init_actingweb(appreq=self,
                                              id=id,
                                              path='subscriptions',
                                              subpath=peerid + '/' + subid + '/' + seqnr,
                                              config=self.config)
        if not myself or check.response["code"] != 200:
            return
        if not check.checkAuthorisation(path='subscriptions', subpath='<id>/<id>', method='GET', peerid=peerid):
            self.response.set_status(403)
            return
        sub = myself.getSubscriptionObj(peerid=peerid, subid=subid)
        subData = sub.get()
        if not sub:
            self.response.set_status(404, "Subscription does not exist")
            return
        if not isinstance(seqnr, int):
            seqnr = int(seqnr)
        diff = sub.getDiff(seqnr=seqnr)
        if not diff:
            self.response.set_status(404, 'No diffs available')
            return
        try:
            d = json.loads(diff["data"])
        except:
            d = diff["data"]
        pairs = {
            'id': myself.id,
            'peerid': peerid,
            'subscriptionid': subid,
            'timestamp': diff["timestamp"].strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
            'target': subData["target"],
            'subtarget': subData["subtarget"],
            'resource': subData["resource"],
            'sequence': seqnr,
            'data': d,
        }
        sub.clearDiff(seqnr)
        out = json.dumps(pairs)
        self.response.write(out)
        self.response.headers["Content-Type"] = "application/json"
        self.response.set_status(200, 'Ok')


