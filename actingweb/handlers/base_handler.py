
from typing import Any, Optional, TYPE_CHECKING

from actingweb import aw_web_request
from actingweb import config as config_class

if TYPE_CHECKING:
    from actingweb.interface.hooks import HookRegistry
    from actingweb.interface.actor_interface import ActorInterface


class BaseHandler:

    def __init__(
        self,
        webobj: aw_web_request.AWWebObj = aw_web_request.AWWebObj(),
        config: config_class.Config = config_class.Config(),
        hooks: Optional['HookRegistry'] = None,
    ) -> None:
        self.request = webobj.request
        self.response = webobj.response
        self.config = config
        self.hooks = hooks
        
    def _get_actor_interface(self, actor) -> Optional['ActorInterface']:
        """Get ActorInterface wrapper for given actor."""
        if actor:
            from actingweb.interface.actor_interface import ActorInterface
            return ActorInterface(actor)
        return None
