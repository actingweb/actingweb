import json

from actingweb import auth
from actingweb.handlers import base_handler


class ResourcesHandler(base_handler.BaseHandler):

    def get(self, actor_id, name):
        (myself, check) = auth.init_actingweb(
            appreq=self,
            actor_id=actor_id,
            path="resources",
            subpath=name,
            config=self.config,
        )
        if not myself or not check or check.response["code"] != 200:
            return
        if not check.check_authorisation(path="resources", subpath=name, method="GET"):
            if self.response:
                self.response.set_status(403)
            return
        pair = self.on_aw.get_resources(name=name)
        if pair and any(pair):
            out = json.dumps(pair)
            if self.response:
                self.response.write(out)
                self.response.headers["Content-Type"] = "application/json"
                self.response.set_status(200)
        else:
            if self.response:
                self.response.set_status(404)

    def delete(self, actor_id, name):
        (myself, check) = auth.init_actingweb(
            appreq=self,
            actor_id=actor_id,
            path="resources",
            subpath=name,
            config=self.config,
        )
        if not myself or not check or check.response["code"] != 200:
            return
        if not check.check_authorisation(
            path="resources", subpath=name, method="DELETE"
        ):
            if self.response:
                self.response.set_status(403)
            return
        pair = self.on_aw.delete_resources(name=name)
        if pair:
            if isinstance(pair, int) and 100 <= pair <= 999:
                return
            if any(pair):
                out = json.dumps(pair)
                if self.response:
                    self.response.write(out)
                    self.response.headers["Content-Type"] = "application/json"
                    self.response.set_status(200)
        else:
            if self.response:
                self.response.set_status(404)

    def put(self, actor_id, name):
        (myself, check) = auth.init_actingweb(
            appreq=self,
            actor_id=actor_id,
            path="resources",
            subpath=name,
            config=self.config,
        )
        if not myself or not check or check.response["code"] != 200:
            return
        if not check.check_authorisation(path="resources", subpath=name, method="PUT"):
            if self.response:
                self.response.set_status(403)
            return
        try:
            body = self.request.body
            if isinstance(body, bytes):
                body = body.decode("utf-8", "ignore")
            elif body is None:
                body = "{}"
            params = json.loads(body)
        except (TypeError, ValueError, KeyError):
            if self.response:
                self.response.set_status(400, "Error in json body")
            return
        pair = self.on_aw.put_resources(name=name, params=params)
        if pair:
            if isinstance(pair, int) and 100 <= pair <= 999:
                return
            if any(pair):
                out = json.dumps(pair)
                if self.response:
                    self.response.write(out)
                    self.response.headers["Content-Type"] = "application/json"
                    self.response.set_status(200)
        else:
            if self.response:
                self.response.set_status(404)

    def post(self, actor_id, name):
        (myself, check) = auth.init_actingweb(
            appreq=self,
            actor_id=actor_id,
            path="resources",
            subpath=name,
            config=self.config,
        )
        if not myself or not check or check.response["code"] != 200:
            return
        if not check.check_authorisation(path="resources", subpath=name, method="POST"):
            if self.response:
                self.response.set_status(403)
            return
        try:
            body = self.request.body
            if isinstance(body, bytes):
                body = body.decode("utf-8", "ignore")
            elif body is None:
                body = "{}"
            params = json.loads(body)
        except (TypeError, ValueError, KeyError):
            if self.response:
                self.response.set_status(400, "Error in json body")
            return
        pair = self.on_aw.post_resources(name=name, params=params)
        if pair:
            if isinstance(pair, int) and 100 <= pair <= 999:
                return
            if any(pair):
                out = json.dumps(pair)
                if self.response:
                    self.response.write(out)
                    self.response.headers["Content-Type"] = "application/json"
                    self.response.set_status(201, "Created")
        else:
            if self.response:
                self.response.set_status(404)
