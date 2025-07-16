"""
Bridge between the new ActingWeb interface and the existing OnAWBase system.

This module provides compatibility between the new hook-based system and the
existing OnAWBase callback system.
"""

from typing import Any, Dict, List, Optional, Union, TYPE_CHECKING
import logging

from ..on_aw import OnAWBase

if TYPE_CHECKING:
    from .actor_interface import ActorInterface
    from .app import ActingWebApp


class ActingWebBridge(OnAWBase):
    """
    Bridge class that implements OnAWBase and delegates to the new hook system.
    
    This allows the new interface to work with the existing ActingWeb handlers
    without breaking changes.
    """
    
    def __init__(self, aw_app: 'ActingWebApp'):
        super().__init__()
        self.aw_app = aw_app
        self.hook_registry = aw_app.hooks
        
    def aw_init(self, auth=None, webobj=None):
        """Initialize with auth and webobj from existing system."""
        super().aw_init(auth, webobj)
        
    def _get_actor_interface(self) -> Optional['ActorInterface']:
        """Get ActorInterface wrapper for current actor."""
        if self.myself:
            from .actor_interface import ActorInterface
            return ActorInterface(self.myself)
        return None
        
    def bot_post(self, path: str) -> bool:
        """Handle bot POST requests through hooks."""
        # Execute application-level callback hooks for bot (no actor context)
        processed = self.hook_registry.execute_app_callback_hooks("bot", {"path": path, "method": "POST"})
        if processed:
            return True
        
        # Fall back to factory function if available
        if self.aw_app._actor_factory_func:
            try:
                # Bot requests typically don't have an actor, so we handle differently
                return True
            except Exception as e:
                logging.error(f"Error in bot factory function: {e}")
                return False
                
        return False
        
    def get_properties(self, path: List[str], data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle property GET requests through hooks."""
        actor_interface = self._get_actor_interface()
        if not actor_interface:
            return data
            
        if not path:
            # Getting all properties - apply hooks to each
            result: Dict[str, Any] = {}
            for key, value in data.items():
                transformed = self.hook_registry.execute_property_hooks(key, "get", actor_interface, value, [])
                if transformed is not None:
                    result[key] = transformed
            return result
        else:
            # Getting specific property
            property_name = path[0]
            transformed = self.hook_registry.execute_property_hooks(property_name, "get", actor_interface, data, path)
            return transformed if transformed is not None else None
            
    def delete_properties(self, path: List[str], old: Dict[str, Any], new: Dict[str, Any]) -> bool:  # pylint: disable=unused-argument
        """Handle property DELETE requests through hooks."""
        actor_interface = self._get_actor_interface()
        if not actor_interface:
            return True
            
        if path:
            property_name = path[0]
            # Execute delete hook - if it returns None, reject the deletion
            result = self.hook_registry.execute_property_hooks(property_name, "delete", actor_interface, old, path)
            return result is not None
            
        return True
        
    def put_properties(self, path: List[str], old: Dict[str, Any], new: Union[Dict[str, Any], str]) -> Optional[Union[Dict[str, Any], str]]:  # pylint: disable=unused-argument
        """Handle property PUT requests through hooks."""
        actor_interface = self._get_actor_interface()
        if not actor_interface:
            return new
            
        if path:
            property_name = path[0]
            return self.hook_registry.execute_property_hooks(property_name, "put", actor_interface, new, path)
            
        return new
        
    def post_properties(self, prop: str, data: Union[Dict[str, Any], str]) -> Optional[Union[Dict[str, Any], str]]:
        """Handle property POST requests through hooks."""
        actor_interface = self._get_actor_interface()
        if not actor_interface:
            return data
            
        return self.hook_registry.execute_property_hooks(prop, "post", actor_interface, data, [prop])
        
    def get_callbacks(self, name):
        """Handle GET callbacks through hooks."""
        actor_interface = self._get_actor_interface()
        if not actor_interface:
            return False
            
        result = self.hook_registry.execute_callback_hooks(name, actor_interface, {"method": "GET"})
        if isinstance(result, dict) and result:
            # Return None to indicate processed (like base class can)
            return None
        # Return False like base class default
        return False
        
    def delete_callbacks(self, name):
        """Handle DELETE callbacks through hooks."""
        actor_interface = self._get_actor_interface()
        if not actor_interface:
            return False
            
        result = self.hook_registry.execute_callback_hooks(name, actor_interface, {"method": "DELETE"})
        # Base class always returns False - we need to match that
        return False
        
    def post_callbacks(self, name):
        """Handle POST callbacks through hooks."""
        actor_interface = self._get_actor_interface()
        if not actor_interface:
            return False
            
        # Get request body if available
        import json
        data = {"method": "POST"}
        if (self.webobj and hasattr(self.webobj, 'request') and 
            hasattr(self.webobj.request, 'body') and self.webobj.request.body):
            try:
                body_bytes = self.webobj.request.body
                if body_bytes:
                    body_str = body_bytes.decode('utf-8', 'ignore')
                    data["body"] = json.loads(body_str)
            except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
                body_bytes = self.webobj.request.body
                if body_bytes:
                    data["body"] = body_bytes.decode('utf-8', 'ignore')
                
        result = self.hook_registry.execute_callback_hooks(name, actor_interface, data)
        # Base class always returns False - we need to match that
        return False
        
    def post_subscriptions(self, sub, peerid, data):
        """Handle subscription callbacks through hooks."""
        actor_interface = self._get_actor_interface()
        if not actor_interface:
            return True
            
        result = self.hook_registry.execute_subscription_hooks(actor_interface, sub, peerid, data)
        # Base class always returns True - we need to match that
        return True
        
    def delete_actor(self) -> None:
        """Handle actor deletion through lifecycle hooks."""
        actor_interface = self._get_actor_interface()
        if actor_interface:
            self.hook_registry.execute_lifecycle_hooks("actor_deleted", actor_interface)
            
    def check_on_oauth_success(self, token=None):
        """Handle OAuth success check through lifecycle hooks."""
        actor_interface = self._get_actor_interface()
        if actor_interface:
            result = self.hook_registry.execute_lifecycle_hooks("oauth_success", actor_interface, token=token)
            return result if result is not None else True
        return True
        
    def actions_on_oauth_success(self):
        """Handle OAuth success actions through lifecycle hooks."""
        actor_interface = self._get_actor_interface()
        if actor_interface:
            result = self.hook_registry.execute_lifecycle_hooks("oauth_success", actor_interface)
            return result if result is not None else True
        return True
        
    def get_resources(self, name: str) -> Dict[str, Any]:
        """Handle GET resources through hooks."""
        actor_interface = self._get_actor_interface()
        if not actor_interface:
            return {}
            
        processed = self.hook_registry.execute_callback_hooks(f"resource_{name}", actor_interface, {"method": "GET"})
        return {} if not processed else {"status": "handled"}
        
    def delete_resources(self, name: str) -> Dict[str, Any]:
        """Handle DELETE resources through hooks."""
        actor_interface = self._get_actor_interface()
        if not actor_interface:
            return {}
            
        processed = self.hook_registry.execute_callback_hooks(f"resource_{name}", actor_interface, {"method": "DELETE"})
        return {} if not processed else {"status": "handled"}
        
    def put_resources(self, name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle PUT resources through hooks."""
        actor_interface = self._get_actor_interface()
        if not actor_interface:
            return {}
            
        processed = self.hook_registry.execute_callback_hooks(f"resource_{name}", actor_interface, {"method": "PUT", "params": params})
        return {} if not processed else {"status": "handled"}
        
    def post_resources(self, name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle POST resources through hooks."""
        actor_interface = self._get_actor_interface()
        if not actor_interface:
            return {}
            
        processed = self.hook_registry.execute_callback_hooks(f"resource_{name}", actor_interface, {"method": "POST", "params": params})
        return {} if not processed else {"status": "handled"}
        
    def www_paths(self, path=""):
        """Handle www paths through hooks."""
        actor_interface = self._get_actor_interface()
        if not actor_interface:
            return False
            
        result = self.hook_registry.execute_callback_hooks("www", actor_interface, {"path": path})
        # Base class always returns False - we need to match that
        return False
        
    def get_methods(self, name: str = "") -> Optional[Dict[str, Any]]:
        """Handle GET methods through hooks."""
        actor_interface = self._get_actor_interface()
        if not actor_interface:
            return None
            
        if not name:
            # Return list of available methods
            # This could be enhanced to automatically discover methods
            return {"methods": list(self.hook_registry._method_hooks.keys())}
            
        result = self.hook_registry.execute_method_hooks(name, actor_interface, {"method": "GET"})
        return result
        
    def post_methods(self, name: str = "", data: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Handle POST methods through hooks."""
        actor_interface = self._get_actor_interface()
        if not actor_interface:
            return None
            
        result = self.hook_registry.execute_method_hooks(name, actor_interface, data or {})
        return result
        
    def put_methods(self, name: str = "", data: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Handle PUT methods through hooks."""
        actor_interface = self._get_actor_interface()
        if not actor_interface:
            return None
            
        result = self.hook_registry.execute_method_hooks(name, actor_interface, data or {})
        return result
        
    def delete_methods(self, name: str = "") -> bool:
        """Handle DELETE methods through hooks."""
        actor_interface = self._get_actor_interface()
        if not actor_interface:
            return False
            
        result = self.hook_registry.execute_method_hooks(name, actor_interface, {"method": "DELETE"})
        return result is not None
        
    def get_actions(self, name: str = "") -> Optional[Dict[str, Any]]:
        """Handle GET actions through hooks."""
        actor_interface = self._get_actor_interface()
        if not actor_interface:
            return None
            
        if not name:
            # Return list of available actions
            # This could be enhanced to automatically discover actions
            return {"actions": list(self.hook_registry._action_hooks.keys())}
            
        result = self.hook_registry.execute_action_hooks(name, actor_interface, {"method": "GET"})
        return result
        
    def post_actions(self, name: str = "", data: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Handle POST actions through hooks."""
        actor_interface = self._get_actor_interface()
        if not actor_interface:
            return None
            
        result = self.hook_registry.execute_action_hooks(name, actor_interface, data or {})
        return result
        
    def put_actions(self, name: str = "", data: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Handle PUT actions through hooks."""
        actor_interface = self._get_actor_interface()
        if not actor_interface:
            return None
            
        result = self.hook_registry.execute_action_hooks(name, actor_interface, data or {})
        return result
        
    def delete_actions(self, name: str = "") -> bool:
        """Handle DELETE actions through hooks."""
        actor_interface = self._get_actor_interface()
        if not actor_interface:
            return False
            
        result = self.hook_registry.execute_action_hooks(name, actor_interface, {"method": "DELETE"})
        return result is not None