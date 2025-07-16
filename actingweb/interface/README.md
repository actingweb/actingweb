# ActingWeb Modern Interface

This module provides a modern, developer-friendly interface for the ActingWeb library. It replaces the complex `OnAWBase` callback system with a clean, fluent API and decorator-based hooks.

## Key Features

- **Fluent Configuration API**: Chain configuration methods for easy setup
- **Decorator-Based Hooks**: Simple, focused functions for handling events
- **Automatic Route Generation**: Web framework integration with auto-generated routes
- **Intuitive Actor Interface**: Clean, object-oriented actor management
- **Type Safety**: Better type hints and IDE support
- **Backward Compatibility**: Works with existing ActingWeb applications

## Quick Start

### Basic Application

```python
from actingweb.interface import ActingWebApp, ActorInterface

# Create app with fluent configuration
app = ActingWebApp(
    aw_type="urn:actingweb:example.com:myapp",
    database="dynamodb",
    fqdn="myapp.example.com"
).with_oauth(
    client_id="your-client-id",
    client_secret="your-client-secret"
).with_web_ui().with_devtest()

# Define actor factory
@app.actor_factory
def create_actor(creator: str, **kwargs) -> ActorInterface:
    actor = ActorInterface.create(creator=creator, config=app.get_config())
    actor.properties.email = creator
    return actor

# Add hooks
@app.property_hook("email")
def handle_email(actor, operation, value, path):
    if operation == "get":
        return value if actor.is_owner() else None
    elif operation == "put":
        return value.lower() if "@" in value else None
    return value

# Run the application
app.run(port=5000)
```

### Flask Integration

```python
from flask import Flask
from actingweb.interface import ActingWebApp

# Create Flask app
flask_app = Flask(__name__)

# Create ActingWeb app
aw_app = ActingWebApp(
    aw_type="urn:actingweb:example.com:myapp",
    database="dynamodb"
).with_web_ui()

# Integrate with Flask (auto-generates all routes)
aw_app.integrate_flask(flask_app)

# Run Flask app
flask_app.run()
```

## Core Components

### ActingWebApp

The main application class that provides fluent configuration:

```python
app = ActingWebApp(
    aw_type="urn:actingweb:example.com:myapp",
    database="dynamodb",
    fqdn="myapp.example.com"
)

# Configuration methods
app.with_oauth(client_id="...", client_secret="...")
app.with_web_ui(enable=True)
app.with_devtest(enable=True)
app.with_bot(token="...", email="...")
app.with_unique_creator(enable=True)
app.add_actor_type("myself", relationship="friend")
```

### ActorInterface

Clean interface for working with actors:

```python
# Create actor
actor = ActorInterface.create(creator="user@example.com", config=config)

# Access properties
actor.properties.email = "user@example.com"
actor.properties["settings"] = {"theme": "dark"}

# Manage trust relationships
peer = actor.trust.create_relationship(
    peer_url="https://peer.example.com/actor123",
    relationship="friend"
)

# Handle subscriptions
actor.subscriptions.subscribe_to_peer(
    peer_id="peer123",
    target="properties"
)

# Notify subscribers
actor.subscriptions.notify_subscribers(
    target="properties",
    data={"status": "active"}
)
```

### PropertyStore

Dictionary-like interface for actor properties:

```python
# Set properties
actor.properties.email = "user@example.com"
actor.properties["config"] = {"theme": "dark"}

# Get properties
email = actor.properties.email
config = actor.properties.get("config", {})

# Check existence
if "email" in actor.properties:
    print("Email is set")

# Iterate
for key, value in actor.properties.items():
    print(f"{key}: {value}")
```

### TrustManager

Simplified trust relationship management:

```python
# Create relationship
relationship = actor.trust.create_relationship(
    peer_url="https://peer.example.com/actor123",
    relationship="friend"
)

# List relationships
for rel in actor.trust.relationships:
    print(f"Trust with {rel.peer_id}: {rel.relationship}")

# Find specific relationship
friend = actor.trust.find_relationship(relationship="friend")

# Approve relationship
actor.trust.approve_relationship(peer_id="peer123")

# Check if peer is trusted
if actor.trust.is_trusted_peer("peer123"):
    print("Peer is trusted")
```

### SubscriptionManager

Easy subscription handling:

```python
# Subscribe to peer
subscription_url = actor.subscriptions.subscribe_to_peer(
    peer_id="peer123",
    target="properties",
    granularity="high"
)

# List subscriptions
for sub in actor.subscriptions.all_subscriptions:
    print(f"Subscription to {sub.peer_id}: {sub.target}")

# Notify subscribers
actor.subscriptions.notify_subscribers(
    target="properties",
    data={"status": "active"}
)

# Unsubscribe
actor.subscriptions.unsubscribe(
    peer_id="peer123",
    subscription_id="sub123"
)
```

## Hook System

### Property Hooks

Handle property operations:

```python
@app.property_hook("email")
def handle_email_property(actor, operation, value, path):
    if operation == "get":
        return value if actor.is_owner() else None
    elif operation == "put":
        return value.lower() if "@" in value else None
    return value

# Hook specific operations
@app.property_hook("settings", operations=["put", "post"])
def handle_settings_property(actor, operation, value, path):
    if isinstance(value, str):
        import json
        try:
            return json.loads(value)
        except:
            return None
    return value
```

### Callback Hooks

Handle callback requests:

```python
@app.callback_hook("bot")
def handle_bot_callback(actor, name, data):
    if data.get("method") == "POST":
        # Process bot request
        return True
    return False

@app.callback_hook("status")
def handle_status_callback(actor, name, data):
    return {"status": "active", "actor_id": actor.id}
```

### Subscription Hooks

Handle subscription callbacks:

```python
@app.subscription_hook
def handle_subscription_callback(actor, subscription, peer_id, data):
    print(f"Received data from {peer_id}: {data}")
    
    # Process the subscription data
    if subscription.get("target") == "properties":
        # Handle property changes from peer
        pass
        
    return True
```

### Lifecycle Hooks

Handle actor lifecycle events:

```python
@app.lifecycle_hook("actor_created")
def on_actor_created(actor, **kwargs):
    # Initialize new actor
    actor.properties.created_at = str(datetime.now())

@app.lifecycle_hook("actor_deleted")
def on_actor_deleted(actor, **kwargs):
    # Cleanup before deletion
    print(f"Actor {actor.id} is being deleted")

@app.lifecycle_hook("oauth_success")
def on_oauth_success(actor, **kwargs):
    token = kwargs.get("token")
    if token:
        actor.properties.oauth_token = token
```

## Migration from Old Interface

### Before (OnAWBase)

```python
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
        return new
```

### After (New Interface)

```python
@app.property_hook("email")
def handle_email_property(actor, operation, value, path):
    if operation == "get":
        return None if not actor.is_owner() else value
    elif operation == "put":
        return value.lower() if "@" in value else None
    return value
```

## Benefits

1. **Reduced Boilerplate**: No more manual route definitions or complex handler setup
2. **Better Organization**: Hooks are focused on specific functionality
3. **Improved Readability**: Code is easier to understand and maintain
4. **Type Safety**: Better IDE support and error detection
5. **Flexibility**: Easy to add new hooks without modifying core classes
6. **Testing**: Hooks can be tested independently

## Backward Compatibility

The new interface is fully backward compatible with existing ActingWeb applications. You can:

1. Continue using the old `OnAWBase` system
2. Gradually migrate to the new interface
3. Mix both approaches during transition

The new interface uses a bridge pattern to translate between the hook system and the existing
`OnAWBase` callbacks, ensuring seamless operation.
