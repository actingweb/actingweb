# What was left of the root `TODO.md`

**Provenance:** the two items of the root `TODO.md` still open when it was
checked against `master` at `ccc64b8` (2026-11-17) and deleted.

## What is still open

- **The web UI stores the trust type as the relationship name.**
  `actingweb/handlers/www.py`, the trust-creation branch, carries the
  comment "TODO: Store human-readable relationship name separately if
  different from trust_type". The `relationship` field holds the protocol's
  trust type, so a custom display name has nowhere to go. Low: nothing reads
  a separate name today.
- **Revoking one client's tokens reads all of the actor's tokens.**
  `ActingWebTokenManager._revoke_matching_tokens` (`oauth2_server/token_manager.py`)
  snapshots the actor's access and refresh buckets and filters by client id
  in memory. The cost is bounded by one actor's live tokens, not by the
  store. An index by client would make it a lookup; do it only if an actor
  with very many tokens is measured.
