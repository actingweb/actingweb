# Verification: MCP trust cache client crossing (authorization bypass)

**Date:** 2026-07-31
**Plan:** `thoughts/plans/2026-07-30-mcp-trust-cache-crosses-clients.md`
**Research:** `thoughts/research/2026-07-30-mcp-trust-cache-crosses-clients.md`
**Branch:** `bug/trust_mcp_cache`
**Commit:** `c2a0a51` (plus three fixes applied during this verification, see
*Fixes applied*)

**Scope:** This verification covers **Phases 1–4 in full, and Phase 5's code
and documentation deliverables**. It does **not** cover Phase 5's final step
(PR opened and merged to master) or Phase 6 (cutting `v3.13.0rc3`), neither of
which has happened. The plan therefore stays `status: active` with no
`verified:` back-link — adding one would assert the release landed when it has
not.

## Automated Check Results

All checks were run firsthand against the working tree, not taken from the
plan's claims.

- **Ruff check:** Pass — `All checks passed!`
- **Ruff format:** Pass *after a fix* — initially failed on two new test files
  (`tests/test_flask_context_integration.py`,
  `tests/test_runtime_context_isolation.py`). Reformatted; now
  `303 files already formatted`. See *Issues Found #1*.
- **Pyright:** Pass — `0 errors, 0 warnings, 0 informations`
- **Pytest (parallel, `make test-all-parallel`):** Pass — **2572 passed,
  26 skipped, 0 failed** in 51s. Exactly matches the count the plan claims for
  Phases 4 and 5.
- **Pytest (sequential, `make test-integration`):** Pass — **756 passed,
  8 skipped, 0 failed** in 58s. Run because Phase 4 changes concurrency
  semantics and parallel runs can mask isolation issues. Matches the plan.
- **`poetry build`:** Pass — built `actingweb-3.13.0rc2.tar.gz` and
  `actingweb-3.13.0rc2-py3-none-any.whl`.
- **Version strings:** `pyproject.toml:3` and `actingweb/__init__.py:1` both
  read `3.13.0rc2` — correctly **not** bumped on the branch, per `CLAUDE.md`.
- **Sphinx docs build:** Pass *after a fix* — initially emitted 10
  errors/warnings, 5 of them distinct and all newly introduced by this branch's
  `runtime_context.py` docstring rewrite (proved by parsing the base commit's
  and HEAD's docstrings through docutils side by side: `cc29c03` → 0 messages,
  `HEAD` → 5). Fixed; the build is now **0 warnings, 0 errors**. See
  *Issues Found #2*.
- **Leftover debug code:** none — grepping the whole `actingweb/`+`tests/` diff
  for `TODO`/`FIXME`/`XXX`/`HACK`/`print(`/`breakpoint(`/`pdb` returns nothing.
- **Working tree:** clean at the start of verification; the throwaway
  acceptance-probe test file named in Phase 5 was indeed deleted.

## Phase Verification

### Phase 1: Tuple trust-cache key, safe eviction, cache hygiene — VERIFIED

**Changes verified:**

- `actingweb/handlers/mcp.py:49` — `_trust_cache: dict[tuple[str, str], dict[str, Any]]`,
  documented as `(actor_id, client_id) -> {"trust": …, "cached_at": float}`.
  Matches the plan.
- `actingweb/handlers/mcp.py:85-113` — all reads and writes funnel through
  `_trust_cache_key()` / `_trust_cache_get()` / `_trust_cache_put()`. The
  single-construction-helper requirement holds: the only direct index write in
  the module is inside `_trust_cache_put`.
- `actingweb/handlers/mcp.py:94-108` — the truthiness trap the plan called out
  is handled correctly: `_trust_cache_get` returns an explicit `(hit, trust)`
  tuple, and its docstring tells callers to branch on the flag, never on the
  trust's truthiness. Both call sites do.
- `actingweb/handlers/mcp.py:1426-1438` (hot path) and `:1506-1507` (full auth)
  — both key by the tuple; a cached `None` still yields `peer_id = ""` at
  `:1445-1447` and `:1519` rather than raising.
