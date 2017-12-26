from actingweb import auth
from actingweb.handlers import base_handler


class WwwHandler(base_handler.BaseHandler):

    def get(self, actor_id, path):
        (myself, check) = auth.init_actingweb(appreq=self,
                                              actor_id=actor_id, path='www', subpath=path,
                                              config=self.config)
        if not myself or check.response["code"] != 200:
            return
        if not self.config.ui:
            self.response.set_status(404, "Web interface is not enabled")
            return
        if not check.check_authorisation(path='www', subpath=path, method='GET'):
            self.response.write('')
            self.response.set_status(403)
            return

        if not path or path == '':
            self.response.template_values = {
                'url': self.request.url,
                'id': actor_id,
                'creator': myself.creator,
                'passphrase': myself.passphrase,
            }
            return

        if path == 'init':
            self.response.template_values = {
                'id': myself.id,
            }
            return
        if path == 'properties':
            properties = myself.get_properties()
            self.response.template_values = {
                'id': myself.id,
                'properties': properties,
            }
            return
        if path == 'property':
            lookup = myself.get_property(self.request.get('name'))
            if lookup.value:
                self.response.template_values = {
                    'id': myself.id,
                    'property': lookup.name,
                    'value': lookup.value,
                    'qual': '',
                }
            else:
                self.response.template_values = {
                    'id': myself.id,
                    'property': lookup.name,
                    'value': 'Not set',
                    'qual': 'no',
                }
            return
        if path == 'trust':
            relationships = myself.get_trust_relationships()
            if not relationships or len(relationships) == 0:
                self.response.set_status(404, 'Not found')
                return
            for t in relationships:
                t["approveuri"] = self.config.root + myself.id + '/trust/' + t.relationship + '/' + t.peerid
                self.response.template_values = {
                    'id': myself.id,
                    'trusts': relationships,
                }
            return
        output = self.on_aw.www_paths(path=path)
        if output:
            self.response.write(output)
        else:
            self.response.set_status(404, "Not found")
        return
