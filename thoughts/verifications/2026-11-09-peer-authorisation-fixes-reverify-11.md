# Verification: peer authorisation fixes (eleventh run: reverify-10's fixes)

**Date:** 2026-11-09
**Plan:** thoughts/plans/2026-11-06-peer-authorisation-fixes.md
**Research:** thoughts/research/2026-11-06-peer-authorisation-fixes.md
**Branch:** fix/3.16.0-peer-authorisation (local only; not pushed)
**Commit:** 5c96d67 (code as of 09890b6; 5c96d67 adds records only)

This run verifies Iterations 81 to 84 (`c938090..09890b6`). They answered
`verifications/2026-11-09-peer-authorisation-fixes-reverify-10.md` Issues 1
to 10. The owner chose all ten, and to keep the environment's HTTP(S)
proxy for verification GETs (its sockets tracked, SOCKS refused): plain
HTTP is for development only, so the fetch must free its worker over
HTTPS.

## Automated Check Results

- **Browser QA:** N/A. No iteration in the range touches a page, template
  or `handlers/www.py`.
- **Outside voice** (the outside-voice agent):
  - **Codex** (`codex exec -s read-only`, outside the sandbox): the list
    key's `<subtarget>/<name>` path (Issue 4), the client-id listing and
    the `None` flag wording (notes, Issue 7).
  - **The fresh-context Claude reviewer:** the resync path and
    `FanOutManager` still push to client rows, with the resync's endless
    "missed" record (Issue 1); the multi-address connect (Issue 2); the
    double slot release (Issue 6).
  - Both found clean: double release on cancel, leaked duplicate
    descriptors, one fetch shutting another's socket, the thread-local
    left set on a pooled thread, the CONNECT tunnel socket (it is the one
    `_new_conn` returns, so it is recorded), redirects, and a retry after
    `opened()` raises (`max_retries=0` gives `MaxRetryError`).
    `_has_peer_endpoint` cannot hide a real peer: protocol rows carry
    `established_via="trust"`.
- **Built-in code review** (`/code-review high 16f5972..09890b6`): ten
  findings, deduplicated against the above. Confirmed here: the resync
  path and `FanOutManager` (Issue 1), the multi-address connect (Issue 2),
  the silent SOCKS refusal and the vacuous SOCKS test (Issue 3; PySocks is
  not installed: `import socks` raises `ModuleNotFoundError`), the double
  `/meta` try on a full pool (Issue 5), the duplicated OAuth2-origin rule
  (Issue 9), the stale comment (Issue 8), the changelog's missing
  **Behavior change:** marker (Issue 7). Its finding that the denial log
  at DEBUG loses the operator's trace is the owner's iteration 83
  decision (reverify-10 Issue 9); recorded as accepted, not an issue.
- **Built-in security review** (this context, scoped to the range,
  confidence bar 8): no finding at or above the bar.
  - Every change in the range narrows what a peer or client is given
    (no push to a client row, no passed peer id in a listing, list keys
    checked at more paths) or retries a lookup; none widens access.
  - Issue 1's self-addressed POST sends the client row's secret to this
    actor's own base URI; the receiver refuses it (the path's peer is this
    actor, which has no trust row with itself). Issue 2 is availability,
    which those rules exclude; it is reported below as the plan's own
    claim.
- **ruff check:** pass. **ruff format --check:** pass, 532 files.
  **pyright:** 0 errors, 0 warnings. **verify_groups:** 54 groups
  documented, wire registry consistent.
- **DynamoDB** (`make test-all-parallel`): 6168 passed, 60 skipped,
  1 xfailed, no failure.
- **PostgreSQL** (`make test-all-parallel` with the PostgreSQL env):
  5965 passed, 263 skipped, 1 xfailed, no failure.
- **Docs** (`sphinx-build -W`): pass.
- **Wire recordings:** unchanged (`git status` clean after both runs).
- **Emm's suite on `09890b6`** (environment 9, adoption worktree
  unchanged): PostgreSQL 2 failed / 7406 passed, DynamoDB 3 failed / 54
  passed, the `master` baseline's failures by name.

## Phase Verification

### Iterations 81 to 84 - ISSUES FOUND

