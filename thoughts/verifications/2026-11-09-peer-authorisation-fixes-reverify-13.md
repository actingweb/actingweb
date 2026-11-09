# Verification: peer authorisation fixes (thirteenth run: reverify-12's fixes)

**Date:** 2026-11-09
**Plan:** thoughts/plans/2026-11-06-peer-authorisation-fixes.md
**Research:** thoughts/research/2026-11-06-peer-authorisation-fixes.md
**Branch:** fix/3.16.0-peer-authorisation (local only; not pushed)
**Commit:** 80ed40d (code as of ad95c79; 80ed40d adds records only)

This run verifies Iterations 88 and 89 (`e0cf495..ad95c79`). They answered
Issues 1, 3 and 5 of `verifications/2026-11-09-peer-authorisation-fixes-reverify-12.md`,
under the owner's rule of fixing only what users would meet. Issue 2
went with `FanOutManager`'s removal in `spec-1-5`, by owner decision on
2026-11-09. The reviews were scaled to the delta: about 90 lines of
`actor.py` and their tests.

## Automated Check Results

- **Browser QA:** N/A. No iteration in the range touches a page, a
  template or `handlers/www.py`.
- **Outside voice** (the outside-voice agent), with two providers:
  - **The fresh-context Claude reviewer:**
    - a client subscribed to one property gets its resync past the grant's
      exclusions (Issue 1);
    - the stored full state carries no marker that says it is one
      (Issue 2);
    - nothing tests the `allowed_gai_family()` half of iteration 89
      (Issue 11).
  - **Codex** (`codex exec -s read-only`, outside the sandbox):
    - a list's full state is an `extend` (Issue 2);
    - a resume whose snapshot races a concurrent write (Issue 6);
    - a state that could not be built is stored as `{}` and counted
      (Issue 4);
    - a retry stacks a second full state (Issue 3);
    - unbounded rows for an inactive client (Issue 7).
    - It reported no permission bypass: it did not check the shape of
      a subscription to one property.
  - **Both found nothing to fix in `_connect`.** When `socket()` raises,
    `sock` is `None` and the close is guarded. EMFILE moves on to the next
    address, and the last error fails the verification closed.
- **Built-in code review** (`/code-review high e0cf495..ad95c79`): ten
  findings, deduplicated against the above.
  - It agrees on Issues 2, 3 and 5.
  - It adds:
    - the state rebuilt for every client subscription (Issue 8);
    - the count's contract, "callbacks sent" (Issue 9);
    - a peer with a blank base URI counted, a dead guard, and a deleted
      subscription recorded as missed (Issue 10);
    - the last-error masking and the narrow test (Issue 11).
- **Built-in security review** (this context, the delta only,
  confidence bar 8): one finding at the bar, Issue 1. I checked it against
  the code:
  - `actor.py:4690` stores `{subtarget: prop_data}`, but `register_diffs`
    stores such a subscription's diff unwrapped (`actor.py:5119`
    `finblob = blob`).
  - The pull filter checks each key at `<subtarget>/<key>`
    (`actor.py:3893-3896`), so the one child it checks is `notes/notes`.
  - With a resource, `actor.py:3915` (`if not children or not excluded:
    return as_text`) returns the whole value.
- **ruff check:** pass. **ruff format --check:** pass, 532 files.
  **pyright:** 0 errors, 0 warnings. **verify_groups:** 54 groups
  documented, wire registry consistent.
- **DynamoDB** (`make test-all-parallel`): 6174 passed, 60 skipped,
  1 xfailed, no failure.
- **PostgreSQL** (`make test-all-parallel` with the PostgreSQL env):
  5971 passed, 263 skipped, 1 xfailed, no failure.
- **Docs** (`sphinx-build -W`): pass.
- **Wire recordings:** unchanged (`git status` clean after both runs).
- **Emm's suite on `ad95c79`** (recorded in `80ed40d`): PostgreSQL
  2 failed / 7406 passed, DynamoDB 3 failed / 54 passed. These are the
  `master` baseline's failing tests, by name.

## Phase Verification

### Iterations 88 and 89 - ISSUES FOUND

