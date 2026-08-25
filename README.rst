====================================================================
ActingWeb — a Python framework for AI-ready, per-user micro-services
====================================================================

.. image:: https://github.com/actingweb/actingweb/actions/workflows/tests.yml/badge.svg
   :target: https://github.com/actingweb/actingweb/actions/workflows/tests.yml
   :alt: Tests

.. image:: https://codecov.io/gh/actingweb/actingweb/branch/master/graph/badge.svg
   :target: https://codecov.io/gh/actingweb/actingweb
   :alt: Coverage

.. image:: https://img.shields.io/pypi/v/actingweb.svg
   :target: https://pypi.org/project/actingweb/
   :alt: PyPI

.. image:: https://readthedocs.org/projects/actingweb/badge/?version=latest
   :target: https://actingweb.readthedocs.io/en/latest/?badge=latest
   :alt: Documentation Status

**ActingWeb** is a Python framework for building secure, per-user services where
each user gets their own isolated instance — an *actor* — with a unique URL, its
own data, and its own set of relationships. It is the reference implementation of
the `ActingWeb REST protocol <https://actingweb.readthedocs.io/>`_ for
distributed micro-services, and it has grown into a full application framework for
shipping the same backend to three kinds of clients at once:

- **AI clients** over the `Model Context Protocol (MCP) <https://modelcontextprotocol.io>`_ —
  expose per-user tools, prompts, and resources to ChatGPT, Claude, and other LLM
  hosts, with OAuth2 authentication and per-user data isolation built in.
- **Web apps** — a built-in server-rendered Web UI for simple deployments, or a
  first-class **SPA mode** with a hardened token/refresh-token session flow for
  React/Vue/Svelte front-ends.
- **Native mobile apps** — iOS, Android, and Capacitor apps sign in with Apple,
  Google, or GitHub using native OAuth flows (RFC 8252 code exchange, RFC 7523
  JWT-bearer, and single-use deep-link tickets).

The same actor, the same properties, and the same trust and permission model back
all three. You write your business logic once as hooks and it is reachable from an
LLM tool call, a browser, a mobile app, or another ActingWeb service over REST.

Why ActingWeb?
--------------

ActingWeb is well suited to applications where **each individual user's data needs
a high degree of security and privacy** *and* a high degree of controlled
interaction with the outside world — personal AI assistants and memory services,
IoT "things" that act on a user's behalf, and bot-to-bot / service-to-service
data sharing where the user stays in control of who sees what.

Its defining constraint is that there is no way to query across users. Getting
``xyz``'s data is a request to ``/{xyz}/...``; there is no endpoint that returns
``xyz`` and ``yyz`` together. Sharing between users happens **only** through
explicit, per-user trust relationships and the standardized ActingWeb REST
protocol. This makes accidental data leakage structurally hard and makes granular,
revocable sharing the default rather than an afterthought.

Out of the box you get:

- A REST **actor** representing one user's thing, service, or agent.
- **Properties** — granular, per-actor key/value (and nested/list) storage exposed
  over REST with per-property access hooks.
- A **trust** system for per-user relationships with fine-grained permissions.
- A **subscription** system so one actor can subscribe to another actor's changes.
- **OAuth2 authentication** (Google, GitHub, Apple) for both humans and AI clients.
- **MCP**, **Web UI / SPA**, and **native-mobile** front-ends over one backend.
- Pluggable persistence: **DynamoDB** (serverless) or **PostgreSQL** (SQL).

Quick example
-------------

.. code-block:: python

    from actingweb.interface import ActingWebApp, ActorInterface
    from actingweb.mcp import mcp_tool

    app = (
        ActingWebApp(
            aw_type="urn:actingweb:example.com:myapp",
            database="dynamodb",        # or "postgresql"
            fqdn="myapp.example.com",
        )
        .with_oauth(client_id="...", client_secret="...")  # Google by default
        .with_web_ui(enable=True)       # server-rendered UI (False for pure SPA)
        .with_mcp(enable=True, server_name="myapp")         # AI clients over /mcp
    )

    # Lifecycle hook: initialize each new actor
    @app.lifecycle_hook("actor_created")
    def on_actor_created(actor: ActorInterface, **kwargs):
        actor.properties.email = actor.creator

    # Per-property access control
    @app.property_hook("email")
    def handle_email(actor, operation, value, path):
        if operation == "get":
            return None                 # hide email from external reads
        return value

    # An MCP tool — the same callable is reachable at GET/POST /<actor_id>/actions
    @app.action_hook("search")
    @mcp_tool(description="Search this actor's properties")
    def search(actor: ActorInterface, action_name: str, data: dict):
        q = str(data.get("query", "")).lower()
        return "\n".join(f"{k}: {v}" for k, v in actor.properties.items()
                         if q in k.lower() or q in str(v).lower())

    # Wire into your web framework of choice
    from fastapi import FastAPI
    api = FastAPI()
    app.integrate_fastapi(api)          # or app.integrate_flask(flask_app)

