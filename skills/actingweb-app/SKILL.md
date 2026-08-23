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
agent either has or doesn't. Actor-to-actor traffic -- establishing trust,
subscribing, delivering callbacks -- is not a proprietary wire format
either: it runs entirely over the **ActingWeb protocol**, a standardized
REST specification written in IETF Internet-Draft format and published
alongside this library's own docs. Two independently-built ActingWeb apps
interoperate peer-to-peer because they both implement the same documented
spec, not because they share code. Full text:
https://actingweb.readthedocs.io/en/latest/docs/protocol/actingweb-spec.html
Reach for ActingWeb when your app needs one or more of:

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

`database` (or the `DATABASE_BACKEND` environment variable, which takes
precedence) picks the storage backend. **DynamoDB** and **PostgreSQL** are
the two supported today -- both production-ready, not one favored over the
other. Every backend implements the same set of `typing.Protocol` interfaces
(`actingweb/db/protocols.py`), so hooks and application code never branch on
which one is active. Contributions adding another backend (MySQL, SQLite,
etc.) behind that same protocol set are welcome. Comparison and setup for
each: https://actingweb.readthedocs.io/en/latest/docs/reference/database-backends.html

## Running locally

```bash
pip install 'actingweb[fastapi,dynamodb]'   # or [flask,...] / [...,postgresql]

docker run -p 8000:8000 amazon/dynamodb-local
export AWS_ACCESS_KEY_ID=local AWS_SECRET_ACCESS_KEY=local AWS_DEFAULT_REGION=us-east-1
export AWS_DB_HOST=http://localhost:8000
```

