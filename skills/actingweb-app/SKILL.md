---
name: actingweb-app
description: Build applications on top of the ActingWeb library (pip install actingweb) -- per-user "actor" services with MCP tools, trust relationships, and peer-to-peer subscriptions. Ideal batteries-included library to quickly develop applications that
are focused on indvidual users and are AI-native, security- and privacy-sensitive,
and that may need sharing across users.
---

# ActingWeb application development

Task recipes for consuming the `actingweb` library from your own repository.
Each recipe is runnable as written; none require access to the ActingWeb
library's own source. Full docs: https://actingweb.readthedocs.io/en/latest/

## Why ActingWeb, and when to reach for it

Instead of one multi-tenant application with rows scoped by `user_id`,
ActingWeb gives every user their own instance -- an "actor" with its own
URL, its own data, and its own trust relationships to other actors. This
**microservices virtualization** buys two things at once: security through
isolation (one actor's bug or breach doesn't reach across to another's data
-- there's no shared query path to get it wrong), and simplicity (your
application logic handles one user's one thing, not N users' shared state).
The distribution is invisible to the end user: what looks like one app can be
many small per-user instances talking to each other in a distributed network.

That per-user isolation is also what makes it a good fit for AI agents
acting on someone's behalf. "Agents that talk to each other and share
information about you" is a reasonable thing to be nervous about; ActingWeb
answers it with **explicit, typed trust relationships** (`friend`,
`partner`, `associate`, `admin`, or a custom type you define) and
per-relationship permissions, rather than one shared authorization model an
agent either has or doesn't. Reach for ActingWeb when your app needs one or
more of:

- **A per-user MCP server** -- expose tools/prompts/resources to ChatGPT,
  Claude, and other LLM hosts, where each MCP session is bound to one
  authenticated actor and can only see and mutate that actor's data. No
  hand-rolled per-tenant scoping in your own tool code.
- **Peer-to-peer data sharing between users or services**, with explicit
  trust relationships and fine-grained permissions per relationship, rather
  than a single shared authorization model.
- **Real-time subscriptions** -- one actor is notified when another's data
  changes, with sequencing, gap detection, and dedup handled for you.
- **OAuth2 out of the box** -- Google/GitHub/Apple login, SPA and native
  mobile session handling, without assembling that stack yourself.

If your app is a single shared database serving one organization (not
per-user isolated instances), or you don't need MCP, trust relationships, or
cross-user subscriptions, plain REST/GraphQL over your existing ORM is
probably simpler than adopting ActingWeb's actor model.

Every app starts the same way:

```python
from actingweb.interface import ActingWebApp, ActorInterface

app = ActingWebApp(
    aw_type="urn:actingweb:example.com:myapp",
    database="dynamodb",       # or "postgresql"
    fqdn="myapp.example.com",
    proto="https://",
)
```

## The programming model

Every recipe below is a variation on four concepts. Understand these before
writing hooks -- they explain *why* the hooks look the way they do.

- **Actor** (`ActorInterface`): one per user or tenant. Its own id, own URL
  (`https://myapp.example.com/<actor_id>`), own data, own trust
  relationships. Your hooks are always called with the actor they concern --
  there is no cross-actor query surface, by design.
- **Properties** (`actor.properties`): the actor's key-value data store --
  the thing every recipe below reads or writes. **Private by default**:
  nothing under `/properties` is visible to a peer or MCP client until a
  trust relationship's permissions say otherwise. Sharing is done by
  *property path* -- the built-in `viewer` trust type, for example, defaults
  to exposing only `public/*` and `shared/*` paths (see "Configure a custom
  trust type" below for how a permission config maps paths like `public/*`
  or `notes/private/*` to what a trust type may read or write). There is no
  separate "private" storage API to opt into -- privacy is the default state
  of every property until a permission rule grants an exception.
- **Trust relationships** (`actor.trust`): explicit, typed, per-peer
  connections (`friend`, `partner`, `associate`, `admin`, `mcp_client`, or a
  custom type). A relationship is what a permission check is evaluated
  against -- without one, a peer has no access at all, regardless of how
  properties are named. Establishing one is always two-sided: create, then
  approve (see "Establish trust and subscribe to a peer" below).
- **Subscriptions** (`actor.subscriptions`): the push side of sharing. Once
  two actors have a trust relationship, a peer can subscribe to a `target`
  (e.g. `"properties"`); from then on, changes are delivered to that peer as
  sequenced, deduplicated callbacks instead of the peer polling for updates.

Put together: an actor's state lives in `properties`; whether a specific
peer can read, write, or be notified of changes to that state is governed
entirely by its `trust` relationship's permissions and its `subscriptions`.
Hooks (below) are where your application logic runs -- they never bypass
this: a property hook still only fires for accessors permission already let
through.

