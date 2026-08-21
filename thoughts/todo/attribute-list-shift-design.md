# TODO: `ListAttribute` has the same shift-loop design `ListProperty` had before this plan

`actingweb/attribute_list.py`'s `ListAttribute.__delitem__()`/`.insert()`
delete/insert an item by shifting every later item with a loop of separate,
non-transactional writes and updating the stored `length` last — the same
design `ListProperty` had before
`thoughts/plans/2026-08-08-property-list-index-integrity.md` fixed it there.
An interruption mid-shift (process death, throttle, timeout) leaves the same
class of permanent damage: holes, inflated `length`, or an exact-duplicate
residue, with the list logging errors on every subsequent read and no
built-in repair path.

Flagged independently by both research docs on this plan:
- `thoughts/research/2026-08-07-property-list-index-integrity.md`
- `thoughts/research/2026-08-08-property-list-index-integrity-review.md`
  ("found a fourth no-crash formation path ... plus the same shift design in
  `ListAttribute`")

**Why this wasn't folded into the property-list plan:** `ListAttribute`
backs actor *attributes* (internal/bucket-scoped key-value storage used by
hooks and internal state), not user-facing *properties* — a distinct class,
distinct storage keys, distinct call sites (`attribute_list_store.py`,
`tests/test_attribute_list.py`, `tests/integration/test_attribute_lists_advanced.py`).
Extending the property-list plan's fixes to it would have doubled the
plan's scope for a class with materially lower blast radius (no known
production incident, unlike the property-list case this plan was written to
fix — see `actingweb_mcp/thoughts/research/2026-07-28-run-records-index-skew.md`).

**Options for whoever picks this up**, roughly increasing in cost, matching
the phased approach this plan used for `ListProperty`:

1. Minimal: port Phase 1's hardening only (fail-fast on backend read/write
   faults instead of swallowing them, fix any stale-handle-reuse bugs in the
   shift loop analogous to the `insert()` DynamoDB bug this plan fixed).
   Leaves the shift-loop non-atomicity itself unfixed, same as
   `ListProperty` between Phase 1 and Phase 4 of this plan.
2. Repair primitives: a `verify()`/`compact()` pair (Phase 2's design)
   without a storage-format change.
3. Full fix: adopt the same fractional-rank-key storage format
   `ListProperty` uses (Phase 4/5 of this plan) — makes the shift-loop
   corruption class structurally impossible, same as it did for
   `ListProperty`. The largest option, but the only one that actually
   closes the underlying design flaw rather than mitigating its symptoms.

**Decided 2026-08-14** (owner walkthrough): **option 3, the full v2 port.** It
is the only one that closes the corruption class rather than mitigating its
symptoms, and it is materially cheaper than when this was filed — the
fractional-rank format, its `verify()`/`compact()` primitives and its migration
shape all now exist and are proven on `ListProperty`. Note the port inherits
`thoughts/todo/whole-list-rewrite-atomicity.md`'s open commit-protocol gap, so
sequence it after that work rather than reproducing the gap in a second class.

**Updated 2026-08-21, after `thoughts/plans/2026-08-20-v2-positional-access-cost.md`
(v3.14.0) landed.** Two things for whoever picks this up next:

- **A second sequencing dependency, alongside the existing one.**
  `remote_storage.py`'s subscription diff vocabulary is closed on both
  sides — an unrecognised operation makes a peer replica silently diverge
  — and 3.14 Phase 10 changed it (`remove`/`update` diffs gained
  value-addressed semantics, `update` gained an optional `old_item`
  field), specifically for `ListProperty`. A v2 port for `ListAttribute`
  will want the equivalent diff support if `ListAttribute` mutations are
  ever notified/subscribed to the same way — check whether they are before
  assuming the vocabulary is already settled for this class, and if diffs
  are in scope, sequence behind that work having actually shipped and
  stabilized (it just landed in 3.14.0; give it real-world exposure before
  building a second consumer of the same wire format).
- **Adopt the handle API rather than reinvent an identity-addressed
  primitive.** 3.14 Phase 7 added `ListItemHandle` /
  `items_with_handles()` / `find()` and Phase 10 added the handle-based
  mutators (`delete_by_handle`, `update_by_handle`, `remove_where`,
  `update_where`) precisely because deriving a position from a fractional
  rank list requires a whole-list read — the same cost problem a
  `ListAttribute` v2 port would otherwise reproduce from scratch if it
  designed its own position-vs-identity access pattern. Port the handle
  shape (frozen `rank` + `raw_value` dataclass, single-shot
  compare-and-swap mutators, no built-in retry) rather than re-deriving
  it independently — see `property_list.py`'s handle mutators and
  `thoughts/plans/2026-08-20-v2-positional-access-cost.md` Phases 7 and 10
  for the design and the constraints it settled (handles are not
  wire-stable across a list generation; `BatchWriteItem` cannot express
  conditions, so bulk handle mutation is still *k* point writes, not one
  batch call).

Whoever scopes this should re-read both research docs above for the
measured corruption mechanics (they were reproduced against real
dynamodb-local, not just reasoned about) before designing a fix — several
initially-plausible fixes for the equivalent `ListProperty` bug turned out
to make things worse under measurement (see the "Verified 2026-08-07" note
in the now-resolved `thoughts/todo/property-list-delete-leaves-holes.md`
git history).
