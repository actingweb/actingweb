# List items: an append that creates nothing, a TTL, retained generations

**Filed:** 2026-11-19, by `thoughts/plans/2026-11-19-emm-4-0-adoption-findings.md` (the consumer's V2 with `require_actor`,
V3 and V4). Additive list features for comments and versioning; each a minor.
4.0's stored-format rule (`need`, `format`, side-row naming) keeps all
three possible without an operator step.

- **V2, an append that creates nothing (`require_actor`).** An append to a
  list of an actor that is being deleted recreates the list's meta row. The
  application can append and then read the deletion tombstone
  (`ActorInterface.get_deletion_status`) and remove what it wrote; the
  one-step form needs the creation-path choice in
  `meta-row-create-unconditional-for-description-writers.md` first.
- **V3, a time-to-live on an item.** Attribute rows carry a TTL on both
  backends; a v2 list's count is a hint and survives rows that vanish.
  Undesigned: a spanned item's body rows, `append_once` key rows, and
  PostgreSQL's purge.
- **V4, the previous generation of a spanned item kept.** A retained
  generation is an orphan to the sweep unless a head in the same list names
  it, and a body row's name includes the list name, so a history item cannot
  point at it in 4.0's shape. It needs a new locating field, which an
  envelope's `need` now makes safe to add; a new side-row kind is named
  `list:{name}-$<kind>-...` (the 4.0 rule).
