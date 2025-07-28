"""
Main ActingWebApp class providing fluent API for application configuration.
"""

import os
import logging
from typing import Optional, Dict, Any, Callable, Union, TYPE_CHECKING
from flask import Flask

from ..config import Config
from ..actor import Actor as CoreActor
from .hooks import HookRegistry

if TYPE_CHECKING:
    from .actor_interface import ActorInterface
    from .integrations.flask_integration import FlaskIntegration
    from .integrations.fastapi_integration import FastAPIIntegration
    try:
        from fastapi import FastAPI
    except ImportError:
        FastAPI = Any


class ActingWebApp:
    """
    Main application class for ActingWeb with fluent configuration API.
    
    Example usage:
        app = ActingWebApp(
            aw_type="urn:actingweb:example.com:myapp",
            database="dynamodb",
            fqdn="myapp.example.com"
        ).with_oauth(
            client_id="...",
            client_secret="..."
        ).with_web_ui().with_devtest()
        
        @app.actor_factory
        def create_actor(creator: str, **kwargs) -> 'ActorInterface':
            from .actor_interface import ActorInterface
            actor = ActorInterface.create(creator=creator, config=app.get_config())
            return actor
    """
    
    def __init__(self, aw_type: str, database: str = "dynamodb", fqdn: str = "", proto: str = "https://"):
        self.aw_type = aw_type
        self.database = database
        self.fqdn = fqdn or os.getenv("APP_HOST_FQDN", "localhost")
        self.proto = proto or os.getenv("APP_HOST_PROTOCOL", "https://")
        
        # Configuration options
        self._oauth_config: Optional[Dict[str, Any]] = None
        self._actors_config: Dict[str, Dict[str, Any]] = {}
        self._enable_ui = False
        self._enable_devtest = False
        self._enable_bot = False
        self._bot_config: Optional[Dict[str, Any]] = None
        self._www_auth = "basic"
        self._unique_creator = False
        self._force_email_prop_as_creator = False
        
        # Hook registry
        self.hooks = HookRegistry()
        
        # Actor factory function
        self._actor_factory_func: Optional[Callable[..., 'ActorInterface']] = None
        
        # Internal config object (lazy initialized)
        self._config: Optional[Config] = None
        
    def with_oauth(self, client_id: str, client_secret: str, scope: str = "",
                   auth_uri: str = "", token_uri: str = "", **kwargs: Any) -> 'ActingWebApp':
        """Configure OAuth authentication."""
        self._oauth_config = {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": f"{self.proto}{self.fqdn}/oauth",
            "scope": scope,
            "auth_uri": auth_uri or "https://api.actingweb.net/v1/authorize",
            "token_uri": token_uri or "https://api.actingweb.net/v1/access_token",
            "response_type": "code",
            "grant_type": "authorization_code",
            "refresh_type": "refresh_token",
            **kwargs
        }
        self._www_auth = "oauth"
        return self
        
    def with_web_ui(self, enable: bool = True) -> 'ActingWebApp':
        """Enable or disable the web UI."""
        self._enable_ui = enable
        return self
        
    def with_devtest(self, enable: bool = True) -> 'ActingWebApp':
        """Enable or disable development/testing endpoints."""
        self._enable_devtest = enable
        return self
        
    def with_bot(self, token: str = "", email: str = "", secret: str = "", admin_room: str = "") -> 'ActingWebApp':
        """Configure bot integration."""
        self._enable_bot = True
        self._bot_config = {
            "token": token or os.getenv("APP_BOT_TOKEN", ""),
            "email": email or os.getenv("APP_BOT_EMAIL", ""),
            "secret": secret or os.getenv("APP_BOT_SECRET", ""),
            "admin_room": admin_room or os.getenv("APP_BOT_ADMIN_ROOM", "")
        }
        return self
        
    def with_unique_creator(self, enable: bool = True) -> 'ActingWebApp':
        """Enable unique creator constraint."""
        self._unique_creator = enable
        return self
        
    def with_email_as_creator(self, enable: bool = True) -> 'ActingWebApp':
        """Force email property as creator."""
        self._force_email_prop_as_creator = enable
        return self
        
    def add_actor_type(self, name: str, factory: str = "", relationship: str = "friend") -> 'ActingWebApp':
        """Add an actor type configuration."""
        self._actors_config[name] = {
            "type": self.aw_type,
            "factory": factory or f"{self.proto}{self.fqdn}/",
            "relationship": relationship
        }
        return self
        
    def actor_factory(self, func: Callable[..., 'ActorInterface']) -> Callable[..., 'ActorInterface']:
        """Decorator to register actor factory function."""
        self._actor_factory_func = func
        return func
        
    def property_hook(self, property_name: str = "*") -> Callable[..., Any]:
        """Decorator to register property hooks."""
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self.hooks.register_property_hook(property_name, func)
            return func
        return decorator
        
    def callback_hook(self, callback_name: str = "*") -> Callable[..., Any]:
        """Decorator to register actor-level callback hooks."""
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self.hooks.register_callback_hook(callback_name, func)
            return func
        return decorator
        
    def app_callback_hook(self, callback_name: str) -> Callable[..., Any]:
        """Decorator to register application-level callback hooks (no actor context)."""
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self.hooks.register_app_callback_hook(callback_name, func)
            return func
        return decorator
        
    def subscription_hook(self, func: Callable[..., Any]) -> Callable[..., Any]:
        """Decorator to register subscription hooks."""
        self.hooks.register_subscription_hook(func)
        return func
        
    def lifecycle_hook(self, event: str) -> Callable[..., Any]:
        """Decorator to register lifecycle hooks."""
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self.hooks.register_lifecycle_hook(event, func)
            return func
        return decorator
        
    def method_hook(self, method_name: str = "*") -> Callable[..., Any]:
        """Decorator to register method hooks."""
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self.hooks.register_method_hook(method_name, func)
            return func
        return decorator
        
    def action_hook(self, action_name: str = "*") -> Callable[..., Any]:
        """Decorator to register action hooks."""
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self.hooks.register_action_hook(action_name, func)
            return func
        return decorator
        
    def get_config(self) -> Config:
        """Get the underlying ActingWeb Config object."""
        if self._config is None:
            # Add default actor type
            if "myself" not in self._actors_config:
                self.add_actor_type("myself")
                
            self._config = Config(
                database=self.database,
                fqdn=self.fqdn,
                proto=self.proto,
                aw_type=self.aw_type,
                desc=f"ActingWeb app: {self.aw_type}",
                version="3.0",
                devtest=self._enable_devtest,
                actors=self._actors_config,
                force_email_prop_as_creator=self._force_email_prop_as_creator,
                unique_creator=self._unique_creator,
                www_auth=self._www_auth,
                logLevel=os.getenv("LOG_LEVEL", "INFO"),
                ui=self._enable_ui,
                bot=self._bot_config or {},
                oauth=self._oauth_config or {},
            )
        return self._config
        
    def get_actor_factory(self) -> Optional[Callable[..., 'ActorInterface']]:
        """Get the registered actor factory function."""
        return self._actor_factory_func
        
    def integrate_flask(self, flask_app: Flask) -> 'FlaskIntegration':
        """Integrate with Flask application."""
        from .integrations.flask_integration import FlaskIntegration
        integration = FlaskIntegration(self, flask_app)
        integration.setup_routes()
        return integration
        
    def integrate_fastapi(self, fastapi_app: 'FastAPI', templates_dir: Optional[str] = None, **options: Any) -> 'FastAPIIntegration':
        """
        Integrate ActingWeb with FastAPI application.
        
        Args:
            fastapi_app: The FastAPI application instance
            templates_dir: Directory containing Jinja2 templates (optional)
            **options: Additional configuration options
            
        Returns:
            FastAPIIntegration instance
            
        Raises:
            ImportError: If FastAPI is not installed
        """
        try:
            from .integrations.fastapi_integration import FastAPIIntegration
        except ImportError as e:
            if "fastapi" in str(e).lower():
                raise ImportError(
                    "FastAPI is required for FastAPI integration. "
                    "Install with: pip install fastapi"
                ) from e
            raise
            
        integration = FastAPIIntegration(self, fastapi_app, templates_dir=templates_dir)
        integration.setup_routes()
        return integration
        
    def run(self, host: str = "0.0.0.0", port: int = 5000, debug: bool = False) -> None:
        """Run as standalone application with Flask."""
        flask_app = Flask(__name__)
        self.integrate_flask(flask_app)
        flask_app.run(host=host, port=port, debug=debug)