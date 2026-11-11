# Verification: peer authorisation fixes (tenth run: reverify-9's fixes)

**Date:** 2026-11-09
**Plan:** thoughts/plans/2026-11-06-peer-authorisation-fixes.md
**Research:** thoughts/research/2026-11-06-peer-authorisation-fixes.md
**Branch:** fix/3.16.0-peer-authorisation (local only; not pushed)
**Commit:** 7cda6db (code as of 16f5972; 7cda6db adds records only)

This run verifies Iterations 76 to 80 (`3012efc..16f5972`). They answered
`verifications/2026-11-09-peer-authorisation-fixes-reverify-9.md` Issues 1
to 7. The owner chose to fix all seven, with any flag that is not `true` or
`false` raising `ValueError`.

## Automated Check Results

- **Outside voice:**
  - **Codex** (`codex exec -s read-only`, outside the sandbox, stdin
    closed): found Issues 1 (the proxy), 2 and 3, and the `ValueError`
    break in Issue 8.
  - **The fresh-context Claude reviewer** read the whole diff. It found
    Issue 1 (HTTPS) and Issues 5, 6, 7 and 9.
  - Both checked every `json.dumps` of a trust row in `handlers/trust.py`
    and `async_trust.py`. None emits the token for an unapproved row's
    peer.
  - Both confirmed the Session is per fetch, so a shut-down socket cannot
    belong to another fetch.
- **Built-in code review** (`/code-review high 3012efc..16f5972`): ten
  findings.
  - Issues 1 (HTTPS and the proxy, both reproduced here), 2, 6 to 10, and
    the hygiene note were confirmed.
  - Its finding that the re-pair's 201 decision reads a text `"false"` as
    approved is pre-existing (`handlers/trust.py:607` predates the range).
    It is also unreachable: `replace_trust_secret` returns the row read
    back from the store, with bool flags (`actor.py`,
    `return (updated or None)`). It is not an issue.
- **Built-in security review** (this context, scoped to the range,
  confidence bar 8): nothing at or above the bar under its rules.
  - The fetch-path gaps are availability findings, which those rules
    exclude. They are reported below as the plan's own claim.
  - No change widens what a peer or client can read or write.
- **Browser QA:** N/A. No template or page changed in this range.
- **Full tier** on `7cda6db` (code `16f5972`), one run at a time:
  - `poetry run ruff check actingweb tests`: pass.
  - `poetry run ruff format --check actingweb tests`: pass (532 files).
  - `poetry run pyright actingweb tests`: 0 errors, 0 warnings.
  - `poetry run python tests/integration/verify_groups.py`: 54 groups;
    wire rows registry consistent.
  - `make test-all-parallel`, DynamoDB: **6153 passed**, 60 skipped,
    1 xfailed.
  - `make test-all-parallel`, PostgreSQL: **5950 passed**, 263 skipped,
    1 xfailed.
  - `sphinx-build -W ...`: build succeeded.
  - Wire: no recording changed. The tree is clean after the runs.
- **Emm's suite** on `16f5972` (recorded in the plan by `7cda6db`, code
  unchanged since): PostgreSQL 2 failed / 7406 passed, DynamoDB 3 failed /
  54 passed. These are the baseline's failures, by name.

## Phase Verification

### Iterations 76 to 80 - ISSUES FOUND

**Changes verified (they match the iterations):**
- **76, the fetch.** `actor.py` `_socket_tracking_session`,
  `_verification_get`, `_shut_down`, `_verification_deadline` and
  `_bounded_get_json(url, headers, deadline, timeout)`.
  - `_base_uri_serves(..., deadline)` fetches `/meta` through it. It makes
    two tries, the second only when the first got no answer, and follows
    no redirect.
  - The two steps of each verification share one deadline
    (`actor.py:2308`, `:2609`).
  - The caller side holds.
  - The worker side holds only for a plain-HTTP, unproxied socket that
    connects before the deadline (Issues 1 to 3).
