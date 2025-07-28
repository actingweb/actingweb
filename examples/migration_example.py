"""
Example migration from old ActingWeb interface to new interface.

This example shows how to convert an existing ActingWeb application
to use the new fluent API and hook system.
"""

# OLD WAY (actingwebdemo/application.py style)
"""
import os
from flask import Flask, request, redirect, Response, render_template
from actingweb import config, aw_web_request, actor
import on_aw
from actingweb.handlers import ...

app = Flask(__name__)
OBJ_ON_AW = on_aw.OnAWDemo()

def get_config():
    # Long configuration setup...
    return config.Config(
        database="dynamodb",
        fqdn=os.getenv("APP_HOST_FQDN", "localhost"),
        proto=os.getenv("APP_HOST_PROTOCOL", "https://"),
        # ... many more config options
    )

@app.route("/", methods=["GET", "POST"])
def app_root():
    h = Handler(request)
    # Complex handler logic...
    return h.get_response()

# Many more manual route definitions...
"""

# NEW WAY (using new interface)
import os
from flask import Flask
from actingweb.interface import ActingWebApp, ActorInterface


# Create app with fluent configuration
app = ActingWebApp(
    aw_type="urn:actingweb:actingweb.org:actingwebdemo",
    database="dynamodb",
    fqdn=os.getenv("APP_HOST_FQDN", "localhost")
).with_oauth(
    client_id=os.getenv("APP_OAUTH_ID", ""),
    client_secret=os.getenv("APP_OAUTH_KEY", ""),
    scope=""
).with_web_ui().with_devtest().with_bot(
    token=os.getenv("APP_BOT_TOKEN", ""),
    email=os.getenv("APP_BOT_EMAIL", ""),
    secret=os.getenv("APP_BOT_SECRET", "")
)

# Add actor type
app.add_actor_type("myself", relationship="friend")


# Actor factory (replaces complex OnAWDemo class)
@app.actor_factory
def create_actor(creator: str, **kwargs) -> ActorInterface:
    """Create a new actor instance."""
    actor = ActorInterface.create(creator=creator, config=app.get_config())
    
    # Initialize actor properties
    actor.properties.email = creator
    actor.properties.created_at = str(datetime.now())
    
    return actor


# Property hooks (replaces get_properties, put_properties, etc.)
@app.property_hook("email")
def handle_email_property(actor: ActorInterface, operation: str, value: any, path: list) -> any:
    """Handle email property with access control."""
    if operation == "get":
        # Hide email from non-owners (similar to PROP_HIDE)
        return None if not actor.is_owner() else value
    elif operation == "put":
        # Validate and normalize email
        if isinstance(value, str) and "@" in value:
            return value.lower()
        return None  # Reject invalid emails
    elif operation == "post":
        # Same validation for POST
        if isinstance(value, str) and "@" in value:
            return value.lower()
        return None
    return value


@app.property_hook("settings")
def handle_settings_property(actor: ActorInterface, operation: str, value: any, path: list) -> any:
    """Handle settings property."""
    if operation == "put" or operation == "post":
        # Ensure settings is always a dict
        if isinstance(value, str):
            try:
                import json
                return json.loads(value)
            except:
                return None
        return value if isinstance(value, dict) else {}
    return value


# Callback hooks (replaces get_callbacks, post_callbacks, etc.)
@app.callback_hook("bot")
def handle_bot_callback(actor: ActorInterface, name: str, data: dict) -> bool:
    """Handle bot callbacks."""
    if data.get("method") == "POST":
        # Process bot request
        # This replaces the bot_post method in OnAWDemo
        return True
    return False


@app.callback_hook("status")
def handle_status_callback(actor: ActorInterface, name: str, data: dict) -> bool:
    """Handle status callbacks."""
    if data.get("method") == "GET":
        # Return actor status
        return {"status": "active", "last_seen": str(datetime.now())}
    return False


