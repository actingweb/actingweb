from builtins import str
from actingweb.handlers import base_handler


class CallbackOauthHandler(base_handler.BaseHandler):

    def get(self):
        if not self.request.get('code'):
            self.response.set_status(400, "Bad request. No code.")
            return
        code = self.request.get('code')
        actor_id = self.request.get('state')
        self.response.set_redirect(self.config.root + str(actor_id) + '/oauth?code=' + str(code))
