"""
Flask integration for ActingWeb applications.

Automatically generates Flask routes and handles request/response transformation.
"""

from typing import TYPE_CHECKING, Any, Dict, Optional
from flask import Flask, request, redirect, Response, render_template
import logging

from ...aw_web_request import AWWebObj
from ...handlers import (
    callbacks, properties, meta, root, trust, devtest, subscription,
    resources, oauth, callback_oauth, bot, www, factory, methods, actions
)
if TYPE_CHECKING:
    from ..app import ActingWebApp


class FlaskIntegration:
    """
    Flask integration for ActingWeb applications.
    
    Automatically sets up all ActingWeb routes and handles request/response
    transformation between Flask and ActingWeb.
    """
    
    def __init__(self, aw_app: 'ActingWebApp', flask_app: Flask):
        self.aw_app = aw_app
        self.flask_app = flask_app
        
    def setup_routes(self) -> None:
        """Setup all ActingWeb routes in Flask."""
        
        # Root factory route
        @self.flask_app.route("/", methods=["GET", "POST"])
        def app_root():
            return self._handle_factory_request()
            
        # OAuth callback
        @self.flask_app.route("/oauth", methods=["GET"])
        def app_oauth_callback():
            return self._handle_oauth_callback()
            
        # Bot endpoint
        @self.flask_app.route("/bot", methods=["POST"])
        def app_bot():
            return self._handle_bot_request()
            
        # Actor root
        @self.flask_app.route("/<actor_id>", methods=["GET", "POST", "DELETE"])
        def app_actor_root(actor_id):
            return self._handle_actor_request(actor_id, "root")
            
        # Actor meta
        @self.flask_app.route("/<actor_id>/meta", methods=["GET"])
        @self.flask_app.route("/<actor_id>/meta/<path:path>", methods=["GET"])
        def app_meta(actor_id, path=""):
            return self._handle_actor_request(actor_id, "meta", path=path)
            
        # Actor OAuth
        @self.flask_app.route("/<actor_id>/oauth", methods=["GET"])
        @self.flask_app.route("/<actor_id>/oauth/<path:path>", methods=["GET"])
        def app_oauth(actor_id, path=""):
            return self._handle_actor_request(actor_id, "oauth", path=path)
            
        # Actor www
        @self.flask_app.route("/<actor_id>/www", methods=["GET", "POST", "DELETE"])
        @self.flask_app.route("/<actor_id>/www/<path:path>", methods=["GET", "POST", "DELETE"])
        def app_www(actor_id, path=""):
            return self._handle_actor_request(actor_id, "www", path=path)
            
        # Actor properties
        @self.flask_app.route("/<actor_id>/properties", methods=["GET", "POST", "DELETE", "PUT"])
        @self.flask_app.route("/<actor_id>/properties/<path:name>", methods=["GET", "POST", "DELETE", "PUT"])
        def app_properties(actor_id, name=""):
            return self._handle_actor_request(actor_id, "properties", name=name)
            
        # Actor trust
        @self.flask_app.route("/<actor_id>/trust", methods=["GET", "POST", "DELETE", "PUT"])
        @self.flask_app.route("/<actor_id>/trust/<relationship>", methods=["GET", "POST", "DELETE", "PUT"])
        @self.flask_app.route("/<actor_id>/trust/<relationship>/<peerid>", methods=["GET", "POST", "DELETE", "PUT"])
        def app_trust(actor_id, relationship=None, peerid=None):
            return self._handle_actor_request(actor_id, "trust", relationship=relationship, peerid=peerid)
            
        # Actor subscriptions
        @self.flask_app.route("/<actor_id>/subscriptions", methods=["GET", "POST", "DELETE", "PUT"])
        @self.flask_app.route("/<actor_id>/subscriptions/<peerid>", methods=["GET", "POST", "DELETE", "PUT"])
        @self.flask_app.route("/<actor_id>/subscriptions/<peerid>/<subid>", methods=["GET", "POST", "DELETE", "PUT"])
        @self.flask_app.route("/<actor_id>/subscriptions/<peerid>/<subid>/<int:seqnr>", methods=["GET"])
        def app_subscriptions(actor_id, peerid=None, subid=None, seqnr=None):
            return self._handle_actor_request(actor_id, "subscriptions", peerid=peerid, subid=subid, seqnr=seqnr)
            
        # Actor resources
        @self.flask_app.route("/<actor_id>/resources", methods=["GET", "POST", "DELETE", "PUT"])
        @self.flask_app.route("/<actor_id>/resources/<path:name>", methods=["GET", "POST", "DELETE", "PUT"])
        def app_resources(actor_id, name=""):
            return self._handle_actor_request(actor_id, "resources", name=name)
            
        # Actor callbacks
        @self.flask_app.route("/<actor_id>/callbacks", methods=["GET", "POST", "DELETE", "PUT"])
        @self.flask_app.route("/<actor_id>/callbacks/<path:name>", methods=["GET", "POST", "DELETE", "PUT"])
        def app_callbacks(actor_id, name=""):
            return self._handle_actor_request(actor_id, "callbacks", name=name)
            
        # Actor devtest
        @self.flask_app.route("/<actor_id>/devtest", methods=["GET", "POST", "DELETE", "PUT"])
        @self.flask_app.route("/<actor_id>/devtest/<path:path>", methods=["GET", "POST", "DELETE", "PUT"])
        def app_devtest(actor_id, path=""):
            return self._handle_actor_request(actor_id, "devtest", path=path)
            
        # Actor methods
        @self.flask_app.route("/<actor_id>/methods", methods=["GET", "POST", "DELETE", "PUT"])
        @self.flask_app.route("/<actor_id>/methods/<path:name>", methods=["GET", "POST", "DELETE", "PUT"])
        def app_methods(actor_id, name=""):
            return self._handle_actor_request(actor_id, "methods", name=name)
            
        # Actor actions
        @self.flask_app.route("/<actor_id>/actions", methods=["GET", "POST", "DELETE", "PUT"])
        @self.flask_app.route("/<actor_id>/actions/<path:name>", methods=["GET", "POST", "DELETE", "PUT"])
        def app_actions(actor_id, name=""):
            return self._handle_actor_request(actor_id, "actions", name=name)
            
    def _normalize_request(self) -> Dict[str, Any]:
        """Convert Flask request to ActingWeb format."""
        cookies = {}
        raw_cookies = request.headers.get("Cookie")
        if raw_cookies:
            for cookie in raw_cookies.split("; "):
                if "=" in cookie:
                    name, value = cookie.split("=", 1)
                    cookies[name] = value
                    
        headers = {}
        for k, v in request.headers.items():
            headers[k] = v
            
        params = {}
        for k, v in request.values.items():
            params[k] = v
            
        return {
            "method": request.method,
            "path": request.path,
            "data": request.data,
            "headers": headers,
            "cookies": cookies,
            "values": params,
            "url": request.url,
        }
        
    def _create_flask_response(self, webobj: AWWebObj):
        """Convert ActingWeb response to Flask response."""
        if webobj.response.redirect:
            response = redirect(webobj.response.redirect, code=302)
        else:
            response = Response(
                response=webobj.response.body,
                status=webobj.response.status_message,
                headers=webobj.response.headers,
            )
            
        response.status_code = webobj.response.status_code
        
        # Set cookies
        for cookie in webobj.response.cookies:
            response.set_cookie(
                cookie["name"], 
                cookie["value"], 
                max_age=cookie.get("max_age"),
                secure=cookie.get("secure", False)
            )
            
        return response
        
    def _handle_factory_request(self):
        """Handle factory requests (actor creation)."""
        req_data = self._normalize_request()
        webobj = AWWebObj(
            url=req_data["url"],
            params=req_data["values"],
            body=req_data["data"],
            headers=req_data["headers"],
            cookies=req_data["cookies"]
        )
        
        handler = factory.RootFactoryHandler(webobj, self.aw_app.get_config(), hooks=self.aw_app.hooks)
        
        try:
            method_name = request.method.lower()
            handler_method = getattr(handler, method_name, None)
            if handler_method and callable(handler_method):
                handler_method()
            else:
                return Response(status=405)
        except Exception as e:
            logging.error(f"Error in factory handler: {e}")
            return Response(status=500)
            
        # Handle template rendering for factory
        if request.method == "GET" and webobj.response.status_code == 200:
            return Response(render_template("aw-root-factory.html", **webobj.response.template_values))
        elif request.method == "POST":
            # Only render templates for form submissions, not JSON requests
            is_json_request = request.content_type and "application/json" in request.content_type
            if not is_json_request and webobj.response.status_code in [200, 201]:
                return Response(render_template("aw-root-created.html", **webobj.response.template_values))
            elif not is_json_request and webobj.response.status_code == 400:
                return Response(render_template("aw-root-failed.html", **webobj.response.template_values))
                
        return self._create_flask_response(webobj)
        
    def _handle_oauth_callback(self):
        """Handle OAuth callback."""
        req_data = self._normalize_request()
        webobj = AWWebObj(
            url=req_data["url"],
            params=req_data["values"],
            body=req_data["data"],
            headers=req_data["headers"],
            cookies=req_data["cookies"]
        )
        
        handler = callback_oauth.CallbackOauthHandler(webobj, self.aw_app.get_config(), hooks=self.aw_app.hooks)
        handler.get()
        
        return self._create_flask_response(webobj)
        
    def _handle_bot_request(self):
        """Handle bot requests."""
        req_data = self._normalize_request()
        webobj = AWWebObj(
            url=req_data["url"],
            params=req_data["values"],
            body=req_data["data"],
            headers=req_data["headers"],
            cookies=req_data["cookies"]
        )
        
        handler = bot.BotHandler(webobj=webobj, config=self.aw_app.get_config(), hooks=self.aw_app.hooks)
        handler.post(path="/bot")
        
        return self._create_flask_response(webobj)
        
    def _handle_actor_request(self, actor_id: str, endpoint: str, **kwargs):
        """Handle actor-specific requests."""
        req_data = self._normalize_request()
        webobj = AWWebObj(
            url=req_data["url"],
            params=req_data["values"],
            body=req_data["data"],
            headers=req_data["headers"],
            cookies=req_data["cookies"]
        )
        
        # Get appropriate handler
        handler = self._get_handler(endpoint, webobj, actor_id, **kwargs)
        if not handler:
            return Response(status=404)
            
        # Execute handler method
        try:
            method_name = request.method.lower()
            handler_method = getattr(handler, method_name, None)
            if handler_method and callable(handler_method):
                # Build positional arguments based on endpoint and kwargs
                args = [actor_id]
                if endpoint == "meta":
                    # MetaHandler.get(actor_id, path) - path defaults to "" if not provided
                    args.append(kwargs.get("path", ""))
                elif endpoint == "trust":
                    if kwargs.get("relationship"):
                        args.append(kwargs["relationship"])
                    if kwargs.get("peerid"):
                        args.append(kwargs["peerid"])
                elif endpoint == "subscriptions":
                    # Different subscription handlers:
                    # SubscriptionRootHandler.get(actor_id)
                    # SubscriptionRelationshipHandler.get(actor_id, peerid)
                    # SubscriptionHandler.get(actor_id, peerid, subid)
                    # SubscriptionDiffHandler.get(actor_id, peerid, subid, seqnr)
                    if kwargs.get("peerid"):
                        args.append(kwargs["peerid"])
                    if kwargs.get("subid"):
                        args.append(kwargs["subid"])
                    if kwargs.get("seqnr"):
                        args.append(kwargs["seqnr"])
                elif endpoint == "www":
                    # WwwHandler.get(actor_id, path) - path defaults to "" if not provided
                    args.append(kwargs.get("path", ""))
                elif endpoint == "properties":
                    # PropertiesHandler.get(actor_id, name) - name defaults to "" if not provided
                    args.append(kwargs.get("name", ""))
                elif endpoint == "callbacks":
                    # CallbacksHandler.get(actor_id, name) - name defaults to "" if not provided
                    args.append(kwargs.get("name", ""))
                elif endpoint == "resources":
                    # ResourcesHandler.get(actor_id, name) - name defaults to "" if not provided
                    args.append(kwargs.get("name", ""))
                elif endpoint == "devtest":
                    # DevtestHandler.get(actor_id, path) - path defaults to "" if not provided
                    args.append(kwargs.get("path", ""))
                elif endpoint == "methods":
                    # MethodsHandler.get(actor_id, name) - name defaults to "" if not provided
                    args.append(kwargs.get("name", ""))
                elif endpoint == "actions":
                    # ActionsHandler.get(actor_id, name) - name defaults to "" if not provided
                    args.append(kwargs.get("name", ""))
                
                handler_method(*args)
            else:
                return Response(status=405)
        except Exception as e:
            logging.error(f"Error in {endpoint} handler: {e}")
            return Response(status=500)
            
        # Special handling for www endpoint templates
        if endpoint == "www" and request.method == "GET" and webobj.response.status_code == 200:
            path = kwargs.get("path", "")
            if not path:
                return Response(render_template("aw-actor-www-root.html", **webobj.response.template_values))
            elif path == "init":
                return Response(render_template("aw-actor-www-init.html", **webobj.response.template_values))
            elif path == "properties":
                return Response(render_template("aw-actor-www-properties.html", **webobj.response.template_values))
            elif path == "property":
                return Response(render_template("aw-actor-www-property.html", **webobj.response.template_values))
            elif path == "trust":
                return Response(render_template("aw-actor-www-trust.html", **webobj.response.template_values))
                
        return self._create_flask_response(webobj)
        
    def _get_handler(self, endpoint: str, webobj: AWWebObj, actor_id: str, **kwargs) -> Optional[Any]:  # pylint: disable=unused-argument
        """Get the appropriate handler for an endpoint."""
        config = self.aw_app.get_config()
        
        handlers = {
            "root": lambda: root.RootHandler(webobj, config, hooks=self.aw_app.hooks),
            "meta": lambda: meta.MetaHandler(webobj, config, hooks=self.aw_app.hooks),
            "oauth": lambda: oauth.OauthHandler(webobj, config, hooks=self.aw_app.hooks),
            "www": lambda: www.WwwHandler(webobj, config, hooks=self.aw_app.hooks),
            "properties": lambda: properties.PropertiesHandler(webobj, config, hooks=self.aw_app.hooks),
            "resources": lambda: resources.ResourcesHandler(webobj, config, hooks=self.aw_app.hooks),
            "callbacks": lambda: callbacks.CallbacksHandler(webobj, config, hooks=self.aw_app.hooks),
            "devtest": lambda: devtest.DevtestHandler(webobj, config, hooks=self.aw_app.hooks),
            "methods": lambda: methods.MethodsHandler(webobj, config, hooks=self.aw_app.hooks),
            "actions": lambda: actions.ActionsHandler(webobj, config, hooks=self.aw_app.hooks),
        }
        
        # Special handling for trust endpoint
        if endpoint == "trust":
            path_parts = [p for p in [kwargs.get("relationship"), kwargs.get("peerid")] if p]
            if len(path_parts) == 0:
                return trust.TrustHandler(webobj, config, hooks=self.aw_app.hooks)
            elif len(path_parts) == 1:
                return trust.TrustRelationshipHandler(webobj, config, hooks=self.aw_app.hooks)
            else:
                return trust.TrustPeerHandler(webobj, config, hooks=self.aw_app.hooks)
                
        # Special handling for subscriptions endpoint
        if endpoint == "subscriptions":
            path_parts = [p for p in [kwargs.get("peerid"), kwargs.get("subid")] if p]
            seqnr = kwargs.get("seqnr")
            
            if len(path_parts) == 0:
                return subscription.SubscriptionRootHandler(webobj, config, hooks=self.aw_app.hooks)
            elif len(path_parts) == 1:
                return subscription.SubscriptionRelationshipHandler(webobj, config, hooks=self.aw_app.hooks)
            elif len(path_parts) == 2 and seqnr is None:
                return subscription.SubscriptionHandler(webobj, config, hooks=self.aw_app.hooks)
            else:
                return subscription.SubscriptionDiffHandler(webobj, config, hooks=self.aw_app.hooks)
                
        if endpoint in handlers:
            return handlers[endpoint]()
            
        return None