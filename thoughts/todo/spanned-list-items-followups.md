# Spanned list items: follow-ups from the 2026-10-31 verification

Found by `thoughts/verifications/2026-10-31-spanned-list-items.md` (code
review, outside voice) against `a176a82`; the High findings and M1-M4 were
fixed in the plan's first iteration batch. What is left, each verified
against the tree:

- **M5. Reference diffs.** The subscription full-state fallback applies
  `diff_reference` per list (`actor.py`, after
  `_get_full_state_for_subscription`), but an all-properties subscription
  merges scalars and every list into one blob that can still exceed the
  diff row cap and fail the store. `RemotePeerStore._apply_list_operation`
  answers a reference with `success: false` and every caller discards the
  result (`subscription_manager.py`, `handlers/callbacks.py`), so a built-in
  mirror stays out of sync; its WARNING's "a resync brings it back" is false
  for a peer without resync. The fallback also resolves every spanned body
  only to discard it. Decide whether the receiver triggers a re-read, and
  apply the size rule to the merged blob.
- **M6. A raised span threshold hides spanned items from value scans.**
  `_sought_value_cannot_span` compares with the threshold configured now, so
  an item that spanned under a lower one is skipped by `remove()`,
  `index()`, `count()`. Compare the sought value's encoded size with the
  head's `span.bytes` instead.
- **M7. `--sweep-spans` runs a full rebalance.** The sweep is reached only
  through `compact()`, which then moves and copies every spanned item whose
  rank changes. Expose the sweep as its own method and call that from
  `verify_property_lists`.
- **M8. A pre-3.16 actor id ending in `$aux`.** Deleting `alice` sweeps the
  partition `alice$aux`; if a consumer created an actor with that id before
  3.16, its `list:` rows go with it. Generated ids are hex. Add a pre-deploy
  audit line to `docs/migration/v3.16.rst`, or check for such an actor
  before sweeping.
- **Lows.** `validate_limit_pair` allows a pair that needs more than 9,999
  parts (a plain `ValueError` after the meta row); `PUT ?index=` maps
  `ListItemSpanError` to 400 and the www editor maps it to 400 and
  `ListItemTooLargeError` to 500; one malformed head fails the whole
  `metadata=true` GET (`sizes_from_rows`); a pre-3.16 v2 item whose first
  key is `__aw_env` reads as an envelope; `Properties._delete_side_partition`
  gives up after three passes without a log line; `_read_span` checks the
  byte count only (a digest in the envelope would catch same-length wrong
  content).

None loses data on its own; M5 and M6 return wrong results without an error,
which is why they come first. Fix before 3.16.0 is tagged if PR 2 has room,
else 3.16.1.
