# `GET /{actor_id}/trust` returns each relationship's secret and verification token

Scheduled. The work is Phase 1 (B) of
`thoughts/plans/2026-09-25-mcp-oauth-hardening-and-credential-exposure.md`;
delete this file and its `INDEX.md` row when that phase lands.

What triage changed about the original filing (full record in
`thoughts/research/2026-09-25-mcp-oauth-hardening-and-credential-exposure.md`,
report 2):

- The protocol spec's list example shows `secret`
  (`docs/protocol/actingweb-spec.rst:1499-1520`), so the strip is a spec
  example change and the release is a minor.
- The strip is **list-only, at the handler**. The per-relationship GET keeps
  both fields: the spec says the secret SHOULD be readable there
  (`:1754-1758`) and peer verification reads `verification_token` from it
  (`actingweb/actor.py:1263`).
- No library caller, test, template or consumer reads either field from the
  list route.

**Provenance.** Found 2026-09-15 by actingweb_mcp todo #59 (its persisted
bootstrap snapshot carried trust secrets); that project stopped sending the
two fields in its own bootstrap aggregate the same day.