`.with_devtest(True)` turns on a `/<actor_id>/devtest` helper endpoint for
poking at an actor during manual testing -- it still requires
authentication, it is not an auth bypass, and MCP's OAuth2 requirement in
particular is unaffected by it (see the MCP tool recipe's Gotcha below).
**Must be `False` in production.** Full setup for both backends (Docker
commands, required env vars, PostgreSQL + Alembic migrations):
https://actingweb.readthedocs.io/en/latest/docs/quickstart/local-dev-setup.html

## The programming model

Every recipe below is a variation on five concepts. Understand these before
writing hooks -- they explain *why* the hooks look the way they do.

- **Actor** (`ActorInterface`): one per user or tenant. Its own id, own URL
  (`https://myapp.example.com/<actor_id>`), own data, own trust
  relationships. Your hooks are always called with the actor they concern --
  there is no cross-actor query surface, by design.
- **Properties** (`actor.properties`): the actor's key-value data store for
  data that is, or might become, shareable. Exposed at `/properties` over
  REST and readable/writable there by anyone with a trust relationship whose
  permissions allow it. **Private by default**: nothing is visible to a peer
  or MCP client until a trust relationship's permissions say otherwise.
  Sharing is done by *property path* -- the built-in `viewer` trust type,
  for example, defaults to exposing only `public/*` and `shared/*` paths
  (see "Configure a custom trust type" below for how a permission config
  maps a path like `public/*` to what a trust type may read or write).
- **Attributes** (`from actingweb import attribute`): a second, separate
  key-value store for data that is never part of the property model at
  all -- not exposed at `/properties`, not addressable by any trust-type
  permission pattern, never delivered by a subscription. Use it for secrets,
  service credentials, feature flags, locks, and other bookkeeping your own
  code manages and a peer or MCP client should never be able to reach
  through the actor's public surface, regardless of trust type:

  ```python
  from actingweb import attribute

  bucket = attribute.Attributes(actor_id=actor.id, bucket="service", config=app.get_config())
  bucket.set_attr(name="stripe_customer_id", data="cus_abc123")
  attr = bucket.get_attr(name="stripe_customer_id")  # {"data": "cus_abc123", "timestamp": ...}
  ```

  Full reference (bucket conventions, atomic `conditional_update_attr()`,
  cleanup on actor deletion):
  https://actingweb.readthedocs.io/en/latest/docs/sdk/attributes-buckets.html
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
  Only properties are subscribable -- attributes never generate a
  subscription event.

Put together: an actor's *shareable* state lives in `properties`, and
whether a specific peer can read, write, or be notified of changes to it is
governed entirely by its `trust` relationship's permissions and its
`subscriptions`. An actor's *own* bookkeeping -- data no peer or client
should ever reach, no matter how trust is configured -- lives in
`attributes` instead. Hooks (below) are where your application logic runs
-- they never bypass this: a property hook still only fires for accessors
permission already let through.

## Two frontend models: templates vs. SPA

`with_web_ui()` picks which one you get; the choice is app-wide, not
per-route.

- **Server-rendered templates** (`with_web_ui(True)`, the default): the
  library serves `/<actor_id>/www` -- a dashboard, property editor, and
  trust-relationship manager -- rendered from Jinja2 templates it ships
  with fixed names (`aw-actor-www-root.html`, `aw-actor-www-properties.html`,
  `aw-actor-www-trust.html`, etc.). Session-cookie authentication and
  browser redirects (unauthenticated -> `/login`, authenticated -> `/www`)
  are handled automatically. Works out of the box with zero frontend code,
  but you are not limited to its default look: pass your own
  `templates_dir` to `integrate_fastapi(api, templates_dir="templates")`
  (or the Flask equivalent) and drop a same-named file in it --
  `templates/aw-actor-www-properties.html` -- to replace that page's
  markup entirely; your directory is searched before the library's
  defaults, per template, so you only need to override the pages you want
  to change. Full customization guide:
  https://actingweb.readthedocs.io/en/latest/docs/guides/web-ui.html#template-customization
- **SPA mode** (`with_web_ui(False)`): the library serves no UI at all --
  you own the frontend completely. You provide `/login` and
  `/<actor_id>/app` yourself (an SPA shell your JavaScript drives), and
  ActingWeb still handles the redirect logic (unauthenticated -> `/login`,
  authenticated -> `/<actor_id>/app`), pointing at your routes instead of
  its own. Auth is OAuth2 bearer tokens obtained via `/oauth/spa/authorize`
  + `/oauth/spa/token`, not cookies. Full guide, including the token
  refresh flow:
  https://actingweb.readthedocs.io/en/latest/docs/guides/spa-authentication.html

Whichever mode you pick, an authenticated SPA calls two *different* kinds
of endpoint on the same running server, both with the same bearer token:

1. **The ActingWeb spec REST API** -- `/<actor_id>/properties`,
   `/<actor_id>/trust`, `/<actor_id>/subscriptions`, etc. Defined by the
   protocol itself (see "Why ActingWeb" above) and handled entirely by the
   library; nothing to register.
2. **Your own private API** -- routes you add directly on the same
   FastAPI/Flask app object ActingWeb integrates into
   (`aw_app.integrate_fastapi(api)`), for anything the spec doesn't cover
   (business logic, third-party webhooks, app-specific queries). Namespace
   them distinctly from the spec paths (e.g. `/<actor_id>/api/...`) so
   they're never confused with protocol endpoints.

**Gotcha**: ActingWeb only protects the routes *it* registers. A private
route you add gets no authentication for free -- you must verify the caller
yourself, in every such route, with `actingweb.auth.check_and_verify_auth()`
(sync, e.g. Flask) or `check_and_verify_auth_async()` (FastAPI) -- the same
mechanism the library's own handlers use, checking the identical bearer
token your SPA already holds. Skipping this on a custom route is a silent
security hole: the endpoint accepts any request, authenticated or not. Full
reference:
https://actingweb.readthedocs.io/en/latest/docs/guides/authentication.html#custom-route-authentication

## Actor lifecycle: create and delete

```python
actor = ActorInterface.create(
    creator="user@example.com", config=app.get_config(), hooks=app.hooks
)
```

**Gotcha**: pass `hooks=app.hooks` or the `actor_created` lifecycle hook
never fires -- the actor is still created, just silently without your
setup logic running. Creating an actor over REST via the factory endpoint
always runs it; this only matters for programmatic creation.

```python
actor.delete()
```

**Gotcha**: `actor.delete()` does **not** run the `actor_deleted` /
`actor_deleted_complete` lifecycle hooks -- only the HTTP
`DELETE /<actor_id>` path fires those. Deleting an actor programmatically
means your own code owns any cleanup those hooks would have done (e.g.
telling a third-party service to drop its record of this user). What *is*
automatic either way: all of the actor's properties, attributes, trust
relationships, and subscriptions are deleted with it -- nothing is left
behind for you to clean up in `actor.properties` or `attribute.Attributes`
buckets yourself.

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

**Gotcha**: `create_relationship()` only approves the relationship on the
side that calls it -- the peer's side is created unapproved, and
`subscribe_to_peer()` gets a `403` until *both* sides are approved. The
`approve_relationship()` call above only covers your own side. The peer's
own app has to approve too, typically from a
`@app.lifecycle_hook("trust_request_received")` handler on *their* app:

```python
@app.lifecycle_hook("trust_request_received")
def on_trust_request_received(actor, peer_id, **kwargs):
    actor.trust.approve_relationship(peer_id=peer_id)  # demo-only auto-approve
```

Do not auto-approve an unverified peer this way in a real application --
see the next Gotcha.

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

**Gotcha (Lambda/serverless)**: subscription callbacks are async
fire-and-forget by default, so on a platform that freezes the process after
the response returns, a callback can be silently lost mid-flight. Call
`app.with_sync_callbacks()` to make callback delivery blocking instead.

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

## See also

Not covered above as task recipes, but worth knowing exist:

- **Configuration reference** -- every `ActingWebApp` builder method and
  environment variable in one place:
  https://actingweb.readthedocs.io/en/latest/docs/quickstart/configuration.html
- **Third-party service integrations** (`app.add_service(...)`,
  `actor.services`) -- OAuth2-backed clients (Google, Stripe, etc.) managed
  per-actor the same way trust relationships are:
  https://actingweb.readthedocs.io/en/latest/docs/guides/service-integration.html
- **Logging and request correlation** -- structured logs with a request ID
  you can grep across an actor-to-actor call chain:
  https://actingweb.readthedocs.io/en/latest/docs/guides/logging-and-correlation.html
- **Troubleshooting** -- common errors and their fixes:
  https://actingweb.readthedocs.io/en/latest/docs/guides/troubleshooting.html
