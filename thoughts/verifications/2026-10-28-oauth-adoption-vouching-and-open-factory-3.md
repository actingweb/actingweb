# Verification: vouched actors, clean-slate adoption, a closable factory, SPA `prompt` (eighth run)

**Date:** 2026-10-28
**Plan:** thoughts/plans/2026-10-26-oauth-adoption-vouching-and-open-factory.md
**Research:** thoughts/research/2026-10-26-v3.16-scope-oauth-adoption-vouching-and-spanned-list-items.md
**Branch:** release/3.16.0-oauth-adoption-vouching
**Commit:** 52abce6 (base; all work uncommitted)

Scope: Iterations entries 47-49, after
`thoughts/verifications/2026-10-28-oauth-adoption-vouching-and-open-factory-2.md`.
No research note was written; these are small fixes recorded in the plan
entries.

## Automated Check Results

- **Browser QA:** N/A. No page changed.
- **Second opinion:** outside-voice ran Codex (`codex exec -s read-only`,
  unsandboxed) and a fresh-context Claude over entries 47-49. `/code-review high`
  ran over the whole diff. A focused **security review** of the cap and the
  successor step found nothing at confidence 8 or above.
- **Full tier:** this is the run recorded in the plan's batch after entries
  47-49, taken on this tree. Only plan text has changed since; it was not
  re-run, because the machine's load average stood at 35 from other
  sessions.
  - ruff, ruff format: pass (423 files). pyright: 0/0.
  - `verify_groups.py`: 50 groups.
  - DynamoDB `make test-all-parallel`: 4061 passed, 31 skipped, 1 failed.
    The failure is `test_async_hooks.py::TestAsyncHookFlaskCompatibility::test_asyncio_gather_in_flask_context`,
    which asserts `elapsed < 0.1` and ran at a load average of 35. Re-run
    sequentially, it passed 3/3, and its file passed 36/36. This work does
    not touch it.
  - PostgreSQL `make test-all-parallel`: 3951 passed, 142 skipped.
  - Docs build: succeeded.
  - Benchmarks: 17 passed. The timings are not comparable under that load
    (attribute read 0.71 ms, actor delete 3.52 ms, actor create 9.7 ms).
    Re-measure on a quiet machine.

## Phase Verification

### Entry 47: the lockout sentence (BG) - VERIFIED, one addition

`CHANGELOG.rst:72-77` is now accurate for the verification click. It does
not say that a squatter's `factory` actor causes the same 409 before any
click (see BV).

### Entry 48: re-read before each delete, and the cap (BH, BI) - ISSUES FOUND

- `oauth2.py`:
  - `SWEEP_LIMIT`;
  - `_sweep_factory_actors` re-classifies inside the loop and truncates to
    the lowest 10 ids.
- Tests (both fail with their fix disabled):
  - `test_sibling_vouched_during_the_sweep_is_kept`;
  - `test_one_sign_in_removes_at_most_the_limit`.
- The cap makes leftover factory actors a normal state on the replace
  path, and the successor step still trusts a ranked pick (BR). The cap
  bounds deletes but not reads (BS). The replace path with more than 10 is
  untested (BU).

### Entry 49: consistent peer-trustee reads (BJ) - VERIFIED

`db/dynamodb/peertrustee.py:154,174` pass `consistent_read=True`. That is
valid: this is a base-table hash-key query, and PynamoDB's `Model.query`
takes the keyword. `test_peer_trustee_reads_are_consistent` fails without
it.

## Security property demonstrated

With more than `SWEEP_LIMIT` factory actors and no owner actor, the leftover
factory actors classify as `replace`, so the sign-in creates a fresh
successor and is never handed a squatter's actor (`oauth2.py:2142-2151`).
The security review traced this and found nothing at confidence 8 or above.

## Previous Verification

**Previous:** thoughts/verifications/2026-10-28-oauth-adoption-vouching-and-open-factory-2.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| BG: lockout after the click | Docs fixed; session-at-click in todo | Entry 47 |
| BH: re-read not just before delete | Fixed | Entry 48 |
| BI: unbounded inline wipes | Fixed (deletes capped; reads not: BS) | Entry 48 |
| BJ: inconsistent peer-trustee reads | Fixed | Entry 49 |
| BK-BQ (Low) | Filed | `thoughts/todo/adoption-fault-and-hygiene-followups.md` |

## Remaining Tasks

- [ ] BR and BS, which belong to the root-cause plan the owner asked for
  (fault semantics, creator uniqueness); see the Overall Assessment.
- [ ] BU, BV and BW, small.
- [ ] Re-measure the benchmarks on a quiet machine.
- [ ] Emm AI prod: `2f4c5bea…`.
- [ ] Release PR.

## Issues Found

### BR. An unreadable marker ranks like an unvouched one, so one read fault can strand the owner's actor
**Severity:** Medium
**Description:** `actor.py:309-318` `_candidate_rank` maps
`classify_marker(...) is None` to rank 1, the same rank as `email_unverified`,
`creator_changed` and legacy actors. Two ways it bites:
- **Replace path, beyond the cap** (outside voice, both reviewers):
  leftover factory actor F11, whose marker read faults, ties with the
  owner's unvouched U and wins on its lower id. `classify_store` then reads
  it as `replace`, and the else branch (`oauth2.py:2142-2147`) creates a new
  vouched V, which strands U for good. The comment at `:2096-2098` says
  this must not happen.
