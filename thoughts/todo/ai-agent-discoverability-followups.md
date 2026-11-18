# AI agent discoverability — follow-ups

Deferred from `thoughts/plans/2026-08-22-ai-agent-discoverability.md`. Each
needs a resource this environment does not have: a live OAuth2 provider and MCP
client, a fresh agent session in a scratch repo, or an account on a third-party
submission form.

`thoughts/plans/2026-11-15-3-16-release-validation.md` did the other two on
2026-11-18 (a real MCP client against the quickstart, and the Agent Skill
in a fresh consumer session with Claude Code and Codex); its research note
has the outcome. What is left waits on the stable tag.

## 1. Submit to Context7

Context7 is the third-party doc-indexing service AI coding tools query for
library documentation. The owner has an account and the `context7-admin` MCP
server is connected (teamspace "Personal", no libraries yet). **Action:** add
and claim `actingweb` once stable 4.0 is tagged and its docs are live on Read
the Docs, so Context7 indexes the 4.0 docs and not 3.15's; the steps are in
`thoughts/plans/2026-11-15-3-16-release-validation.md`, "After the tag". Note that checking whether it
is *already* listed by fetching `context7.com/actingweb/actingweb` proves
nothing: that host returns 200 for any made-up path.