**Changes verified (they match the iterations):**
- **81, the fetch** (`actor.py:73-347`).
  - `_FetchSockets` records `sock.dup()` per socket (`:124-136`);
    `cancel()` shuts the duplicates down, `release()` closes them and the
    session; a socket that arrives after either is shut down and the
    connect raises `ConnectionAbortedError`.
  - `_TrackedHttp`/`_TrackedHttps` record from `_new_conn`;
    `_TrackedAdapter` sets the tracked pool classes on the pool manager and
    on each proxy manager, and refuses a `socks*` proxy (`:209-217`).
  - Admission: `_verify_slots.acquire(blocking=False)` (`:321`); the slot
    is freed once on every path that acquired it: by the worker's
    `finally` (`:254-257`), or by the caller when `submit` raises or
    `future.cancel()` succeeds (`:332-339`). Residue: Issue 6.
  - The comment at `:73-84` says only a name lookup cannot be cut short.
    Residue: Issue 2.
- **82, no push to a client row.** `_has_peer_endpoint` (`actor.py:56`),
  checked in `callback_subscription` (`:3536`). Not in the resync
  (`:4356`) or `FanOutManager._deliver_single` (`fanout.py:503`):
  Issue 1.
- **83, the client view.** `_own_rows` is `{permission_id, accessor_id}`
  (`authenticated_views.py:745-748`); `permission_id` clears the resolver
  only after it answered (`:84-89`).
- **84, flags, log, list keys.** `modify_trust_and_notify` parses with
  `trust.as_flag`; the denial log at DEBUG
  (`permission_evaluator.py:567`); a `list:` key under a subtarget checked
  at `<subtarget>/list:<name>` and `<name>` (`actor.py:3836-3845`).
  Residue: Issues 4 and 8.

**Security properties, demonstrated (each test failed on the code
before):**
- **The worker freed over TLS:**
  `tests/test_verification_fetch.py::TestOverTls::test_a_trickled_handshake_frees_its_worker`
  and `::test_trickled_headers_after_the_handshake_free_their_worker`:
  eight stalled `https://127.0.0.1` peers past a 0.5 s deadline, then an
  honest one answered with 200.
- **Through a proxy:** `TestThroughAProxy::test_a_proxied_fetch_frees_its_worker`
  (http and https through a trickling proxy), same assertion.
- **A late connect:** `TestLateAndFull::test_a_socket_connected_after_the_deadline_is_shut_down`
  (connect delayed 1 s past the deadline; the honest fetch is still
  answered).
- **A full pool refuses at once:** `TestLateAndFull::test_a_full_pool_refuses_at_once`
  (`(None, None)` in under 0.5 s).
- **SOCKS:** `TestThroughAProxy::test_a_socks_proxy_is_refused` asserts
  only `(None, None)`, which requests gives without the guard here
  (Issue 3). Not demonstrated.
- **No push to a client row:**
  `tests/test_trust_re_pair.py::TestTheClientViewAfterReverify10::test_a_clients_subscription_gets_no_push`
  (no POST), with `::test_a_peers_subscription_is_still_pushed` as the
  control. Only for `callback_subscription` (Issue 1).
- **Listing:** `::test_a_listing_ignores_a_peer_id_passed_in`.
- **List keys:** `tests/test_peer_paths_binding.py::test_a_list_key_excluded_under_its_subtarget_is_dropped`
  asserts `"list:private" not in sent and '"open"' in sent` for the
  exclusion `settings/list:private`.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-09-peer-authorisation-fixes-reverify-10.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. Shutdown reaches no socket on HTTPS or through a proxy | Fixed | `TestOverTls`, `TestThroughAProxy`; iteration 81 |
| 2. A late connect is never shut down | Fixed for a socket that connects late; open for the connect loop itself (Issue 2) | `TestLateAndFull`; `actor.py:124-136` |
| 3. A busy pool queues without limit | Fixed (refused at once) | `actor.py:321`; `test_a_full_pool_refuses_at_once` |
| 4. Tests cover plain HTTP only | Fixed, except SOCKS (Issue 3) | `tests/test_verification_fetch.py` |
| 5. A client's subscription gets push callbacks | Partly: the diff callback only; resync and `FanOutManager` still push (Issue 1) | `actor.py:3536`; iteration 82 |
| 6. Listing trusts a passed peer id | Fixed | `authenticated_views.py:745`; iteration 83 |
| 7. A resolver fault drops the client's row | Fixed | `authenticated_views.py:84-89`; iteration 83 |
| 8. Flag edges | Fixed (`modify_trust_and_notify`, docstrings); the `None` wording is Issue 7 | iteration 84 |
| 9. A WARNING per subscriber per diff | Fixed (DEBUG; accepted that it leaves no WARNING trace) | `permission_evaluator.py:567` |
| 10. A `list:` key escapes a subtarget exclusion | Fixed at two paths; the third, `<subtarget>/<name>`, is Issue 4 | `actor.py:3836-3845` |