# Subscription hooks (replaces post_subscriptions)
@app.subscription_hook
def handle_subscription_callback(actor: ActorInterface, subscription: dict, peer_id: str, data: dict) -> bool:
    """Handle subscription callbacks."""
    print(f"Received subscription callback from {peer_id}: {data}")
    
    # Process the subscription data
    if subscription.get("target") == "properties":
        # Handle property changes from peer
        if "status" in data:
            actor.properties.peer_status = data["status"]
            
    return True


# Lifecycle hooks (replaces delete_actor, actions_on_oauth_success, etc.)
@app.lifecycle_hook("actor_deleted")
def on_actor_deleted(actor: ActorInterface, **kwargs):
    """Handle actor deletion."""
    print(f"Actor {actor.id} is being deleted")
    # Custom cleanup logic here


@app.lifecycle_hook("oauth_success")
def on_oauth_success(actor: ActorInterface, **kwargs):
    """Handle OAuth success."""
    token = kwargs.get("token")
    print(f"OAuth successful for actor {actor.id}")
    # Store OAuth token or perform other actions
    if token:
        actor.properties.oauth_token = token


# Flask integration (replaces all manual route definitions)
flask_app = Flask(__name__)
integration = app.integrate_flask(flask_app)


# Alternative: Run as standalone app
if __name__ == "__main__":
    # This replaces all the manual Flask setup
    app.run(host="0.0.0.0", port=5000, debug=True)


# COMPARISON OF KEY DIFFERENCES:

# OLD: Complex OnAWDemo class with many methods
"""
class OnAWDemo(on_aw.OnAWBase):
    def get_properties(self, path: list[str], data: dict) -> Optional[dict]:
        if not path:
            for k, v in data.copy().items():
                if k in PROP_HIDE:
                    del data[k]
        elif len(path) > 0 and path[0] in PROP_HIDE:
            return None
        return data
    
    def put_properties(self, path: list[str], old: dict, new: Union[dict, str]) -> Optional[dict | str]:
        if not path:
            return None
        elif len(path) > 0 and path[0] in PROP_PROTECT:
            return None
        # ... complex validation logic
        return new
"""

# NEW: Simple, focused hooks
"""
@app.property_hook("email")
def handle_email_property(actor, operation, value, path):
    if operation == "get":
        return None if not actor.is_owner() else value
    elif operation == "put":
        return value.lower() if "@" in value else None
    return value
"""

# OLD: Manual Flask route definitions
"""
@app.route("/<actor_id>/properties", methods=["GET", "POST", "DELETE", "PUT"])
@app.route("/<actor_id>/properties/<path:name>", methods=["GET", "POST", "DELETE", "PUT"])
def app_properties(actor_id, name=""):
    h = Handler(request)
    if not h.process(actor_id=actor_id, name=name):
        return Response(status=404)
    return h.get_response()
"""

# NEW: Automatic route generation
"""
integration = app.integrate_flask(flask_app)  # All routes created automatically
"""

# OLD: Complex configuration
"""
def get_config():
    oauth = {
        "client_id": os.getenv("APP_OAUTH_ID", ""),
        "client_secret": os.getenv("APP_OAUTH_KEY", ""),
        "redirect_uri": proto + myurl + "/oauth",
        # ... many more oauth settings
    }
    actors = {
        "myself": {
            "type": aw_type,
            "factory": proto + myurl + "/",
            "relationship": "friend",
        }
    }
    return config.Config(
        database="dynamodb",
        fqdn=myurl,
        proto=proto,
        # ... many more config options
    )
"""

# NEW: Fluent configuration
"""
app = ActingWebApp(
    aw_type="urn:actingweb:actingweb.org:actingwebdemo",
    database="dynamodb",
    fqdn=os.getenv("APP_HOST_FQDN", "localhost")
).with_oauth(
    client_id=os.getenv("APP_OAUTH_ID", ""),
    client_secret=os.getenv("APP_OAUTH_KEY", "")
).with_web_ui().with_devtest()
"""