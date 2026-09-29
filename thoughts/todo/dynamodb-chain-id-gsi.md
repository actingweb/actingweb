# Promote `chain_id` to a top-level attribute with a GSI on DynamoDB

Raised by the review of PR #153 (3.15.1). The DynamoDB `delete_by_chain`
scans the two SPA token buckets (`spa_access_tokens`, `spa_refresh_tokens`)
under the shared `OAUTH2_SYSTEM_ACTOR` partition on every SPA logout and
`/oauth/revoke`, with a consistent read and an in-memory filter on the
JSON-embedded `chain_id`. PostgreSQL uses an expression index and is O(chain).

3.15.1 accepted the scan from measured production numbers (42 rows, about 3
RCU per call, about 0.4 logouts a day) and logs one WARNING per call when a
bucket holds more than `CHAIN_SCAN_WARN_ROWS` (1,000) rows
(`actingweb/db/dynamodb/attribute.py`). The budget is about 1 MB (about 3,000
rows, one page each, at most about 250 RCU per call); past it each call is
O(bucket) in read capacity and latency.

The fix is to store `chain_id` as a top-level attribute on the row and add a
GSI on it, so the delete is a query by chain. That needs a table-definition
change, a backfill (or a dual-read period) for rows written without the
attribute, and PynamoDB model plus `ensure_table` changes. Trigger: the WARNING
firing in a production deployment, or a consumer whose SPA token partition is
projected past about 2,000 rows. Until then the WARNING is the only guard.
