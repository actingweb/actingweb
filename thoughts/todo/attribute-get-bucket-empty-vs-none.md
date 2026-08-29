# `DbAttribute.get_bucket()`: `None` means "fault" on one backend and "empty or fault" on the other

Deferred from Phase 6a of
`thoughts/plans/2026-08-29-bulk-list-reads-from-a-consumer.md` (v3.14.3).

Both backends return `None` from `get_bucket()` for a *caught* exception. PostgreSQL
(`db/postgresql/attribute.py`) **also** returns `None` for a genuinely empty
bucket, where DynamoDB returns `{}`. Since v3.14.3 `Attributes.get_bucket()` sets
`_bucket_loaded` only when the backend returned a dict, so on PostgreSQL an empty
bucket is never trusted and `get_attr()` on it still point-reads. That is
deliberate and conservative — an empty bucket has no absent-name savings to give
up — but it is a real cross-backend difference in a protocol return value.

Pinned rather than hidden:
`tests/integration/test_db_attribute_buckets.py` asserts
`attrs._bucket_loaded is (DATABASE_BACKEND != "postgresql")` after loading an
empty bucket, so aligning the backends changes a test instead of surprising
anyone.

The fix is small: make PostgreSQL's `get_bucket()` return `{}` for an empty
bucket and reserve `None` for a caught exception, then flip that assertion to
`is True` on both backends. It was not folded into v3.14.3 because
`Attributes.get_bucket()` carries an explicit comment about the divergence, so
it is known and possibly depended on; a grep of `get_bucket()` callers across
`actingweb/` found none branching on `is None` (each either goes through
`Attributes`, which normalises, or writes `or {}`), but "no caller I found" is a
weaker guarantee than "no backend edit", and a patch release whose correctness
argument did not need the change was the wrong place to take that risk. A
follow-up with its own release note is the right one.
