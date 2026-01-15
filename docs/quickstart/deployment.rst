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

In Lambda/serverless environments, async fire-and-forget callbacks may be lost when the function freezes after returning a response. Use ``with_sync_callbacks()`` to ensure subscription callbacks complete before the handler returns:

.. code-block:: python

    aw_app = ActingWebApp(...).with_sync_callbacks(enable=True)

This makes callbacks use blocking HTTP requests instead of async tasks, guaranteeing delivery at the cost of slightly longer response times.

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

Notes
=====

- Ensure AWS IAM policies allow DynamoDB operations your app requires.
- For base paths (reverse proxies, API gateways), templates should use ``actor_root`` and ``actor_www``; see :doc:`www-handler-templates`.
- See :doc:`routing-overview` for generated routes and structure.

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