- **77, flags.** `trust.as_flag`, used by `Trust.modify` (`trust.py:369`)
  and `TrustManager.modify_trust` (`interface/trust_manager.py:888`),
  before any read. Residue: Issue 8.
- **78, the re-pair answer.** `_trust_request_answer` serves both the
  creation 202 (`handlers/trust.py:550`) and the re-pair
  (`handlers/trust.py:605`).
- **79, the client view.**
  - `_client_trust_peer_id(actor, client_id)` ignores a passed peer id.
  - `permission_id` resolves lazily.
  - `create_local_subscription` files under `permission_id`
    (`authenticated_views.py:724`).
  - Residue: Issues 5, 6 and 7.
- **80, the denial log and `list:` keys.**
  - `permission_evaluator.py:566` logs DENIED.
  - A `list:` key is checked by its bare name (`actor.py:3711`).
  - Residue: Issues 9 and 10.

**Security properties, demonstrated:**
- **The caller's deadline:**
  `tests/test_verification_fetch.py::TestTheSocketIsShutDown::test_the_caller_returns_by_the_deadline`.
  Against a real trickling socket with a 0.5 s deadline, it asserts
  `(None, None)` and a return in under 1.5 s.
- **The worker freed:** `::test_the_workers_are_free_again`. Eight
  trickling `http://127.0.0.1` peers, then an honest one, which is
  answered (`status == 200`) in under 2 s. This holds only for that
  shape. A script here (below, Issue 2) breaks it with a 1 s connect.
- **No redirect:** `::test_no_redirect_is_followed`. A 302 to
  `169.254.169.254` is returned as `302, None`.
- **Flags:** `tests/test_trust_re_pair.py::TestFlagsAfterReverify9`.
  - `test_anything_else_raises_and_writes_nothing` checks that `1` and
    `"yes"` raise `ValueError` and leave the row as it was.
  - `test_text_true_and_false_are_flags` checks the text forms.
- **The re-pair answer:**
  `TestTheRePairAnswerAfterReverify9::test_a_re_pair_of_an_unapproved_row_answers_without_its_token`.
  The 202 body has no `verification_token` and no `secret`.
- **The client view:** `TestTheClientViewAfterReverify9`.
  - `test_a_peer_id_passed_in_grants_nothing`.
  - `test_a_clients_subscription_is_kept_under_its_trust`.
  - `test_building_a_view_reads_no_trust`.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-09-peer-authorisation-fixes-reverify-9.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. `/meta` unbounded, follows redirects | Fixed for the caller: one deadline, no redirect, 64 KB | `actor.py` `_base_uri_serves`; iteration 76 |
| 2. A slow peer pins a worker | Partly. Fixed for plain HTTP that connects in time. Open for HTTPS, proxies and a late connect (Issues 1 to 3) | iteration 76; script below |
| 3. `_as_flag` revokes on other truthy values | Fixed (raises `ValueError`, one helper) | `trust.py` `as_flag`; iteration 77 |
| 4. The re-pair 202 carries the token | Fixed | `handlers/trust.py:605`; iteration 78 |
| 5. The client view's identity | Fixed for permissions and storage (residue: Issues 5 to 7) | iteration 79 |
| 6. No denial log; flag parse duplicated | Fixed (residue: log volume, Issue 9) | `permission_evaluator.py:566`; iteration 80 |
| 7. `list:` key under a subtarget | Changed as recommended. The recommendation's premise was incomplete (Issue 10) | `actor.py:3711`; iteration 80 |

## Remaining Tasks

- [ ] `/iterate_plan` for Issues 1 to 10.
- [ ] Todos unchanged: `grant-enforcement-per-route.md`,
      `web-ui-trust-page-gaps.md` and `full-state-fallback-replica.md`
      all exist and keep their `INDEX.md` rows.

## Issues Found

