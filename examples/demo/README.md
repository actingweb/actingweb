# ActingWeb demo application

A complete Flask application built on this library's modern fluent interface
(`ActingWebApp`) and decorator-based hooks. It demonstrates:

- OAuth2 login (Google or GitHub) with one actor per user
- MCP (Model Context Protocol) support, so an AI assistant can be configured
  as a trusted client of a user's actor
- The full hook system: protocol hooks (subscription, trust, lifecycle) in
  `shared_hooks/protocol/`, and app-specific hooks (methods, actions,
  callbacks, property access control, and a web UI) in `shared_hooks/app/`
- Reverse property lookups via `.with_indexed_properties(...)`
- The library's default web UI templates, with several overridden here
  (`templates/`) to show how an application customizes the look of its own
  actor pages

This code is version-locked to the library it ships alongside — it is
exercised by this repository's test suite and CI (see the tests under
`tests/` that import `examples/demo/application.py`), so it cannot drift the
way a separately-versioned reference application can.

**Deployment lives elsewhere.** This directory has the application code only.
The live instance at `demo.actingweb.io` is deployed from the
[`actingwebdemo`](https://github.com/actingweb/actingwebdemo) repository,
which owns the AWS credentials, OAuth client secret, and Serverless
Framework configuration needed to deploy it. Nothing in this directory is
deployable on its own.

## Running locally

1. Start DynamoDB Local:

   ```bash
   docker compose -f docker-compose.test.yml up dynamodb-test
   ```

2. Copy `.env.example` to `.env` in this directory and fill in an OAuth2
   client ID/secret (e.g. from a
   [Google OAuth app](https://console.cloud.google.com/apis/credentials)).
   Point `AWS_DB_HOST` at DynamoDB Local (the `.env.example` default already
   does). Never commit `.env` — it holds real secrets and is gitignored.

3. From the repository root:

   ```bash
   poetry install --extras flask
   poetry run python examples/demo/application.py
   ```

4. Visit `http://localhost:5000` and log in. The API explorer for the demo's
   hooks is at `/{actor_id}/www/demo` once an actor exists.

## The `/nuke` endpoint

`application.py` registers `GET /nuke?secret=<NUKE_SECRET>`, which deletes
every actor in the configured DynamoDB tables. It exists to reset a test
deployment between QA runs and is gated behind `NUKE_SECRET` — leave that
environment variable unset to disable it. **This is a destructive
test-cleanup endpoint, not application code to imitate.** It has no place in
a production deployment.
