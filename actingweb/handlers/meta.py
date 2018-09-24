import json
from actingweb import auth
from actingweb.handlers import base_handler


class MetaHandler(base_handler.BaseHandler):

    def get(self, actor_id, path):
        (myself, check) = auth.init_actingweb(appreq=self,
                                              actor_id=actor_id, path='meta',
                                              subpath=path,
                                              add_response=False,
                                              config=self.config)
        # We accept no auth here, so don't check response code
        if not myself:
            return
        if not check.check_authorisation(path='meta', subpath=path, method='GET', approved=False):
            self.response.set_status(403)
            return

        trustee_root = myself.get_property('trustee_root').value
        if not trustee_root:
            trustee_root = ''
        if not path:
            values = {
                'id': actor_id,
                'type': self.config.aw_type,
                'version': self.config.version,
                'desc': self.config.desc,
                'info': self.config.info,
                'trustee_root': trustee_root,
                'specification': self.config.specification,
                'aw_version': self.config.aw_version,
                'aw_supported': self.config.aw_supported,
                'aw_formats': self.config.aw_formats,
            }
            out = json.dumps(values)
            self.response.write(out.encode('utf-8'))
            self.response.headers["Content-Type"] = "application/json"
            return

        elif path == 'id':
            out = actor_id
        elif path == 'type':
            out = self.config.aw_type
        elif path == 'version':
            out = self.config.version
        elif path == 'desc':
            out = self.config.desc + myself.id
        elif path == 'info':
            out = self.config.info
        elif path == 'trustee_root':
            out = trustee_root
        elif path == 'specification':
            out = self.config.specification
        elif path == 'actingweb/version':
            out = self.config.aw_version
        elif path == 'actingweb/supported':
            out = self.config.aw_supported
        elif path == 'actingweb/formats':
            out = self.config.aw_formats
        else:
            self.response.set_status(404)
            return
        self.response.write(out.encode('utf-8'))
