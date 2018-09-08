from builtins import str
import json
import logging

from actingweb import auth
from actingweb.handlers import base_handler


class CallbacksHandler(base_handler.BaseHandler):

    def get(self, actor_id, name):
        """Handles GETs to callbacks"""
        if self.request.get('_method') == 'PUT':
            self.put(actor_id, name)
        if self.request.get('_method') == 'POST':
            self.post(actor_id, name)
        (myself, check) = auth.init_actingweb(appreq=self,
                                              actor_id=actor_id,
                                              path='callbacks',
                                              add_response=False,
                                              config=self.config
                                              )
        if not myself or (check.response["code"] != 200 and check.response["code"] != 401):
            auth.add_auth_response(appreq=self, auth_obj=check)
            return
        if not check.check_authorisation(path='callbacks', subpath=name, method='GET'):
            self.response.set_status(403, 'Forbidden')
            return
        if not self.on_aw.get_callbacks(name=name):
            self.response.set_status(403, 'Forbidden')

    def put(self, actor_id, name):
        """PUT requests are handled as POST for callbacks"""
        self.post(actor_id, name)

    def delete(self, actor_id, name):
        """Handles deletion of callbacks, like subscriptions"""
        (myself, check) = auth.init_actingweb(appreq=self,
                                              actor_id=actor_id,
                                              path='callbacks',
                                              config=self.config)
        if not myself or check.response["code"] != 200:
            return
        path = name.split('/')
        if path[0] == 'subscriptions':
            peerid = path[1]
            subid = path[2]
            if not check.check_authorisation(path='callbacks', subpath='subscriptions', method='DELETE', peerid=peerid):
                self.response.set_status(403, 'Forbidden')
                return
            sub = myself.get_subscription_obj(peerid=peerid, subid=subid, callback=True)
            if sub:
                sub.delete()
                self.response.set_status(204, 'Deleted')
                return
            self.response.set_status(404, 'Not found')
            return
        if not check.check_authorisation(path='callbacks', subpath=name, method='DELETE'):
            self.response.set_status(403, 'Forbidden')
            return
        if not self.on_aw.delete_callbacks(name=name):
            self.response.set_status(403, 'Forbidden')

    def post(self, actor_id, name):
        """Handles POST callbacks"""
        (myself, check) = auth.init_actingweb(appreq=self,
                                              actor_id=actor_id,
                                              path='callbacks',
                                              add_response=False,
                                              config=self.config)
        # Allow unauthenticated requests to /callbacks/subscriptions, so
        # do the auth check further below
        path = name.split('/')
        if path[0] == 'subscriptions':
            peerid = path[1]
            subid = path[2]
            sub = myself.get_subscription(peerid=peerid, subid=subid, callback=True)
            if sub and len(sub) > 0:
                logging.debug("Found subscription (" + str(sub) + ")")
                if not check.check_authorisation(
                        path='callbacks',
                        subpath='subscriptions',
                        method='POST',
                        peerid=peerid):
                    self.response.set_status(403, 'Forbidden')
                    return
                try:
                    params = json.loads(self.request.body.decode('utf-8', 'ignore'))
                except (TypeError, ValueError, KeyError):
                    self.response.set_status(405, "Error in json body")
                    return
                if self.on_aw.post_subscriptions(sub=sub, peerid=peerid, data=params):
                    self.response.set_status(204, 'Found')
                else:
                    self.response.set_status(405, 'Processing error')
                return
            self.response.set_status(404, 'Not found')
            return
        if not myself or (check.response["code"] != 200 and check.response["code"] != 401):
            auth.add_auth_response(appreq=self, auth_obj=check)
            return
        if not check.check_authorisation(path='callbacks', subpath=name, method='POST'):
            self.response.set_status(403, 'Forbidden')
            return
        if not self.on_aw.post_callbacks(name=name):
            self.response.set_status(403, 'Forbidden')
