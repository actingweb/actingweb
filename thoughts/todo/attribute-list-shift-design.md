# TODO: `ListAttribute` still has the shift-loop design `ListProperty` had before v2

`actingweb/attribute_list.py`'s `ListAttribute.__delitem__()` / `.insert()`
delete or insert an item by shifting every later item with a loop of separate,
non-transactional writes, updating the stored `length` last — the design
`ListProperty` had before
`thoughts/plans/2026-08-08-property-list-index-integrity.md` fixed it there. An
interruption mid-shift (process death, throttle, timeout) leaves the same class
of permanent damage: holes, inflated `length`, or an exact-duplicate residue,
with the list logging errors on every subsequent read and no built-in repair
path.

**Scope note:** `ListAttribute` backs actor *attributes* (internal,
bucket-scoped storage used by hooks and internal state), not user-facing
*properties* — distinct class, distinct storage keys, distinct call sites
(`attribute_list_store.py`, `tests/test_attribute_list.py`,
`tests/integration/test_attribute_lists_advanced.py`). Blast radius is
materially lower than the property-list case: no known production incident.

**The approach is the full v2 port** — adopt the same fractional-rank storage
format `ListProperty` uses, which makes the shift-loop corruption class
structurally impossible rather than mitigating its symptoms. It is much cheaper
than when this was filed: the format, its `verify()`/`compact()` primitives and
its migration shape all exist and are proven. (The cheaper options — port only
the fail-fast hardening, or add repair primitives without a format change —
leave the non-atomicity itself in place.)

## Constraints for whoever picks this up

- **Sequencing against `thoughts/todo/whole-list-rewrite-atomicity.md`.** The
  port inherits that open commit-protocol gap. Either sequence after it, or
  accept the same documented window `ListProperty` shipped with and fix both
  classes later — that call has not been made.
- **Check the subscription diff vocabulary before assuming it is settled.**
  `remote_storage.py`'s diff vocabulary is closed on both sides — an
  unrecognised operation makes a peer replica silently diverge — and it changed
  for `ListProperty` (`remove`/`update` diffs gained value-addressed semantics,
  `update` gained an optional `old_item`). If `ListAttribute` mutations are
  notified or subscribed the same way, the port needs equivalent diff support;
  establish whether they are before designing.
- **Adopt the handle API rather than reinvent an identity-addressed
  primitive.** `ListItemHandle` / `items_with_handles()` / `find()` and the
  handle-based mutators (`delete_by_handle`, `update_by_handle`, `remove_where`,
  `update_where`) exist precisely because deriving a position from a fractional
  rank list requires a whole-list read — the cost problem a fresh
  position-vs-identity design would reproduce. Port the shape (frozen `rank` +
  `raw_value` dataclass, single-shot compare-and-swap mutators, no built-in
  retry); see `property_list.py`'s handle mutators and
  `thoughts/plans/2026-08-20-v2-positional-access-cost.md` Phases 7 and 10 for
  the constraints they settled (handles are not wire-stable across a list
  generation; `BatchWriteItem` cannot express conditions, so bulk handle
  mutation is *k* point writes, not one batch call).
- **Read the corruption mechanics before designing a fix.**
  `thoughts/research/2026-08-07-property-list-index-integrity.md` and
  `thoughts/research/2026-08-08-property-list-index-integrity-review.md`
  reproduced them against real dynamodb-local rather than reasoning about them,
  and several initially-plausible fixes for the equivalent `ListProperty` bug
  turned out to make things worse under measurement.
