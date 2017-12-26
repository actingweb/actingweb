import json

from actingweb import auth
from actingweb.handlers import base_handler


class RootHandler(base_handler.BaseHandler):

    def get(self, actor_id):
        if self.request.get('_method') == 'DELETE':
            self.delete(actor_id)
            return
        (myself, check) = auth.init_actingweb(appreq=self, actor_id=actor_id, path='', subpath='',
                                              config=self.config)
        if not myself or check.response["code"] != 200:
            return
        if not check.check_authorisation(path='/', method='GET'):
            self.response.set_status(403)
            return
        pair = {
            'id': myself.id,
            'creator': myself.creator,
            'passphrase': myself.passphrase,
        }
        trustee_root = myself.get_property('trustee_root').value
        if trustee_root and len(trustee_root) > 0:
            pair['trustee_root'] = trustee_root
        out = json.dumps(pair)
        self.response.write(out.encode('utf-8'))
        self.response.headers["Content-Type"] = "application/json"
        self.response.set_status(200)

    def delete(self, actor_id):
        (myself, check) = auth.init_actingweb(appreq=self,
                                              actor_id=actor_id, path='', subpath='', config=self.config)
        if not myself or check.response["code"] != 200:
            return
        if not check.check_authorisation(path='/', method='DELETE'):
            self.response.set_status(403)
            return
        self.on_aw.delete_actor()
        myself.delete()
        self.response.set_status(204)
        return