- `actingweb/handlers/mcp.py:116-127`, `:203-236` — eviction and cleanup both
  scan `.copy()`, not the live dict. The plan specified `list(d)`; `.copy()` is
  a strictly safer deviation, documented in the phase notes with the reasoning.
- `actingweb/handlers/mcp.py:71-72`, `:1386-1390` — the dead
  `time.time() % 20 == 0` scheduler is replaced by a monotonic
  `_next_cleanup_at` deadline. The lock-free-ness argument in the comment is
  sound (idempotent cleanup, so a racing double-run is harmless) and is the
  right call versus the counter the plan first suggested.
- `actingweb/handlers/mcp.py:1688-1721` — the C11 invariant check is
  format-aware (handles `@`/`.`/`:` normalization), logs only `actor_id`,
  `client_id` and the peer id's **prefix segment**, never the raw peer id
  (which embeds a user email) and never `token_data`, and never denies. Wired
  into both resolution sites (`:1436`, `:1507`).
- `actingweb/handlers/mcp.py:1372-1381`, `:44-48` — the stale "cached per
  actor" docstring and the false `trust_context` promise on the `_actor_cache`
  declaration are both corrected.
- `docs/guides/mcp-applications.rst:832-843`, `docs/guides/caching.md` — both
  updated and now agree with the implementation.

**Tests verified:** `tests/test_mcp_trust_cache_key.py` — 12 tests, all
meaningful. They exercise the *real* module globals and the real
`authenticate_and_get_actor_cached()`, mocking only the storage and OAuth2
boundaries, and clear all three caches in setup/teardown so ordering can't
matter. Coverage matches the plan item-for-item: A/B/A/B/A identity sequence
(asserting `client_id`, `peer_id` *and* `trust_relationship.peerid`, plus
`_cache_stats` to prove the later requests are genuine hits), resolver call
counts, per-client cached `None`, actor-expiry eviction scoped to one actor,
a separate test that the new scheduler trigger actually fires cleanup,
`clear_token_from_cache`, concurrent-mutation eviction, async parity, and three
invariant-check tests including one asserting no email or token data in the
emitted record.

**Deviations from plan:** Two, both acceptable and both documented in the
phase's notes — `.copy()` instead of `list(d)`, and a monotonic deadline
instead of a request counter.

