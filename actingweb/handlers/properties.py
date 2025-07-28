import copy
import json
import logging

from actingweb import auth
from actingweb.handlers import base_handler


def merge_dict(d1, d2):
    """Modifies d1 in-place to contain values from d2.

    If any value in d1 is a dictionary (or dict-like), *and* the corresponding
    value in d2 is also a dictionary, then merge them in-place.
    Thanks to Edward Loper on stackoverflow.com
    """
    for k, v2 in list(d2.items()):
        v1 = d1.get(k)  # returns None if v1 has no value for this key
        if isinstance(v1, dict) and isinstance(v2, dict):
            merge_dict(v1, v2)
        else:
            d1[k] = v2


def delete_dict(d1, path):
    """Deletes path (an array of strings) in d1 dict.

    d1 is modified to no longer contain the attr/value pair
    or dict that is specified by path.
    """
    if not d1:
        # logging.debug('Path not found')
        return False
    # logging.debug('d1: ' + json.dumps(d1))
    # logging.debug('path: ' + str(path))
    if len(path) > 1 and path[1] and len(path[1]) > 0:
        return delete_dict(d1.get(path[0]), path[1:])
    if len(path) == 1 and path[0] and path[0] in d1:
        # logging.debug('Deleting d1[' + path[0] + ']')
        try:
            del d1[path[0]]
            return True
        except KeyError:
            return False
    return False


