# Triage: actor deletion semantics (DEL1–DEL5) for rc2

**Date:** 2026-07-26
**Input:** `2026-07-26-actor-deletion-semantics-and-orphan-writes.md`
**Companion:** `2026-07-25-rc2-triage.md` (the 3.13 scaling delta; rc2 already in
progress)
**Library state:** `3.13.0rc2` in `pyproject.toml` / `__init__.py`, committed
(`9a0a3cb`), not tagged. CHANGELOG has an `rc2` section.
**Consumer status at intake:** their release **gated on rc2 shipping DEL1**.

Every claim in the feedback doc was checked against the working tree. All five
findings are real and cited accurately. What follows is what shipped, what did
not, and why.

---

## Outcome: DEL1, DEL2, DEL3, DEL4 landed. DEL5 deferred.

### The discriminating question

The consumer supplied an acceptance list (their §"What they will re-verify on
rc2"). Walking it against a tombstone-only design:

| # | Requirement | Satisfied by |
| --- | --- | --- |
| 1 | Reported deleted **throughout** the wipe | tombstone written before step 1 |
| 2 | Outlives a 3-day retry window | 30-day TTL |
| 3 | Infra failure distinguishable from deleted | `UNKNOWN` |
| 4 | Replay for deleted actor writes zero rows | tombstone |
| 5 | Replay for live actor + store unreachable still writes | `UNKNOWN` → proceed |

**All five are satisfied by the tombstone API alone.** Nothing in the gate
required moving the actor-row deletion or changing `DbActor.get()`'s exception
semantics. That set the scope.

### DEL1 — tombstone (their preference #1). Landed.

`actingweb/deletion.py`: `mark_actor_deleted()` / `clear_actor_tombstone()` /
`get_deletion_status()`, plus `DeletionStatus` (`DELETED` / `NOT_DELETED` /
`UNKNOWN`) and `ActorInterface.get_deletion_status()`. Written as the first
statement of `CoreActor.delete()` — which covers every deletion path, since all
three callsites (`handlers/root.py`, `ActorInterface.delete()`,
`Actor.create(delete=True)`) funnel through it.

Storage: the attributes table under `DELETED_ACTORS_STORE = "_actingweb_deleted"`,
bucket `_deleted_actors`, `name=<actor_id>`. Deliberately **not**
`ACTINGWEB_SYSTEM_ACTOR`: that is a real actor, and deleting an actor wipes every
bucket it owns, so tombstones under it would be destroyable by the very mechanism
they describe. A test asserts a `Buckets(ACTINGWEB_SYSTEM_ACTOR).delete()` leaves
tombstones intact.

**The trap this design walked into and had to route around.**
`DbAttribute.get_attr()` has *exactly the DEL2 collapse* — bare
`except Exception: return None`. Building the tombstone read on it would have
returned `None` on a throttle → read as "no tombstone" → read as **"not
deleted"**: acceptance #3 failing invisibly, inside the fix for DEL1. Hence
`get_attr_strict()` on both backends: `DoesNotExist` → `None`, everything else
raises. `get_attr()` was left alone — it is called everywhere and narrowing it
globally is a large blast radius for no gain here.

Also deliberately *not* routed through `InternalStore`, whose `_ensure_loaded()`
issues a full-bucket `Query`. The consumer budgeted for a point read, so the path
is a bare `Attribute.get(...)`. **Measured, not asserted:** exactly
`{GetItem: 1}` via `BaseClient._make_api_call`, with a live-counter assertion so
the count cannot be vacuous (the `get_session()` trap from D7).

`Actor.create()` now clears any tombstone for its id. Not in the feedback doc,
but a real hole: generated ids are never reused, yet `create(actor_id=...)`
accepts a caller-supplied one, and a stale tombstone would report the new actor
as deleted for 30 days and suppress every write for it.

### DEL1 preference #2 — delete the actor row first. **Rejected**, deliberately.

The consumer labelled this "hardening, not a substitute", and acceptance #1 is
already met without it. Against it:

- **It destroys retriability.** Today a failed wipe step leaves the actor row, so
  `DELETE` can be reissued. Row-first strands the remaining rows permanently with
  nothing pointing at them.
- **It contradicts DEL5 in the same release.** The feedback doc's own
  §"Reads must be consistent" notes that *today's* ordering is what makes orphan
  classification safe. Row-first would make mid-deletion actors classify as
  orphaned — adding that hazard in the release that documents orphan detection.
- **It buys nothing the gate needs.** It converts the window from "reports live"
  to "reports missing", and missing is indistinguishable from "read failed"
  anyway. The tombstone answers the question without the trade.

Documented as contract rather than left implicit, so nobody re-derives it.

### DEL2 — scoped down to logging + docs. Landed.

`DbActor.get()` on DynamoDB now catches `DoesNotExist` → `None` silently, and
logs anything else at ERROR naming the exception type and consequence. It still
returns `None`.

**Not** narrowed to propagate. That is the feedback doc's own stated minimum
("At minimum, log the swallowed exception… If the current behaviour is deliberate
for backward compatibility, please say so in the docs"), and raising would turn
every transient throttle across auth, OAuth2 and MCP into a 500 on a release
already validated in production. The tri-state they actually need is on
`get_deletion_status()`, which is the call their guard uses.

### DEL3 — docs only. Landed.

`docs/reference/actor-deletion.rst` §"Actor-scoped writes have no referential
integrity". No strict mode: the feedback doc itself says "the docs change is the
valuable half", and a `require_actor` option adds a read to every write for a
guard the informed caller can place better.

### DEL4 — `actor_deleted_complete`. Landed.

Fired in `handlers/root.py` after `myself.delete()`, with `actor=None,
actor_id=<id>`. Passing `None` in the `actor` slot rather than smuggling a string
into it keeps every lifecycle hook's first argument an `ActorInterface`-or-nothing;
the absence *is* the signal.

This is the finding with the best leverage-to-cost ratio in the whole doc: it
removes the race **at its source** for the common "cancel an external
subscription on deletion" pattern, independently of the tombstone. The tombstone
is the safety net; this is the fix.

Not fired from `ActorInterface.delete()` — that path runs no lifecycle hooks
today, and adding them could double-execute cleanup for applications that already
do it manually. The asymmetry is documented instead.

### DEL5 — orphan detection in the verifier. **Deferred.**

Does not gate the consumer, they are already building their own, and it is the
largest single chunk in the doc. Their four edge cases are too valuable to lose,
so they are written into `docs/reference/actor-deletion.rst`
§"Finding orphaned rows" — each one is a way to delete live data, and a
consumer writing their own sweep needs them whether or not the library ships one.

---

## Acceptance evidence

| # | Requirement | Test |
| --- | --- | --- |
| 1 | DELETED throughout the wipe | sampled at the **first** wipe step and again **after** `Buckets.delete()` — both DELETED |
| — | (why it's needed) | `get_by_id()` asserted **non-None** mid-wipe, pinning the ordering |
| 2 | Outlives 3 days | raw `ttl_timestamp > now + 3d`; expired tombstone reads as absent |
| 3 | Infra failure ≠ deleted | store raising → `UNKNOWN` + ERROR logged; `get_attr_strict` raises where `get_attr` returns `None` |
| 4 | Deleted actor → zero rows | end-to-end webhook stand-in: bucket empty |
| 5 | Live actor + store unreachable → still writes | end-to-end: entitlement written |
| — | Point read | `{GetItem: 1}`, counted with a live-counter check |

`tests/test_actor_deletion_tombstone.py`, 29 cases.

## Two defects caught in review of this work, both fixed

- **A test wiped global state.** `test_tombstone_survives_the_wipe_of_a_system_actor`
  called `Buckets(ACTINGWEB_SYSTEM_ACTOR).delete()`, which removes *every*
  attribute row under that id — including `TRUST_TYPES_BUCKET` and
  `TRUST_PERMISSIONS_BUCKET` (`constants.py:114-115`), shared table state. Under
  `-n auto --dist loadgroup` it could wipe the trust-type registry out from
  under a concurrent worker. It passed, but that is exactly the
  passed-standalone / failed-in-the-full-run shape recorded twice in
  `2026-07-25-rc2-triage.md`. Replaced with a constants assertion plus a test
  that one actor's deletion leaves another's tombstone alone; the real
  behaviour was already covered by the last-wipe-step case, which only touches
  the actor being deleted.

- **The FastAPI dispatch path was unverified.** `_handle_actor_request` prefers a
  `<method>_async` handler variant and only falls back to the sync method in a
  thread pool (`fastapi_integration.py:2498-2524`). Confirmed `RootHandler` has
  no `delete_async`, so Flask and FastAPI both reach the `delete()` that fires
  the hook — but nothing stopped someone adding one later and silently dropping
  `actor_deleted_complete` on the very deployment shape (Lambda container
  images) that asked for it. Now guarded by an explicit assertion with a
  remediation message.

## Gates

- pyright **0 errors / 0 warnings**; ruff check clean; ruff format applied.
- Sphinx builds clean (0 warnings) with all new cross-references resolving.
- DynamoDB: `make test-all-parallel` → **2515 passed, 26 skipped, 0 failed**
  (2486 before; +29 new), stable across three consecutive runs.
- PostgreSQL: the new file → **21 passed, 8 skipped** (skips are the
  DynamoDB-internals cases). Full suite → 6 failures, **all pre-existing**:
  verified by stashing the change and reproducing the identical 6 in the same
  environment (5 × `tests/performance/test_backend_performance.py` failing on
  `invalid input syntax for type boolean: ""` in `postgresql/trust.py`, code this
  change does not touch, plus `test_docker_services`, which needs a running app).

  Worth noting separately: those 5 PG performance failures are a **real
  pre-existing defect**, not just noise. Not in scope here — filed as an
  observation, not fixed.

## Version: rc2 is still correct

Checked rather than assumed, because adding a payload under an already-published
version would be a silent content change: **the `v3.13.0rc2` tag does not
exist**, so nothing has been published to TestPyPI (publication is
tag-triggered, and per `CLAUDE.md` tags release only from master). The
`origin/v3.13.0rc2` *branch* is pushed and contains `9a0a3cb`, which is
harmless. No rc3 needed.

## Not done

- Tag/push. Left to the maintainer.
- DEL5's orphan sweep (above).
- The `subs_list` cache asymmetry and I0, still per
  `2026-07-25-rc2-triage.md` and `thoughts/todo/subs-list-cache-asymmetry.md`.

## Consumer reply — the two things they asked to be told

1. **Yes, the tombstone read is a single point read.** One
   strongly-consistent DynamoDB `GetItem`, measured. `ActorInterface.get_deletion_status(actor_id, config)`.
2. **The actor row still goes last** — preference #2 was not taken, for the
   three reasons above. Their guard keying on the tombstone rather than on
   absence was the right call and is now the documented one.

Also worth flagging to them: the rc2 CHANGELOG re-validation note now names the
deletion path, since they are pinning forward from rc1 in production.