The fluent ``ActingWebApp`` builder auto-generates every protocol route
(``/properties``, ``/trust``, ``/subscriptions``, ``/callbacks``, ``/meta``,
``/actions``, ``/methods``, the OAuth2 endpoints, and ``/mcp``) and wires your
hooks in. You supply configuration and business logic; the framework supplies the
protocol, auth, storage, and client surfaces.

Installation
------------

ActingWeb requires **Python 3.11+**. Install from PyPI with the extras you need:

.. code-block:: bash

    # Minimal (no database backend or web framework)
    pip install actingweb

    # Pick a database backend
    pip install 'actingweb[dynamodb]'
    pip install 'actingweb[postgresql]'

    # Pick a web framework integration
    pip install 'actingweb[flask]'
    pip install 'actingweb[fastapi]'

    # Combine as needed
    pip install 'actingweb[fastapi,postgresql]'

    # Everything (both backends, both frameworks, MCP)
    pip install 'actingweb[all]'

Key capabilities
----------------

Fluent application builder
^^^^^^^^^^^^^^^^^^^^^^^^^^^

``ActingWebApp`` configures the whole application through chained ``with_*``
builders — OAuth providers, Web UI/SPA, MCP, database backend, indexed properties,
subscription processing, peer caching, and more — then integrates with Flask or
FastAPI in one call. Decorator-based hooks (``@app.lifecycle_hook``,
``@app.property_hook``, ``@app.action_hook``, ``@app.method_hook``,
``@app.subscription_hook``, ``@app.callback_hook``) replace the boilerplate
subclassing of older ActingWeb apps.

AI / MCP support
^^^^^^^^^^^^^^^^

``.with_mcp()`` exposes an authenticated MCP server at ``/mcp``. Action and method
hooks annotated with ``@mcp_tool`` / ``@mcp_prompt`` become per-user MCP **tools**
and **prompts**, with safety annotations and input schemas surfaced to the client.
Because each MCP session is bound to an authenticated actor, an LLM only ever sees
and mutates that one user's data. See
`docs/guides/mcp-applications <https://actingweb.readthedocs.io/en/latest/docs/guides/mcp-applications.html>`_
and
`docs/guides/mcp-quickstart <https://actingweb.readthedocs.io/en/latest/docs/guides/mcp-quickstart.html>`_.

Authentication: web, SPA, and native mobile
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

OAuth2 with Google, GitHub, and **Sign in with Apple** is built in, with email
validation, encrypted-state CSRF protection, and login-hint support. Beyond the
server-rendered login, ActingWeb ships a hardened session layer for rich clients:

