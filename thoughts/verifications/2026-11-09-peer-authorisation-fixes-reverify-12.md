# Verification: peer authorisation fixes (twelfth run: reverify-11's fixes)

**Date:** 2026-11-09
**Plan:** thoughts/plans/2026-11-06-peer-authorisation-fixes.md
**Research:** thoughts/research/2026-11-06-peer-authorisation-fixes.md
**Branch:** fix/3.16.0-peer-authorisation (local only; not pushed)
**Commit:** a43bde0 (code as of 03a0d8c; a43bde0 adds records only)

This run verifies Iterations 85 to 87 (`cdd1a96..03a0d8c`). They answered
Issues 1 to 3 of `verifications/2026-11-09-peer-authorisation-fixes-reverify-11.md`.
The owner's rule for that iteration was "only those that result in actual
user facing issues". Issues 4 to 9 were left by that rule. The reviews
below were scaled to the delta: about 100 lines of library code in
`actor.py` and `fanout.py`, plus their tests.

## Automated Check Results

- **Browser QA:** N/A. No iteration in the range touches a page, a
  template or `handlers/www.py`.
- **Outside voice** (the outside-voice agent), with two providers:
  - **Codex** (`codex exec -s read-only`, outside the sandbox): a
    `FanOutManager` failure for every client (Issue 2) and the duplicate
    descriptors kept per failed address (Issue 8). Its IPv6 finding was
    lowered and narrowed to Issue 3 after a check of urllib3 2.8.0's
    `_has_ipv6`.
  - **The fresh-context Claude reviewer:** no recovery for a client
    after a suspension (Issue 1), the connect after a give-up (Issue 4),
    `socket()` outside the `try` (Issue 3), the lost `sys.audit` event
    (Issue 7), the resume docstring (Issue 5), and the weak test for the
    late DNS answer (Issue 6).
  - **Both found clean:**
    - Raw `OSError`/`TimeoutError` from `_new_conn` still reach
      `_read_json` as requests' `ConnectionError`, which returns
      `(None, None)`.
    - Proxy CONNECT still works (`_dns_host` is the proxy's host).
    - `source_address` and the socket options are applied.
    - The read timeout is reset after the connect, in `getresponse()`.
    - `_verify_local.deadline` is cleared in the same thread's `finally`.
    - The deadline is never `None` on this path.
    - The resync has one production caller (`actor.py:4218`), and it
      handles `None`.
- **Built-in code review** (`/code-review high cdd1a96..03a0d8c`): nine
  findings, deduplicated against the above. It agrees on Issues 1 to 5.
  It adds the error classes urllib3 no longer gives (Issue 7), a real
  peer with an empty base URI read as a client (Issue 9), and the client
  rule copied at three call sites with three outcomes (Issue 10). Its
  nested-ternary nit is a note here, not an issue.
- **Built-in security review** (this context, the delta only,
  confidence bar 8): no finding at or above the bar.
  - The two guards narrow what is sent: no POST to a client's row, and
    no resync to it.
  - The connect rewrite bounds the worker more tightly than before.
  - Issue 4 is a gap in that bound (availability, which those rules
    exclude). It is reported below because the plan claims the bound.
- **ruff check:** pass. **ruff format --check:** pass, 532 files.
  **pyright:** 0 errors, 0 warnings. **verify_groups:** 54 groups
  documented, wire registry consistent.
- **DynamoDB** (`make test-all-parallel`): 6173 passed, 60 skipped,
  1 xfailed, no failure.
- **PostgreSQL** (`make test-all-parallel` with the PostgreSQL env):
  5970 passed, 263 skipped, 1 xfailed, no failure.
- **Docs** (`sphinx-build -W`): pass.
- **Wire recordings:** unchanged (`git status` clean after both runs).
- **Emm's suite on `03a0d8c`** (recorded in `a43bde0`; adoption worktree
  unchanged): PostgreSQL 2 failed / 7406 passed, DynamoDB 3 failed / 54
  passed. These are the `master` baseline's failing tests, by name.

## Phase Verification

### Iterations 85 to 87 - ISSUES FOUND

**Changes verified (they match the iterations):**
- **85: no push and no resync to a client's row.**
  - `_callback_subscription_resync` returns `None` when
    `_has_peer_endpoint` is false (`actor.py:4447-4450`). This happens
    after the trust read and before the capability check, so no fetch
    goes to the client.
  - `_send_resync_callbacks` counts only `True` and records a miss only
    for `False` (`actor.py:4218-4222`).
  - `FanOutManager._deliver_single` returns a failed `DeliveryResult`
    before it reads the secret (`fanout.py:503-513`).
  - Residue: Issues 1, 2, 5 and 9.
