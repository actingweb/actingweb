# A default-uniqueness `Config` that skips `check_ready()` creates an empty `creators` table

Found by the Phase 2-4 outside-voice review of
`thoughts/plans/2026-11-01-single-mode-and-consumer-primitives.md`; the plan
accepted the hazard for 3.16.0 (Phase 2 "Failure Scenarios": a direct `Config()`
user) and the migration guide tells such code to call `check_ready()`. Recorded
here because the review rated it high.

**What happens.** `DbActor(unique_creator=True)` calls `ensure_table(Creator)`
(`actingweb/db/dynamodb/actor.py`, the constructor), which creates an **empty**
`<prefix>_creators` table. A process that builds a default `Config()` (or
`ActingWebApp(...).get_config()`) and creates actors without `integrate_flask`,
`integrate_fastapi` or `check_ready()` - a worker, a cron job, a Lambda entry
point - then claims creators against that empty table. If the creator already
belongs to an actor in the main application's data, a second actor is created
and the record is written. `check_ready()` in the main app later answers "not
backfilled" rather than "table missing", so the damage shows up late.

**Options.** (a) Stop `DbActor.__init__` creating `Creator`; leave creation to
`actingweb-unique-creators enable` and the prewarm that `check_ready()` runs,
and let an enforced create against a missing table raise `DbError` (fail
closed). (b) Run the single `GetItem` readiness probe once per process inside
`DbActor` when `unique_creator` is true. Either changes who creates the table,
so it needs a look at `enable`, the prewarm and the integration fixtures, and a
changelog entry.

**Also unverified:** `actingweb/maintenance/verify_orphans.py`,
`verify_property_lists.py` and `migrate_property_lists.py` build a bare `Config()`;
whether they reach `get_actor(config)` was not traced.
