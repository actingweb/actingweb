# A batch take for version history

**Filed:** 2026-11-27, by the triage of the Emm AI repository's review of
the version-history plan
(`thoughts/research/2026-11-27-emm-review-of-version-history-plan.md`,
finding 6; the consumer was `actingweb_mcp` at `4fd6fdc1`).

A consumer that keeps deleted items recoverable takes a version of each
element before a bulk delete (a whole list of several hundred). One take
is about four to five store calls by the plan's sequence (create the
marker, read the newest id, write the head, advance the marker, a range
read when a limit is set); 500 elements are about 2,500 calls in one
request. The figure is from the plan, not measured.

Wanted: `take_many` over a list of `(key, content, metadata)` that shares
the reads (one range read of the markers under a prefix in place of a read
per key). It still writes a head and a marker per element, so the saving
is the reads. Measure a real bulk delete on DynamoDB first, including
whether the shared `{id}$ver` partition key throttles: that decides
whether this is worth building.

Additive: a minor or a patch (a new method with defaults).