**Changes verified (they match the iterations):**
- **88. A client's resync is stored as a diff.**
  - For a row without a peer endpoint, `_callback_subscription_resync`
    takes the next sequence number and stores
    `_store_full_state_diff(...)`. It returns `True` when the diff was
    stored (`actor.py:4455-4469`).
  - `_store_full_state_diff` is the former fallback body, shared with the
    peer fallback (`actor.py:4611-4628`).
  - The loop counts truthy results and records every other result as
    missed (`actor.py:4225-4229`).
  - The changelog and `docs/guides/subscriptions.rst:261-263` were
    updated.
  - Residue: Issues 1 to 10.
- **89. `_connect`.** `socket()` is now inside the `try` and the close is
  guarded (`actor.py:197-218`). `getaddrinfo` gets `allowed_gai_family()`
  (`:192`). Residue: Issue 11.

**Security property, demonstrated or not:**
- **No push to a client's row:**
  `tests/test_trust_re_pair.py::TestTheResyncAfterReverify11::test_a_clients_row_gets_its_resync_as_a_diff`
  asserts no POST, for both kinds of client row.
- **The client's grant on the stored resync: not demonstrated, and
  false for a subscription to one property (Issue 1).**
  - The test reads the raw rows (`sub_obj.get_diffs()`), never through
    `GET /subscriptions/...`.
  - It covers a whole-target subscription only.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-09-peer-authorisation-fixes-reverify-12.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. A client gets nothing after a suspension | Fixed as specified, but the stored full state breaks the grant and the client's merge (Issues 1 to 4) | `actor.py:4455-4469`; iteration 88 |
