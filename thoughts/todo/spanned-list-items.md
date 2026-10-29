# A list item cannot be larger than one storage row

Filed from `thoughts/inbound/large-list-item-values.md` (Emm AI project,
2026-10-18, while planning read-only HTML output documents,
`actingweb_mcp/thoughts/plans/2026-10-18-read-only-html-output-documents.md`
Decision D2 "cap in v1, span later"). Verified against 52abce6 in
`thoughts/research/2026-10-26-inbound-triage-factory-squat-list-item-size-spa-prompt.md`;
design in
`thoughts/research/2026-10-26-v3.16-scope-oauth-adoption-vouching-and-spanned-list-items.md`
(Part 2). Owner's decision, 2026-10-26: address in 3.16.0 as far as a minor
allows; if it slips, 3.17, never holding the auth work.

A list item is one row, `list:{name}-#{rank}`, and DynamoDB caps a row at
400 KB. The consumer refuses documents over 380,000 bytes with its own
error. An oversized write surfaces as `DbError("property write")`, not a
typed error. `chunk_size` in the list metadata is written as `1` and never
read; `docs/quickstart/configuration.rst:590` and `property_list.py:5` call
this "chunked storage", which it is not. A list-item diff carries the whole
value into a `SubscriptionDiff` row with the same cap, so any design for
large items has to decide what a diff carries.

What is owed, in order:

1. `ListItemTooLargeError` raised before any write on both backends, and the
   two wording fixes.
2. Spanned items: head row at the existing key holding an envelope
   (`gen`, `parts`, `bytes`), body rows at `list:{name}-$span-{gen}-{part}`,
   a region outside the v1 and v2 item ranges and under the `list:` prefix
   plain reads exclude. Body rows are written first, the head through the
   existing compare-and-swap, the previous gen's bodies deleted after;
   readers never mix generations and the handle contract is unchanged.
   Gen-keyed so rank rebalancing moves heads only. Default threshold is the
   size that would otherwise fail (no existing row changes shape);
   configurable lower as the consumer's range-scan cost lever; hard ceiling
   default 4 MB.
3. Every list-row enumeration site learns the region or leaks body rows:
   `clear()`, `delete()`, `sweep_foreign_format_rows()`,
   `_v1_item_names_in_range`/`_v2_item_names_in_range`, `verify()`,
   `_v2_compact()`, `migrate_to_v2()` and the downgrade (refuse a list with
   spanned items), the partition-dump groupers and `list_prefix_with_rows`,
   `scripts/verify_property_lists.py`, `scripts/migrate_property_lists.py`,
   and the `/properties` handlers that serve items whole. Verify by grepping
   every `get_range`, `get_prefix` and `batch_delete` caller, not this list.
4. A spanned item's diff carries `{"index", "spanned": true, "bytes",
   "value": null}`; the subscriber fetches the item. Not a regression: such
   items cannot exist today.
5. Integration test over 400 KB against DynamoDB Local. Whether DynamoDB
   Local enforces the cap is unverified; if not, assert the row shape.
   Run the benchmarks (list storage changes).

Constraints: never rewrite or re-key an existing row (the failure class of
`whole-list-rewrite-atomicity.md`); the only new failure mode is an orphan
body row, inert and swept by `verify()`/`compact()`. The partition-wide 1 MB
Query ceiling stays in `prop-list-key-prefix-scheme.md`.
