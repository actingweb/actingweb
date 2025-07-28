#!/usr/bin/env python3
"""
Simple example showing the new ActingWeb interface.

This demonstrates how to create a basic ActingWeb application
using the new fluent API and hook system.
"""

from datetime import datetime
from actingweb.interface import ActingWebApp, ActorInterface


# Create app with fluent configuration
app = ActingWebApp(
    aw_type="urn:actingweb:example.com:simple-demo",
    database="dynamodb",
    fqdn="localhost:5000"
).with_web_ui().with_devtest().with_unique_creator()


# Define actor factory
@app.actor_factory
def create_actor(creator: str, **kwargs) -> ActorInterface:
    """Create a new actor instance with default properties."""
    actor = ActorInterface.create(creator=creator, config=app.get_config())
    
    # Initialize actor properties
    actor.properties.email = creator
    actor.properties.created_at = str(datetime.now())
    actor.properties.status = "active"
    actor.properties.settings = {"theme": "light", "notifications": True}
    
    return actor


# Property hooks for access control and validation
@app.property_hook("email")
def handle_email_property(actor, operation, value, path):
    """Handle email property with validation and access control."""
    if operation == "get":
        # Allow access to email
        return value
    elif operation == "put":
        # Validate email format
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
def handle_settings_property(actor, operation, value, path):
    """Handle settings property ensuring it's always a dict."""
    if operation == "put" or operation == "post":
        if isinstance(value, str):
            try:
                import json
                return json.loads(value)
            except:
                return None
        return value if isinstance(value, dict) else {}
    return value


@app.property_hook("status")
def handle_status_property(actor, operation, value, path):
    """Handle status property with allowed values."""
    if operation == "put" or operation == "post":
        allowed_statuses = ["active", "inactive", "suspended"]
        if value in allowed_statuses:
            # Update last_modified when status changes
            actor.properties.last_modified = str(datetime.now())
            return value
        return None  # Reject invalid status
    return value


# Callback hooks for custom endpoints
@app.callback_hook("ping")
def handle_ping_callback(actor, name, data):
    """Handle ping callback to check actor status."""
    if data.get("method") == "GET":
        return {
            "status": "pong",
            "actor_id": actor.id,
            "timestamp": str(datetime.now())
        }
    return False


@app.callback_hook("stats")
def handle_stats_callback(actor, name, data):
    """Handle stats callback to return actor statistics."""
    if data.get("method") == "GET":
        return {
            "actor_id": actor.id,
            "creator": actor.creator,
            "trust_relationships": len(actor.trust.relationships),
            "subscriptions": len(actor.subscriptions.all_subscriptions),
            "properties": len(actor.properties.to_dict())
        }
    return False


# Subscription hooks
@app.subscription_hook
def handle_subscription_callback(actor, subscription, peer_id, data):
    """Handle subscription callbacks from other actors."""
    print(f"Received subscription callback from {peer_id}: {data}")
    
    # Process the subscription data
    if subscription.get("target") == "properties":
        # Handle property changes from peer
        if "status" in data:
            # Store peer status
            actor.properties[f"peer_{peer_id}_status"] = data["status"]
            
            # Notify our own subscribers about the change
            actor.subscriptions.notify_subscribers(
                target="peer_updates",
                data={"peer_id": peer_id, "status": data["status"]}
            )
    
    return True


# Lifecycle hooks
@app.lifecycle_hook("actor_created")
def on_actor_created(actor, **kwargs):
    """Handle actor creation."""
    print(f"New actor created: {actor.id} for {actor.creator}")
    
    # Set initial properties
    actor.properties.version = "1.0"
    actor.properties.created_by = "simple_example"


@app.lifecycle_hook("actor_deleted")
def on_actor_deleted(actor, **kwargs):
    """Handle actor deletion."""
    print(f"Actor {actor.id} is being deleted")
    
    # Could perform cleanup here
    # For example, notify external systems about the deletion


# Helper function to demonstrate actor usage
def demo_actor_operations():
    """Demonstrate various actor operations."""
    print("=== ActingWeb Simple Demo ===")
    
    # Create an actor
    config = app.get_config()
    actor = ActorInterface.create(creator="demo@example.com", config=config)
    print(f"Created actor: {actor}")
    
    # Set properties
    actor.properties.bio = "This is a demo actor"
    actor.properties.age = 25
    actor.properties.settings = {"theme": "dark", "lang": "en"}
    
    # Get properties
    print(f"Actor email: {actor.properties.email}")
    print(f"Actor settings: {actor.properties.settings}")
    print(f"Actor status: {actor.properties.status}")
    
    # Demonstrate property access
    print(f"All properties: {actor.properties.to_dict()}")
    
    # Clean up
    actor.delete()
    print("Actor deleted")


if __name__ == "__main__":
    # Run the demo
    demo_actor_operations()
    
    # Start the web server
    print("\nStarting ActingWeb server on http://localhost:5000")
    print("Try these endpoints:")
    print("- GET  /                    - Actor factory")
    print("- POST /                    - Create actor")
    print("- GET  /<actor_id>/www      - Actor web UI")
    print("- GET  /<actor_id>/ping     - Ping callback")
    print("- GET  /<actor_id>/stats    - Actor stats")
    print("- GET  /<actor_id>/properties - Actor properties")
    
    app.run(host="0.0.0.0", port=5000, debug=True)