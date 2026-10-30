# A property-list append cannot be repeated safely after a lost answer

**Filed from** `thoughts/inbound/no-atomic-keyed-create-for-property-list-items.md`
(the Emm AI app, `actingweb_mcp`, 2026-10-29, from the create-retry audit on
its PR #349, `scripts/audits/create-retry-adoption.md` there, and the app's
`thoughts/todo/create-retry-server-identity.md`). Triaged 2026-10-29 against
the tree at `8e8b4df` plus the uncommitted 3.16 fault-contract work.

## What is wrong

`ListProperty.append(item)` (`actingweb/property_list.py`) takes no key. A
client whose first answer was lost (API Gateway answers 504 at about 30 s
while the Lambda finishes the write) cannot tell "not created" from
"created, answer lost". Today the app guards with a duplicate check:
`ListProperty.find()` or its own scan, then `append`. That leaves three
holes:
- **a check-then-write race** (two repeats both pass the check and both
  append);
- **no identity** a repeat from another page or device can look for;
- **content matching** that adopts another writer's identical item.

## What the triage changed

- **Confirmed:** no keyed or conditional append exists. `find()` is a
  whole-list read matched in memory, so a find-then-append is a race by
  construction.
- **The primitive already exists.** `DbProperty.create_if_not_exists` (both
  backends; v2 rank-key inserts use it) is the conditional create the report
  asks for. A keyed append is a conditional create of a key row (for example
  `list:{name}-key:{digest(key)}`, holding the item's rank), then the item.
  A later call with the same key reads the key row and returns the stored
  item. The "unique caller-named field" variant (the app's path) is the same
  mechanism with the field value as the key.
- **The library has the same duplicate internally.**
  [A conditional write retried by the SDK can report False for a write that landed](conditional-write-ambiguous-after-sdk-retry.md)
  traces `_v2_append` writing an item twice after a DynamoDB SDK retry of a
  lost response. A key written in the same step closes both; fix them
  together.
- **Storage-layout constraint:** key rows need a region that plain reads,
  `list_all`, the v1 index scan and the v2 rank ranges all skip. Spanned
  list items' body rows met the same constraint with the actor's derived
  side partition (`{actor_id}$aux`, see
  `thoughts/plans/2026-10-30-spanned-list-items.md`); key rows go there too
  (`list:{name}-$key-{hash}`), and that plan's Phase 3 is this item.

## Decisions needed

- The key-row lifetime: kept with the item and deleted with it, or a TTL. A
  repeat can come days later from another device.
- Whether `delete`, `pop` and `clear` remove the key rows, so a key can be
  reused after its item is gone.
- The API: a keyword-only `append(item, *, key=None)` returning the stored
  item (additive, so 3.16 can take it), and whether `extend` and `insert`
  take keys.
- Whether the v1 format gets it, or the key needs v2 (lazy migration already
  moves a list to v2 on first mutation).

## Why it waits

It belongs with spanned list items, on the same layer and in the same audit,
and it is a new public API. It does not belong in the fault-contract PR. If
spanned items ships in 3.16, this rides with it; if spanned items moves to
3.17, so does this.