## Remaining Tasks

- [ ] `/iterate_plan` for Issues 1 to 9 (Issues 1 and 2 before the PR).
- [ ] Todos unchanged: `grant-enforcement-per-route.md`,
      `web-ui-trust-page-gaps.md` and `full-state-fallback-replica.md`
      all exist and keep their `INDEX.md` rows. Nothing in this range was
      to close a todo.

## Issues Found

### Issue 1: the resync path and `FanOutManager` still push to a client's trust row
**Severity:** Medium (the changelog's "nothing is pushed to it" is false;
an endless "missed" record)
**Description:**
- Since iteration 79 a client's subscription is filed under its trust
  row's peer id. Iteration 82 put `_has_peer_endpoint` in
  `callback_subscription` only (`actor.py:3536`).
- **Resync.** `_callback_subscription_resync` reads the same row
  (`actor.py:4391`) and builds `trust_data.get("baseuri", "") +
  "/callbacks/subscriptions/" ...` (`:4399-4405`).
  - An `oauth2_client` row has no base URI (`trust_manager.py:601-611`),
    so it returns False (`:4407-4411`) and the caller records the
    subscription as missed (`:4172-4173`). The pending record is written
    again on every later resume and never clears, and the count is always
    short.
  - An interactive OAuth2 row stores this actor's own URL as base URI
    (`trust_manager.py:604-609`), so the resync POSTs the client row's
    secret as a bearer to the actor's own `/callbacks/subscriptions/...`.
- **FanOutManager** (public API): `if not secret or not baseuri:`
  (`fanout.py:505`) passes an interactive row and pushes to the actor
  itself; an `oauth2_client` row gets a failed `DeliveryResult`.
**Recommendation:** one shared "push target" check (`_has_peer_endpoint`)
in all three paths; skip such subscriptions before the resync loop counts
or records them; a test per path.

### Issue 2: a connect to a host with many addresses holds its worker past the deadline
**Severity:** Medium (availability; the comment and the changelog say only
a name lookup cannot be cut short)
**Description:** urllib3's `create_connection` loops `for res in
socket.getaddrinfo(...)` with `sock.connect(sa)` per address, each with
the 5 s connect timeout, before `_new_conn` returns; only then is the
socket recorded (`actor.py:179-186`), and `given_up()` is never checked
inside that loop. A base URI whose name resolves to many unroutable
addresses holds a worker for about N × 5 s after the 15 s deadline. A
trust request that triggers a verification is unauthenticated, and with
iteration 81's refuse-at-once rule (`actor.py:321`) eight such requests
refuse every verification in the process for minutes, renewable.
`actor.py:82`: "Only a name lookup cannot be cut short".
**Recommendation:** open the socket in the tracked wrapper (record before
`connect`, check `given_up()` between addresses), or resolve first and
connect to at most one or two addresses; correct the comment and the
changelog sentence.

### Issue 3: the SOCKS refusal is silent and its test passes without the guard
**Severity:** Low
**Description:** `InvalidSchema` from `_TrackedAdapter.proxy_manager_for`
(`actor.py:212`) is folded by `except Exception: return None, None`
(`actor.py:271-272`) with no log line, so an environment with
`ALL_PROXY=socks5://...` fails every verification with nothing naming the
cause. `test_a_socks_proxy_is_refused` asserts only `(None, None)`;
without PySocks requests already raises `InvalidSchema("Missing
dependencies for SOCKS support")`, so the test passes with the guard
removed.
**Recommendation:** log the refusal at WARNING; make the test assert the
guard (patch `HTTPAdapter.proxy_manager_for` and assert it is not
called, or assert on the message).