### Issue 1: the shutdown reaches no socket on HTTPS or through a proxy
**Severity:** Medium (all three providers; reproduced here). It falsifies
the changelog's "the socket shut down then" for the production shape.
**Description:**
- **HTTPS.** `_Https._new_conn` records the raw socket
  (`actor.py:94-97`, `sockets.append(sock)`). urllib3 then wraps that
  socket for TLS, and `SSLContext.wrap_socket` detaches it: the raw
  socket's `fileno()` is -1 afterwards. `_shut_down` then fails with
  `OSError: [Errno 9] Bad file descriptor`, and `actor.py:146-148`
  (`except OSError: pass`) swallows it.
  - Checked here: a wrapped `socketpair` end shows fileno -1, and its
    shutdown fails with EBADF.
  - A peer behind `https://` that sends its handshake or headers slowly
    keeps the worker, exactly as before iteration 76.
- **Proxy.** The tracking pool classes are installed only on the
  adapter's `poolmanager` (`actor.py:107-111`). With `HTTPS_PROXY` or
  `HTTP_PROXY` set, requests uses `proxy_manager_for()` instead
  (`requests/adapters.py:285`, `:296`). That builds a `ProxyManager` or
  `SOCKSProxyManager` with the default classes, so nothing is recorded.
  The docstring says "the environment's proxy settings still apply".
- **The tests.** Every test uses `http://127.0.0.1` without a proxy.
**Location:** `actingweb/actor.py:80-150`
**Recommendation:**
- Record the connection object and shut down `conn.sock` when the
  deadline passes. Once wrapped, that is the `SSLSocket`.
- For a handshake that is still running, keep a `dup()` of the raw socket
  and shut that down.
- Either do not use the environment's proxy for a verification
  (`session.trust_env = False`), or override `proxy_manager_for` the same
  way. Whichever is chosen, document it.
- Add a test with a TLS peer that sends slowly.

### Issue 2: a socket that connects after the deadline is never shut down
**Severity:** Medium (Codex, the code review; reproduced here)
**Description:**
- **When it happens.** A socket is recorded only when `_new_conn`
  returns, after DNS and the TCP connect (`actor.py:89-91`).
  `_shut_down` shuts down only the sockets in the list when the deadline
  passes (`actor.py:144`). The old `cancelled` event is gone, and nothing
  tells a late-connecting worker that the caller has left.
- **Two triggers.** A `/meta` try started with little budget left, or a
  slow answer from a DNS server the requester controls.
  - In either case the worker connects after the shutdown, then follows a
    trickle with only its 5 s per-read timeout.
  - DNS itself (`getaddrinfo`) can be stopped by nothing and holds the
    worker for the resolver's retry budget.
- **Reproduced.** I delayed `create_connection` by 1 s against the
  test's trickle server.
  - Eight fetches with a 0.3 s deadline all returned `(None, None)` at
    0.3 s.
  - An honest fetch 8 s later, past the read timeout, got `(None, None)`
    after its full 3 s. The pool was still held.
  - Script: `scratchpad/late_socket2.py` (not kept).
**Location:** `actingweb/actor.py:86-91`, `:137-150`, `:229-232`
**Recommendation:** set a cancelled flag, under a lock, before the
shutdown pass. `_new_conn` (and the TLS wrap) checks it after recording a
socket and shuts that socket down at once. DNS cannot be cut short, so
bound admission instead (Issue 3).

### Issue 3: a busy pool queues work without limit
**Severity:** Low. The comment's claim is false, and the cost is the one
reverify-8 set out to remove.
**Description:** `_verification_pool().submit(...)` (`actor.py:220`)
queues without limit. When the pool is full, each new verification waits
in the queue, and its caller's request thread waits for the whole
deadline. The comment at `actor.py:52-59` says "Once the pool is busy, a
verification fails closed instead of waiting". Together with Issues 1
and 2, each anonymous trust request holds a request thread for 15 s.
**Location:** `actingweb/actor.py:52-59`, `:218-224`
**Recommendation:** put a non-blocking semaphore of `_VERIFY_WORKERS`
around the submit and return `(None, None)` when it cannot be taken;
release it in the worker. Otherwise, correct the comment.

