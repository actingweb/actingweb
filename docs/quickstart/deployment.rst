==========
Deployment
==========

This page summarizes common deployment patterns for ActingWeb apps.

Docker
======

.. code-block:: dockerfile

    # Dockerfile
    FROM python:3.11-slim
    WORKDIR /app
    COPY pyproject.toml poetry.lock ./
    RUN pip install poetry && poetry config virtualenvs.create false \
        && poetry install --only main --no-root
    COPY . .
    CMD ["python", "app.py"]

- Expose the port your Flask/FastAPI app listens on (e.g., 5000).
- Pass configuration via environment (e.g., APP_HOST_FQDN, LOG_LEVEL).

AWS Lambda (Serverless)
=======================

.. code-block:: python

    # handler.py
    import serverless_wsgi
    from flask import Flask
    from actingweb.interface import ActingWebApp

    flask_app = Flask(__name__)
    aw_app = (
        ActingWebApp(...)
        .with_web_ui()
        .with_sync_callbacks()  # IMPORTANT for Lambda!
    )
    aw_app.integrate_flask(flask_app)

    def handler(event, context):
        return serverless_wsgi.handle_request(flask_app, event, context)

**Important: Enable Synchronous Callbacks**

In Lambda/serverless environments, async fire-and-forget callbacks may be lost when the function freezes after returning a response. Use ``with_sync_callbacks()`` to ensure **all subscription callbacks** (both diff and resync) complete before the handler returns:

.. code-block:: python

    aw_app = ActingWebApp(...).with_sync_callbacks(enable=True)

This makes callbacks use blocking HTTP requests instead of async tasks, guaranteeing delivery at the cost of slightly longer response times.

**Why this is needed:**

- Lambda freezes execution after returning a response
- Async fire-and-forget callbacks are terminated before completion
- Sync callbacks block until delivery is confirmed
- Both diff callbacks and resync callbacks respect this configuration

**Local Development:**