class PropertiesHandler(base_handler.BaseHandler):
    def get(self, actor_id, name):
        if self.request.get("_method") == "PUT":
            self.put(actor_id, name)
            return
        if self.request.get("_method") == "DELETE":
            self.delete(actor_id, name)
            return
        (myself, check) = auth.init_actingweb(
            appreq=self,
            actor_id=actor_id,
            path="properties",
            subpath=name,
            config=self.config,
        )
        if not myself or not check or check.response["code"] != 200:
            return
        if not name:
            path = []
        else:
            path = name.split("/")
            name = path[0]
        if not check.check_authorisation(path="properties", subpath=name, method="GET"):
            if self.response:
                self.response.set_status(403)
            return
        # if name is not set, this request URI was the properties root
        if not name:
            self.listall(myself)
            return
        lookup = myself.property[name] if myself and myself.property else None
        if not lookup:
            if self.response:
                self.response.set_status(404, "Property not found")
            return
        try:
            jsonblob = json.loads(lookup)
            try:
                out = jsonblob
                if len(path) > 1:
                    del path[0]
                    for p in path:
                        out = out[p]
                # Execute property hook if available
                if self.hooks:
                    actor_interface = self._get_actor_interface(myself)
                    if actor_interface:
                        # Use the original name for the hook, not the modified path
                        hook_path = name.split("/") if name else []
                        transformed = self.hooks.execute_property_hooks(
                            name or "*", "get", actor_interface, out, hook_path
                        )
                        if transformed is not None:
                            out = transformed
                        elif name:  # If hook returns None for specific property, it means 404
                            if self.response:
                                self.response.set_status(404)
                            return
                out = json.dumps(out)
            except (TypeError, ValueError, KeyError):
                if self.response:
                    self.response.set_status(404)
                return
            # Keep as string for response.write()
        except (TypeError, ValueError, KeyError):
            out = lookup
        if self.response:
            self.response.set_status(200, "Ok")
            self.response.headers["Content-Type"] = "application/json"
            self.response.write(out)

    def listall(self, myself):
        properties = myself.get_properties()
        if not properties or len(properties) == 0:
            self.response.set_status(404, "No properties")
            return
        pair = dict()
        for name, value in list(properties.items()):
            try:
                js = json.loads(value)
                pair[name] = js
            except ValueError:
                pair[name] = value
        # Execute property hooks for all properties if available
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                result = {}
                for key, value in pair.items():
                    transformed = self.hooks.execute_property_hooks(key, "get", actor_interface, value, [])
                    if transformed is not None:
                        result[key] = transformed
                pair = result
        if not pair:
            self.response.set_status(404)
            return
        out = json.dumps(pair)
        self.response.write(out)
        self.response.headers["Content-Type"] = "application/json"
        return

    def put(self, actor_id, name):
        (myself, check) = auth.init_actingweb(
            appreq=self,
            actor_id=actor_id,
            path="properties",
            subpath=name,
            config=self.config,
        )
        if not myself or (check and check.response["code"] != 200):
            return
        resource = None
        if not name:
            path = []
        else:
            path = name.split("/")
            name = path[0]
            if len(path) >= 2 and len(path[1]) > 0:
                resource = path[1]
        if not check or not check.check_authorisation(path="properties", subpath=name, method="PUT"):
            if self.response:
                self.response.set_status(403)
            return
        body = self.request.body
        if isinstance(body, bytes):
            body = body.decode("utf-8", "ignore")
        elif body is None:
            body = ""
        if len(path) == 1:
            old = myself.property[name] if myself and myself.property else None
            try:
                old = json.loads(old or "{}")
            except (TypeError, ValueError, KeyError):
                old = {}
            try:
                new_body = json.loads(body)
                is_json = True
            except (TypeError, ValueError, KeyError):
                new_body = body
                is_json = False
            # Execute property put hook if available
            new = new_body
            if self.hooks:
                actor_interface = self._get_actor_interface(myself)
                if actor_interface and path:
                    property_name = path[0] if path else "*"
                    transformed = self.hooks.execute_property_hooks(
                        property_name, "put", actor_interface, new_body, path
                    )
                    if transformed is not None:
                        new = transformed
                    else:
                        self.response.set_status(400, "Payload is not accepted")
                        return
            if is_json:
                if myself and myself.property:
                    myself.property[name] = json.dumps(new)
            else:
                if myself and myself.property:
                    myself.property[name] = new
            myself.register_diffs(target="properties", subtarget=name, blob=body)
            self.response.set_status(204)
            return
        # Keep text blob for later diff registration
        blob = body
        # Make store var to be merged with original struct
        try:
            body = json.loads(body)
        except (TypeError, ValueError, KeyError):
            pass
        store = {path[len(path) - 1]: body}
        # logging.debug('store with body:' + json.dumps(store))
        # Make store to be at same level as orig value
        i = len(path) - 2
        while i > 0:
            c = copy.copy(store)
            store = {path[i]: c}
            # logging.debug('store with i=' + str(i) + ' (' + json.dumps(store) + ')')
            i -= 1
        # logging.debug('Snippet to store(' + json.dumps(store) + ')')
        orig = myself.property[name] if myself and myself.property else None
        logging.debug("Original value(" + (orig or "") + ")")
        try:
            orig = json.loads(orig or "{}")
            merge_dict(orig, store)
            res = orig
        except (TypeError, ValueError, KeyError):
            res = store
        # Execute property put hook if available
        final_res = res
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface and path:
                property_name = path[0] if path else "*"
                transformed = self.hooks.execute_property_hooks(property_name, "put", actor_interface, res, path)
                if transformed is not None:
                    final_res = transformed
                else:
                    self.response.set_status(400, "Payload is not accepted")
                    return
        res = final_res
        res = json.dumps(res)
        logging.debug("Result to store( " + res + ") in /properties/" + name)
        if myself and myself.property:
            myself.property[name] = res
        myself.register_diffs(target="properties", subtarget=name, resource=resource, blob=blob)
        self.response.set_status(204)

    def post(self, actor_id, name):
        (myself, check) = auth.init_actingweb(
            appreq=self,
            actor_id=actor_id,
            path="properties",
            subpath=name,
            config=self.config,
        )
        if not myself or not check or check.response["code"] != 200:
            return
        if not check.check_authorisation(path="properties", subpath=name, method="POST"):
            if self.response:
                self.response.set_status(403)
            return
        if len(name) > 0:
            if self.response:
                self.response.set_status(400)
        pair = dict()
        # Handle the simple form
        if self.request.get("property") and self.request.get("value"):
            # Execute property post hook if available
            val = self.request.get("value")
            if self.hooks:
                actor_interface = self._get_actor_interface(myself)
                if actor_interface:
                    prop_name = self.request.get("property")
                    transformed = self.hooks.execute_property_hooks(
                        prop_name, "post", actor_interface, val, [prop_name]
                    )
                    if transformed is not None:
                        val = transformed
                    else:
                        if self.response:
                            self.response.set_status(403)
                        return
            pair[self.request.get("property")] = val
            if myself and myself.property:
                myself.property[self.request.get("property")] = self.request.get("value")
        elif len(self.request.arguments()) > 0:
            for name in self.request.arguments():
                # Execute property post hook if available
                val = self.request.get(name)
                if self.hooks:
                    actor_interface = self._get_actor_interface(myself)
                    if actor_interface:
                        transformed = self.hooks.execute_property_hooks(name, "post", actor_interface, val, [name])
                        if transformed is not None:
                            val = transformed
                        else:
                            continue
                pair[name] = val
                if myself and myself.property:
                    myself.property[name] = val
        else:
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
            for key in params:
                # Execute property post hook if available
                val = params[key]
                if self.hooks:
                    actor_interface = self._get_actor_interface(myself)
                    if actor_interface:
                        transformed = self.hooks.execute_property_hooks(key, "post", actor_interface, val, [key])
                        if transformed is not None:
                            val = transformed
                        else:
                            continue
                pair[key] = val
                if isinstance(val, dict):
                    text = json.dumps(val)
                else:
                    text = val
                if myself and myself.property:
                    myself.property[key] = text
        if not pair:
            if self.response:
                self.response.set_status(403, "No attributes accepted")
            return
        out = json.dumps(pair)
        myself.register_diffs(target="properties", blob=out)
        if self.response:
            self.response.write(out)
            self.response.headers["Content-Type"] = "application/json"
            self.response.set_status(201, "Created")

    def delete(self, actor_id, name):
        (myself, check) = auth.init_actingweb(
            appreq=self,
            actor_id=actor_id,
            path="properties",
            subpath=name,
            config=self.config,
        )
        if not myself or not check or check.response["code"] != 200:
            return
        resource = None
        if not name:
            path = []
        else:
            path = name.split("/")
            name = path[0]
            if len(path) >= 2 and len(path[1]) > 0:
                resource = path[1]
        if not check.check_authorisation(path="properties", subpath=name, method="DELETE"):
            self.response.set_status(403)
            return
        if not name:
            # Execute property delete hook if available
            if self.hooks:
                actor_interface = self._get_actor_interface(myself)
                if actor_interface:
                    result = self.hooks.execute_property_hooks(
                        "*", "delete", actor_interface, myself.get_properties(), path
                    )
                    if result is None:
                        self.response.set_status(403)
                        return
            myself.delete_properties()
            myself.register_diffs(target="properties", subtarget=None, blob="")
            self.response.set_status(204)
            return
        if len(path) == 1:
            old_prop = myself.property[name] if myself and myself.property else None
            # Execute property delete hook if available
            if self.hooks:
                actor_interface = self._get_actor_interface(myself)
                if actor_interface and path:
                    property_name = path[0] if path else "*"
                    result = self.hooks.execute_property_hooks(
                        property_name, "delete", actor_interface, old_prop or {}, path
                    )
                    if result is None:
                        self.response.set_status(403)
                        return
            if myself and myself.property:
                myself.property[name] = None
            myself.register_diffs(target="properties", subtarget=name, blob="")
            self.response.set_status(204)
            return
        orig = myself.property[name] if myself and myself.property else None
        old = orig
        logging.debug("DELETE /properties original value(" + (orig or "") + ")")
        try:
            orig = json.loads(orig or "{}")
        except (TypeError, ValueError, KeyError):
            # Since /properties/something was handled above
            # orig must be json loadable
            self.response.set_status(404)
            return
        if not delete_dict(orig, path[1:]):
            self.response.set_status(404)
            return
        # Execute property delete hook if available
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface and path:
                property_name = path[0] if path else "*"
                result = self.hooks.execute_property_hooks(property_name, "delete", actor_interface, old or {}, path)
                if result is None:
                    self.response.set_status(403)
                    return
        res = json.dumps(orig)
        logging.debug("Result to store( " + res + ") in /properties/" + name)
        if myself and myself.property:
            myself.property[name] = res
        myself.register_diffs(target="properties", subtarget=name, resource=resource, blob="")
        self.response.set_status(204)
