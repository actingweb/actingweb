# DbTrust.create()'s `approved` param is typed str but PostgreSQL's column is boolean

`DbTrust.create()` in both `actingweb/db/dynamodb/trust.py` and
`actingweb/db/postgresql/trust.py` types `approved: str = ""`. On PostgreSQL,
`trusts.approved` is a genuine `boolean` column — calling `create()` without
passing `approved` explicitly raises:

```
invalid input syntax for type boolean: ""
CONTEXT:  unnamed portal parameter $8 = ''
```

DynamoDB's backend tolerates the empty-string default silently (schemaless
attribute), which is presumably why this has gone unnoticed: any caller that
relies on the default only fails on PostgreSQL.

Found while writing `tests/integration/test_verify_orphans.py` (Phase 13 of
`thoughts/plans/2026-08-20-v2-positional-access-cost.md`), which calls
`get_trust(config).create(...)` directly without an `approved` kwarg. Worked
around there by passing `approved=True` explicitly — this todo is about the
library's own default, not that test.

## Fix

Either:
- Change the type hint to `bool` and the default to `False` in both backends'
  `create()` signatures (and audit call sites currently passing a string), or
- Coerce `approved` to a bool before the PostgreSQL INSERT, matching whatever
  DynamoDB's attribute actually stores.

Check whether any in-repo caller passes a non-empty string for `approved`
(e.g. `"true"`) expecting truthy behavior before deciding which fix is
correct — that call site would need updating either way.
