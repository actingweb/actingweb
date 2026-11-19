# A bounded read of a v2 list (tail, `start=`/`limit=`)

**Filed:** 2026-11-19, by `thoughts/plans/2026-11-19-emm-4-0-adoption-findings.md` (cut from it on the evaluation; the
consumer's V1). First after 4.0.0rc1.

A consumer's comments feature reads the newest N items of a long list. Today
`slice()` (`list_core.py`) reads the rank keys of the whole list first, so a
tail read costs the whole list's range Query.

The design is open in three places, which is why it was cut from the plan:

- **PostgreSQL ordering.** The `properties` table has no `COLLATE "C"`
  index on `name` (`db/postgresql/schema.py`), so a range read in rank
  order needs an index revision (and its migration) to be bounded.
- **The handle contract for paging across requests.** `list_core.py` says a
  rank is "never persist or transmit one"; a page cursor that crosses a
  request is exactly that. Either a cursor format the library owns
  (opaque, validated) or a rule that pages restart from an index.
- **Four wrapper layers** (`ListProperty`, `NotifyingListProperty`,
  `interface/property_store.py`, `AuthenticatedPropertyListStore`) each need
  the method, with the permission filter on the authenticated one.

Additive: a minor. Done when a tail of N items costs O(N) rows on both
backends, with the cursor contract written down.
