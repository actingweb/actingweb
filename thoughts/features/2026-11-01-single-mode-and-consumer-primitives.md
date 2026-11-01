# Feature: One mode after the 3.16 upgrade, and the two primitives the consumer asked for

**Date:** 2026-11-01
**Author:** Greger Wedel (with Claude), from the 3.16 scope review of 2026-11-01

## Problem

Three populations feel this, and the first two are known people.

**The operator** (the owner, running `actingweb_mcp` in production and the
demo at `demo.actingweb.io`, measured on upgrades that do not take the
service down and on what each deployment costs to run) pays for every
second mode the library keeps alive. The legacy property reverse-lookup
path (a value-keyed GSI, a v1 lookup table, their fallback tiers and the
`use_lookup_table` flag) has been deprecated since v3.13 and both
deployments left it long ago, yet its tables, startup branches and
~40 directly-constructed test accessors are still there. Creator uniqueness
shipped in 3.16 as an opt-in, so the duplicate-tolerant adoption code
(ranking, sibling sweep, `SWEEP_LIMIT`, the recursive hand-off) stays
beside the enforced path and has to be reasoned about on every change to
sign-in. Every MCP connector registration writes a client record and a
system-actor trust row that nothing ever deletes, and each registration
walks the full trust list to find its own row: the `mcp_clients` bucket and
the global client index grow by one per connect, forever, which the
consumer's connector audit found on 2026-09-21.

**The consumer's client developer** (the person maintaining the Emm apps'
`TokenManager` and the MCP tools, measured on sessions that do not end for
no reason and on documents that are not duplicated) works around two gaps.
A 401 on the refresh grant is final by the SPA guide's own rule, but not
every 401 that reaches the app is the library's: a captive portal, a tunnel
or a JSON-answering gateway can send one, and the client can only sniff the
body (`isApi401` accepts any JSON with an `error` or `detail` key), so such
a gateway can still sign the user out. And there is no atomic
"store this attribute unless one exists": two MCP clients asking for an
instructions-unlock window within milliseconds both store an ask, because
the only tools are compare-and-swap on an existing value or read-then-set.

**An unknown third-party deployment** on PyPI that still runs the legacy
lookup, or carries duplicate creators, works today and after 3.16 must act.
Nobody has heard from one; the risk is that they exist and upgrade blind.

**Demand evidence:** the consumer filed both primitives as its own todos
(`client-401-api-marker.md` #150, the unlock-window gap in
`instructions-unlock-window-consent-gaps.md`) and asked for the 401 half in
3.16 by name; it backfilled 12 production accounts by hand on 2026-10-27 to
survive the 3.16 adoption rule; its connector audit measured the
registration growth. The legacy-GSI and duplicate-tolerant code have no
user who would miss them; that is a hypothesis about third parties, not a
measured fact.

## Users

- **Operator of an ActingWeb deployment** (the owner for the two known
  ones; measured on zero-downtime upgrades and running cost) — needs the
  upgrade to tell them, before it serves a request, exactly which command
  to run if their data is not ready, and needs nothing to grow without
  bound afterwards.
- **Consumer client developer** (the Emm apps' and MCP tools' maintainer;
  measured on unexplained sign-outs and duplicate writes) — needs a 401
  they can trust and a first-writer-wins attribute write, so two
  workarounds can be deleted.
- **Third-party deployment on the legacy lookup or with duplicate
  creators** — must be stopped at startup with the fix named, never left
  running with reverse lookups that answer "no such actor" (which creates a
  second actor at the next sign-in).
- **Custom database backend authors** — affected by one more protocol
  method; 3.16 already asks two of them.
- **MCP client authors and direct `check_and_verify_auth()` callers** —
  affected by the small behaviour changes (parse error, option tags, glob
  escapes, a required config).

## Premises

1. The right problem is "a 3.16 upgrade leaves no second mode alive and
   gives the consumer the two primitives it asked for"; no reframing gives
   a simpler or more impactful release — agreed 2026-11-01
