import json
import datetime
from actingweb import auth
from actingweb import aw_proxy
from actingweb import attribute
from actingweb.handlers import base_handler


class devtest_handler(base_handler.base_handler):

    def put(self, id, path):
        """Handles PUT for devtest"""

        if not self.config.devtest:
            self.response.set_status(404)
            return
        (myself, check) = auth.init_actingweb(
            appreq=self,
            id=id,
            path='devtest',
            subpath=path,
            config=self.config)
        if not myself or check.response["code"] != 200:
            return
        try:
            params = json.loads(self.request.body.decode('utf-8', 'ignore'))
        except:
            params = self.request.body.decode('utf-8', 'ignore')
        paths = path.split('/')
        if paths[0] == 'proxy':
            mytwin = myself.getPeerTrustee(shorttype='myself')
            if mytwin and len(mytwin) > 0:
                if paths[1] == 'properties' and paths[2] and len(paths[2]) > 0:
                        proxy = aw_proxy.aw_proxy(peer_target=mytwin, config=self.config)
                        if params:
                            proxy.changeResource('/properties/' + paths[2], params = params)
                        self.response.set_status(proxy.last_response_code)
                        return
        elif paths[0] == 'ping':
            self.response.set_status(204)
            return
        elif paths[0] == 'attribute':
            if len(paths) > 2:
                bucket = attribute.attributes(actorId=myself.id, bucket=paths[1], config=self.config)
                bucket.set_attr(paths[2], params, timestamp=datetime.datetime.now())
                self.response.set_status(204)
                return
        self.response.set_status(404)

    def delete(self, id, path):
        """Handles DELETE for devtest"""

        if not self.config.devtest:
            self.response.set_status(404)
            return
        (myself, check) = auth.init_actingweb(appreq=self,
                                                      id=id, path='devtest', 
                                                      subpath=path,
                                                      config=self.config)
        if not myself or check.response["code"] != 200:
            return
        paths = path.split('/')
        if paths[0] == 'proxy':
            mytwin = myself.getPeerTrustee(shorttype='myself')
            if mytwin and len(mytwin) > 0:
                if paths[1] == 'properties':
                    proxy = aw_proxy.aw_proxy(peer_target=mytwin, config=self.config)
                    proxy.deleteResource(path='/properties')
                    self.response.set_status(proxy.last_response_code)
                    return
        elif paths[0] == 'ping':
            self.response.set_status(204)
            return
        elif paths[0] == 'attribute':
            if len(paths) > 2:
                bucket = attribute.attributes(actorId=myself.id, bucket=paths[1], config=self.config)
                bucket.delete_attr(paths[2])
                self.response.set_status(204)
                return
            else:
                buckets = attribute.buckets(actorId=myself.id, config=self.config)
                buckets.delete()
                self.response.set_status(204)
                return
        self.response.set_status(404)

    def get(self, id, path):
        """Handles GET for devtest"""

        if not self.config.devtest:
            self.response.set_status(404)
            return
        (myself, check) = auth.init_actingweb(appreq=self,
                                              id=id, path='devtest',
                                              subpath=path,
                                              config=self.config)
        if not myself or check.response["code"] != 200:
            return
        paths = path.split('/')
        if paths[0] == 'proxy':
            mytwin = myself.getPeerTrustee(shorttype='myself')
            if mytwin and len(mytwin) > 0:
                if paths[1] == 'properties':
                    proxy = aw_proxy.aw_proxy(peer_target=mytwin, config=self.config)
                    prop = proxy.getResource(path='/properties')
                    if proxy.last_response_code != 200:
                        self.response.set_status(proxy.last_response_code)
                        return
                    out = json.dumps(prop)
                    self.response.write(out.encode('utf-8'))
                    self.response.headers["Content-Type"] = "application/json"
                    self.response.set_status(200)
                    return
        elif paths[0] == 'ping':
            self.response.set_status(204)
            return
        elif paths[0] == 'attribute':
            if len(paths) > 1:
                bucket = attribute.attributes(actorId=myself.id, bucket=paths[1], config=self.config)
                params = bucket.get_bucket()
                for k,v in params.iteritems():
                    params[k]["timestamp"] = v["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
                out = json.dumps(params)
                self.response.write(out.encode('utf-8'))
                self.response.headers["Content-Type"] = "application/json"
                self.response.set_status(200)
                return
            else:
                buckets = attribute.buckets(actorId=myself.id, config=self.config)
                params = buckets.fetch()
                if len(params) == 0:
                    self.response.set_status(404)
                    return
                for b,d in params.iteritems():
                    for k,v  in d.iteritems():
                        d[k]["timestamp"] = v["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
                out = json.dumps(params)
                self.response.write(out.encode('utf-8'))
                self.response.headers["Content-Type"] = "application/json"
                self.response.set_status(200)
                return
        self.response.set_status(404)

    def post(self, id, path):
        """Handles POST for devtest"""

        if not self.config.devtest:
            self.response.set_status(404)
            return
        (myself, check) = auth.init_actingweb(appreq=self,
                                              id=id, path='devtest',
                                              subpath=path,
                                              config=self.config)
        if not myself or check.response["code"] != 200:
            return
        try:
            params = json.loads(self.request.body.decode('utf-8', 'ignore'))
        except:
            params = None
        paths = path.split('/')
        if paths[0] == 'proxy':
            mytwin = myself.getPeerTrustee(shorttype='myself')
            if mytwin and len(mytwin) > 0:
                if paths[1] == 'create':
                        proxy = aw_proxy.aw_proxy(peer_target=mytwin, config=self.config)
                        meta = proxy.getResource(path='/meta')
                        if params:
                            proxy.createResource('/properties', params = params)
                        out = json.dumps(meta)
                        self.response.write(out.encode('utf-8'))
                        self.response.headers["Content-Type"] = "application/json"
                        self.response.headers["Location"] = str(mytwin["baseuri"])
                        self.response.set_status(200)
                        return
        elif paths[0] == 'ping':
            self.response.set_status(204)
            return
        elif paths[0] == 'attribute':
            if paths[1] and len(paths[1]) > 0:
                bucket = attribute.attributes(actorId=myself.id, bucket=paths[1], config=self.config)
                for k,v in params.iteritems():
                    bucket.set_attr(k, v, timestamp=datetime.datetime.now())
                out = json.dumps(params)
                self.response.write(out.encode('utf-8'))
                self.response.headers["Content-Type"] = "application/json"
                self.response.set_status(200)
                return
        self.response.set_status(404)
