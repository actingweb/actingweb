# Verification: SPA logout and `/oauth/revoke` end the refresh chain

**Date:** 2026-09-29
**Plan:** thoughts/plans/2026-09-29-logout-does-not-revoke-refresh-chain.md
**Research:** thoughts/research/2026-09-28-logout-does-not-revoke-refresh-chain.md
**Branch:** fix/3.15.1-logout-revokes-chain
**Commit:** 63c1cb3 (the implementation is an uncommitted working tree on top of it; this verifies that tree)

There is no feature document for this plan, so no Success Measures section.
There is no previous verification for this plan.

## Automated Check Results

The full tier from `CLAUDE.md`, run once, one run at a time (no concurrent
runs). Both test runs are the **parallel** `make test-all-parallel` (`-n auto
--dist loadgroup`, 11 workers). Neither showed a failure, so no sequential
re-run was needed; every number below comes from the parallel run.

- **Browser QA:** N/A. No phase adds or changes a page a user sees; the
  changes are handlers, integrations and token stores. The one browser-visible
  effect (the www UI's non-AJAX logout answering a 503 where it redirected) is
  covered by route tests, not a browser: `### App` says browser QA cannot
  cover login (real OAuth2 provider, no test account). **The UI was not
  exercised.**
- **Second opinion:** Codex ran unsandboxed through the outside-voice agent
  (`use codex` pin for diffs), plus a fresh-context Claude read for the parts
  Codex did not cover. Findings under Issues Found (I1-I7).
- **Built-in code review (high):** ran (10 findings). Four are kept as I9-I12
  below after checking them against the tree; the rest were discarded or
  merged: the reviewer's claim that hybrid delivery from `/oauth/spa/token`
  scopes the refresh cookie away from logout is wrong (`_set_refresh_token_cookie`
  uses `path="/"`; only the provider-callback hybrid uses `/oauth/spa/token`,
  which the plan already lists under What We're NOT Doing); its claim that
  `single_use._mask` lacks the short-token guard is wrong (it has it); the
  duplicated `ttl_deadline`, the private-name import, the hard-coded SDK cookie
  lists and the per-call DynamoDB scan cost are style or plan-accepted (the
  scan is Decision 2).
- **Built-in security review:** ran over the diff (it touches auth, input
  handling and data access); 0 findings at confidence 8 or above. It
  considered the cross-site `GET /oauth/logout` forced logout, which the
  owner accepted (plan Decisions).
- `poetry run ruff check actingweb tests`: pass, "All checks passed!".
- `poetry run ruff format --check actingweb tests`: pass, 405 files already
  formatted.
- `poetry run pyright actingweb tests`: pass, 0 errors, 0 warnings.
- `make test-all-parallel` on **DynamoDB** (default backend): pass, **3881
  passed, 31 skipped**, 0 failed (3912 collected).
- `make test-all-parallel` on **PostgreSQL**
  (`DATABASE_BACKEND=postgresql`, port 5433): pass, **3772 passed, 140
  skipped**, 0 failed (3912 collected). The higher skip count is the
  DynamoDB-only tests skipping; both runs include `tests/integration/`.
- `sphinx-build -W --keep-going ...`: pass, "build succeeded", 0 warnings.
- Phase-specific integration files, on both backends (from the runs above):
  `tests/integration/test_spa_chain_revocation_backend.py` (4 tests),
  `tests/integration/test_oauth2_spa_logout.py` (6 tests) and
  `tests/integration/test_mcp_refresh_rotation_backend.py` all PASSED on
  DynamoDB and on PostgreSQL.
- Benchmarks: not run. The plan touched the token attribute layer
  (`delete_by_chain`, `set_attr` TTL helper) but not list storage, and
  benchmarks are excluded from CI.

## Phase Verification

### Phase 1: Fault-safe chain revocation in both token stores - VERIFIED (minor findings)

**Changes verified:**
- `actingweb/single_use.py:224` `revoke_chain_confirmed`: matches the plan
  (any exception to `StoreFault`; anchor strict-read on zero; anchor gone
  returns 0; anchor present or unreadable raises). `_mask` is the one masking
  helper, imported by `token_manager.py` as `_mask_token`.
- `actingweb/oauth_session.py:928` `revoke_token_chain(..., anchor=)`: calls
  the helper, maps `StoreFault` to `TokenStoreUnavailable`, evicts in
  `finally`, logs INFO, returns 0 without an anchor (public contract kept).
- `actingweb/oauth_session.py:1030` `revoke_session`: strict read in the
  hinted bucket then the other; chain path anchors on the row; chain-less path
  uses `delete_confirmed` and raises on False; returns the row data.
- `store_access_token` raises `TokenStoreUnavailable` on a failed write
  (`oauth_session.py`, the `set_attr` check); `new_chain_id()` added.
- `actingweb/db/dynamodb/attribute.py:391-455` `delete_by_chain`:
  `startswith(bucket + ":")`, query failure raises instead of `continue`,
  iterates and counts, WARNING past `CHAIN_SCAN_WARN_ROWS = 1000`, docstring
  rewritten; `db/protocols.py` note updated. PostgreSQL unchanged in behaviour
  (still answers 0 on a fault; the helper's anchor read is what disambiguates).
- `ttl_deadline()` helper in both backends (deviation: named `ttl_deadline`,
  not `ttl_timestamp`, accepted and recorded in the plan).
- `token_manager.py`: `_revoke_chain` calls the shared core and keeps the
  MCP rule that a zero without an anchor is a fault; `revoke_client_tokens`
  evicts in `finally` per token and once per client; `validate_access_token`
  expired branch passes `actor_id`/`google_token_key`, fallback branch is
  index-first with `delete_confirmed`; `_search_auth_code_in_actors` and
  `_load_google_token_data` are strict (the former reuses
  `_search_indexed_token`, an accepted deviation); the provider-token read is
  before the consume; `cleanup_expired_tokens` is `_sweep_index` x3 with a
  `skipped` key.
- Theft branch in `oauth2_spa.py` (~747-777): anchored revoke inside
  `try/except TokenStoreUnavailable` returning `_store_unavailable()`; the
  chain-less fallback goes through `revoke_session`.
- `_generate_actingweb_token` no longer swallows the write failure
  (`oauth2_spa.py:1621-1646`).

**Tests verified** (exist and assert the promised properties):
- Theft fault family on the fault-injecting double,
  `tests/test_oauth2_spa_refresh_rotation.py`:
  `test_a_theft_revocation_fault_answers_503_and_keeps_the_used_token` (:407,
  parametrised over the `zero`/`raise` faults),
  `test_a_partial_theft_revocation_keeps_the_anchor_and_the_retry_finishes`
  (:431), `test_a_faulting_anchor_read_after_a_zero_delete_answers_503` (:452),
  `test_a_concurrent_revocation_is_done_not_a_fault` (:465),
  `test_a_legacy_chainless_reuse_fault_answers_503_and_keeps_the_row` (:482),
  `test_the_mcp_caches_are_evicted_on_the_fault_path_too` (:506).
- `tests/test_dynamodb_delete_by_chain.py`: sibling bucket not read (:51),
  anchor deleted last (:66), failing query raises (:88), row-budget WARNING
  (:99) and no WARNING within budget (:118), `ttl_deadline` skew (:131).
- `tests/test_oauth_session.py` (+145), `tests/test_single_use.py` (+74),
  `tests/test_mcp_token_store_faults.py` (+250) and
  `tests/test_mcp_auth_code_single_use.py` (+50) carry the `revoke_session`,
  `revoke_chain_confirmed`, sweep, eviction and auth-code cases the plan
  listed; all pass on both backends.
- `tests/integration/test_spa_chain_revocation_backend.py`: anchored delete
  removes only that chain (:54), a second revoke is "done" not a fault (:79),
  `revoke_session` with the refresh token ends the access token too (:102),
  chain-less revokes only itself (:120). Real backend, both backends green.

**Failure Scenarios** (plan section, each has its test): delete raises
mid-scan (partial test), PG silent zero (zero test), anchor read faults (hook
test), concurrent revocation (hook-pop test), eviction on raise (spy test),
query cannot be built (`test_dynamodb_delete_by_chain.py:88`), login-time
write fails (`store_access_token` `write_faults` test), partition growth
(:99), sweep meets an unreadable row (`test_mcp_token_store_faults.py` sweep
cases).

**Deviations from plan:** all recorded in the plan's Implementation Summary
and acceptable: `ttl_deadline` name, `_search_indexed_token` reuse,
`cleanup_expired_tokens` always returns `skipped`, the DynamoDB prefix test
stubs `Attribute.query` instead of extending the double.

### Phase 2: Login tagging, `/oauth/revoke`, `/oauth/logout`, SDK logout - VERIFIED (findings I1, I2)

**Changes verified:**
- Login tagging at all five sites: `oauth2_callback.py:709-721` and
  `:1241-1250`; `oauth2_spa.py:1011` (authorization code), `:1172`
  (`_finalize_native_session`, shared by the JWT bearer and mobile ticket
  grants) and `:1421` (passphrase). The `www` cookie token stays chain-less.
- `_handle_revoke` (`oauth2_spa.py:1459-1554`): token source order body,
  Bearer, `refresh_token` cookie (hint becomes refresh), `access_token` /
  `oauth_token` cookie; `revoke_session`; provider token cleared after the
  confirm; `TokenStoreUnavailable` maps to `_store_unavailable()`; the blanket
  `except Exception` is gone; unknown token still 200.
- `/oauth/logout` (`oauth2_endpoints.py`): `_logout_refresh_tokens` (body JSON
  only for a JSON content type, form field, cookie on any method, never a 400),
  `_handle_provider_token_logout` routing, `_handle_session_token_logout`
  outside the branch's `except`, `_LOGOUT_COOKIES` as `(name, path)` with the
  second `refresh_token` clear at `/oauth/spa/token`, `oauth_refresh_token`
  dropped everywhere including `oauth2_server.py`.
- SDK `handle_logout_request` (`oauth2_server.py:~769`) returns
  `{"action": "retry", "retry_after": 5}` with no `clear_cookies`.
- FastAPI `/oauth/logout` always delegates and returns the handler response;
  the 302 only for a non-AJAX success with the `oauth_token` cookie, copying
  `Set-Cookie` and CORS headers. `OAuth2SPAHandler._handle_logout` and its
  dispatch are deleted; `handler.post("logout")` answers 404
  (`tests/test_oauth2_spa_logout_revokes_chain.py:548`).

**Tests verified** (security properties demonstrated, per the project
addendum; each is a test that fails if the property is lost):
- *Revocation ends the chain*: `test_logout_with_the_login_access_token_ends_the_chain`
  (`tests/test_oauth2_spa_logout_revokes_chain.py:198`) logs out with the
  login access token, then asserts both rows are gone
  (`alive(...) == (False, False)`), that the refresh token now answers **401**
  at `_handle_refresh_token`, and that a second login (another chain) is still
  `(True, True)`. `test_logout_after_a_rotation_ends_the_rotated_chain` (:212)
  asserts the rotated successor and its consumed predecessor both 401. The
  same on the real backends:
  `tests/integration/test_oauth2_spa_logout.py::test_logout_with_the_access_token_kills_the_refresh_token`,
  `test_revoke_with_the_refresh_token_ends_the_chain`,
  `test_revoking_a_used_refresh_token_kills_its_successor`,
  `test_logout_with_only_a_refresh_token_in_the_body_ends_the_chain`,
  `test_logout_with_the_refresh_cookie_alone_ends_the_chain` (all passed on
  DynamoDB and PostgreSQL).
- *Fail closed, no cookie cleared, token kept as the retry handle*:
  `test_a_chain_fault_on_logout_is_503_and_keeps_everything` (:339) asserts
  status 503, `Retry-After: 5`, the exact body, `handler.response.cookies == []`,
  both tokens still present, no provider clear, then a retry after the fault is
  lifted succeeds and clears the five `(name, path)` pairs.
  `test_a_faulting_lookup_is_503_not_logged_out` (:371) and
  `test_revoking_an_unknown_token_during_an_outage_is_503_not_a_false_200` (:493).
- *Chain-less legacy revokes only itself*: `..._legacy_chainless_access_token_removes_only_that_row` (:225).
- *One scan for two tokens of one chain*: `test_both_tokens_of_one_chain_cost_one_chain_delete` (:306).
- Tagging assertions: `:159` (passphrase, on the double's store) and
  `test_oauth2_callback_spa_json_chain.py:45` (site A, its own test), plus the
  `MagicMock` `call_args.kwargs["chain_id"]` checks in
  `test_mobile_oauth2.py`, `test_oauth2_spa_mobile_ticket.py` and
  `test_oauth2_callback_apple.py` (authorization code, mobile ticket, Apple web
  callback).
- `tests/test_spa_session_retrieve.py` (new, 7 tests) closes the
  session-retrieve todo.
- Existing suites the plan named (`test_oauth2_spa_refresh_rotation.py:179`,
  `test_mcp_revocation_evicts_caches.py:278`) pass unchanged.

**Deviations from plan:** `_handle_session_token_logout` takes a *list* of
refresh tokens (body and cookie can differ); `/oauth/revoke` answers 400 for a
non-object JSON body; the FastAPI route needed no CORS rebuild for the handler
response. All acceptable and recorded.

### Phase 3: CORS, documentation, changelog, todo bookkeeping - VERIFIED (one scope note, I8)

**Changes verified:**
- `spa_cors_headers` (`oauth2_spa.py:128`) is used by the handler, Flask's
  logout and SPA-endpoint branches and FastAPI's logout, logout preflight,
  SPA-endpoint and session-retrieve responses. It honours `spa_cors_origins`
  and adds `Access-Control-Expose-Headers: Retry-After`.
- Docs: `docs/guides/spa-authentication.rst`, `docs/reference/security.rst`
  and `docs/guides/database-maintenance.rst` read against the code: the 503
  bodies match `_store_unavailable`/`_json_error` and the logout fault body;
  the cookie list and precedence match `_LOGOUT_COOKIES` and
  `_logout_refresh_tokens`. The docs build passes with `-W`.
- Changelog (`CHANGELOG.rst`, `Unreleased`): SECURITY leads with the
  fail-open theft response, CHANGED/ADDED/FIXED cover every item in the plan's
  list, each with **Behavior change:** sentences, the v3.15 guide line and the
  3.15.0 `/oauth/token` wording corrected in the 3.15.1 entry. The "login
  tagging" list (passphrase, authorization code, JWT bearer, mobile ticket,
  both callbacks) matches the five call sites above.
- Todo bookkeeping: the five todo files are deleted with their `INDEX.md`
  rows; `mcp-token-manager-hygiene-followups.md` is trimmed to two items
  (renumbered) with its `INDEX.md` row updated; the
  `db-layer-get-bucket-or-empty.md` row names the new `loaded` consumers.
  Every remaining mention of the deleted file names is inside a dated
  snapshot (research, plans, verifications), which are not edited.
- Plan Verification bullet "re-read `thoughts/README.md` before deleting
  the todos": the README was read for this run and the deletions follow its
  rules (todo files deleted, not annotated).
- Consumer message: the plan has no separate consumer-message phase; the
  changelog entry is the consumer message. It is accurate after
  implementation (checked against the code above).

**Tests verified:** `tests/test_spa_token_retry_after.py` (+189) covers
`Access-Control-Expose-Headers` on the 503s for Flask and FastAPI, the
allowlist behaviour and the `OPTIONS /oauth/spa/logout` origins (:165, :171);
`tests/integration/test_oauth2_flows.py::TestOAuth2CORSPreflight` gained the
logout header check.

**Deviations from plan:** the FastAPI `OPTIONS /oauth/spa/logout` defect was
fixed in this release instead of filed as `spa-logout-options-wildcard-with-credentials.md`
(plan Phase 3 said to file it). See I8.

## Remaining Tasks

- [ ] Nothing from the plan is unimplemented. Follow-ups below (I1, I2, I3)
      are decisions for the owner; if they are not taken now, file them in
      `thoughts/todo/` with an `INDEX.md` row.
- [ ] The whole change is uncommitted. Nothing here is committed or pushed;
      `/changelog` -> `/commit` is the next step once the findings are settled.

## Issues Found

Ordered by severity. Each finding quotes a line; findings from the outside
voice were checked against the tree where noted.

### I1. Logout and refresh rotation race can leave a live pair
**Severity:** Medium
**Description:** `revoke_session` reads the anchor, then `delete_by_chain`
sweeps the two buckets. A concurrent refresh that consumed the old token
before the sweep mints its successors afterwards
(`oauth2_spa.py:788-793`, `new_access_token = self._generate_actingweb_token(...)`
then `create_refresh_token(...)`), so a new access and refresh row with the
same `chain_id` can appear after the sweep. Logout then answered success for a
chain that is still alive. The tests run revoke and refresh one after the
other. The window is milliseconds and needs the client itself (or a thief) to
refresh at the moment of logout; the outside voice rated it High, I rate it
Medium: it is inherent to a delete-by-chain without a revoked-chain marker and
is the same shape as the pre-existing theft response.
**Location:** `actingweb/oauth_session.py:928` (`revoke_token_chain`),
`actingweb/handlers/oauth2_spa.py:788`
**Recommendation:** After minting, re-check the chain's anchor (or a
chain-revoked marker) and delete what was minted; or accept and document the
window. Not a regression, so it is a todo unless the owner wants it in 3.15.1.

### I2. The logout catch-all still answers 200 and clears cookies on any non-store error
**Severity:** Medium
**Description:** The plan says "The outer catch-all at `:936-951` stays for
genuine bugs", so this is a plan decision, but it contradicts the headline
guarantee "no cookie is cleared unless the revoke was confirmed". Any error
other than `TokenStoreUnavailable` in `_handle_session_token_logout` (for
example `get_attribute` failing, or `_clear_provider_token_for_actor`
raising outside its own catch) falls into
`"message": "Logged out (token revocation failed)", "clear_cookies": list(_LOGOUT_COOKIES)`
and answers 200 with the tokens still valid. The changed test
`tests/test_oauth2_logout_mcp_tokens.py:213-230` pins that behaviour. The line
existed before (`git show HEAD:...` has the same text), so the swallow is not
new; what is new is that the documentation and changelog say the contract is
fail-closed.
**Location:** `actingweb/handlers/oauth2_endpoints.py:959-967`
**Recommendation:** Answer 503 with `Retry-After` and no cookie change there
too, or word the changelog and guide so a reader does not assume a 200 always
means revoked.

### I3. PostgreSQL `delete_by_chain` errors read as "already revoked" when the anchor has expired meanwhile
**Severity:** Low
**Description:** PostgreSQL's `delete_by_chain` catches every error and returns
0 (`actingweb/db/postgresql/attribute.py:704-706`). The helper treats a
strict-read `None` on the anchor as a concurrent revocation
(`actingweb/single_use.py:274-284`), and `revoke_token_chain` then logs "was
already revoked". A delete that failed on PostgreSQL while the anchor row
happened to pass its TTL in the same instant is reported as done. The anchor
is a 1 h access token or a 14-day refresh token and the fault has to coincide
with expiry, so this is theoretical; DynamoDB's raises instead.
**Location:** `actingweb/db/postgresql/attribute.py:704`
**Recommendation:** Let PostgreSQL `delete_by_chain` raise, or accept and note
it in the helper's docstring.

### I4. `_sweep_index` counts unconfirmed deletes as cleaned and deletes rows it cannot parse
**Severity:** Low
**Description:** `cleaned["index_entries"] += 1` follows `index.delete_attr(...)`
without using its result (`token_manager.py:1623` and `:1637`), and
`cleaned[counter] += 1` follows `remove(...)` whose `_remove_access_token`
result is dropped (`access_remove` returns None, `:1631`). A delete the store
did not perform is reported as removed rather than skipped, so the returned
counters overstate. The `else` branch at `:1633-1637` also fires for a row
whose `data` is present but not a dict ("Absent, expired or malformed"), which
deletes it although the docstring promises a strict read that returns nothing
never hides a live row (a non-dict payload would be a schema change or mixed
version deploy).
**Location:** `actingweb/oauth2_server/token_manager.py:1615-1637`
**Recommendation:** Count only confirmed deletes; skip (and count as
`skipped`) a row whose payload is present but not a dict.

### I5. Expired-but-unreaped access rows leave their provider-token row behind on revoke and sweep
**Severity:** Low
**Description:** In the `validate_access_token` fallback, `token_data` is read
strictly, and for an expired-but-unreaped row it is `None`, so
`token_data.get("google_token_key")` is never reached and the provider-token
row stays (`token_manager.py`, the `if isinstance(token_data, dict) and
token_data.get("google_token_key")` guard). The sweep's "absent" branch has the
same gap. The provider row has its own TTL, and the sweep's provider-token
purge is a no-op on DynamoDB, so on DynamoDB the leftover lives to its TTL.
**Location:** `actingweb/oauth2_server/token_manager.py` (fallback branch of
`_remove_access_token`), `:1633-1637`
**Recommendation:** Rely on the provider row's TTL and say so in the
docstring, or store the key on the index row.

### I6. `revoke_session` reports a present-but-malformed row as "unknown"
**Severity:** Low
**Description:** `if row and isinstance(row.get("data"), dict)` then
`if found_bucket is None or data is None: return None`
(`oauth_session.py:1086`). A row that exists with non-dict data is answered as
an unknown token (200, cookies cleared) while the row stays. Whether such a row
would validate elsewhere is not established.
**Location:** `actingweb/oauth_session.py:1086`
**Recommendation:** Delete or raise on a present-but-malformed row.

### I7. Stale docstring on `_store_unavailable`
**Severity:** Low
**Description:** It still says "for a token-store fault on the refresh grant";
it now also serves `/oauth/revoke` and the theft branch.
**Location:** `actingweb/handlers/oauth2_spa.py:1758-1762`
**Recommendation:** Reword to "on the SPA token endpoints".

### I8. Unplanned change: FastAPI `OPTIONS /oauth/spa/logout` fixed instead of filed
**Severity:** Low (scope)
**Description:** The plan said to file the OPTIONS wildcard-with-credentials
defect as a todo (What We're NOT Doing, Phase 3). The implementation fixed it
(`fastapi_integration.py`, the `request.method == "OPTIONS"` branch in
`oauth2_spa_logout`). It is small, covered by
`tests/test_spa_token_retry_after.py:165,171`, named in the changelog and in
the plan's Implementation Summary, and it is not a public signature change, so
a patch may carry it. It was decided after review rather than planned; the
plan text ("What We're NOT Doing") still lists it as out of scope, which is
now misleading.
**Location:** `actingweb/interface/integrations/fastapi_integration.py`
(`oauth2_spa_logout`)
**Recommendation:** Accepted as-is; leave the plan text as the record of what
was decided at the time (the Implementation Summary records the change).

### I9. A patch that changes wire shape has no **Breaking:** lead and no migration note
**Severity:** Medium (release process; owner decision)
**Description:** `CLAUDE.md` `### Changelog` says a wire-shape or API change
gets a **Breaking:** lead under `CHANGED`, and `### Release` says a patch is
for changes with no route, hook, kwarg, response field or public signature
change. This branch adds 503 answers on `/oauth/revoke` and session-token
`/oauth/logout`, a new `action: "retry"` from the public
`handle_logout_request`, a different `clear_cookies`/`cleared_cookies` list,
a new `skipped` key, a FastAPI logout that no longer answers
`{"message": "No active session to logout"}`, and a CORS allowlist effect. The
plan's outside-voice verdict was "3.15.1 stands; the changelog carries the
response-field and 503 changes", so the vehicle was decided, but the entries
use **Behavior change:** sentences and none carries a **Breaking:** lead.
**Location:** `CHANGELOG.rst` `Unreleased`, CHANGED entries
**Recommendation:** Confirm 3.15.1 with the owner against the release rule, and
lead the SDK `retry` entry and the FastAPI logout entry with **Breaking:**, or
record why they are not.

### I10. MCP token plus SPA refresh cookie: only the MCP chain is revoked, but the SPA cookie is cleared
**Severity:** Low
**Description:** `_handle_provider_token_logout` returns
`_handle_mcp_token_logout(token)` when the token has the MCP prefix and drops
`refresh_tokens` (`oauth2_endpoints.py`, `if token and token.startswith(...)`).
A request with an MCP Bearer token and an SPA `refresh_token` cookie gets 200
and all cookies cleared while the SPA chain stays live. A mixed request is
unusual; the browser still holds no cookie afterwards, but a copied value
stays valid.
**Recommendation:** Also revoke the presented refresh tokens on that path, or
do not clear the SPA cookies there.

### I11. A refresh token in the POST query string is accepted
**Severity:** Low
**Description:** `_logout_refresh_tokens` adds `self.request.params.get("refresh_token")`
on POST; `params` is the merged query and form values, so
`POST /oauth/logout?refresh_token=...` works, and a credential in a URL lands
in access logs. The docs promise a JSON body or a form field only.
**Location:** `actingweb/handlers/oauth2_endpoints.py`, `_logout_refresh_tokens`
**Recommendation:** Read form-body values only.

### I12. The sweep's unconfirmed delete is never retried (sharpens I4)
**Severity:** Low
**Description:** The removers delete the index row first, so when the actor-row
delete then faults, the sweep counts it as removed and no later sweep sees the
orphan (its index row is gone); only the row's TTL reaps it. The
`_sweep_index` docstring's "the next run retries them" does not hold for that
case.
**Location:** `actingweb/oauth2_server/token_manager.py:1631`

## Overall Assessment

The implementation matches the plan on every phase: both endpoints now end the
whole refresh chain through one entry point, `revoke_session`; a store fault on
logout, revoke or the theft response answers 503 with `Retry-After`, keeps the
presented token as the retry handle, clears no cookie and evicts caches. The
security property is demonstrated, not inferred: the tests named above assert
the refresh token answers 401 after logout, that another chain survives, and
that on a fault nothing is cleared and the retry succeeds, and the same
properties hold on the real DynamoDB and PostgreSQL backends. The full tier is
green on both backends (3881 and 3772 passed, no failures), lint, type check
and the `-W` docs build are clean, and the todo bookkeeping and changelog
match the code. The UI was not exercised: no phase adds a page, and browser QA
cannot log in without a real OAuth2 provider, so the www UI's non-AJAX logout
change is verified through route tests only.

Nothing found blocks merging in my view, but three findings deserve an owner
decision before the release: I9 (whether a **Breaking:** lead and a minor are
due under the project's own release rule), I1 (the logout-versus-refresh race, which the
outside voice rated High and I rated Medium) and I2 (the logout catch-all that
still answers 200 for a non-store error, at odds with the fail-closed
wording in the changelog and guide). The rest are Low.

The plan update above stands: `verified:` points at this document.

**Plan update:** the plan already carries `status: done`. `verified:` is set to
this document because the verification covers all three phases. The plan
status and link are set as part of this run.