2. Doing nothing costs dead code paths kept for holdouts nobody has heard
   from, a registry that grows by one per connect forever, and two consumer
   workarounds that each fail in a user-visible way — agreed 2026-11-01

## Desired Outcome

After upgrading to 3.16 an operator runs one library with one reverse-lookup
mechanism and creator uniqueness on, and a deployment whose data is not
ready for either is stopped at startup by a message naming the command that
makes it ready; nothing in the MCP client registry outlives the tokens that
justify it. The consumer deletes its 401 body-sniffing and its
read-then-write ask, because the library's 401s carry a stable code and an
attribute can be created only-if-absent. Every other 3.16 behaviour change
that could only ride a minor (the MCP parse error, the advertised option
tags, glob escapes, a required auth config) ships in the same release, so
the next patch releases carry none of them.

**10x version:** the upgrade is self-diagnosing end to end — `check_ready()`
names every migration still owed with a dry-run command for each, the
consumer's two workarounds are replaced by one-line library calls, and no
3.17 is needed for any of the known minor-only todos.

**Smallest version:** the legacy-lookup removal with a fail-closed start,
the uniqueness default flipped with the opt-out kept, the two consumer
primitives, and registration expiry. The small minor-only items are the gap
between the two; this round takes them because they are hours each and
cannot ride a patch.

## User Experience

**Main path (operator, both known deployments):**
1. Reads the 3.16 migration guide: both deployments already run the lookup
   table and `with_unique_creator()`, so the only new steps are the
   `actingweb-unique-creators` Step 0 they already owe and the vouched
   marking.
2. Deploys. `check_ready()` passes; the application serves.
3. Over the following weeks the `mcp_clients` bucket and the system actor's
   trust list stop growing: a connector that is registered but never
   authorized is gone a day later; one that is used lives as long as its
   newest refresh token and disappears with it. Reconnecting re-registers
   (claude.ai's DCR fallback already does this), so nobody notices.

**Main path (consumer client developer):**
1. Pins 3.16. Changes `isApi401` to "the response carries
   `X-ActingWeb-Error`" and deletes the body sniffing; a gateway's JSON 401
   now reads as "no answer" and keeps the session.
2. Replaces the unlock-ask's read-then-write with
   `create_attr_if_absent(...)`: the first client's ask is stored, the
   second learns it lost and shows the existing ask instead of a second
   banner.

**Edge paths:**
- **Third-party deployment still on the legacy lookup upgrades blind** —
  the process refuses to start with an error naming
  `scripts/backfill_property_lookup.py`, the dry-run flag and the migration
  guide section; `with_legacy_property_index(True)` or
  `USE_PROPERTY_LOOKUP_TABLE=false` fail at configure time with the same
  pointer. Downtime until the backfill runs; never a second actor.
- **Deployment with duplicate creators upgrades blind** — refuses to start
  with `UniqueCreatorNotReady`, as a flag-on deployment does today, naming
  `report`, `resolve --apply`, `enable --apply`; the operator may instead
  opt out with `with_unique_creator(False)` and keep running as before.
- **A connector's registration expired while the user was away** — the
  next connect answers `invalid_client`; the client re-registers and the
  user authorizes again. No data is lost; the actor and its memories are
  untouched.
- **A direct `check_and_verify_auth()` caller omits the config** —
  `TypeError` at the call, naming the argument; the two integrations are
  unaffected.
- **An authenticated MCP client posts a body that is not JSON (or an empty
  one)** — HTTP 400 with JSON-RPC `-32700 Parse error`; an unauthenticated
  one still gets the 401 discovery challenge first, because auth is decided
  before the body is read.
- **A permission rule names an identifier with a literal `*`** — the
  author writes `\*` and it matches only `*`; a rule that already contains
  a backslash should be re-read, since its meaning changes.

## Success Measures

| Measure | Target | How we observe it |
| --- | --- | --- |
| Deployments that start with a lookup table or `creators` table that is not ready | zero | `check_ready()` raises; the error line in the startup log, and a test that pins both refusals |
| `mcp_clients` bucket and system-actor trust row count in the consumer's prod | stops growing; falls to about the number of live connectors within one refresh lifetime | the consumer's connector audit script re-run 30 days after the pin, compared with the 2026-09-21 numbers |
| Sign-outs caused by a non-library 401 in the consumer's apps | zero after the client change | the consumer's `[TokenManager] refresh failed` diagnostic with a 401 and no `X-ActingWeb-Error` |
| Duplicate instructions-unlock asks | zero | the consumer's ask row after a concurrent-request test; no library-side observation exists |
| Legacy lookup code, tables and tests remaining | zero | `grep` for `PropertyLegacy`, `PropertyIndex`, `get_v1`, `use_lookup_table`; the removed test files |
| Minor-only todos left in `thoughts/todo/` after the release | only those deliberately left (`/sessions` route, MCP batch receive, dual-era) | `thoughts/todo/INDEX.md` |

We cannot observe third-party deployments at all; whether any is stopped
by the fail-closed start is unknowable from here, which is why the start
must name its own fix.

## Hypothesis (untested)

- **Legacy lookup removal.** Delete the `PropertyLegacy` model, the
  `PropertyIndex` GSI class, the legacy branch of
  `get_actor_id_from_property` on both backends (including PostgreSQL's
  value-only sequential scan), the v1 lookup-table tier, and the
  `use_lookup_table` surface (`with_legacy_property_index()`,
  `USE_PROPERTY_LOOKUP_TABLE`, the mode conditional in the pre-warm); keep
  `with_indexed_properties()`. The startup probe that today logs an ERROR
  when properties exist and the v2 lookup table is empty becomes a
  `check_ready()` refusal, shaped like `UniqueCreatorNotReady`: definite
  absence refuses, a fault refuses. Config injection through the
  `actingweb.db` factories becomes mandatory (constructing an accessor
  without a config raises), which also removes the import-time
  table-name reads. `scripts/backfill_property_lookup.py` stays.
- **Uniqueness default.** `unique_creator` defaults to on in `Config` and
  `ActingWebApp`; `with_unique_creator(False)` survives, so the ranking,
  sibling sweep and `SWEEP_LIMIT` survive with it, documented as the
  opt-out path. The test that pins the default flips.
- **Registration expiry.** A registration and its trust row are written
  with a 24-hour TTL; every token issue or refresh for that client raises
  both TTLs to the new refresh token's expiry (one write per refresh, which
  already writes). The database deletes them; no scheduled job. The
  registration path stops walking the trust list to find its own row.
