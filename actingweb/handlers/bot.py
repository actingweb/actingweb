from actingweb.handlers import base_handler


class BotHandler(base_handler.BaseHandler):
    def post(self, path):
        """Handles POST callbacks for bots."""
        # Validate bot configuration and token
        bot_token = self._get_bot_token()
        if not bot_token:
            if self.response:
                self.response.set_status(404)
            return

        # Execute application-level bot callback hook
        ret = None
        if self.hooks:
            hook_data = {
                "path": path,
                "method": "POST",
                "bot_token": bot_token,  # Provide bot token to hooks for service calls
            }
            # Parse request body if available
            try:
                body: str | bytes | None = self.request.body
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

        # Handle hook response
        if ret and isinstance(ret, int) and 100 <= ret < 999:
            self.response.set_status(ret)
            return
        elif ret:
            self.response.set_status(204)
            return
        else:
            self.response.set_status(404)
            return

    def _get_bot_token(self) -> str:
        """Get bot token from configuration."""
        try:
            bot_cfg = getattr(self.config, "bot", None)
            if isinstance(bot_cfg, dict):
                return bot_cfg.get("token", "") or ""
        except Exception:
            pass
        return ""
