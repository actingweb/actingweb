from actingweb import auth
from actingweb.handlers import base_handler

class bot_handler(base_handler.base_handler):

    def post(self, path):
        """Handles POST callbacks for bots."""

        if not self.config.bot['token'] or \
                        len(self.config.bot['token']) == 0:
            self.response.set_status(404)
            return
        check = auth.auth(id=None, config=self.config)
        check.oauth.token = self.config.bot['token']
        ret = self.on_aw.bot_post(path=path)
        if ret and 100 <= ret < 999:
            self.response.set_status(ret)
            return
        elif ret:
            self.response.set_status(204)
            return
        else:
            self.response.set_status(404)
            return