- **401 marker.** Every error the SPA token endpoints answer carries
  `X-ActingWeb-Error: <stable code>`; the code is also added to the JSON
  body. `spa_cors_headers()` and the fault handler's CORS set expose it.
  The SPA guide's rule 7 is rewritten around the header.
- **Create-if-absent.** `create_attr_if_absent(actor_id, bucket, name,
  data, timestamp=None, ttl_seconds=None) -> bool` on
  `DbAttributeProtocol`, both backends and `attribute.Attributes`: `True`
  when this call created the row, `False` when one exists, `DbError` on a
  fault. In the same change `conditional_update_attr` and
  `delete_attr_conditional` raise `DbError` on a fault and keep `False` for
  a lost condition.
- **Small items.** `check_and_verify_auth()` helpers require `config`
  (`TypeError` otherwise); `_glob_to_regex` honours `\*` and `\?` as
  literals; `POST /mcp` answers `-32700` for a body that is not JSON or is
  empty, after authentication; `/meta/actingweb/supported` drops
  `sessions` and adds `listproperties`.

**Alternatives considered:**
- **Deprecation notice in 3.16, removal later** — rejected by the owner:
  the removal rides 3.16 and the notice is unnecessary.
- **Uniqueness on with the opt-out removed (one mode, duplicate-tolerant
  code deleted)** — rejected: it forces every deployment with duplicates
  through `resolve` before it can start, with no way to defer.
- **Registration idle clock (90 days after the last token use, stamped
  coarsely)** — rejected: an extra write and a second notion of
  liveness; the token's own expiry is the only liveness the registry needs.
