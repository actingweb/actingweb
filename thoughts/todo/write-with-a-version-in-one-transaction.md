# A write together with a version of what it replaces, in one transaction

**Filed:** 2026-11-27, by the triage of the Emm AI repository's review of
the version-history plan
(`thoughts/research/2026-11-27-emm-review-of-version-history-plan.md`,
findings 1 and 2; the consumer was `actingweb_mcp` at `4fd6fdc1`). Deferred
by the owner the same day.

Version history (4.1, `thoughts/plans/2026-11-26-version-history-and-restore.md`)
has no restore call. An application takes a version and then writes, in two
store calls. What that leaves:

- **List elements.** `update_by_handle` is a compare-and-swap, so a writer
  in between fails the write and nothing is lost. A lost swap or a failed
  write leaves a duplicate version, and at the limit that take has already
  trimmed an older one.
- **Properties and attributes.** The public write is not conditional. A
  writer between the take and the write is overwritten, and its value is
  in no version unless it took one.

Wanted: one call that writes the new value and stores a version of the
value it replaces, or neither. It serves "edit with history" and "restore"
alike. Design it once for all three kinds, starting from list elements,
which is where the consumer's content and its concurrent writers (an agent
and an editor on one document) are.

Start from the plan's Removed Phases section: the two backend methods
(`set_with_version_rows`, `set_attr_with_version_rows`), the transaction
shapes on both backends and the evaluation rows that shaped them (10, 11,
19, 43, 44, 57, 77). Open:

- whether a spanned element can be covered (its bodies are written outside
  the head's conditional write; DynamoDB allows 100 items and 4 MB in a
  transaction);
- attribute lists, whose rows and version rows are in different tables;
- the start-up refusal for a custom backend lacking the methods (the
  plan's dropped AC-54).

Additive: a minor. Build it when the two-call form is shown to hurt.
