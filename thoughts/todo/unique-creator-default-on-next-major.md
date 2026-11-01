# TODO: Turn creator uniqueness on by default at the next major

**Status:** Blocked on the next major version bump.
**Filed by:** Greger Wedel (with Claude), 2026-10-29, from the "Exit for the
opt-in default" decision in
`thoughts/plans/2026-10-28-db-fault-semantics-and-creator-uniqueness.md`.

## Why it waits

3.16 makes `with_unique_creator()` a guarantee the database enforces, but
leaves it off by default: turning it on forces every deployment with
duplicate creators through `actingweb-unique-creators report/resolve/enable`
before it can start. A minor must not do that. Both known consumers
(`actingweb_mcp`, the demo) already run with the flag on, so in 3.16 the most
complex adoption path (the default, duplicate-tolerant one) is the least
exercised. This todo makes that transitional.

## What the flip is

- `Config.unique_creator` and `ActingWebApp._unique_creator` default to
  `True`. `tests/test_unique_creator_default.py` pins both to `False` and
  names this file: change it together with the flip.
- The migration guide for the major says to run the command's Step 0
  (`report`, `resolve --apply`, `enable --apply`) before upgrading, and how to
  stay off with `with_unique_creator(False)` for a while.

## What is deleted with it

The duplicate-handling code the flag-off path needs (research §6):

- `actingweb/oauth2.py`: `_factory_siblings`,
  `_sweep_factory_actors`, `SWEEP_LIMIT`, the successor step's `remaining`
  logic, the recursive hand-off to `_adopt_actor` and its `carried` argument.
- `actingweb/actor.py`: the ranking in `get_from_creator` and the
  `factory_sibling_ids` / `creator_ids` / `creator_classes` attributes it
  fills (read in `oauth2.py`'s adoption steps).
- Decide then whether `with_unique_creator(False)` survives at all; if it
  does, the code above survives with it.