- **86: the connect is bounded by the deadline.**
  - `_connect` (`actor.py:174-213`) replaces urllib3's `create_connection`
    for both tracked connection classes (`:216-223`).
  - Each socket is recorded before its connect. Each connect waits
    `min(conn.timeout, time left)`, and no further address is tried once
    the fetch was given up or the deadline passed.
  - `_fetch_json` sets and clears `_verify_local.deadline`
    (`:296`, `:301`). The comment at `:73-86` matches.
  - Residue: Issues 3, 4, 7 and 8.
- **87: the SOCKS refusal is logged.** `proxy_manager_for` logs a WARNING
  that names the scheme only (`actor.py:246-258`).

**Security properties, demonstrated:**
- **No resync to a client's row:**
  `tests/test_trust_re_pair.py::TestTheResyncAfterReverify11::test_a_clients_row_gets_no_resync_and_no_miss`,
  run for `oauth2_client` (empty base URI) and for `oauth2_interactive`
  (the actor's own URI). It asserts no POST, a count of 0 and
  `missed == []`.
  - The control, `::test_a_peer_still_gets_its_resync`, asserts that the
    send was called and the count is 1.
  - The outside voice confirmed that both parameters fail on the
    reverted code.
- **No fan-out push to a client's row:**
  `tests/test_fanout.py::test_nothing_is_pushed_to_an_oauth2_clients_row`
  asserts that nothing is posted. It does not check `result.failed`
  (Issue 2).
- **The worker is freed despite many dead addresses:**
  `tests/test_verification_fetch.py::TestLateAndFull::test_a_name_with_many_dead_addresses_frees_its_worker`.
  - `getaddrinfo` returns eight `192.0.2.x:80` addresses. The test
    asserts that an honest fetch is answered in under 2 s.
  - It failed on HEAD's code here, where 192.0.2.0/24 drops packets.
  - Where the network refuses that range at once, it passes on the old
    code too (Issue 6).
- **The SOCKS refusal is logged:** `TestThroughAProxy::test_a_socks_proxy_is_refused_and_said`.
  `caplog` contains "socks5 proxy" and not the proxy's password. It fails
  on the reverted code.
- **No connect after the deadline:**
  `TestLateAndFull::test_a_dns_answer_after_the_deadline_connects_nothing`.
  It also passes on `cdd1a96`, so it guards the earlier behaviour and not
  iteration 86 (Issue 6).

## Previous Verification

**Previous:** thoughts/verifications/2026-11-09-peer-authorisation-fixes-reverify-11.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. The resync and `FanOutManager` push to a client's row; the miss never clears | Fixed: no push and no endless miss. Its cost is Issues 1 and 2 | `actor.py:4447`, `fanout.py:505`; iteration 85 |
| 2. A many-address connect holds its worker past the deadline | Fixed. Residue: Issues 3 and 4 | `actor.py:174-213`; iteration 86 |
| 3. The SOCKS refusal is silent; its test is vacuous | Fixed | `actor.py:246-258`; `test_a_socks_proxy_is_refused_and_said` |
| 4. A `list:` key is not checked at `<subtarget>/<name>` | Accepted as-is (owner's rule, iteration 85 note) | plan, "after verification …reverify-11.md" |
| 5. A full pool makes `/meta` try twice | Accepted as-is (owner's rule) | same |
| 6. A failed thread start frees the slot twice | Accepted as-is (owner's rule) | same |
| 7. Changelog: no **Behavior change:** marker; the `None` wording | Accepted as-is (owner's rule) | same |
| 8. A stale comment at `actor.py:3825-3826` | Accepted as-is (owner's rule) | same |
| 9. `_has_peer_endpoint` duplicates `_oauth2_origin` | Accepted as-is (owner's rule); see Issue 10 | same |

## Remaining Tasks

- [ ] `/iterate_plan` for the issues below. Under the owner's rule, the
      user-facing ones are Issues 1 and 2, plus Issue 3 on hosts where
      IPv6 is disabled.
- [ ] Todos are unchanged. `grant-enforcement-per-route.md`,
      `web-ui-trust-page-gaps.md` and `full-state-fallback-replica.md`
      exist and keep their `INDEX.md` rows. Nothing in this range was
      meant to close a todo.
- [ ] Before anything is pushed: the second security plan
      (`grant-enforcement-per-route`).

## Issues Found

### Issue 1: a client gets nothing for the changes made while its target was suspended
**Severity:** Medium (user-facing: an MCP client keeps a stale view, and
nothing tells it so)
**Description:**
- A change made under `suspend_subscriptions` stores no diff and moves no
  sequence. `resume_subscriptions` says the resync "is the only recovery
  for the changes made while suspended" (`actor.py:4104-4105`).
- For a client's row the resync now returns `None`
  (`actor.py:4447-4450`: `if not _has_peer_endpoint(trust_data, self.id):
  ... return None`). So a client that reads its diffs finds no gap and no
  full-state diff. The comment "the client reads its diffs" assumes a
  diff exists.
- This is not a regression of iteration 85: the client got nothing before
  either. But its subscription id used to land in `missed`. Now the gap
  is silent.

**Location:** `actingweb/actor.py:4447`
**Recommendation:** for a client's row, store a full-state diff with a new
sequence and send no POST. The fallback at `actor.py:4548-4570`
(`_store_subscription_diff`) already builds one. Count it as sent. Add a
test: suspend, change a property, resume, and the client's diff list
holds the full state.

### Issue 2: `FanOutManager` reports every client subscription as a failed delivery
**Severity:** Medium (user-facing for a consumer of the public fan-out
API)
**Description:**
- `fanout.py:507-512` returns `success=False, error="the subscriber is an
  OAuth2 client; it reads its diffs"`. The result loop counts it under
  `failed += 1` (`fanout.py:459-460`).
- `FanOutManager` is exported (`actingweb/interface/__init__.py:10`), and
  `docs/guides/subscriptions.rst:514` has consumers loop over the
  failures.
- An app that alerts or retries on `result.failed` therefore does so on
  every change while an MCP client is subscribed. A retry can never
  succeed.
- This also disagrees with the resync, which counts a client as neither
  sent nor missed. No caller in the library or in Emm reads `failed`
  today.

**Location:** `actingweb/fanout.py:505`
**Recommendation:** follow the `circuit_open` pattern. Use a fixed error
code (for example `"oauth2_client"`) with its own counter, kept out of
`failed`. Then assert `result.failed == 0` in
`test_nothing_is_pushed_to_an_oauth2_clients_row`.

### Issue 3: an error while creating a socket ends the walk over the addresses
**Severity:** Low (user-facing only where IPv6 is disabled in the
kernel: there, every verification to a dual-stack peer fails)
**Description:**
- `actor.py:196` `sock = socket.socket(family, kind, proto)` sits before
  the `try:` at `:197`.
- `socket.getaddrinfo(host, conn.port, 0, ...)` (`:191`) asks for both
  families. urllib3 instead uses `allowed_gai_family()`, which is
  IPv4-only when `::1` cannot be bound.
- On a kernel booted with `ipv6.disable=1`, `socket(AF_INET6)` raises
  EAFNOSUPPORT. EMFILE does the same under descriptor pressure. Either
  error escapes the loop, so the IPv4 addresses are never tried.

**Location:** `actingweb/actor.py:196`
**Recommendation:** create the socket inside the `try`, and pass
`urllib3.util.connection.allowed_gai_family()` instead of `0`.

### Issue 4: a connect that completes after the give-up is not shut down
**Severity:** Low (a narrow window, but the plan claims the bound)
**Description:**
- The socket is recorded before its connect (`actor.py:199`). If
  `cancel()` runs between that point and the end of `connect()`,
  `shutdown()` on the unconnected socket does nothing: `_end_socket`
  swallows the ENOTCONN.
- The connect can then succeed at `:208`. Nothing re-checks `given_up()`,
  so a peer that trickles header bytes can hold the worker at 5 s per
  `recv`.
- The old `_record_socket` ran after the connect and closed exactly this
  hole.
- The comment at `actor.py:386-388` ("a socket it connects later is shut
  down as it arrives") still describes the old guarantee.

**Location:** `actingweb/actor.py:208`
**Recommendation:** after `sock.connect(address)`, if `tracked.given_up()`,
end the socket and raise `ConnectionAbortedError`. Then correct the
comment.

### Issue 5: the resume count contract is false while a client is subscribed
**Severity:** Low (consumer-facing documentation)
**Description:**
- `actor.py:4179-4180` reads "a return value below the number of
  subscribers means some missed the resync". `CHANGELOG.rst:2191-2192`
  (Unreleased) says the same.
- A client's subscription is now neither counted nor missed. A caller who
  compares the count with its subscriber count will therefore always see
  a miss.

**Location:** `actingweb/actor.py:4179`, `CHANGELOG.rst:2191`
**Recommendation:** if Issue 1 counts the client's stored diff as sent,
the sentence holds again. Otherwise reword both places to "subscribers
with a peer endpoint".

### Issue 6: two fetch tests do not pin iteration 86
**Severity:** Low (test quality)
**Description:**
- `test_a_dns_answer_after_the_deadline_connects_nothing` passes on
  `cdd1a96` too. The old `opened()` already shut a late socket down.
- `test_a_name_with_many_dead_addresses_frees_its_worker` depends on the
  network. Its own docstring says a connect to 192.0.2.0/24 "fails at
  once where the network refuses it", and there it passes on the old
  code.

**Location:** `tests/test_verification_fetch.py:338`, `:363`
**Recommendation:** make the dead addresses deterministic. Patch the
connect step to block until its timeout. Then assert the elapsed time
against the deadline.

### Issue 7: urllib3's error classes and audit event are gone for verification connects
**Severity:** Low (operator logs; fails closed today)
**Description:**
- `_TrackedHttp._new_conn` returns `_connect(self)` (`actor.py:217`)
  instead of urllib3's `_new_conn`. Three things are lost:
  - The error classes: `NameResolutionError`, `ConnectTimeoutError` and
    `NewConnectionError`.
  - The `sys.audit("http.client.connect", ...)` event.
  - The handling of ECONNRESET. A raw ECONNRESET from the connect is
    swallowed by urllib3's `_make_request` around `conn.request`. It
    then fails later as an `AttributeError` on a `None` socket.
- `_read_json`'s broad `except` fails closed in all these cases. But a
  log or a later narrower `except` sees the wrong cause.

**Location:** `actingweb/actor.py:174-213`
**Recommendation:** wrap the errors as urllib3 does (`ConnectTimeoutError`
for a timeout, `NewConnectionError` otherwise), and call `sys.audit`
before the return.

### Issue 8: a failed address keeps its duplicate descriptor until the fetch ends
**Severity:** Low
**Description:**
- `actor.py:210-212` closes the original socket only. Its duplicate
  stays in `_FetchSockets` until `release()`.
- A requester's name with many addresses that refuse fast therefore holds
  one extra descriptor per address, in each of eight workers.

**Location:** `actingweb/actor.py:210`
**Recommendation:** when an attempt fails, remove its duplicate and close
it under the lock.

### Issue 9: a peer row with an empty base URI is treated as a client's
**Severity:** Low (a protocol row always carries a base URI)
**Description:**
- `_has_peer_endpoint` is false for any row with an empty base URI
  (`actor.py:70`). Such a row's resync therefore returns `None` (not
  counted, no log, no miss), where it used to log "missing baseuri" and
  be missed.
- `FanOutManager` names the same row "an OAuth2 client". The checks below
  the guard become unreachable for that case: `actor.py:4460-4464` and
  `fanout.py:516-521`.

**Location:** `actingweb/actor.py:4447`, `actingweb/fanout.py:505`
**Recommendation:** decide "a client's row" by OAuth2 origin
(`OAUTH2_SOURCES`, `legacy_oauth2_row`), and leave an empty base URI to
the existing checks.

### Issue 10: the client-row rule sits at three call sites, each with its own outcome
**Severity:** Low (design)
**Description:**
- The three sites are `callback_subscription` (`actor.py:3582`, silent
  return), the resync (`:4447`, `None`) and `FanOutManager`
  (`fanout.py:505`, a failure via a local import of a private helper).
- Each of the last three verifications found another push path that
  lacked this check. The outcomes already disagree (Issue 2). This
  continues reverify-11 Issue 9.

**Location:** `actingweb/fanout.py:503`
**Recommendation:** one delivery-policy helper that returns push,
client or no endpoint, used by all three sites. This would fold in
Issues 2 and 9.

**Note (not an issue):** the expression at `actor.py:202-204`, `limit if
left is None else left if limit is None else min(limit, left)`, would read
better as the minimum of the bounds that exist.

## Overall Assessment

Iterations 85 to 87 land what they set out to:
- Nothing is pushed or resynced to an OAuth2 client's trust row, and the
  endless miss is gone.
- A verification's connect now stays within its deadline across many
  addresses.
- The SOCKS refusal is logged.
- The Full tier is green on both backends (DynamoDB 6173, PostgreSQL
  5970), the docs build passes, no recording changed, and Emm's suite
  matches its baseline.
- The security review finds nothing that widens access.

Two Medium issues stand before the PR, and both are the cost of the client
skip, not of the connect rewrite:
- **Issue 1:** a client gets no full-state diff after a suspension, so its
  view stays stale with nothing to show it.
- **Issue 2:** the public fan-out API reports every client as a failed
  delivery.

Issue 3 is user-facing only on IPv6-disabled hosts. The rest are small.
The second security plan (`grant-enforcement-per-route`) still comes
before anything is pushed.
