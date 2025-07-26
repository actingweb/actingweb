from typing import Any, Dict, Optional, Union

from actingweb import auth
from actingweb.handlers import base_handler


class BotHandler(base_handler.BaseHandler):

    def post(self, path):
        """Handles POST callbacks for bots."""

        if not self.config.bot["token"] or len(self.config.bot["token"]) == 0:
            self.response.set_status(404)
            return
        check = auth.Auth(actor_id=None, config=self.config)
        if check.oauth:
            check.oauth.token = self.config.bot["token"]
            
        # Execute application-level bot callback hook
        ret = None
        if self.hooks:
            hook_data = {"path": path, "method": "POST"}
            # Parse request body if available
            try:
                body: Union[str, bytes, None] = self.request.body
                if body is not None:
                    if isinstance(body, bytes):
                        body_str = body.decode("utf-8", "ignore")
                    else:
                        body_str = body
                    import json
                    hook_data["body"] = json.loads(body_str)
            except (TypeError, ValueError, KeyError):
                pass  # No body or invalid JSON
                
            ret = self.hooks.execute_app_callback_hooks("bot", hook_data)
        if ret and isinstance(ret, int) and 100 <= ret < 999:
            self.response.set_status(ret)
            return
        elif ret:
            self.response.set_status(204)
            return
        else:
            self.response.set_status(404)
            return
