from actingweb.handlers import base_handler

class callback_oauth_handler(base_handler.base_handler):

    def get(self):
        if not self.request.get('code'):
            self.response.set_status(400, "Bad request. No code.")
            return
        code = self.request.get('code')
        id = self.request.get('state')
        self.redirect(self.config.root + str(id) + '/oauth?code=' + str(code))