- **SPA mode** — ``/oauth/spa/*`` endpoints issue short-lived access tokens and
  rotating refresh tokens with reuse detection, scoped chain revocation, bounded
  retention, and a self-contained expiry purge (no cron/Lambda required).
  ``with_spa_redirect_origins()`` / ``with_spa_cors_origins()`` support
  split-domain deployments.
- **Native mobile** — RFC 8252 authorization-code exchange, RFC 7523 JWT-bearer
  grants (``with_google_native()``, ``with_apple_sign_in()``), and single-use
  deep-link ``mobile_ticket`` grants (``with_github()`` and Apple-on-Android) so no
  IdP code or ActingWeb token ever rides a deep link.

See
`docs/guides/authentication <https://actingweb.readthedocs.io/en/latest/docs/guides/authentication.html>`_,
`docs/guides/spa-authentication <https://actingweb.readthedocs.io/en/latest/docs/guides/spa-authentication.html>`_,
and
`docs/guides/apple-sign-in <https://actingweb.readthedocs.io/en/latest/docs/guides/apple-sign-in.html>`_.

Trust, permissions, and subscriptions
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Per-user trust relationships carry fine-grained permissions that govern what a peer
(or an AI client) may read, write, or call. Subscriptions let one actor be notified
of another's changes, with sync or async callback delivery — use
``.with_sync_callbacks()`` on Lambda/serverless so callbacks complete before the
function freezes. Start with the
`peer-to-peer quickstart <https://actingweb.readthedocs.io/en/latest/docs/guides/p2p-quickstart.html>`_
for a runnable two-actor example, or see
`docs/guides/trust-relationships <https://actingweb.readthedocs.io/en/latest/docs/guides/trust-relationships.html>`_,
`docs/guides/access-control <https://actingweb.readthedocs.io/en/latest/docs/guides/access-control.html>`_,
and
`docs/guides/subscriptions <https://actingweb.readthedocs.io/en/latest/docs/guides/subscriptions.html>`_.

Pluggable persistence
^^^^^^^^^^^^^^^^^^^^^^

Two production-ready backends behind a common protocol:

- **DynamoDB** (default) — AWS-managed, auto-scaling, native TTL; ideal for
  serverless. Uses PynamoDB / boto3.
- **PostgreSQL** — PostgreSQL 12+ with Alembic migrations and connection pooling.
  Install with the ``postgresql`` extra.

Select with ``database="postgresql"`` or the ``DATABASE_BACKEND`` environment
variable. **Property reverse-lookup tables** (on by default; configure names
with ``with_indexed_properties``) enable find-actor-by-property-value with no
value-size limits and no plaintext values in the lookup table. See
`docs/reference/database-backends <https://actingweb.readthedocs.io/en/latest/docs/reference/database-backends.html>`_.

The ActingWeb model
-------------------

The ActingWeb micro-services model defines bot-to-bot and
service-to-service communication that allows extreme distribution of data and
functionality — well suited to holding small pieces of sensitive data on behalf of
a user or "thing" and sharing them in a granular, revocable way.

The micro-services model
^^^^^^^^^^^^^^^^^^^^^^^^^

The programming model focuses on representing exactly **one small set of
functionality for exactly one user or entity**. The only way to reach that
functionality is through the user's actor and its REST interface — for example
``GET https://mini-app-url/{actor_id}/properties/location``. There is no
cross-actor query, and the security model enforces access per actor: holding a
token for one actor grants nothing on another. Any cross-actor behavior (``xyz``
sharing location with ``yyz``) happens through the standardized ActingWeb REST
protocol, so **any** service that speaks the protocol can interoperate.

The REST protocol
^^^^^^^^^^^^^^^^^

Each actor exposes a set of standard endpoints under its root URL
``https://mini-app-url/{actor_id}``:

- ``/properties`` — attribute/value pairs (flat or nested JSON) to store the
  actor's data.
- ``/meta`` — a public structure so actors can discover each other's capabilities.
- ``/trust`` — request, approve, and manage trust relationships with other actors.
- ``/subscriptions`` — establish and manage subscriptions to another actor's paths
  once a trust relationship exists.
- ``/callbacks`` — verification during trust/subscription setup, subscription
  delivery, and a hook for 3rd-party webhooks.
- ``/resources`` — a skeleton for exposing arbitrary resources where
  ``/properties`` does not fit.
- ``/actions`` and ``/methods`` — application-defined operations (also surfaced as
  MCP tools/prompts).
- ``/oauth`` and ``/oauth/spa/*`` — OAuth2 flows tying an actor to an identity
  provider for web, SPA, and native-mobile clients.

The security model
^^^^^^^^^^^^^^^^^^

Trust is between **actors**, not applications. Each instance holding a user's
sensitive data must be connected by a trust relationship to another actor — which
need not be the same type of application. A location-sharing actor could, for
example, establish trust with an emergency-services actor so responders can always
locate the user, while every other relationship remains untouched and independently
revocable.

Trust is established either through an explicit OAuth flow (tying an actor to an
account at Google, GitHub, Apple, etc.) or through a trust-request flow where one
actor requests a relationship that another approves — interactively or
programmatically over REST. The modern OAuth2 layer adds email validation,
encrypted-state CSRF protection, provider auto-detection, and the SPA/native-mobile
session hardening described above.

See `https://actingweb.org/ <https://actingweb.org/>`_ for the model in depth.

Documentation
-------------

Comprehensive documentation is source-tracked in this repository's ``docs``
directory and published at
`https://actingweb.readthedocs.io/en/latest/ <https://actingweb.readthedocs.io/en/latest/>`_
— that's the canonical target below; Read the Docs also serves ``/en/stable/``
(the latest tagged release) and per-version URLs.

- **Quickstart & getting started**:
  `docs/quickstart/ <https://actingweb.readthedocs.io/en/latest/docs/quickstart/>`_
- **Peer-to-peer quickstart**:
  `docs/guides/p2p-quickstart <https://actingweb.readthedocs.io/en/latest/docs/guides/p2p-quickstart.html>`_
- **Configuration reference**:
  `docs/quickstart/configuration <https://actingweb.readthedocs.io/en/latest/docs/quickstart/configuration.html>`_
- **Authentication & OAuth2**:
  `docs/guides/authentication <https://actingweb.readthedocs.io/en/latest/docs/guides/authentication.html>`_
- **SPA authentication**:
  `docs/guides/spa-authentication <https://actingweb.readthedocs.io/en/latest/docs/guides/spa-authentication.html>`_
- **Sign in with Apple**:
  `docs/guides/apple-sign-in <https://actingweb.readthedocs.io/en/latest/docs/guides/apple-sign-in.html>`_
- **Building MCP applications**:
  `docs/guides/mcp-applications <https://actingweb.readthedocs.io/en/latest/docs/guides/mcp-applications.html>`_
- **Web UI & routing**:
  `docs/guides/web-ui <https://actingweb.readthedocs.io/en/latest/docs/guides/web-ui.html>`_,
  `docs/reference/routing-overview <https://actingweb.readthedocs.io/en/latest/docs/reference/routing-overview.html>`_
- **Hooks reference**:
  `docs/reference/hooks-reference <https://actingweb.readthedocs.io/en/latest/docs/reference/hooks-reference.html>`_
- **Trust, access control, subscriptions**:
  `docs/guides/ <https://actingweb.readthedocs.io/en/latest/docs/guides/>`_
- **Database backends**:
  `docs/reference/database-backends <https://actingweb.readthedocs.io/en/latest/docs/reference/database-backends.html>`_
- **SDK & developer API**:
  `docs/sdk/ <https://actingweb.readthedocs.io/en/latest/docs/sdk/>`_

Repository and links
---------------------

- **PyPI**: `https://pypi.org/project/actingweb/ <https://pypi.org/project/actingweb/>`_ (``pip install actingweb``)
- **Source**: `https://github.com/actingweb/actingweb <https://github.com/actingweb/actingweb>`_
- **Docs**: `https://actingweb.readthedocs.io/ <https://actingweb.readthedocs.io/>`_
- **Protocol & project home**: `https://actingweb.org/ <https://actingweb.org/>`_
- **Example application**: `examples/demo/ <https://github.com/actingweb/actingweb/tree/master/examples/demo>`_
  in this repository — a full reference app covering the core ActingWeb
  protocol (Web/SPA + OAuth2, not MCP — see ``examples/mcp_quickstart.py``
  for that), version-locked to the ActingWeb release you have checked out, tested by
  this repository's own CI. `actingwebdemo
  <https://github.com/actingweb/actingwebdemo>`_ is the deployment pipeline
  for ``demo.actingweb.io`` (AWS credentials, OAuth secret, Serverless
  config); the application code itself lives here, not there.
- **Agent Skill for building on ActingWeb**: task recipes (add a property
  hook, expose an MCP tool, establish trust and subscribe to a peer, and
  more) for AI coding agents working in a repository that consumes this
  library. ``git clone`` this repository and point your agent at
  ``skills/actingweb-app/``, or (if your agent supports the Agent Skills
  CLI) ``npx skills add actingweb/actingweb``.

Contributing
------------

See ``CONTRIBUTING.rst`` for local setup, the development workflow, testing, and
coding standards. In short:

.. code-block:: bash

    poetry install --extras all      # install with all optional backends/integrations
    poetry run pyright actingweb tests   # type checking — must be 0 errors
    poetry run ruff check actingweb tests # linting — must pass
    make test-all-parallel               # run the full test suite (900+ tests)

ActingWeb holds a zero-tolerance quality standard: type hints on all functions,
Pyright clean, Ruff clean, and 100% of tests passing before merge.

Ordinary PRs need no version bump — just a ``CHANGELOG.rst`` entry under
"Unreleased". A release PR carries the version bump and changelog rename itself;
once it is merged, maintainers tag the merge commit (``vX.Y.Z``), which triggers
CI to publish to PyPI. See ``CLAUDE.md`` and ``CHANGELOG.rst`` for the release
process and history.

License
-------

BSD. See ``LICENSE``.
</content>
</invoke>
