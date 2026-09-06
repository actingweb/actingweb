# AI agent discoverability — follow-ups

Deferred from `thoughts/plans/2026-08-22-ai-agent-discoverability.md`. Each
needs a resource this environment does not have: a live OAuth2 provider and MCP
client, a fresh agent session in a scratch repo, or an account on a third-party
submission form.

## 1. Submit to Context7

Context7 is the third-party doc-indexing service AI coding tools query for
library documentation. Submission needs an account and a form outside this
repo's tooling. **Action:** submit `actingweb` — the Read the Docs build is
live, so Context7 would index the corrected docs. Note that checking whether it
is *already* listed by fetching `context7.com/actingweb/actingweb` proves
nothing: that host returns 200 for any made-up path.

## 2. Connect a real MCP client to `examples/mcp_quickstart.py`

`docs/guides/mcp-quickstart.rst` was verified by running the example server and
exercising `initialize`/`tools/list` manually, never by pointing an actual MCP
client (Claude Desktop, Cursor, or `mcp-remote`) at it end-to-end with real
OAuth2 credentials. **Action:**
follow the guide's own "Connecting a Real MCP Client" section as a fresh
user would, using a real OAuth2 provider, and fix anything that doesn't
match.

## 3. Verify the Agent Skill actually activates in a consumer repo

`skills/actingweb-app/SKILL.md` was written and content-reviewed in place, but
never installed into a separate scratch repository and tested
against a fresh agent session picking it up unprompted (`git clone` +
"point agent at skills/" or `npx skills add actingweb/actingweb`, per the
verified precedent from
`docs.readthedocs.com/platform/latest/reference/agent-skills.html`).
**Action:** in a throwaway repo with only `pip install actingweb`, install
the skill and confirm an agent session surfaces and follows it for a task
like "add a property hook."