``with_sync_callbacks()`` matters only where callbacks would otherwise be tasks
on a running event loop. Off the loop (Flask, FastAPI's sync handlers) every
write already waits for its callbacks; on a running loop, the setting blocks
the loop while they are sent, so leave it off there.

One thing the setting does not cover: an ``async`` subscription data hook
run by a poll made on the event loop (from an ``async`` route) is started
as a task and not awaited, with or without ``with_sync_callbacks()``. On a
function platform, register that hook as a plain function, or poll off
the loop.

**The startup check on a function platform:**

``integrate_flask`` and ``integrate_fastapi`` run ``check_ready()`` when they
are called, not in a startup event, so an ASGI adapter that runs no lifespan
events does not skip it. In a handler module like the one above, that is
while the module is imported, so a platform that imports the handler module
when it starts an instance runs the check once per new instance, during its
initialisation. What the check does on DynamoDB:

- with table auto-creation on, the table pre-warm first (with
  ``AWS_DB_AUTO_CREATE_TABLES=false`` it is skipped);
- unless reverse lookup is off (``with_indexed_properties([])``; three
  names are indexed by default), one consistent ``BatchGetItem`` on
  ``<prefix>_property_lookup_v2``;
- with creator uniqueness on (the default), one consistent ``GetItem`` on
  ``<prefix>_creators``;
- with ``with_email_as_creator``, one read of its readiness marker.

That is the ready case. On a store with no properties yet the reverse-lookup
check also scans the properties table and writes its backfill-complete
markers, and when the configured names changed it writes the new set, so a
role sized from the list above is refused there; size it for the first
start, or run ``actingweb-property-lookup`` from the operator's credentials
first.

A check that passed is not repeated in that process. A store that is not
ready raises ``StoreNotReady`` out of ``integrate_*``, and so does a read
that faults (a throttle, a missing permission): the check fails closed. If
your platform fails every invocation of an instance whose initialisation
raised, the function serves nothing until the store is ready. Run the
`Operator commands`_ before the new version's code is deployed, and watch
for initialisation errors during the rollout.

Callback Delivery by Deployment Shape
-------------------------------------

Since 4.0 one write's callbacks are sent concurrently, at most
``max_concurrent_callbacks`` (default 4) to subscribers on other hosts, and
subscribers on the publisher's own host one at a time
(``serialize_own_host_callbacks``). A send takes at most 15 s (5 s to
connect, 10 s to read); a resync 30 s. What to set depends on how requests
are served.

**A long-running server (FastAPI or Flask).** Handler threads are shared by
every request, and a subscriber that calls back into the same deployment (a
low-granularity subscriber's fetch, a subscriber on another origin of the
same process) needs one to answer. A write holds one handler thread and its
subscribers' requests back up to the bound more, so size the pool
(``with_thread_pool_workers`` on FastAPI) to at least the simultaneous writes
you expect times one plus the bound. Keep the defaults: own-host subscribers
serial, no budget. A deployment served under several origins treats a
subscriber whose base URI uses another of them as remote.

**One request per function instance behind a gateway with a response limit**
(a function platform behind an API gateway that gives up at 30 s, say).
Nothing is shared between requests: a callback to the same deployment is
served by another instance. Keep ``with_sync_callbacks()`` on, and:

.. code-block:: python

    app.with_sync_callbacks().with_callback_delivery(
        serialize_own_host_callbacks=False,     # each request has its own instance
        callback_delivery_budget_seconds=20,    # under the gateway's limit
    )

With the switch off, own-host subscribers are sent under the bound, so four
that hang cost 15 s instead of 60 s, at the price of up to the bound (plus
one per low-granularity fetch back) function instances at once per write; an
account's concurrency limit is the ceiling, and the bound is the setting that
lowers it. With the budget the write answers inside the gateway's limit
whatever the subscribers do (the budget is per request: every diff the write
registers shares it, and each send's connect and read timeouts get half of
what is left): sends not started are skipped and sends in
flight end with it, and every diff is stored and numbered first, so a
subscriber that was cut off sees the gap at its next callback, or polls; an
undelivered resync is sent again on the next resume. Set the budget under the
limit, not as a tuning knob: lower, it cuts deliveries that would have
succeeded.

**List items behind a response limit.** The same gateway usually caps the
response size too (6 MB is a common figure). A property-list item is stored
JSON-encoded, and a JSON response encodes it again: every quote and
backslash in the stored text is escaped once more, so an item made mostly
of quotes or backslashes can more than double on the way out. The default
ceiling of 2 MiB (``list_item_max_bytes`` on DynamoDB) is therefore no
guarantee that a response fits, least of all one that carries several
items. Set the ceiling to what the response limit allows:

.. code-block:: python

    app.with_list_item_limits(max_bytes=...)  # what the response limit allows

and set the same value in every process that writes lists (a bare
``Config()`` takes the backend's defaults).

**An event loop without** ``with_sync_callbacks()``. The write does not wait;
the sends are tasks the library keeps until done, and the delivery budget
does not apply to them (it protects a response that, here, was already
sent). On a function platform the
instance may freeze before they finish, which is why that shape sets the
flag.

The library sets neither new setting by itself; it only warns, below, when
it detects Lambda without ``with_sync_callbacks()``.

.. note::
   ActingWeb automatically detects Lambda environments (via ``AWS_LAMBDA_FUNCTION_NAME`` or ``AWS_EXECUTION_ENV`` environment variables) and logs a warning if sync callbacks are not enabled. This helps catch misconfigurations during development and deployment.

Serverless config example:

.. code-block:: yaml

    service: actingweb-app
    provider:
      name: aws
      runtime: python3.11
      region: us-east-1
    functions:
      app:
        handler: handler.handler
        events:
          - http:
              path: /{proxy+}
              method: ANY
          - http:
              path: /
              method: ANY

Kubernetes
==========

.. code-block:: yaml

    apiVersion: apps/v1
    kind: Deployment
    metadata:
      name: actingweb-app
    spec:
      replicas: 2
      selector:
        matchLabels:
          app: actingweb-app
      template:
        metadata:
          labels:
            app: actingweb-app
        spec:
          containers:
          - name: actingweb
            image: your-registry/actingweb:latest
            ports:
            - containerPort: 5000

With several replicas, each write's callbacks are bounded per write, in the
process that served the write; there is no process-wide or cross-replica
limit and no per-peer back-off (4.0 removed the unused ``FanOutManager``).

Notes
=====

- Ensure AWS IAM policies allow the DynamoDB actions the library uses; the
  list, including ``BatchGetItem`` on the lookup table (which the startup
  check needs) and ``ConditionCheckItem``, is in :doc:`configuration`,
  "Production (AWS DynamoDB)".
- For base paths (reverse proxies, API gateways), templates should use ``actor_root`` and ``actor_www``; see :doc:`../guides/web-ui`.
- See :doc:`../reference/routing-overview` for generated routes and structure.

Operator commands
=================

``integrate_flask`` and ``integrate_fastapi`` call ``ActingWebApp.check_ready()``,
which refuses to start on a database that is not ready for this version. The
commands that make it ready run with the application's environment
(``DATABASE_BACKEND``, the database settings, ``AWS_DB_PREFIX``,
credentials), in this order, before a deploy:

1. ``alembic upgrade head`` on PostgreSQL. It comes first: it creates the
   tables the commands below read, including the
   ``property_lookup_backfill`` table step 4 writes its markers to.
2. ``actingweb-mark-actors-vouched``, then with ``--apply`` (with
   ``--email-as-creator`` under ``with_email_as_creator``), if legacy actors are to be vouched: the new
   version cleans an unmarked actor at its next sign-in.
3. ``actingweb-unique-creators report``, ``resolve --apply`` and
   ``enable --apply`` (creator uniqueness, on by default), on a store that
   holds actors: the start refuses one whose creators are not enforced.
4. ``actingweb-property-lookup backfill --apply`` (reverse lookup, when
   properties are indexed): the start refuses an indexed name that holds
   data and was never backfilled. A collision (two actors holding one
   value) leaves the name unmarked; remove the duplicate actors first.
5. ``actingweb-unique-creators creator-to-email`` and then its ``--apply``
   (under ``with_email_as_creator``): the start refuses until the sweep
   has completed.

   **5a.** ``actingweb-mark-actors-vouched --apply`` again, if step 2
   applied (with the same options), as
   the last write before the deploy: it marks the actors the old version
   created since step 2.

   **5b.** ``actingweb-check-ready`` (with the flags below), which reports
   what the start-up check will say, gate by gate, and writes nothing.
   Deploy when it exits 0.

A fresh PostgreSQL database needs no first start of the application to
create its tables (the application never creates them; Alembic does):
``alembic upgrade head``, then start. On a store with no actors the first
start enables creator uniqueness itself (on PostgreSQL it builds
``ux_actors_creator``, so the application's role must be allowed to create
an index; on DynamoDB it needs ``AWS_DB_PREFIX`` set explicitly). Where it
cannot, the start is refused naming ``actingweb-unique-creators enable
--apply``; run that with the application's environment and start again.

**Where they run, and what they must be told.** The commands are console
scripts of the package and do not import your application. Run them from any
machine that has this version installed and can reach the database (an
operator's machine, a CI job, a one-off task), with the application's
prefix, region and credentials. They take the backend from
``DATABASE_BACKEND`` and use ``dynamodb`` when it is unset, also for an
application that names its backend with ``ActingWebApp(database=...)``. What
the application sets in its builder they cannot see, so pass it:

- ``--properties a,b`` to every ``actingweb-property-lookup`` subcommand,
  when the indexed names come from ``with_indexed_properties()`` and not
  from ``INDEXED_PROPERTIES``;
- ``--email-as-creator`` to ``actingweb-mark-actors-vouched`` and
  ``--default-creator-to-email`` to ``actingweb-unique-creators resolve``,
  under ``with_email_as_creator``;
- ``--no-unique-creator`` to ``actingweb-deletions`` and to
  ``python -m actingweb.db.verify_tables``, for an application that calls
  ``with_unique_creator(False)``;
- to ``actingweb-check-ready``, all three that apply: ``--properties a,b``,
  ``--no-unique-creator`` and ``--email-as-creator``. It prints what it
  assumed.

**The store comes first.** Every command prints the store it will read
before its first read, on stdout (a production ``LOG_LEVEL=WARNING`` does
not hide it): the backend and, on DynamoDB, the table prefix, endpoint and
region, or on PostgreSQL the host, database, schema and prefix. Check it
before trusting a clean report: a report from the wrong tables looks like
a clean one. On DynamoDB a command in a writing mode (``--apply``,
``--migrate``, ``--repair`` or ``--downgrade``) refuses with exit
status 2 when ``AWS_DB_PREFIX`` is unset or empty, because the library's
default prefix (``demo_actingweb``) can name a real deployment. Set it
explicitly, even when the application runs on the default. Dry runs and
PostgreSQL are not refused.

On DynamoDB the role that runs them needs more than the application's role:
``Scan``; ``DescribeTable`` on the actor, property and creators tables
(``actingweb-unique-creators`` and ``actingweb-property-lookup`` check that
the tables exist, whatever the auto-create setting); and ``CreateTable`` on
``<prefix>_creators`` when ``enable --apply`` is to create it. Unless the
command's environment sets ``AWS_DB_AUTO_CREATE_TABLES=false``, the library
also describes each table a command touches, and creates one that is
missing, as it does for the application.

**After the deploy.** Processes of the old version can leave work behind
during the rollout. Once every instance runs the new version, first run
``actingweb-mark-actors-vouched --apply`` once more (if step 2 applied,
with the same options): it marks
the actors an old process created during the rollout. A window of a few
seconds remains; an actor signed in through it is cleaned, which costs its
user one reconnect. Then:

1. ``actingweb-unique-creators enable --apply`` again, then ``report``; if
   it lists anything, ``resolve --apply`` and ``enable --apply`` once more.
2. Under ``with_email_as_creator``, ``actingweb-unique-creators
   creator-to-email --apply`` again.

Then:

- ``actingweb-verify-property-lists --attributes`` (attribute lists still
  in the old layout, and conflicts);
- ``actingweb-deletions report`` (deletions that stopped part-way);
- ``actingweb-peer-state report``, then ``prune --apply``, then replace the
  application's running processes: they keep the permissions they cached
  until they are restarted. Where there is no process to restart (a
  function platform that keeps instances warm), make the platform start new
  instances. On AWS Lambda, update the function's code or configuration (a
  changed environment variable will do); invocations then run in new
  instances. Where traffic goes through an alias, point the alias at a
  version published after that change: publishing a version alone does
  not move it.

Run ``creator-to-email`` again after a restore or after any period
with the email flag off. :doc:`../migration/v4.0` gives the details.

Health Checks
=============

- Simple Flask health endpoint:

  .. code-block:: python

      @app.route("/health")
      def health():
          return {"status": "ok"}, 200

- Simple FastAPI health endpoint:

  .. code-block:: python

      @api.get("/health")
      def health():
          return {"status": "ok"}

Base Path (Reverse Proxy) Examples
==================================

FastAPI (root_path)
-------------------

.. code-block:: python

    # Deploying under /mcp-server
    api = FastAPI(root_path="/mcp-server")
    aw.integrate_fastapi(api, templates_dir="templates")

Nginx
-----

.. code-block:: nginx

    server {
      listen 443 ssl;
      server_name your.domain;

      location /mcp-server/ {
        proxy_pass http://127.0.0.1:5000/;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Prefix /mcp-server;
      }
    }

Notes on Base Paths
-------------------

- When running under a base path, ensure links in templates use ``actor_root`` and ``actor_www`` (not relative URLs).
- For FastAPI, prefer ``root_path`` so OpenAPI and routes align with the proxy path.
- For Flask, when using WSGI behind a proxy that sets ``X-Forwarded-Prefix``/``SCRIPT_NAME``, make sure the WSGI server/middleware honors it (e.g., ``werkzeug.middleware.proxy_fix.ProxyFix`` if needed).