- **Vouched owner** (code review): a fault on the owner's vouched V lets a
  lower-id unvouched sibling A win; for example, the attacker's actor
  renamed to the victim's address (`creator_changed`). A is cleaned and
  vouched, and both then rank 0, so A's lower id strands V. The attacker
  loses control of A in the clean, so this is data stranding, not access.

**Location:** `actingweb/actor.py:305-318`, `actingweb/oauth2.py:2100-2151`
**Recommendation:** an unreadable candidate fails the lookup closed, and the
successor step classifies the `remaining` rows strictly, refusing to create
while any is not `replace`. This is the fault-semantics root cause again.

### BS. The cap bounds deletes, not reads
**Severity:** Medium
**Description:** Every owner sign-in reads every factory actor before the cap
applies:
- `get_from_creator` ranks every candidate (`actor.py:366-370`);
- `_factory_siblings` classifies and loads every sibling
  (`oauth2.py:1830-1851`).

So it costs about 3N reads per sign-in to remove 10, and the open factory
lets anyone add actors faster than sign-ins remove them. A fault on sibling
#500, which the cap never reaches, also fails the replace closed, so the
cleanup makes no progress.
**Location:** `actingweb/actor.py:356-375`, `actingweb/oauth2.py:1822-1858`
**Recommendation:** truncate before reading: rank in id order until the
first vouched actor, and have `_factory_siblings` require readability only
for the ids it will touch. The lasting fix is the uniqueness root cause:
with one actor per creator, there is nothing to rank or sweep.

### BU. The cap on the replace path is untested
**Severity:** Medium
**Description:** `test_one_sign_in_removes_at_most_the_limit` uses a vouched
owner. Nothing exercises `oauth2.py:2086` with more than `SWEEP_LIMIT`
siblings, either with leftovers plus an unvouched owner (which should clean
the owner) or with leftovers and no owner (exactly one successor, never a
factory actor). BR sits in that gap.
**Recommendation:** add both cases with `SWEEP_LIMIT` patched to 2, plus a
variant where one leftover's `classify_marker` answers None.

### BV. A squatter's factory actor locks an email-less-provider user out of the free-text form
**Severity:** Low
**Description:** `oauth_email.py:468-474` answers 409 for any existing actor,
`factory` included. While the factory is open, anyone can `POST /` the
address of a user whose provider supplies no verified email, and that user
can never use the free-text form for it. Nothing reaches the factory actor,
because those sign-ins never prove the address. The behaviour is older than
3.16, but entry 47's CHANGELOG sentence reads as if only the click causes it.
**Recommendation:** say so in the sentence and point at
`with_open_factory(False)`. Alternatively, let the form replace a `factory`
actor: the emailed link still has to prove the address.

### BW. "At most 10" is 11 on the replace path
**Severity:** Low
**Description:** `CHANGELOG.rst:88`. A replacing sign-in removes the actor it
replaces through `_remove_for_replacement` and then up to `SWEEP_LIMIT` more.
**Recommendation:** "the replaced actor and at most 10 beside it", or count
the victim inside the cap.

### Notes (not findings)

- **A just-created factory actor missing from DynamoDB's creator index**
  (code review): `_factory_siblings` fails closed when the victim is not
  listed. On the factory-form OAuth flow, that would fail the first login if
  the callback came back within the index lag. The lag is usually well
  under the OAuth round trip, so it is Low. Uniqueness enforcement removes
  the dependency on the index.
- **Already filed, not repeated:**
  - BK (the stale index creator);
  - BP (the double SPA scan);
  - BQ (SPA wiring);
  - the type hints;
  - the FastAPI 400-as-200, which is older than 3.16.
- **`revoke_all_tokens_for_actors` counts a failed delete as revoked**
  (`oauth_session.py:930,948`). The count was computed the same way before
  the method was split out. Strict callers raise anyway; for non-strict
  callers, the log line overstates.
- **Flask `GET /?format=json` reflects `Origin` with credentials**
  (`factory.py:134-141`). The handler's CORS headers are older than 3.16 and
  FastAPI already served them. The content is public configuration, so the
  impact is Low. Worth tightening with the root-cause work or separately.

## Overall Assessment

Entries 47-49 do what they claim, each has a test that fails without it, the
full tier is green (one load-induced timing flake re-run clean), and the
security review again finds no exploit. What remains is not new kinds of
bug.
- **BR** is a backend fault being read as an answer.
- **BS** is the cost of not having one actor per creator.
- **BU** is the missing test for BR.

Those are the two root causes the owner has asked to implement. I recommend
not running another iteration here. Fold BR, BS and BU into the root-cause
plan: with strict reads at the DB layer and one actor per creator, the
ranking, the sweep cap and the successor guesswork become unnecessary.
BV and BW are a sentence each and can go with that plan's docs, or into this
branch before the release PR.
