# /research_codebase addendum

- When the input is an inbound report (`thoughts/inbound/<slug>.md`, or a
  consumer's plan or todo), the research note is the triage record: verify
  every claim against the tree, quote `file:line` for each, and say what the
  check changed (cause, blast radius, or the fix the codebase already
  supports). Carry the attribution across (who filed it, when, out of what),
  because the inbound file is deleted afterwards.
- Check both backends for any storage claim; `actingweb/db/protocols.py` is
  the contract and the two implementations diverge in what they return for
  expired rows and faults.
- Before proposing a fix shape, grep `CHANGELOG.rst` and `thoughts/` for the
  behaviour: several "gaps" are recorded deliberate decisions (fail-open on
  an evaluator outage, the `-32600` dual-era signal). Name them as such.
- Reports about MCP OAuth or the SPA token store should name the existing
  `oauth_session.py` design before proposing a parallel one.
- End with the release shape (patch or minor, per the `### Release` rule in
  `CLAUDE.md`) and the decisions the owner has to make, so `/create_plan` can
  start from them.
