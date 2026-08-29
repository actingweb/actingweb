# Attribute upsert: the two backends disagree on who owns a colliding row

Found while writing Phase 1's tests in
`thoughts/plans/2026-08-29-bulk-list-reads-from-a-consumer.md`.

`Attribute`'s primary key is `(id, bucket_name)` on **both** backends, and
`bucket_name` is `bucket + ":" + name`. Because bucket names contain `:`
(`remote:{peer_id}`) and attribute names contain `:` (`list:{name}:{index}`,
`"{actor_id}:{peer_id}"`), two different `(bucket, name)` pairs can produce the
same `bucket_name` — bucket `remote:abc`/name `x` and bucket `remote`/name
`abc:x` both key on `remote:abc:x`. They are therefore the same row, and a
write from either overwrites the other.

The backends then disagree about the surviving row's *attribution*:

- DynamoDB: `Attribute(...).save()` is a PutItem, which replaces the whole
  item — so the stored `bucket`/`name` become the last writer's.
- PostgreSQL: `INSERT ... ON CONFLICT (id, bucket_name) DO UPDATE SET data,
  timestamp, ttl_timestamp` — `bucket` and `name` are **not** in the SET list,
  so they keep the first writer's values.

After Phase 1 both backends agree on the part that matters for isolation: the
row answers to exactly one bucket, never both
(`tests/integration/test_db_attribute_buckets.py::
TestBucketPrefixIsolation::test_colliding_composite_key_answers_to_exactly_one_bucket`
pins that, and deliberately accepts either winner).

Two ways to close the divergence, neither obviously right:

1. Add `bucket = EXCLUDED.bucket, name = EXCLUDED.name` to the PostgreSQL
   upsert, making both last-writer-wins.
2. Stop the collision existing: give the composite key a delimiter that cannot
   appear in either half, which is a key-layout change (see
   `thoughts/todo/prop-list-key-prefix-scheme.md` for the same question on
   property lists) and needs a migration.

Reaching the collision at all requires one bucket name to be a prefix of
another *and* an attribute name equal to the remainder, so this is not
urgent — but the first fix is one line and removes a real "same input,
different stored state" difference between the backends.