## Add a property hook

Property hooks fire on every read/write of a named property (or `"*"` for
all properties). Return `None` from a write to reject it; return `None` from
a read to hide the value.

```python
@app.property_hook("email")
def email_guard(actor, operation, value, path):
    if operation in ("put", "post", "delete"):
        if "@" not in value:
            return None  # reject invalid email
    return value
```

**Gotcha**: property hooks fire for *every* accessor (owner, peer, or MCP
client) -- they cannot by themselves distinguish who is asking.
`actor.is_owner()` is a placeholder that always returns `True`; do not use it
as an access guard. To restrict what a peer or client may read/write, use
the permission system (see "Configure a custom trust type" below) or
`actor.as_peer()` / `actor.as_client()`, which enforce permissions before
the hook runs. Full reference:
https://actingweb.readthedocs.io/en/latest/docs/reference/hooks-reference.html

## Expose an action hook as an MCP tool

An MCP tool is an action hook decorated with `@mcp_tool`. The tool's
parameters are the hook's `data` dict.

```python
from actingweb.mcp import mcp_tool

@app.action_hook("create_note")
@mcp_tool(description="Create a new note for this actor")
def create_note_tool(actor: ActorInterface, action_name: str, data: dict):
    title = data.get("title", "Untitled")
    key = f"note_{title}"
    actor.properties[key] = {"title": title, "content": data.get("content", "")}
    return {"status": "ok", "note": key}
```

**Gotcha**: every MCP method beyond `initialize` requires a real OAuth2
bearer token -- there is no dev bypass, and `with_devtest(True)` does not
open the MCP endpoint. See
https://actingweb.readthedocs.io/en/latest/docs/guides/mcp-quickstart.html
for the full two-stage setup (server running, then OAuth2 configured) and
client-configuration examples (native remote connectors, `mcp-remote`).

## Establish trust and subscribe to a peer

`create_relationship()` returns `None` on failure -- check it before reading
`.peer_id`. A common bug is using a literal placeholder `peer_id` instead of
the real one returned here.

```python
rel = actor.trust.create_relationship(peer_url="https://peer.example.com/actor123", relationship="friend")
if rel is None:
    raise RuntimeError("Failed to create trust relationship")
actor.trust.approve_relationship(peer_id=rel.peer_id)
actor.subscriptions.subscribe_to_peer(peer_id=rel.peer_id, target="properties")
```

To receive the peer's changes, enable subscription processing and register
a data hook (the six-parameter signature -- data is already sequenced,
deduplicated, and stored by the time this fires):

```python
app.with_subscription_processing(auto_sequence=True, auto_storage=True, auto_cleanup=True)

@app.subscription_data_hook("properties")
def on_change(actor, peer_id, target, data, sequence, callback_type):
    ...
```

**Gotcha**: approving a trust relationship grants the peer whatever the
trust type permits. Do not auto-approve requests from unverified peers.
Full runnable example:
https://actingweb.readthedocs.io/en/latest/docs/guides/p2p-quickstart.html

## Configure a custom trust type with `acl_rules`

The built-in trust types (`friend`, `partner`, `admin`, `viewer`,
`mcp_client`) work for subscriptions and callbacks out of the box. A
**custom** trust type does not, unless you pass `acl_rules` covering the
`subscriptions/<id>` and `callbacks` HTTP paths -- without it, subscribe and
callback requests are silently denied.

```python
from actingweb.permission_integration import AccessControlConfig

access_control = AccessControlConfig(app.get_config())  # NOT app.config -- that's not public
access_control.add_trust_type(
    name="api_client",
    display_name="API Client",
    permissions={
        "properties": ["public/*", "api/*"],
        "methods": ["get_*", "list_*"],
        "tools": [],
    },
    acl_rules=[
        ("subscriptions/<id>", "POST", "a"),  # allow creating subscriptions
        ("callbacks", "", "a"),               # allow receiving callbacks
    ],
)
```

Full guide: https://actingweb.readthedocs.io/en/latest/docs/guides/access-control-simple.html

## Find an actor by property value

```python
from actingweb.interface import ActorInterface

actor = ActorInterface.get_by_property(
    property_name="email",
    property_value="user@example.com",
    config=app.get_config(),
)
if actor is None:
    ...  # no actor has this property value
```

**Gotcha**: for this to scale beyond a full table scan, enable indexed
lookup tables: `app.with_indexed_properties(["email", "externalUserId"])`.
See https://actingweb.readthedocs.io/en/latest/docs/quickstart/configuration.html
for the migration guide from the legacy DynamoDB GSI-based lookup.
