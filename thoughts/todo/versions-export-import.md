# Export and import of an actor's versions

**Filed:** 2026-11-27, by the triage of the Emm AI repository's review of
the version-history plan
(`thoughts/research/2026-11-27-emm-review-of-version-history-plan.md`,
finding 7; the consumer was `actingweb_mcp` at `4fd6fdc1`).

A per-actor backup that reads the actor's own partition
(`fetch_all_including_lists`, `db/dynamodb/property.py:910`) misses the
hidden partitions `{id}$ver` (versions) and `{id}$aux` (the body rows of
spanned list elements). A create with a caller-supplied id clears
`{id}$ver` first (the plan's AC-73), so a delete and re-create of an
account drops its history unless the rows are written back afterwards.
The 4.1 maintenance guide says so; the consumer extends its own script.

Wanted: `actingweb-versions export --actor ID` and `import`, so a consumer
does not write to the version partition by row name. Decide with it
whether an import into a different actor id is supported, and whether
`$aux` belongs to the same command or to a per-actor export of its own.

Additive.
