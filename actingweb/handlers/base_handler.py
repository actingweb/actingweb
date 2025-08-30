
from typing import Any, Optional, TYPE_CHECKING

from actingweb import aw_web_request, auth
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
    
    def _init_dual_auth(self, actor_id: str, api_path: str, web_subpath: str, name: str = "", **kwargs):
        """
        Initialize authentication supporting both web UI (OAuth) and API (basic) access.
        
        This helper method detects whether a request is coming from the web UI (by checking
        for oauth_token cookie) and chooses the appropriate authentication path:
        - Web UI requests: path="www", subpath=web_subpath (OAuth authentication)  
        - API requests: path=api_path, subpath=name (basic authentication)
        
        Args:
            actor_id: The actor ID
            api_path: Path to use for API authentication (e.g., "properties", "methods")
            web_subpath: Subpath to use for web UI authentication (e.g., "properties", "methods")
            name: Name/subpath for API authentication (optional)
            **kwargs: Additional arguments to pass to auth.init_actingweb
            
        Returns:
            Tuple of (actor, auth_check) from auth.init_actingweb
        """
        # Detect web UI context by checking for OAuth cookie
        is_web_ui_request = False
        try:
            # Check for OAuth cookie indicating web UI context
            if hasattr(self.request, 'cookies') and self.request.cookies:
                is_web_ui_request = 'oauth_token' in self.request.cookies
            elif hasattr(self, 'request'):
                # Alternative cookie access pattern for different frameworks
                oauth_cookie = getattr(self.request, 'get', lambda x, cookie=False: None)('oauth_token', cookie=True)
                is_web_ui_request = oauth_cookie is not None
        except Exception:
            # Fallback to basic auth if cookie detection fails
            is_web_ui_request = False
            
        if is_web_ui_request:
            # Web UI context - use OAuth authentication
            return auth.init_actingweb(
                appreq=self,
                actor_id=actor_id,
                path="www",
                subpath=web_subpath,
                config=self.config,
                **kwargs
            )
        else:
            # API context - use basic authentication
            return auth.init_actingweb(
                appreq=self,
                actor_id=actor_id,
                path=api_path,
                subpath=name,
                config=self.config,
                **kwargs
            )
