# AGENTS.md

**ActingWeb** is a Python framework for building secure, per-user
micro-services: each user gets their own "actor" instance with a unique
URL, its own data, and its own trust relationships to other actors. It
ships an authenticated per-actor MCP server, OAuth2 (web, SPA, native
mobile), peer-to-peer subscriptions, and pluggable DynamoDB/PostgreSQL
persistence.

## Contributing to this repository

**All contributor guidance — commands, quality gates, testing, the release
process, architecture — lives in [`CLAUDE.md`](CLAUDE.md). Read it before
making changes.** This file deliberately does not repeat any of it: `CLAUDE.md`
is the maintained source, and duplicating it here is exactly what let an
earlier version of this file go stale for eight months.

## Building an application WITH ActingWeb

If you're consuming this library from another repository (not modifying
ActingWeb itself), start here:

```bash
pip install 'actingweb[fastapi]'   # or [flask], or [all] for everything incl. MCP
```

- MCP quickstart: https://actingweb.readthedocs.io/en/latest/docs/guides/mcp-quickstart.html
- Peer-to-peer quickstart: https://actingweb.readthedocs.io/en/latest/docs/guides/p2p-quickstart.html
- Full documentation: https://actingweb.readthedocs.io/en/latest/
- Reference application: https://github.com/actingweb/actingwebdemo — a
  fuller worked example (MCP + Web/SPA + OAuth2). It pins a floating lower
  bound on `actingweb`, not an exact version, so treat it as illustrative
  rather than a guarantee of matching the current API.
- Agent Skill (task recipes for AI coding agents building on ActingWeb):
  `git clone` this repository and point your agent at
  `skills/actingweb-app/`, or `npx skills add actingweb/actingweb`.

## Thoughts directory

Development notes, research, and plans live under `thoughts/` — see
[`thoughts/README.md`](thoughts/README.md) for the five directories
(`research/`, `plans/`, `verifications/`, `reference/`, `todo/`) and their
conventions.
