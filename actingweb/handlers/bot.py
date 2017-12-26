from actingweb import auth
from actingweb.handlers import base_handler


class BotHandler(base_handler.BaseHandler):

    def post(self, path):
        """Handles POST callbacks for bots."""

        if not self.config.bot['token'] or len(self.config.bot['token']) == 0:
            self.response.set_status(404)
            return
        check = auth.Auth(actor_id=None, config=self.config)
        check.oauth.token = self.config.bot['token']
        # Here we need to manually initialise on_aw as this is normally done in init_actingweb() in auth
        self.on_aw.aw_init(auth=check, webobj=self)
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