### Issue 4: the tests do not cover the shapes production uses
**Severity:** Low (test quality)
**Description:** `tests/test_verification_fetch.py` uses only plain HTTP,
local, unproxied, with an instant connect, which is the one shape that
works. Issues 1 and 2 pass every test.
**Recommendation:** add tests for:
- a TLS server (a self-signed context, with verification turned off for
  the test);
- a delayed connect, by patching `create_connection` as the script did;
- a proxy, if proxies stay supported.

### Issue 5: a client's subscription now gets push callbacks
**Severity:** Medium (an unannounced behaviour change on every write)
**Description:**
- **The change.** `create_local_subscription` now files a client's
  subscription under its trust row's peer id
  (`authenticated_views.py:724`).
- **The push.** `register_diffs` calls `callback_subscription` for every
  inbound subscription (`actor.py:4916`). That reads the trust row
  (`actor.py:3413`) and POSTs to
  `trust_rel["baseuri"] + "/callbacks/subscriptions/..."` with
  `Bearer <secret>` (`actor.py:3453-3462`).
- **Before.** The subscription was filed under the raw client id, which
  has no trust row, so `if not trust_rel: return` stopped it.
- **Now.** Each diff tries a push:
  - a row created by `TrustManager` for an `oauth2_client` has
    `baseuri = ""` (`interface/trust_manager.py:601-610`), which gives a
    URL with no scheme;
  - a legacy row carries the actor's own URL (`oauth2_server/trust_lookup.py:25-36`),
    so the actor POSTs to itself with the client's secret.
- **The cost.** With `with_sync_callbacks()` each attempt blocks the
  write. Clients poll; nothing was meant to push to them.
**Location:** `actingweb/interface/authenticated_views.py:724`,
`actingweb/actor.py:3405-3462`
**Recommendation:**
- Skip pushes for a client trust row: `callback_subscription` returns
  when the row's `established_via` is a client, or when its base URI is
  empty or this actor's own.
- Add a test that a diff to a client's subscription sends no request.
- Mention it in the changelog's client-view entry.

### Issue 6: listing subscriptions still trusts a peer id the caller passed
**Severity:** Low
**Description:** `_own_rows` keeps
`given = trust.get("peerid") or trust.get("peer_id") if trust else ""`
(`authenticated_views.py:747`) in the client's own set. Iteration 79's
rule is "never a peer id the caller passed, which could name another
row". A view built as `as_client(cid, {"peerid": "<another peer>"})` lists
that peer's subscriptions through `all_subscriptions` and the inbound and
outbound lists. Only application code passes a trust dict.
**Recommendation:** drop `given`, and keep only `permission_id` (and the
raw client id, for subscriptions filed before 3.16).

### Issue 7: a fault while resolving the client's row leaves the view on the bare client id for good
**Severity:** Low (it fails closed, but silently)
**Description:**
`resolver, self._client_resolver = self._client_resolver, None`
(`authenticated_views.py:85`) drops the resolver before calling it.
- **A fault.** A `DbError` from `find_client_trust` propagates. Every
  later check on that view evaluates as the client id, which is granted
  nothing, and a later `create_local_subscription` files under the client
  id.
- **Two threads.** A second thread reading `permission_id` during the
  resolution gets the client id too.
**Recommendation:** assign the result before clearing the resolver, and
restore the resolver when it raises. A lock is optional, since views are
per request.

### Issue 8: the flag change's edges
**Severity:** Low
**Description:**
- **Docstring.** `TrustManager.modify_trust` now raises `ValueError`
  before its `try` (`interface/trust_manager.py:888-890`). The docstring
  still says "Returns: True if modification succeeded, False otherwise".
  The changelog names the break (`CHANGELOG.rst:118-122`), so Codex's
  "not in the changelog" does not hold.
