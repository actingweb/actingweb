# AI agent discoverability — follow-ups

Items deferred from
`thoughts/plans/2026-08-22-ai-agent-discoverability.md` (`status: done`).
None were completable inside that session — each needs either a resource
this environment doesn't have (a live OAuth2 provider + MCP client, a second
agent session, network access to a third-party submission form) or has to
wait for the PR to actually merge and publish. The plan is closed; this is
where the remainder lives.

## 1. Confirm the Read the Docs build after merge — DONE 2026-09-02

Both `latest` and `stable` built successfully at the v3.14.3 commit
(`f552747`, RTD builds 34293120/34293121). Every advertised link in
`README.rst`, `AGENTS.md`, `actingweb/__init__.py` and `skills/actingweb-app/
SKILL.md` uses the `/en/latest/docs/...` prefix the root `conf.py` build
produces, and `docs/guides/p2p-quickstart.html` and
`docs/guides/mcp-quickstart.html` both return 200 there. Nothing to do.

## 2. Submit to Context7

Phase 8 of the plan noted Context7 (the third-party doc-indexing service AI
coding tools query for library documentation) as worth submitting to, but
submission requires an account/form outside this repo's tooling — no
in-repo action can complete it. **Action:** submit `actingweb` — item 1 is done, so
Context7 would index the corrected docs. Whether it is *already* listed could
not be told on 2026-09-02: `context7.com/actingweb/actingweb` returns 200, but
so does any made-up path on that host, so a 200 proves nothing.

## 3. Connect a real MCP client to `examples/mcp_quickstart.py`

Phase 2b's guide (`docs/guides/mcp-quickstart.rst`) was verified by running
the example server and exercising `initialize`/`tools/list` manually, but
never by pointing an actual MCP client (Claude Desktop, Cursor, or
`mcp-remote`) at it end-to-end with real OAuth2 credentials. **Action:**
follow the guide's own "Connecting a Real MCP Client" section as a fresh
user would, using a real OAuth2 provider, and fix anything that doesn't
match.

## 4. Verify the Agent Skill actually activates in a consumer repo

`skills/actingweb-app/SKILL.md` (Phase 6b) was written and content-reviewed
in place, but never installed into a separate scratch repository and tested
against a fresh agent session picking it up unprompted (`git clone` +
"point agent at skills/" or `npx skills add actingweb/actingweb`, per the
verified precedent from
`docs.readthedocs.com/platform/latest/reference/agent-skills.html`).
**Action:** in a throwaway repo with only `pip install actingweb`, install
the skill and confirm an agent session surfaces and follows it for a task
like "add a property hook."
