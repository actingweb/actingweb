# A conditional write retried by the SDK can report False for a write that landed

**Provenance:** found during the 2026-09-14 triage of
[`v2-list-mutation-raises-after-its-write-committed.md`](v2-list-mutation-raises-after-its-write-committed.md)
(the plan that closed the touch-fault report). Traced against the installed
PynamoDB/botocore source, not reproduced. Details, retry-mode math and links
are in
[`../research/2026-09-14-v2-list-mutation-raises-after-its-write-committed.md`](../research/2026-09-14-v2-list-mutation-raises-after-its-write-committed.md)'s
"Adjacent finding" section.

## What is wrong

PynamoDB 6.1.0's default retry configuration builds a botocore client in
**standard** retry mode (`total_max_attempts = 4`). Standard mode retries
`ConnectionError`/`HTTPClientError`, which includes a read timeout on a
request whose write actually landed on the server:

1. The first attempt's `PutItem`/`DeleteItem` commits, but the response times
   out client-side.
2. botocore retries the same conditional request.
3. The retry's condition now fails against the row the first attempt already
   wrote (`ConditionalCheckFailedException`).
4. PynamoDB raises `PutError`/`DeleteError` with that cause.
5. ActingWeb maps it to `False` — `create_if_not_exists()` at
   `actingweb/db/dynamodb/property.py:588-593`,
   `delete_if_value_equals()` at `:612-617`.

The mutators read that `False` as "someone else won", not "I won, on the
attempt whose response I never saw":

- `_v2_append()` treats it as a rank collision and writes the item again
  under the next rank — a duplicate.
- `_v2_pop()` re-resolves and deletes the item that now occupies the index —
  removes two items, returns the second.
- `delete_by_handle()`/`update_by_handle()` report `False` ("changed or
  vanished") for their own write.

Different mechanism from the one
[`v2-list-mutation-raises-after-its-write-committed.md`](v2-list-mutation-raises-after-its-write-committed.md)
fixed: that plan closed "the touch fails after the item committed". This one
is ambiguity **inside a single primitive** — the mutator cannot tell "I lost
the race" from "I won it on a retried attempt". Fixing the touch does not
touch this; CHANGELOG's Unreleased entry for that plan says so explicitly.

## What doing it buys

Closes the last documented way a v2 list operation can silently duplicate or
double-remove under otherwise-normal traffic (sustained backend trouble, not
concurrent writers). Without it, "retrying a *raised* mutation is still not
safe in general" stays true even after the touch-fault fix.

## What has to be decided first

- **Reproduce or fix from the trace.** Nothing here has been observed in
  production or under a fault-injection test; the mechanism is inferred from
  reading PynamoDB/botocore source.
- **Whether PostgreSQL has an equivalent.** The psycopg3 path was not
  checked; this todo is written from the DynamoDB/botocore side only.
- **Fix shape**, two candidates:
  - Read-back on `False`: before concluding "lost", re-read the row and
    check whether it already holds *this* mutator's own intended value.
    Cheap on the common path (only pays the extra read on the `False`
    branch) but needs a way to recognise "my own write" — the mutators
    don't currently carry a request-scoped token.
  - An idempotency token where one exists (DynamoDB `TransactWriteItems`'
    `ClientRequestToken`, or a similar per-call token threaded through
    `DbPropertyProtocol`) — closes it at the protocol level but is a new
    primitive, not a call-site fix.
