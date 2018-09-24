from builtins import str
import logging
import json
from actingweb import actor
from actingweb.handlers import base_handler


class RootFactoryHandler(base_handler.BaseHandler):

    def get(self):
        if self.request.get('_method') == 'POST':
            self.post()
            return
        if self.config.ui:
            self.response.template_values = {
            }
        else:
            self.response.set_status(404)

    def post(self):
        myself = actor.Actor(config=self.config)
        try:
            params = json.loads(self.request.body.decode('utf-8', 'ignore'))
            is_json = True
            if 'creator' in params:
                creator = params['creator']
            else:
                creator = ''
            if 'trustee_root' in params:
                trustee_root = params['trustee_root']
            else:
                trustee_root = ''
            if 'passphrase' in params:
                passphrase = params['passphrase']
            else:
                passphrase = ''
        except ValueError:
            is_json = False
            creator = self.request.get('creator')
            trustee_root = self.request.get('trustee_root')
            passphrase = self.request.get('passphrase')
        if not myself.create(url=self.request.url, creator=creator, passphrase=passphrase):
            self.response.set_status(400, 'Not created')
            logging.warning("Was not able to create new Actor("+str(self.request.url) + " " +
                            str(creator) + ")")
            return
        if len(trustee_root) > 0:
            myself.set_property('trustee_root', trustee_root)
        self.response.headers["Location"] = str(self.config.root + myself.id)
        if self.config.www_auth == 'oauth' and not is_json:
            self.response.set_redirect(self.config.root + myself.id + '/www')
            return
        pair = {
            'id': myself.id,
            'creator': myself.creator,
            'passphrase': str(myself.passphrase),
        }
        if len(trustee_root) > 0:
            pair['trustee_root'] = trustee_root
        if self.config.ui and not is_json:
            self.response.template_values = pair
            return
        out = json.dumps(pair)
        self.response.write(out)
        self.response.headers["Content-Type"] = "application/json"
        self.response.set_status(201, 'Created')