- **The swallowed error.** `Actor.modify_trust_and_notify` passes its
  flags to `Trust.modify` inside `except Exception` (`actor.py:1792-1794`),
  so there a `ValueError` becomes `False` with an error traceback.
- **Text `"true"` still slips past three checks.** It skips the
  re-verify gate (`approved is True`, `actor.py:1748`), the
  `only_if_secret` binding (`:1784-1788`) and the peer notification
  (`:1803`). The store still refuses an unverified row
  (`only_if_verified`, `trust.py:417`), so this is a missed notification
  and a looser binding, not an approval bypass.
**Recommendation:** parse the flags with `as_flag` at the top of
`modify_trust_and_notify` and let the `ValueError` through. Add `Raises:`
to both docstrings.

### Issue 9: the new denial log fires per subscriber per diff
**Severity:** Low
**Description:** `logger.warning(f"Permission denied: ...")`
(`permission_evaluator.py:566-569`) runs from `filter_subscription_blob`
for every diff and every subscriber. The call passes
`suppress_logging=True`, as the whole-target filter does. A subscriber
that is denied one hot property writes a WARNING on every write.
**Recommendation:** log at debug here, or once per subscription.
Reverify-9 Issue 6 asked for a trace, not a WARNING per write.

### Issue 10: a `list:` key in ordinary object data now escapes a subtarget exclusion
**Severity:** Low
**Description:** `key[5:] if key.startswith("list:") else f"{subtarget}/{key}"`
(`actor.py:3711`).
- **Where lists go.** List diffs register with the list name as the
  subtarget and never carry `list:` keys, so under a subtarget a `list:`
  key is ordinary data.
- **The escape.** A property `notes` holding `{"list:private": ...}`,
  with the exclusion `notes/*`, is now checked as `private`, which no
  exclusion matches, so the key is sent.
- **Why.** Reverify-9 Issue 7's premise ("lists are top-level
  properties") was right about lists, but this key is not a list.
**Recommendation:** check both `<subtarget>/<key>` and the bare name, and
drop the key if either is excluded. Add a test.

**Notes** (no finding):
- **Per-call setup.** Each verification GET defines four classes and
  builds a Session it never closes (`actor.py:80-118`). Reference cycles
  keep the socket list alive until GC runs. This is a cost, not a defect.
  Module-level classes and `with requests.Session()` would be cheaper.
- **Token emission is clean.** Every route that serialises a trust row
  was checked by both outside reviewers.

## Overall Assessment

Iterations 76 to 80 close what they aimed at on the identity side:
- **Flags** parse strictly in one helper.
- **The re-pair answer** no longer carries the token.
- **A client view** is checked as its own trust row and files its
  subscriptions there.
- **The `/meta` step** shares the verification's deadline and follows no
  redirect, so the caller is bounded on every path.
- **The checks are green.** The Full tier on both backends: DynamoDB 6153,
  PostgreSQL 5950. Emm's suite matches its baseline. No reviewer found a
  hole in authorisation.

The fetch path's second promise, that the worker is freed at the deadline,
holds only for the shape the tests use: plain HTTP, no proxy, an instant
connect. Over HTTPS (the TLS wrap detaches the recorded socket), through a
proxy, or with a connect or DNS answer slower than the time left, the pool
is held as before. The changelog's "the socket shut down then" is false for
real peers. Issues 1 to 4 belong together.

These are availability problems, not authorisation ones, and the request
threads stay bounded either way, apart from Issue 3's queue. Whether to
finish the socket approach (record the connection, a cancelled flag,
bounded admission, no environment proxy) or to narrow the changelog and
the comment to what holds is a decision for the next iteration.

Issue 5 is a new side effect of iteration 79 and needs fixing before the
PR. Issues 6 to 10 are small.
