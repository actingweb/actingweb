# `cleanup_expired_tokens()` orphans TTL-past token rows and stops on one fault

**Provenance:** issue 7 of
`thoughts/verifications/2026-09-25-mcp-oauth-hardening-and-credential-exposure.md`
(found by the outside-voice pass). Not fixed in that plan's first
iteration batch, which the owner scoped to issues 1–6 and the logging todo.

## What is wrong

Since 3.15 the MCP token lookups read strictly (`_strict_read`, both
backends' `get_attr_strict`). That read treats a row past its
`ttl_timestamp` as absent. `ActingWebTokenManager.cleanup_expired_tokens`
walks the global indexes and, for each name, loads the actor row through
that read:

- a TTL-past token reads as "doesn't exist", so only the **index** row is
  deleted and counted as `index_entries`; the actor row stays;
- the `used and used_at + REUSE_WINDOW < now` branch for consumed refresh
  tokens is nearly unreachable, because the consumed row's TTL is
  re-stamped to that same instant;
- nothing in the loop catches `TokenStoreUnavailable`, so one transient
  fault ends the sweep (by design since 3.15: it must not delete index rows
  it could not read, but it should skip the row and continue).

Also (PR #148 review, 2026-09-27): the three `get_bucket()` index reads in
the sweep check truthiness, not `Attributes.loaded`, so a bucket that could
not be read looks empty and the sweep silently no-ops for that index.
`_snapshot_bucket` in the same file shows the check to use.

## Why it is not urgent

The orphaned actor rows are reaped anyway: on PostgreSQL by the throttled
token-endpoint purge (`purge_expired_tokens`, all seven MCP buckets), on
DynamoDB by native TTL. The changelog no longer claims the scheduled job
removes consumed refresh tokens.

## Fix

Delete the actor row by name using the index row's actor id instead of
re-reading it, and catch `TokenStoreUnavailable` per row (count it, log
once, continue). Test on `tests/mcp_token_double.py` with a TTL-past row
(the double does not enforce TTL today, so it needs a mode for that) and
with one faulty bucket.
