import json
import logging
from actingweb import auth, aw_web_request
from actingweb.handlers import base_handler

def merge_dict(d1, d2):
    """ Modifies d1 in-place to contain values from d2.

    If any value in d1 is a dictionary (or dict-like), *and* the corresponding
    value in d2 is also a dictionary, then merge them in-place.
    Thanks to Edward Loper on stackoverflow.com
    """
    for k, v2 in d2.items():
        v1 = d1.get(k)  # returns None if v1 has no value for this key
        if isinstance(v1, dict) and isinstance(v2, dict):
            merge_dict(v1, v2)
        else:
            d1[k] = v2


def delete_dict(d1, path):
    """ Deletes path (an array of strings) in d1 dict.

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


class properties_handler(base_handler.base_handler):

    def get(self, id, name):
        if self.request.get('_method') == 'PUT':
            self.put(id, name)
            return
        if self.request.get('_method') == 'DELETE':
            self.delete(id, name)
            return
        (myself, check) = auth.init_actingweb(appreq=self,
                                              id=id, path='properties', subpath=name,
                                              config=self.config)
        if not myself or check.response["code"] != 200:
            return
        if not name:
            path = {}
            path[0] = None
        else:
            path = name.split('/')
            name = path[0]
        if not check.checkAuthorisation(path='properties', subpath=name, method='GET'):
            self.response.set_status(403)
            return
        # if name is not set, this request URI was the properties root
        if not name:
            self.listall(myself)
            return
        lookup = myself.getProperty(name)
        if not lookup.value:
            self.response.set_status(404, "Property not found")
            return
        try:
            jsonblob = json.loads(lookup.value)
            try:
                out = jsonblob
                if len(path) > 1:
                    del path[0]
                    for p in path:
                        out = out[p]
                out = json.dumps(out)
            except:
                self.response.set_status(404)
                return
        except:
            out = str(lookup.value)
        self.response.set_status(200, "Ok")
        self.response.headers["Content-Type"] = "application/json"
        self.response.write(out.encode('utf-8'))

    def listall(self, myself):
        properties = myself.getProperties()
        if not properties or len(properties) == 0:
            self.response.set_status(404, "No properties")
            return
        pair = dict()
        for name, value in properties.items():
            try:
                js = json.loads(value)
                pair[name] = js
            except ValueError:
                pair[name] = value
        out = json.dumps(pair)
        self.response.write(out.encode('utf-8'))
        self.response.headers["Content-Type"] = "application/json"
        return

    def put(self, id, name):
        (myself, check) = auth.init_actingweb(appreq=self,
                                              id=id, path='properties', subpath=name,
                                              config=self.config)
        if not myself or check.response["code"] != 200:
            return
        if not name:
            path = {}
            path[0] = None
        else:
            path = name.split('/')
            name = path[0]
            if len(path) >= 2 and len(path[1]) > 0:
                resource = path[1]
            else:
                resource = None
        if not check.checkAuthorisation(path='properties', subpath=name, method='PUT'):
            self.response.set_status(403)
            return
        body = self.request.body.decode('utf-8', 'ignore')
        if len(path) == 1:
            myself.setProperty(name, body)
            myself.registerDiffs(target='properties', subtarget=name, blob=body)
            self.response.set_status(204)
            return
        # Keep text blob for later diff registration
        blob = body
        # Make store var to be merged with original struct
        try:
            body = json.loads(body)
        except:
            pass
        store = {}
        store[path[len(path)-1]] = body
        # logging.debug('store with body:' + json.dumps(store))
        # Make store to be at same level as orig value
        i = len(path)-2
        while i > 0:
            c = store.copy()
            store = {}
            store[path[i]] = c
            # logging.debug('store with i=' + str(i) + ' (' + json.dumps(store) + ')')
            i -= 1
        # logging.debug('Snippet to store(' + json.dumps(store) + ')')
        orig = myself.getProperty(name).value
        logging.debug('Original value(' + orig + ')')
        try:
            orig = json.loads(orig)
            merge_dict(orig, store)
            res = json.dumps(orig)
        except:
            res = json.dumps(store)
        logging.debug('Result to store( ' + res + ') in /properties/' + name)
        myself.setProperty(name, res)
        myself.registerDiffs(target='properties', subtarget=name, resource = resource, blob=blob)
        self.response.set_status(204)

    def post(self, id, name):
        (myself, check) = auth.init_actingweb(appreq=self,
                                              id=id, path='properties', subpath=name,
                                              config=self.config)
        if not myself or check.response["code"] != 200:
            return
        if not check.checkAuthorisation(path='properties', subpath=name, method='POST'):
            self.response.set_status(403)
            return
        if len(name) > 0:
            self.response.set_status(405)
        pair = dict()
        # Handle the simple form
        if self.request.get("property") and self.request.get("value"):
            pair[self.request.get("property")] = self.request.get("value")
            myself.setProperty(self.request.get("property"), self.request.get("value"))
        elif len(self.request.arguments()) > 0:
            for name in self.request.arguments():
                pair[name] = self.request.get(name)
                myself.setProperty(name, self.request.get(name))
        else:
            try:
                params = json.loads(self.request.body.decode('utf-8', 'ignore'))
            except:
                self.response.set_status(405, "Error in json body")
                return
            for key in params:
                pair[key] = params[key]
                if isinstance(params[key], dict):
                    text = json.dumps(params[key])
                else:
                    text = params[key]
                myself.setProperty(key, text)
        out = json.dumps(pair)
        myself.registerDiffs(target='properties', blob=out)
        self.response.write(out.encode('utf-8'))
        self.response.headers["Content-Type"] = "application/json"
        self.response.set_status(201, 'Created')

    def delete(self, id, name):
        (myself, check) = auth.init_actingweb(appreq=self,
                                              id=id, path='properties', subpath=name,
                                              config=self.config)
        if not myself or check.response["code"] != 200:
            return
        if not name:
            path = {}
            path[0] = None
        else:
            path = name.split('/')
            name = path[0]
            if len(path) >= 2 and len(path[1]) > 0:
                resource = path[1]
            else:
                resource = None
        if not check.checkAuthorisation(path='properties', subpath=name, method='DELETE'):
            self.response.set_status(403)
            return
        if not name:
            myself.deleteProperties()
            myself.registerDiffs(target='properties', subtarget=None, blob='')
            self.response.set_status(204)
            return
        if len(path) == 1:
            myself.deleteProperty(name)
            myself.registerDiffs(target='properties', subtarget=name, blob='')
            self.response.set_status(204)
            return
        orig = myself.getProperty(name).value
        logging.debug('DELETE /properties original value(' + orig + ')')
        try:
            orig = json.loads(orig)
        except:
            # Since /properties/something was handled above
            # orig must be json loadable
            self.response.set_status(404)
            return
        if not delete_dict(orig, path[1:]):
            self.response.set_status(404)
            return
        res = json.dumps(orig)
        logging.debug('Result to store( ' + res + ') in /properties/' + name)
        myself.setProperty(name, res)
        myself.registerDiffs(target='properties', subtarget=name, resource = resource, blob='')
        self.response.set_status(204)