### Issue 4: a `list:` key under a subtarget is not checked at `<subtarget>/<name>`
**Severity:** Low
**Description:** `filter_subscription_blob` checks `(f"{subtarget}/{key}",
key[5:])` (`actor.py:3841`). The bulk filter
`_filter_subscription_data_by_permissions` checks
`f"{subtarget}/{normalized_name}"` (`actor.py:3909-3917`). An exclusion
`settings/private` therefore drops `list:private` in one filter and not
the other.
**Recommendation:** add `f"{subtarget}/{key[5:]}"` to the tuple, with a
test for that exclusion.

### Issue 5: a full pool makes `/meta` try twice at once
**Severity:** Low
**Description:** a refused slot and no answer both return `None`
(`actor.py:321-326`), so `_base_uri_serves` runs its second try
immediately (`actor.py:2840-2841`) against the same full pool, logging two
"every verification worker is busy" warnings per request.
**Recommendation:** distinguish "refused" from "no answer" and skip the
second try on a refusal.

### Issue 6: a failed thread start frees the slot twice
**Severity:** Low
**Description:** `ThreadPoolExecutor.submit` puts the work item on the
queue before `_adjust_thread_count`, which can raise `RuntimeError("can't
start new thread")`. `except RuntimeError: _verify_slots.release()`
(`actor.py:332-334`) then frees the slot, and the queued item, run later,
frees it again in `_fetch_json`'s `finally`: the `BoundedSemaphore`
raises `ValueError` inside that fetch.
**Recommendation:** free the slot in the caller only when the pool was
shut down, or have `_fetch_json` own the release in every case.

### Issue 7: changelog wording
**Severity:** Low
**Description:** the SOCKS refusal and refuse-at-once are consumer-visible
and sit in a parenthetical with no **Behavior change:** sentence
(`CHANGELOG.rst:114-117`), which the contract requires. The flag sentence
"any other value (``1``, ``"yes"``) raises ``ValueError``"
(`CHANGELOG.rst:124-126`) omits that ``None`` leaves a flag unchanged.
**Recommendation:** a **Behavior change:** sentence for the two; "(``None``
leaves it unchanged)".

### Issue 8: the comment above the list-key check is stale
**Severity:** Low
**Description:** `actor.py:3825-3826`: "A ``list:`` key is a list, a
top-level property: checked by its bare name", but the code below checks
two paths (three after Issue 4).
**Recommendation:** rewrite the comment with the code.

### Issue 9: `_has_peer_endpoint` duplicates the OAuth2-origin rule
**Severity:** Low
**Description:** `actor.py:63-69` re-implements
`trust_lookup._oauth2_origin` for dicts with `if not via` where the
original has `via is None` (`oauth2_server/trust_lookup.py:49`). A row
with `established_via == ""` is legacy-checked here and not there.
**Recommendation:** one helper over a mapping or an object, called from
both.

**Notes (not issues):**
- A client with no trust row lists subscriptions filed under its client
  id before 3.16 (`authenticated_views.py:747`, `accessor_id`); codex
  could not confirm such a client passes MCP authentication. The
  permission check grants it nothing.
- `auth.py:196-197` sets `established_via` from the path hint on a row
  without one; a pre-3.4 OAuth2 row reaching `check_token_auth` would
  then read as a peer to `_has_peer_endpoint`. Unlikely: an OAuth2 row's
  secret is never given to the client.

## Overall Assessment

Iterations 81 to 84 land what they set out to: the verification fetch now
frees its worker over TLS, through an HTTP(S) proxy and on a late connect,
refuses at once on a full pool, and each of those is pinned by a
real-socket test that failed before. The client view's listing and
resolver, the flags, the log level and the list-key paths are fixed. The
Full tier is green on both backends (DynamoDB 6168, PostgreSQL 5965), the
docs build passes, no recording changed, and Emm's suite matches its
baseline. The security review finds nothing that widens access.

Two Medium issues stand before the PR. Iteration 82's "nothing is pushed
to a client's row" holds only for the diff callback: the resync and
`FanOutManager` still push, and the resync records a miss that never
clears (Issue 1). And the worker-freeing guarantee has a gap in the
connect loop that an unauthenticated requester can use to fill all eight
slots (Issue 2); the comment and changelog understate it. Issues 3 to 9
are small. Then the second security plan (`grant-enforcement-per-route`)
comes before anything is pushed.
