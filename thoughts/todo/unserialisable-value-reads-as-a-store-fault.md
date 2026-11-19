# A value `json` cannot encode is reported as a store fault

**Filed:** 2026-11-19, from the consumer's second read of
`thoughts/plans/2026-11-19-emm-4-0-adoption-findings.md` (a round-two candidate), verified in the tree the same day.

An attribute (or property) write of a value `json` cannot encode raises
`TypeError` inside the backend's write `try`, which wraps it as
`DbError("attribute set")` (`db/dynamodb/attribute.py` `set_attr`, where
`JSONAttribute` serialises in `save`; `db/postgresql/attribute.py`, the
`json.dumps` inside the write's `try`). `DbError` answers 503 with
`Retry-After` (`interface/integrations/_errors.py`: `TypeError` is not a
permanent cause), so a client that retries on 503 retries a request that can
never succeed. The value should be refused before the backend call (a
`ValueError`, 400), on both backends and for properties too; check whether
`sanitize_json_data` already covers part of it.