- **Registration expiry by a sweep from the token store** — rejected:
  exact, but needs a scheduled run and a global index walk; TTLs do it for
  free.
- **Not persisting a registration until it is authorized** — rejected: a
  24-hour TTL on the never-authorized row gives the same outcome without a
  second registration shape.
- **A bare marker header on 401s only; or exposing `X-Request-ID`** —
  rejected: a stable code is the same cost and gives the client the error
  code the body lacks; `X-Request-ID` is a header a gateway may add too.
- **`-32700` pre-empting the 401** — rejected: an unauthenticated client
  must still see the discovery challenge.
- **Warn one release before requiring the auth config** — rejected: only
  direct callers are affected, and the rebuild would stay another release.

## Not In Scope

- **The `prop#`/`list#` key-prefix scheme** — plan-sized storage-key
  migration; spanning already took the large bodies out of the partition.
  The lookup removal is its prerequisite, so 3.16 makes it possible next.
- **A `/sessions` route and hook** — needs the session-model decision; only
  the advertised tag is fixed here.
- **MCP batch receive, or dropping protocol `2025-03-26`** — `2025-03-26`
  is the default negotiated version; a compatibility decision, not a
  cleanup.
- **Dual-era (2026-07-28) MCP support** — waits for a client going
  modern-only.
- **A post-authentication hook, CIMD, RFC 8707 audience binding** —
  connector-conformance items with no live failure; pick them when a
  directory submission needs them.
- **The `ListAttribute` shift-loop port** — plan-sized, and the recheck
  moved its weight (peer replicas run through it); decided separately.
- **Resumable actor deletion** — its own plan.
- **The consumer's halves** — API Gateway's exposed headers, `isApi401`,
  the unlock-ask rewrite, dropping `_provider_vouched` and the backfill
  script; they follow the pin.

## Open Questions

### About the codebase
- Which tests construct `DbProperty`/`DbPropertyList`/lookup accessors
  without a config (the todo says ~40), and does any production path still
  do so?
- Does PostgreSQL have a backfill for the v2 lookup table, or does the
  removal of its value-only sequential scan need one? What does a
  PostgreSQL deployment that never set `indexed_properties` look like
  after the removal?
- Can the startup lookup probe be made definite on both backends (table
  present, row present) the way `check_ready()` is for `creators`, and
  what does it cost on a large properties table (today it scans with
  `limit=1`)?
- Can a trust row carry a TTL on both backends, or do only attribute rows
  (`mcp_clients`, the global index) have one? If not, what deletes the
  system-actor trust row when the registration expires?
- Where is the one place a token issue or refresh can raise the
  registration's TTL, and does the MCP refresh ladder's rotation write
  already touch the client record?
- What does an expired registration look like to the authorize and token
  endpoints today (`invalid_client`? a 500?), and does claude.ai's DCR
  fallback re-register on that answer?
- Which SPA error sites have no stable code yet, and is there an existing
  code vocabulary (`invalid_grant`, `invalid_request`) to reuse for
  `X-ActingWeb-Error`?
- Which callers read `False` from `conditional_update_attr` or
  `delete_attr_conditional` as "lost" and would now see `DbError` on a
  fault (the adoption restore path is one)?
- Which permission rules in the shipped defaults, the demo or the
  consumer contain a backslash, and would change meaning?
- Does the FastAPI MCP path read the body before or after authentication,
  so that "401 first" holds there as well as in Flask?
- With `unique_creator` on by default, which tests and fixtures create
  actors with a shared creator and must opt out or change?

### About users and the outside world
- Does any PyPI user still run `with_legacy_property_index(True)` or
  `USE_PROPERTY_LOOKUP_TABLE=false`? (Unknowable; the fail-closed start is
  the answer to not knowing.)
- What exactly does claude.ai do when a stored registration answers
  `invalid_client` — silent re-registration or a user-visible reconnect?
- The consumer's connector-audit numbers from 2026-09-21, for the
  30-day comparison after the pin.
