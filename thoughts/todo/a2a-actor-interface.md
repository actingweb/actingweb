# A2A 1.0 per actor, with long-running tasks

**Filed:** 2026-11-25, from the feature and the research.

- Feature: `thoughts/features/2026-11-24-a2a-actor-interface.md`
- Research: `thoughts/research/2026-11-24-a2a-actor-interface.md`, with its
  companions `.tasks.md`, `.reuse.md` and `.auth.md`

## What it is

Each actor becomes reachable as an A2A 1.0 agent at `/<actor_id>/a2a`, with
an Agent Card at `/<actor_id>/.well-known/agent-card.json`.

- **Callers** are third parties. They never act for the actor and never use
  the `mcp_client` types.
  - The owner creates an A2A client in the app, which issues an API key
    (the trust secret) and `client_credentials`.
  - Clients have a class of their own: `a2a_` ids and the `a2a_client`
    source.
  - Each route refuses the other class's tokens.
  - `/a2a` answers 401 with a `Bearer` challenge.
- **Skills** are the existing method and action hooks, granted through the
  `methods` and `actions` permission categories.
- **Long-running work** goes on a general actor task store, which the
  actor's own tasks use too:
  - a worker handle opened with a task token
  - a `task_dispatch` hook that starts the worker
  - polling only
  - cancel always wins
  - finished tasks kept for 7 days by default

The research note's owner decisions 1–16 hold the full approach.

## Shape

- **Release:** 4.1.0, with A2A off by default and protocol specification 1.6.
- **Three plans, one PR each:**
  - core A2A
  - the general task store and long-running tasks
  - docs and the spec chapter

## Size

This is an estimate by analogy with the features merged this autumn. The plan
sizes it properly.

- **Library code:** about 3,500–6,000 lines across the three plans:
  - core A2A: 1,900–3,100, including the A2A client class
  - the task store and long-running tasks: 1,800–2,900
  - docs and the spec: documentation only
- **Tests:** at least as many lines again.
- **Phases:** about 8.
- **Elapsed:** about 1.5–2 weeks.

Both code plans carry authentication risk:
- **The tasks plan** adds a new token on an authentication path, and
  compare-and-set races on both backends.
- **The core plan** splits the OAuth2 classifiers and adds the token-class
  check on `/mcp`.

## Needs first

- `/create_plan` from the research note.
- **A scope line for `input_required`.** Both A2A and MCP define it. The first
  round may reserve the state without supporting it.

## Carried into the core plan

- **Deleting a trust with an empty `baseuri` fails today, and the row
  stays.** `delete_reciprocal_trust` builds `"" + "/trust/…"`
  (`actor.py:3309`). The request raises on the schemeless URL, and the
  `except` skips the local delete (`actor.py:3313-3325`). An A2A caller's
  trust has no `baseuri`, so the core plan adds a local-only branch next to
  `is_oauth2_trust`. It also quiets the missing-`baseuri` warning that each
  permission change logs for such a peer (TPM-4).

## Follow-ups filed apart

- `a2a-followups.md`
- `per-name-grant-editing.md`
- `mcp-tasks.md`, which builds on this work's task store
