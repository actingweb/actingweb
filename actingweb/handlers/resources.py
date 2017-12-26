import json

from actingweb import auth
from actingweb.handlers import base_handler


class ResourcesHandler(base_handler.BaseHandler):

    def get(self, actor_id, name):
        (myself, check) = auth.init_actingweb(appreq=self,
                                              actor_id=actor_id,
                                              path='resources',
                                              subpath=name,
                                              config=self.config)
        if not myself or check.response["code"] != 200:
            return
        if not check.check_authorisation(path='resources', subpath=name, method='GET'):
            self.response.set_status(403)
            return
        pair = self.on_aw.get_resources(name=name)
        if pair and any(pair): 
            out = json.dumps(pair)
            self.response.write(out.encode('utf-8'))
            self.response.headers["Content-Type"] = "application/json"
            self.response.set_status(200)
        else:
            self.response.set_status(404)

    def delete(self, actor_id, name):
        (myself, check) = auth.init_actingweb(appreq=self,
                                              actor_id=actor_id,
                                              path='resources',
                                              subpath=name,
                                              config=self.config)
        if not myself or check.response["code"] != 200:
            return
        if not check.check_authorisation(path='resources', subpath=name, method='DELETE'):
            self.response.set_status(403)
            return
        pair = self.on_aw.delete_resources(name=name)
        if pair:
            if 100 <= pair <= 999:
                return
            if any(pair): 
                out = json.dumps(pair)
                self.response.write(out.encode('utf-8'))
                self.response.headers["Content-Type"] = "application/json"
                self.response.set_status(200)
        else:
            self.response.set_status(404)

    def put(self, actor_id, name):
        (myself, check) = auth.init_actingweb(appreq=self,
                                              actor_id=actor_id,
                                              path='resources',
                                              subpath=name,
                                              config=self.config)
        if not myself or check.response["code"] != 200:
            return
        if not check.check_authorisation(path='resources', subpath=name, method='PUT'):
            self.response.set_status(403)
            return
        try:
            params = json.loads(self.request.body.decode('utf-8', 'ignore'))
        except (TypeError, ValueError, KeyError):
            self.response.set_status(405, "Error in json body")
            return
        pair = self.on_aw.put_resources(name=name, params=params)
        if pair:
            if 100 <= pair <= 999:
                return
            if any(pair):
                out = json.dumps(pair)
                self.response.write(out.encode('utf-8'))
                self.response.headers["Content-Type"] = "application/json"
                self.response.set_status(200)
        else:
            self.response.set_status(404)

    def post(self, actor_id, name):
        (myself, check) = auth.init_actingweb(appreq=self,
                                              actor_id=actor_id,
                                              path='resources',
                                              subpath=name,
                                              config=self.config)
        if not myself or check.response["code"] != 200:
            return
        if not check.check_authorisation(path='resources', subpath=name, method='POST'):
            self.response.set_status(403)
            return
        try:
            params = json.loads(self.request.body.decode('utf-8', 'ignore'))
        except (TypeError, ValueError, KeyError):
            self.response.set_status(405, "Error in json body")
            return
        pair = self.on_aw.post_resources(name=name, params=params)
        if pair:
            if 100 <= pair <= 999:
                return
            if any(pair):
                out = json.dumps(pair)
                self.response.write(out.encode('utf-8'))
                self.response.headers["Content-Type"] = "application/json"
                self.response.set_status(201, 'Created')
        else:
            self.response.set_status(404)