One note on test technique: `test_this_test_fails_against_actor_only_keying`
*simulates* actor-only keying by patching the two cache helpers, rather than
mutating the source. That is a reasonable permanent form of the teeth-proof
(a real mutation can't live in the suite), and the plan records that the real
mutation was performed manually and did fail as expected.

**Repo-wide check:** `grep -rn "_trust_cache"` across the whole repository (not
just `handlers/mcp.py`) confirms the Evaluation Notes' claim firsthand — the
only production references are in `actingweb/handlers/mcp.py`, and every test
and doc reference uses explicit tuple keys.

### Phase 2: Sync `resources/read` authorization (C8) — VERIFIED

**Changes verified:**

- `actingweb/handlers/mcp.py:1136-1160` — the dead
  `getattr(actor, "_mcp_trust_context", None)` lookup is gone; the sync path
  now reads `RuntimeContext` and evaluates a real permission decision with
  `operation="read"`, mirroring `async_mcp.py:334-355`.
- `grep -rn "_mcp_trust_context" actingweb tests docs` returns **nothing** —
  including the fourth site (a test docstring) that the phase's Changes list
  did not enumerate but the implementation caught.

**Tests verified:** `tests/test_mcp_resource_read_permissions.py` — 5 tests:
sync deny/allow, sync-vs-async parity on both an allowed and a denied peer, and
a no-context regression (later inverted by Phase 3 to assert the fail-closed
denial, which is the correct semantics once "no context" and "no trust" are the
same case). The plan records the mutation-based teeth-proof for this phase too.

**Deviations from plan:** The three test fakes were *removed* from rather than
*converted to* real runtime context, because none of their assertions had ever
depended on the dead attribute. Documented, and correct — converting them would
have added ceremony with no coverage gain.

### Phase 3: Exact trust matching and fail-closed authorization — VERIFIED

**Changes verified:**

- `actingweb/handlers/mcp.py:1599-1686` — the resolver is exact. Arm 1 is
  `oauth_client_id == client_id`. Arm 2 is gated on an OAuth2-family
  `established_via` (or `None` with a legacy `oauth2:`/`oauth2_client:` peer-id
  prefix) **and** full-string set membership against reconstructed candidates —
  no containment, no `endswith`, no bare segment compare. The dead
  `if user_email:` block is gone.
- `actingweb/handlers/mcp.py:1676-1681` — the misleading "permissions will be
  empty" warning is replaced with an actionable one naming `actor_id`,
  `client_id` and the likely cause, without logging the peer id or token data.
- `actingweb/oauth2_server/oauth2_server.py:373-381` — the unreachable
  `else: established_via = "oauth2_interactive"` is deleted and replaced with a
  comment explaining the invariant.
- **Fail-closed lands in every gate the plan enumerated, on both transports.**
  Verified by reading each one: sync `tools/list` (`mcp.py:527-532`),
  `resources/list` (`:777`), `prompts/list` (`:863`) return an empty result
  before the evaluator try/except; sync `tools/call` (`:940`), `prompts/get`
  (`:1022`), `resources/read` (`:1131`) and async `tools/call`
  (`async_mcp.py:138`), `prompts/get` (`:227`), `resources/read` (`:334`) all
  call the shared `_require_mcp_peer_id()`.
- **Placement is correct** — the discipline the plan insisted on holds
  everywhere I checked. Each `_require_mcp_peer_id()` call sits *before* the
  `try:` that imports and constructs the evaluator, so the availability
  fail-open cannot intercept the no-trust denial. In `_handle_resource_read`
  it is also outside the method's *outer* `try`, so the general exception
  handler cannot swallow it either.
- **Fail-open on evaluator exceptions is preserved and commented as a
  deliberate contrast** (`mcp.py:945-947`, `:965-967`).
- **Denial text is distinguishable** — "no trust relationship resolved for this
  client" versus "you don't have permission to use tool 'X'".
- `actingweb/handlers/mcp.py:62` — `_TRUST_CACHE_NEGATIVE_TTL = 10.0`, with a
  comment explaining why a cached `None` needs a short bound under fail-closed.
- **`operation=` strings now agree across transports.** Verified by grepping
  both files: tools → `"use"`, prompts → `"invoke"`, resources → `"read"` on
  both sides. The async `tools/call` value changed from `"invoke"` to `"use"`.
- **Auth always precedes the gates** — `post()` (`mcp.py:305-318`) returns 401
  before dispatch when `authenticate_and_get_actor_cached()` returns `None`,
  and authentication always sets MCP context (with `peer_id=""` when no trust
  resolved), so the `not peer_id` predicate correctly covers both "no context"
  and "no trust".

**Tests verified:** `tests/test_mcp_fail_closed_authorization.py` — 23 tests
covering exact matching (8, including explicit rejection of a peer id that
merely *contains* the client id, one that merely *ends with* it, and one whose
`established_via` is outside the OAuth2 family), fail-closed on all six gates
across both handlers (10), fail-open-preserved (1),
denial-survives-broken-evaluator (1), negative TTL (2), and the
`oauth2_interactive` reachability assertion against the real
`OAuth2StateManager` (1). The phase notes record that the
placement-discriminator test was itself validated against two different
mutations, the first of which did *not* reproduce the risk — that is exactly
the right level of rigor for a test whose whole job is to catch a placement
regression.

**Deviations from plan:** None material. The plan's contingency for an
`oauth2_interactive` resolver branch was correctly not exercised (the branch is
provably unreachable). The batch of pre-existing tests that relied on
`peer_id = None` meaning "skip the gate" were given a resolved peer id plus an
allow-everything evaluator, preserving what each test actually asserts.

### Phase 4: Request-scoped `RuntimeContext` via ContextVars — VERIFIED

**Changes verified:**

- `actingweb/runtime_context.py:79-115` — storage is a module-level
  `ContextVar[dict[str, dict[str, Any]] | None]` keyed by `_actor_key(actor)`,
  defaulting to `None` (not a shared mutable `{}`) and normalized through
  `_all_contexts()`. **No attribute-storage fallback anywhere** — confirmed by
  reading every accessor.
- `actingweb/runtime_context.py:205-214`, `:354-366` — writes build a *new*
  outer dict and a *new* per-actor dict rather than mutating in place, which is
  what makes `copy_context()` boundaries safe. Correct and necessary.
- **The public API is unchanged** — `RuntimeContext(actor)`, `set_*`/`get_*`,
  `get_request_type`, `clear_context`, `has_context`, `set_custom_context`,
  `get_custom_context`, and the module-level `get_client_info_from_context` all
  keep their signatures. `clear_all_context()` is added as framework/test
  plumbing.
- `actingweb/interface/hooks.py:560-577` — the executor hop captures
  `contextvars.copy_context()` **on the calling thread** and submits
  `ctx.run, asyncio.run, coro`. This is the exact fix shape the plan specified;
  wrapping only the coroutine would not have worked.
- `actingweb/interface/integrations/flask_integration.py:117-132` —
  `teardown_request` (not `after_request`) clears context, so an exception
  propagating out of a view cannot leak onto the next request on a reused
  worker thread.
- `actingweb/interface/integrations/fastapi_integration.py:474-483` — the
  middleware `finally` clears runtime context alongside request context, with
  an honest in-line comment that this is defense in depth because Starlette's
  `BaseHTTPMiddleware` child task already provides the primary boundary.
- `fastapi_integration.py:564-580` — the existing `copy_context()` propagation
  into thread-pool work is preserved, and a **fresh** copy is taken per call,
  so sync handlers dispatched from FastAPI get correct isolation too.
- `docs/guides/hooks.rst:304-320` — the "request-scoped and automatically
  managed" claim is now true and explained, with a `.. note::` documenting the
  one real semantic change for application code.

**Tests verified:** `tests/test_runtime_context_isolation.py` (7) plus 3 each in
`tests/test_flask_context_integration.py` and
`tests/test_fastapi_context_integration.py`, and a reset fixture added to
`tests/integration/test_runtime_context_advanced.py`. Coverage matches the plan:
deterministic asyncio interleaving, threaded isolation via barrier (including a
reused-worker-thread scenario), an async hook reading context after an `await`,
the executor hop exercised through the real `HookRegistry` public API rather
than a hand-rolled copy of the fix, two-actor-objects (including the wrapper /
`CoreActor` asymmetry fix), and end-of-request cleanup on both success and
exception paths per integration.

The phase notes are unusually good on test *validity*: they record that the two
end-to-end FastAPI teardown tests pass with or without the middleware's clearing
line (because Starlette's task boundary already isolates them), and that an
additional test calling `dispatch()` directly with an inline `call_next` was
written specifically because it *does* discriminate. That is the difference
between a test that passes and a test that proves something.

**Deviations from plan:** None material. The `_no_id_{id(actor)}` fallback for
actors with no id is a test-only convenience, and its docstring is explicit that
it must not be relied on for production isolation (object addresses can be
reused after GC) — the right way to ship that compromise.

### Phase 5: Documentation, changelog, merge — VERIFIED except the PR

**Changes verified:** every documentation deliverable the phase lists exists and
is accurate:

- `CHANGELOG.rst` — `Unreleased` filled with a prominent `.. note::` and a
  `SECURITY` section covering all five required points: the bypass with the
  `v3.3` → `v3.13.0rc2` window and the "cannot detect past exploitation"
  caveat; `resources/read` unauthorized on Flask only; fail-closed; unreliable
  trust-row metadata; and the still-open 5-minute stale-positive window.
  **No version bump and no section rename** — correct for a branch.
- `docs/migration/v3.13.rst` — the new "Security fix in rc3" section carries the
  at-risk-row query, the Flask resource-URI audit, the peer-id **orphaning**
  consequence (per-peer permission overrides keyed by the old peer id being
  silently abandoned), and the note that `oauth_client_id` backfill needs
  re-authorization rather than merely the next request.
- `docs/guides/troubleshooting.rst`, `docs/guides/mcp-quickstart.rst:126-130`,
  `docs/reference/security.rst` — all present and consistent with the code.
- `thoughts/todo/mcp-cache-lifecycle-and-revocation.md` — records all seven
  deferred items the plan named, plus an eighth found during Phase 3 (the
  sync/async `resources/read` result-*formatting* divergence).

**Claim spot-checked rather than trusted:** the CHANGELOG says trust-row
metadata "self-heals on that client's next request." I traced the writer to
confirm it. `_update_trust_with_client_info` (`mcp.py:1894-1990`) resolves its
target row from `mcp_context.peer_id` — the now-correctly-resolved per-client
peer id — and returns early when there is no context or an empty `peer_id`. So
after this fix each client writes only its own row, and a fail-closed client
writes nothing at all. The claim is accurate. (This mattered because
substring/`endswith` peer-id matching *does* still survive elsewhere, on
`client_registry.py`'s deletion path, per the todo doc — it just isn't used
here.)

**Not done:** the PR is not opened and the branch is not merged.

### Phase 6: Cut `v3.13.0rc3` from master — NOT STARTED

Correctly not started: it must happen on master after the merge, and the branch
still reads `3.13.0rc2` as it should.

## Fixes applied during this verification

Three defects were found and fixed in place rather than only reported, since the
PR is not yet open and all three are within Phase 5's own remit:

1. **`ruff format` drift** — reformatted `tests/test_flask_context_integration.py`
   and `tests/test_runtime_context_isolation.py`.
2. **Sphinx docstring regression** — added the blank line after
   `Architecture Problem:`, `Solution:` and `Concurrency notes:` in
   `actingweb/runtime_context.py`. Docs build went from 10 messages to 0.
3. **Missing `CHANGED` section in `CHANGELOG.rst`** — added entries for the
   `RuntimeContext` migration (including the `set_custom_context` behavior
   change) and the async `tools/call` `operation` alignment.

`ruff check`, `ruff format --check`, `pyright`, the Sphinx build and the full
parallel suite were all re-run after these edits.

## Remaining Tasks

- [ ] Open the PR for `bug/trust_mcp_cache` and merge to master (Phase 5's last
      checkbox).
- [ ] Phase 6 in full: rename `Unreleased` → `v3.13.0rc3`, bump
      `pyproject.toml` and `actingweb/__init__.py` to `3.13.0rc3`, tag, push,
      confirm the TestPyPI upload, and have the consumer re-run the escalation
      probe against the published artifact.
- [ ] Consider a permanent real-storage regression test for the original bypass.
      The Phase 5 acceptance probe ran against DynamoDB Local with two real
      clients and genuinely different trust types, then was deleted by design —
      so the permanent suite's coverage of the bypass is unit-level with fakes.
      Phase 6 already gates on the consumer re-running the probe, so this is a
      durability improvement, not a gap in this release. Belongs in
      `thoughts/todo/` if nobody picks it up now.

## Issues Found

### 1. `ruff format` drift in two new test files — FIXED

**Severity:** Low
**Location:** `tests/test_flask_context_integration.py:304-315`,
`tests/test_runtime_context_isolation.py:83`
**Description:** Both files failed `ruff format --check`. Purely cosmetic, but
`CLAUDE.md` sets a zero-tolerance quality bar. Root cause worth recording: every
phase's verification checklist in the plan lists `ruff check` but **never**
`ruff format --check`, so nothing in the process would have caught this.
**Recommendation:** Fixed. Add `ruff format --check` to future plan checklists.

### 2. Sphinx docstring regression in `runtime_context.py` — FIXED

**Severity:** Low
**Location:** `actingweb/runtime_context.py:9`, `:20`, `:53` (the
`Architecture Problem:` / `Solution:` / `Concurrency notes:` lead-ins)
**Description:** Phase 4 rewrote the module docstring and introduced multi-line
bullets under paragraph lead-ins that have no blank line before the list.
Docutils parses that as an unexpected block quote, producing 3 ERRORs and 2
WARNINGs and mangling the rendered API docs. Proven to be a regression, not
pre-existing: parsing the base commit's docstring gives 0 messages, HEAD's gives
5. `.readthedocs.yaml:16` sets `fail_on_warning: false`, so the build would not
have failed — the damage was silent mis-rendering.
**Recommendation:** Fixed (three blank lines). The docs build is now clean.

### 3. `CHANGELOG.rst` had no entry for Phase 4 — FIXED

**Severity:** Medium
**Location:** `CHANGELOG.rst`, `Unreleased`
**Description:** The `Unreleased` section was `SECURITY`-only. The
`RuntimeContext` ContextVar migration is a behavior change for application
code — `set_custom_context()` data no longer survives to the next request on a
hot cached actor — and was documented **only** in `docs/guides/hooks.rst`. A
consumer who used custom context as a cross-request cache would have broken
silently on upgrade with nothing in the changelog to explain it. The async
`tools/call` `operation="invoke"` → `"use"` change was likewise undocumented.
Since Phase 5's entire deliverable is disclosure documentation, this was a real
gap in that phase rather than a nitpick.
**Recommendation:** Fixed — a `CHANGED` section now covers both.

### 4. Self-referential normalization test, and a latent resolver trap

**Severity:** Low (no impact today)
**Location:** `tests/test_mcp_fail_closed_authorization.py:141-152`;
`actingweb/handlers/mcp.py:1649-1657`
**Description:** `test_client_id_normalization_round_trips` builds the expected
peer id using the resolver's *own* normalization for both segments, so it
asserts self-consistency rather than a round-trip against real trust creation.
The two do in fact differ: the resolver's arm-2 candidate normalizes `:` →
`_colon_` in **both** segments, while `create_or_update_oauth_trust`
(`actingweb/interface/trust_manager.py:454-460`) normalizes `:` only in the
*client* segment and not in the *email* segment. There is no impact today —
client ids are server-generated as `mcp_<32 hex>`
(`client_registry.py:51`), so they contain none of `@`, `.` or `:` and the
normalization is a no-op — but the divergence would silently break arm 2 if
client-id generation ever changed.
**Recommendation:** Not fixed (no impact, and arm 2 is a legacy-row path that
should shrink over time). If touched later, construct the expected peer id by
calling the real trust-creation path so the test round-trips for real.

### 5. Informational: `assert` used for type narrowing after the denial

**Severity:** Informational, no action needed
**Location:** `actingweb/handlers/mcp.py:943`, `:1025`, `:1134`;
`actingweb/handlers/async_mcp.py:143`, `:232`, `:339`
**Description:** Each gate follows `_require_mcp_peer_id()` with
`assert peer_id is not None`. Asserts are stripped under `python -O`. This is
safe — the assert is pure type narrowing, and the preceding
`if denial is not None: return denial` is what actually enforces the decision,
so stripping it changes nothing. Recorded only so a future reader does not
mistake it for a load-bearing check.

## Addendum (same day): PostgreSQL was not covered above, and CI found something

Everything above this line was written before the PR ran CI, and its
automated-check section covers **DynamoDB only** — that is the gap in my own
verification, independent of what it found. `make test-all-parallel` and
`make test-integration` both use the default backend; PostgreSQL needs the
separate opt-in invocation documented in `CLAUDE.md`, and I did not run it.

CI runs both backends. DynamoDB passed (2555/2555). **PostgreSQL failed 3 tests**
in `tests/integration/test_mcp_resource_regression.py`, all with
`-32003 Access denied: no trust relationship resolved for this client`.

**This is not a regression introduced by this branch.** Instrumenting the
resolver showed it receives an **empty trust list** for an actor whose trust row
was created successfully moments earlier. Before this branch that empty read
took the fail-open path and granted **full access**, so the tests passed. The
authorization change did not create the fault; it made a pre-existing one
visible. That is the behavior working as designed, and it is worth stating
plainly: "could not read this actor's trust relationships" used to mean "allow
everything."

Root cause of the larger part, confirmed with direct database evidence: the
PostgreSQL connection pool is a module-level global whose `configure` hook binds
each connection's `search_path` **at connection-creation time**. A pool created
in a test worker before `PG_DB_PREFIX` was set holds connections bound to the
bare `public` schema; connections created later bind to the worker schema. The
pool then serves a mix, so a write could land in `public` while the read went to
the worker schema and returned zero rows **with no error**. A stray MCP trust row
was found sitting in `public` as proof. Fixed in `9fb7dae` by setting the PG
environment and calling `close_pool()` in `setup_database`, mirroring what the
DynamoDB branch always did.

Measured effect over full parallel PostgreSQL runs: failure rate fell from
roughly 40–50% of runs to about 12% (1 of 8), and stray `public` rows went to
zero across 8 consecutive runs.

**A residual ~12% flake remains and is not fixed.** The remaining suspicion is
on the write side — whether the registration-time trust `INSERT` is reliably
committed and visible before the first MCP request — not on the resolver, which
the diagnostic shows never receives the row.

> Superseded by the second addendum below, written later the same day: the
> flake was resolved, the suspicion above was wrong, and its `todo/` entry was
> retired. The durable lesson lives in
> `thoughts/reference/module-globals-assume-one-application.md`.

Revised phase status: **Phase 3 is verified on DynamoDB and only partially on
PostgreSQL.** The fail-closed behavior is correct on both; what PostgreSQL
exposes is an underlying trust-read reliability problem that fail-closed
surfaces rather than causes.

## Overall Assessment

The implementation is complete, correct, and unusually well-evidenced for
Phases 1–4, and Phase 5's documentation deliverables are thorough. The security
fix itself is sound: the trust cache is keyed by `(actor_id, client_id)` through
a single construction helper that both authentication paths use; the resolver
matches exactly with the peer-id fallback properly gated on `established_via`
plus full-string equality; fail-closed is wired into all six sync gates and all
three async gates with the denial placed outside every fail-open `try`, which I
verified by reading each site rather than trusting the checklist; and
`RuntimeContext` is now genuinely request-scoped with no attribute-storage
fallback. The `operation=` strings agree across transports, `_mcp_trust_context`
is gone from the entire repository, and `_trust_cache` has no remaining
string-key assumption anywhere in the repo. Test quality is high — the notable
thing is that several phases record *mutations that failed to discriminate*
before finding one that did, which is what makes the placement and executor-hop
tests trustworthy rather than merely green.

Three defects surfaced during verification and were fixed in place, all within
Phase 5's remit and all cheap because the PR is not yet open: two cosmetic
(`ruff format`, a Sphinx docstring regression that this branch introduced) and
one substantive — the changelog documented the security fix but said nothing
about Phase 4, whose `set_custom_context` change can break application code
silently on upgrade. With those in, nothing blocks the merge. What remains is
process, not code: open and merge the PR, then cut `v3.13.0rc3` from master and
have the consumer re-run the escalation probe against the TestPyPI artifact
before any final `v3.13.0` is tagged.

---

## Second Addendum: the PostgreSQL flake is resolved, and what it was hiding

Added 2026-07-31, after the body above. It **supersedes** the first addendum's
"remaining suspicion is on the write side — whether the registration-time trust
`INSERT` is reliably committed and visible". That suspicion was wrong. The
`INSERT` committed correctly; it committed to the **wrong database**.

### Root cause

`get_actingweb_oauth2_server()` was fixed to rebuild on a new `Config`, but
`ActingWebOAuth2Server.__init__` (`actingweb/oauth2_server/oauth2_server.py:40-42`)
immediately constructs three further singletons — `get_mcp_client_registry()`,
`get_actingweb_token_manager()`, `get_oauth2_state_manager()` — none of which
consulted the config they were handed. The wrapper rebound; its children did
not. Reproduced directly:

```
server.config.database                 -> postgresql   (wrapper rebound)
server.client_registry.config.database -> dynamodb     (registration writes here)
server.client_registry.config.DbTrust  -> actingweb.db.dynamodb.trust
```

That last line is the CI diagnostic's `CREATE ... db=actingweb.db.dynamodb.trust`
reproduced in four lines of Python, with no CI push needed.

An AST sweep of the package found four unguarded getters in total (the three
above plus the `peer_profile` store pair). All four now rebuild on a different
config. `tests/test_config_bound_singletons.py` grew from 7 tests to 12,
including two that would have caught this specific gap: one asserting the
OAuth2 server rebinds **everything it composes**, not just itself, and a
structural test that walks `actingweb/` and fails on any function caching a
module global built from a `config` argument without comparing against it.

The original regression test asserted `server.config is postgres_cfg`, which
passed the entire time the three children were DynamoDB-bound. Checking the
wrapper and not what it composes is the exact shape of this defect.

### Provenance

A pytest plugin recording each singleton's first bind per xdist worker, run
against PostgreSQL on the pre-fix code:

```
gw0  client_registry <- tests/test_oauth2_server_lazy_authenticator.py  db=dynamodb
gw3  client_registry <- tests/test_oauth2_server_lazy_authenticator.py  db=dynamodb
gw1  client_registry <- tests/integration/test_mcp_basic.py             db=postgresql
```

A **unit test** constructing `Config(database="dynamodb")` binds the registry
for the life of the worker. Whether it does so before the MCP integration group
lands on that worker is scheduling luck — the complete explanation for the
intermittency, and for the earlier "failing runs are the slow ones" observation.

### What it was hiding

This is the more consequential half. Instrumenting every getter to record any
caller served an instance bound to a different backend than it asked for, on a
full pre-fix PostgreSQL run:

```
10 tests served a wrong-backend singleton
   7  tests/integration/test_trust_oauth_integration.py
   1  tests/integration/test_mcp_basic.py
   1  tests/integration/test_mcp_client_descriptions.py
   1  tests/integration/test_oauth2_client_manager.py
```

Post-fix the same measurement reports **0**.

Every one of those ten *passed* — against **DynamoDB Local, which runs in the
PostgreSQL CI leg too**. So on affected workers the PostgreSQL leg was not
exercising MCP dynamic client registration, token management or OAuth2 state
handling against PostgreSQL at all; it was re-testing DynamoDB and reporting
green. A coverage hole that looked like coverage. The exact membership varies
per run with scheduling; the shape — the OAuth2/MCP registration surface — does
not.

Compounding it, `AWS_DB_PREFIX` is set only in the DynamoDB branch of
`setup_database`, so those stray DynamoDB writes landed in unprefixed tables
shared by all four workers. That is the origin of the earlier "every worker
reported the same 37 peers" observation: PostgreSQL-leg count assertions over
trusts, peers, clients or tokens were reading a cross-worker-polluted table.

Not affected: `_token_cache`, `_mcp_client_info_cache` and `_trust_cache` in
`mcp.py` are keyed by token, client id and `(actor_id, client_id)` — unique per
application, so they cannot collide the way `_actor_cache` did (keyed by actor
id alone, with `_actingweb_oauth2` shared across apps, which is why that one
needed config-scoping).

### Verification

- 14 consecutive full parallel PostgreSQL runs with `--cov` (the recipe that
  reproduced the flake at ~1 in 6): all clean, 2496 passed / 97 skipped.
- Ruff check, `ruff format --check` (304 files), Pyright: all clean.
- `tests/test_config_bound_singletons.py`: 12 passed.

**Revised phase status: Phase 3 is now verified on PostgreSQL as well as
DynamoDB.** The first addendum's conclusion still holds in its essentials — the
authorization change did not create the fault, it made a pre-existing one
visible — but the fault was backend crossover at registration time, not a
PostgreSQL read/write reliability problem.