| 2. `FanOutManager` counts a client as failed | Superseded: removed with `FanOutManager` in `spec-1-5` Phase 4 (owner) | plan, iteration 88 scope note |
| 3. A socket error ends the address walk | Fixed | `actor.py:197-218`; `test_an_address_whose_socket_cannot_be_made_is_skipped` |
| 4. A connect after the give-up is not shut down | Accepted as-is (owner's rule) | plan scope note |
| 5. The resume count contract | Fixed: a client's stored diff is counted. The "callbacks sent" wording is Issue 9 | `actor.py:4225-4229` |
| 6. Two fetch tests don't pin iteration 86 | Accepted as-is (owner's rule) | same |
| 7. urllib3 error classes and audit event | Accepted as-is (owner's rule) | same |
| 8. Duplicate descriptors per failed address | Accepted as-is (owner's rule) | same |
| 9. A blank-base-URI peer read as a client | Accepted as-is (owner's rule). It now also counts as a stored resync (Issue 10) | same |
| 10. The client rule at three sites | Accepted as-is (owner's rule) | same |

## Remaining Tasks

- [ ] Owner decision: what a client's resync is (see Issue 1's
      recommendation), then `/iterate_plan`.
- [ ] Todos are unchanged. `grant-enforcement-per-route.md`,
      `web-ui-trust-page-gaps.md` and `full-state-fallback-replica.md`
      exist and keep their `INDEX.md` rows.
- [ ] Before anything is pushed: the second security plan
      (`grant-enforcement-per-route`).

## Issues Found

### Issue 1: a client subscribed to one property gets its resync past its grant
**Severity:** High (iteration 88 introduced the path for clients; the
shape already reached peers without resync support)
**Description:**
- `_get_full_state_for_subscription` returns `{subtarget: prop_data}`
  for a scalar property (`actor.py:4690`). `register_diffs` stores the
  diffs of a subscription to `<subtarget>` unwrapped (`actor.py:5119`).
- The pull filter checks each key of the blob at `<subtarget>/<key>`
  (`actor.py:3893-3896`). On the wrapped blob the only key is the
  property's own name, so it checks `notes/notes`, and an exclusion of
  `notes/private` is never matched.
- With a resource, `path` is `notes/<resource>`. If that is allowed, the
  filter returns the whole blob (`actor.py:3915`), so the client gets
  every resource of `notes`.
- Example: the grant allows `notes` and excludes `notes/private`, and the
  client subscribes to `notes`. After a suspend, an import and a resume,
  `GET /subscriptions/<peer>/<sub>` returns `{"notes": {..., "private": ...}}`.
- The same shape mismatch reaches a peer through the low-granularity
  fallback (`actor.py:4569`). Iteration 88 makes every client
  subscription hit it on each resume.
- It also breaks the client's merge, which reads a key `notes` inside
  `notes`.

**Location:** `actingweb/actor.py:4455`, `:4690`
**Recommendation:** this needs an owner decision, together with Issues 2
to 4, 7 and 8:
1. **Recommended: store a resync marker, not the state.** The stored
   diff says `type: "resync"` with the resource URL, as the resync
   callback does (spec "Resync Callback"). The pull handler serves it
   with that type, and the client then re-reads with a GET under its
   own grant.
   - This closes the grant and shape gap, the list `extend`, deleted
     properties, stacking on a retry, the empty `{}`, the per-subscription
     rebuild and the row size.
   - It needs one spec sentence for pulled diffs, and a check of how
     Emm's client reads a diff it does not recognise.
2. **Keep the full state, but in the subscription's own shape.** That
   means the value of `<subtarget>` or of `<subtarget>/<resource>`, as
   `register_diffs` stores it, filtered as any diff is. A marker and a
   replace semantics for lists are still needed (Issue 2). It leaves
   Issues 3, 7 and 8.
3. **Revert iteration 88.** The client again gets nothing after a
   suspension (reverify-12 Issue 1, documented as a known gap), and the
   peer fallback's shape becomes its own todo.

Whatever is chosen, add a test that reads the resync through the
`GET /subscriptions/<peer>/<sub>` handler, for a subscription to one
property, under a grant with an exclusion.

### Issue 2: nothing marks the stored diff as a full state, so the client merges it
**Severity:** Medium (wrong client data, silently)
**Description:**
- The diff is stored as a plain dict (`actor.py:4628`) and served like
  any delta (`handlers/subscription.py:400-405`).
- A client that merges diffs, as it must for every other diff, keeps a
  property deleted during the suspension.
- It also appends a list's items a second time, because the list's full
  state is `"operation": "extend"` (`actor.py:4682`).
- A list over the span threshold arrives as a reference that a merging
  receiver drops.
- `docs/guides/subscriptions.rst:261-263` promises "the full state", but
  gives no way to apply it as a replacement.

**Location:** `actingweb/actor.py:4628`, `:4682`
**Recommendation:** Issue 1's option 1 removes this. Under option 2, mark
the diff and give lists a replace operation.

### Issue 3: a retry after a transient fault stores a second full state
**Severity:** Medium (with Issue 2: lists duplicated again)
**Description:**
- A transient `DbError` from any subscriber puts the suspension back and
  raises it (`actor.py:4244-4250`).
- The caller's retry sends to every subscriber again. A client whose diff
  already landed gets a second full state under a new number.
- Before iteration 88, a retry was harmless for a client.

**Location:** `actingweb/actor.py:4244`
**Recommendation:** Issue 1's option 1 makes a second marker harmless.
Otherwise, skip the subscribers that a resume already served.

### Issue 4: a state that could not be built is stored as `{}` and counted
**Severity:** Medium
**Description:**
- A corrupt list (`actor.py:4674` `return {}`) or a missing subtarget
  (`:4693` `return {}`) is stored as an empty diff.
- The resync counts as sent, and the pending record clears, so it is
  never retried.

**Location:** `actingweb/actor.py:4674`, `:4693`
**Recommendation:** return `False` (missed) when the state could not be
built, and keep `{}` only for a state that really is empty. Issue 1's
option 1 avoids this.

### Issue 5: the sequence number is used even when the store fails
**Severity:** Low (the peer fallback already does the same)
**Description:**
- The client branch takes the next number at `actor.py:4460` before the
  store.
- If `_store_subscription_diff` returns `""`, the client sees a gap, and
  each retry from the pending record uses up another number.

**Location:** `actingweb/actor.py:4460`
**Recommendation:** accept, or store before taking the number, as
`add_diff` does.

### Issue 6: the snapshot can race a write made after the suspension is lifted
**Severity:** Low (applies to the peer fallback too)
**Description:**
- `resume` removes the marker (`actor.py:4137`) before each client's
  number and snapshot (`:4460`).
- A concurrent append can therefore take the next number and also be in
  the snapshot. A merging client then applies it twice.

**Location:** `actingweb/actor.py:4137`
**Recommendation:** Issue 1's option 1 removes it. Otherwise, take the
snapshot before the number.

### Issue 7: every resume adds a full-state row per client subscription
**Severity:** Low
**Description:**
- The branch at `actor.py:4455` has no granularity check, so it also
  stores rows for `granularity="none"`.
- A row is cleared only when the client reads it or clears it
  (`handlers/subscription.py:483`, `:643`). An inactive client and
  frequent imports pile up rows near the size cap.

**Location:** `actingweb/actor.py:4455`
**Recommendation:** skip `granularity="none"`. Then either clear the
subscription's older diffs that the new one supersedes, or follow Issue
1's option 1.

### Issue 8: the full state is rebuilt for each client subscription
**Severity:** Low (cost)
**Description:** `_store_full_state_diff` (`actor.py:4618`) reads every
property, and dumps the whole list partition, once per client
subscription in the loop.
**Location:** `actingweb/actor.py:4618`
**Recommendation:** build it once per target and subtarget, or follow
Issue 1's option 1.

### Issue 9: the count is still documented as "callbacks sent"
**Severity:** Low (documentation)
**Description:**
- `resume_subscriptions` (`actor.py:4098` "The number of resync
  callbacks sent") and `SubscriptionManager.resume`'s example ("Notified
  {callbacks_sent} subscribers") now also count stored client diffs.
**Location:** `actingweb/actor.py:4098`,
`actingweb/interface/subscription_manager.py:835`
**Recommendation:** "the number of subscribers resynced".

### Issue 10: edge cases of the client branch
**Severity:** Low
**Description:**
- A peer row with a blank base URI now gets a stored diff, counted as a
  resync it never receives (reverify-12 Issue 9).
- The guard `if not callback_url or not trust_data.get("baseuri")`
  (`actor.py:4480`) is now dead code.
- A subscription deleted mid-resume (the next number returns 0) is
  recorded as missed. That costs one pending-record write, and the next
  resume filters it out.

**Location:** `actingweb/actor.py:4455`, `:4480`, `:4229`
**Recommendation:** decide a client's row by OAuth2 origin (reverify-12
Issue 10), and remove the dead guard.

### Issue 11: test coverage and error reporting of the delta
**Severity:** Low
**Description:**
- The client resync test covers one scalar on a whole-target
  subscription. It does not cover a subtarget, a list, a reference, a
  deleted property, the grant filter or a failed store recorded as
  missed.
- `v6_first` ignores the family argument, so reverting
  `allowed_gai_family()` still passes.
- `_connect` keeps only the last `OSError`, so a refused IPv4 address
  followed by an EAFNOSUPPORT for IPv6 reports the wrong cause.

**Location:** `tests/test_trust_re_pair.py:2308`,
`tests/test_verification_fetch.py`, `actingweb/actor.py:216`
**Recommendation:** add tests along with whichever option Issue 1 takes.

## Overall Assessment

Iteration 89 is sound: an address whose socket cannot be made is skipped,
and the family is asked for as urllib3 asks. Iteration 88 meets its own
test, but storing the full state as an ordinary diff makes the resume
send data to clients that it never sent them before:
- a client subscribed to one property gets fields its grant excludes,
  and sibling resources (Issue 1, High);
- a merging client keeps deleted properties and duplicates list items
  (Issue 2), again after a retry (Issue 3);
- an unbuildable state counts as delivered (Issue 4).

The Full tier is green on both backends (DynamoDB 6174, PostgreSQL 5971),
the docs build passes, no recording changed, and Emm's suite matches its
baseline.

Iteration 88 must not ship as it is. The choice of what a client's resync
is belongs to the owner. The recommendation is a resync marker that makes
the client re-read under its own grant. The second security plan
(`grant-enforcement-per-route`) still comes before anything is pushed.
