# Verification: a peer's grant is the answer on every route

**Security, unpublished.** Keep local under the same rule as the plan: never
push before the fix.

**Date:** 2026-11-10
**Plan:** thoughts/plans/2026-11-10-grant-enforcement-per-route.md
**Research:** thoughts/research/2026-11-10-grant-enforcement-per-route.md
**Branch:** fix/3.16.0-grant-enforcement (local only)
**Commit:** 78b5953 (Phases 0 to 4: `70521b6`, `167ed5e`, `3e66670`,
`6097f62`, `7b36fbf`; `78b5953` closes the plan)

First verification of this plan (no previous one). No feature document;
the plan's Overview and the audit items (A5 to A7, A10, A13 to A20, T22,
C10) are what it is measured against.

## Automated Check Results

The Full tier ran on the tree of `7b36fbf` after its last code change (the
code at `78b5953` is the same; `78b5953` changes only the plan).

- **ruff check / ruff format --check / pyright** (`actingweb tests`): pass,
  0 errors, 0 warnings.
- **verify_groups.py**: pass ("All 57 groups documented", "Wire rows
  registry consistent").
- **Unit (fast tier)**: 4973 passed, 43 skipped, 1 xfailed.
- **DynamoDB, `make test-all-parallel`**: 6411 passed, 60 skipped, 1
  xfailed.
- **PostgreSQL, `make test-all-parallel`**: 6208 passed, 263 skipped, 1
  xfailed.
- **PostgreSQL, sequential `make test-integration`** (run because an
  earlier parallel PostgreSQL run had failures): 1372 passed, 1 failed:
  `test_callback_processor_concurrency.py::test_two_concurrent_deliveries_run_the_handler_once`
  (`['duplicate', 'processed'] != ['in_progress', 'processed']`). It fails
  identically on `master` (`999f3b6`) and at `6097f62`: not this plan's;
  filed as `thoughts/todo/callback-concurrency-test-sequential-postgresql.md`.
  The same sequential run first exposed a real defect of this plan (a stale
  permission-store cache in a multi-app process); it was fixed in
  `7b36fbf` with `tests/test_evaluator_store_lookup.py`, which fails on the
  code before.
- **Docs** (`sphinx-build -W ...`): build succeeded.
- **Benchmarks**: not run; the plan does not touch list storage or the
  attribute layer.
- **Wire recordings**: each phase's commit changed only the rows it owns
  (Phase 4: `WG18`, `WG19`, `rows.toml`); compared twice after recording.
- **Emm's suite** on `78b5953` (library worktree
  `.claude/worktrees/master-5a7e07f` checked out at `78b5953`; Emm's
  adoption worktree `emm-3-16` unchanged; environment 9): PostgreSQL 2
  failed / 7406 passed / 14 skipped / 179 deselected; DynamoDB lane 3
  failed / 54 passed. The failures are the `master` baseline's by name
  (`test_dynamodb_iam_coverage`, the Stripe mock, the two operation-profile
  tests, the restore import). No new failure. The environment 9 server was
  stopped afterwards.
- **Browser QA:** not run. The only user-facing changes are the authorize
  form's hidden `form_nonce` input and the new `aw-oauth-confirm.html`
  page; both are reached only through an OAuth provider sign-in. The demo's
  local QA mode (`DEMO_QA_BASIC_AUTH=true`) turns OAuth off, and the
  project forbids real credentials in browser QA, so neither page could be
  loaded in a browser. Their behaviour is covered over HTTP by
  `tests/integration/test_oauth2_trust_binding.py:178-414` (honest flow,
  confirmation, decline, replay, expiry, headers) and the `WG15`/`WG16`
  recordings (the HTML form with its nonce input). **The UI was not
  exercised in a browser.**
- **Second opinion:** the outside-voice agent ran **codex**
  (`codex exec -s read-only`) and a fresh-context Claude reviewer on
  `6377a60..78b5953`. Six findings, folded in below.
- **Code review** (built-in, `high`, `6377a60..78b5953`): ten findings,
  folded in below.
- **Security review** (built-in, scoped to `6377a60..78b5953`): no High or
  Medium finding at the 8/10 confidence bar. The reviewer noted
  the access table's prefix match (`properties/public` also admits
  `publicsecret`), moved unchanged into `access_table.py` and so not
  introduced here.
- **Per-phase checks** against the plan's Changes, New Tests and Failure
  Scenarios: four codebase-analyzer passes (Phases 0-1, 2, 3, 4), read-only.
  Their defects were re-read here before being kept; the ones kept are
  below with the line that motivates them.

## Phase Verification

### Phase 0: today's behaviour, recorded - VERIFIED

**Changes verified:** the wire app's resource hooks
(`tests/integration/test_harness.py:443`), the trust-hook recorder
(`:482-487`), `wire_oauth` with the `/_stub/` provider (`conftest.py:994`),
the normaliser's OAuth secrets and `mcp_<hex>` ids (`_wire.py:549`,
`:595-597`), the exposure-owner rule (`verify_groups.py:123`), rows `WG1` to
`WG19` (`test_wire_grants.py:182-1058`) and their recordings.

**Tests verified:** `test_wire_harness.py::test_the_registry_check`
(exposure row with no owner), `test_an_oauth2_secret_nobody_named_fails_the_guard`,
`test_an_unnamed_oauth2_client_id_fails_the_guard`.

**Deviations from plan:** the provider stand-in is served by `wire_oauth`
itself (declared). Every `exposure` flag is `false` at the end, as the
plan's last phase requires.

### Phase 1: one access decision, and the property tree - ISSUES FOUND

**Changes verified:** `access_table.py` (`access_table_admits`,
`matching_access_row`); `GrantSnapshot` and `snapshot()` with one trust-row
read (`permission_evaluator.py:731`); `path_excluded`/`drop_excluded`/
`holds_excluded` (`:195-243`); a stated rule that does not match denies
(`:715-720`); `access_decision.decide` (`access_decision.py:132-202`); the
property handlers on one base class (`properties.py:339-344`), GET filtered
(`:717`), listing per name (`:785-808`), writes refused when stored or new
value holds an excluded part (`:1149`, `:2061`), root DELETE needs every
name (`:2073`), bulk POST authorised whole before apply (`:1496-1505`);
hooks decide through the request's decision and deny on error
(`hooks.py:442-452`); push/pull filter through one snapshot
(`actor.py:4020-4043`, `handlers/subscription.py:456-460`).

**Tests verified:** `test_property_tree_grants.py` (`test_path_excluded`,
`test_drop_excluded`, `test_drop_excluded_visits_each_node_once`),
`test_access_decision.py` (client never falls to the table `:137`;
`DbError` raises `:185`; one read `:226`), `test_property_grants_flow.py`
(parent read without the excluded child `:94-107`; PUT/DELETE 403
`:115-119`; mixed bulk refused whole `:145-155`).

**Deviations from plan:** declared and matching: `access_table.py` module;
one base class; the depth-3 diff fix smaller than planned; the full-state
fallback filtered where it is built. Not declared: hook calls receive the
`Decision` but never `permission_path` (`properties.py:350-362`); the push
passes no `snapshot=` and reads the row twice (`actor.py:3717`); a bulk POST
decides per name, not through one `evaluate_bulk_property_access`.

**Missing tests:** a caller with no `Auth` object; admin parent DELETE; the
excluded depth-3 DELETE and push assertions in
`test_subscription_grants_flow.py` (push only in `WG7`); hook "not
mentioned follows the table" at the hook layer; a handler test reaching the
hook-denial 403.

Issues 1 and 2 below are Phase 1's.

### Phase 2: every other way in - ISSUES FOUND

**Changes verified:** `/resources` decided per verb (`resources.py:14`,
`:32-41`) with hooks not run on refusal; methods and actions through
`named_route_allows` with the request's verb (`access_decision.py:255-264`),
DELETE included (`methods.py:229`, `async_methods.py:190`); listings empty
when the evaluator cannot be built (`:288-295`); JSON-RPC on bare
`/methods` checked by the body's name (`methods.py:291-301`,
`async_methods.py:254-264`); subscription creation through
`subscription_allowed` (`access_decision.py:360-409`,
`subscription.py:345-359`); unapproved listing 403 (`subscription.py:237-248`;
`grep -n "approved=False" actingweb/handlers/subscription.py`: no hit);
`shared_properties` requires an approved row and drops
`excluded_properties` (`trust.py:1591-1706`).

**Tests verified:** `test_resources_grant.py::test_the_grant_decides`
(`("friend", "DELETE", "x", REFUSED)`), `test_methods_actions_decision.py`
(evaluator unbuildable empties the listing; Emm's `"methods": []` is 403;
JSON-RPC name checked sync and async), `test_subscription_grants_flow.py::test_creation_needs_read_access`.

**Deviations from plan:** declared and matching (`_verb_override`,
`_request_method`, the application-target row, `subscribe` became `read`).
Not declared: an evaluator that cannot be built logs at ERROR on every
request, not once per process (`access_decision.py:109`, `:253`); a refused
whole-target creation is not logged by the library's subscriber
(`actor.py:3488-3491`).

**Missing tests:** `/resources` for a type that does not mention
`resources`, and `"resources": []`; a type with nothing readable gets 403
on a whole-target subscription; a `resources` subscription to `private/x`
is 403; actions DELETE; the shared-properties test uses `StubEvaluator`
whose stub ignores `operation`, so `read` vs `subscribe` is pinned only by
`WG13`.

Issues 3 and 4 below are Phase 2's.

### Phase 3: a client's trust type is the user's choice - ISSUES FOUND

**Changes verified:** the client policy (`permission_integration.py:547-589`;
`admin` only when listed); registration refuses an unoffered type and
`client_credentials` (`oauth2_server.py:141`, `:148`); the nonce on the
form and in the state (`:239`, `:293`), compared at the callback in
constant time (`:516-523`); a hook-changed level goes to the confirmation
(`:518`); the confirm route refuses cross-site and checks its cookie
(`oauth2_endpoints.py:664-685`); the pending record hashed, single use,
expiry checked after the consume, strict read
(`token_manager.py:164-228`); approve re-checks client,
`session_generation`, actor and level (`oauth2_server.py:1123-1134`);
`client_credentials` refused for anonymous clients (`:733-737`); no-framing
and no-store headers (`oauth2_endpoints.py:589-595`); re-type with override
removal failing closed (`trust_manager.py:457-482`, `:626-632`).

**Tests verified:** `test_oauth2_trust_type_list.py::test_without_a_list_every_registered_type_but_admin`
(`assert not client_trust_type_acceptable(config, "admin")`);
`test_oauth2_trust_binding.py::test_another_browsers_nonce_asks_for_confirmation`,
`::test_a_replayed_state_asks_for_confirmation`,
`::test_the_confirmation_refuses` (cross-site 403, no cookie 400, reused
400, store fault 503), `::test_approve_grants_only_the_level_shown`,
`::test_a_retyped_row_loses_its_override`.

**Deviations from plan:** declared and matching (the server method
`complete_client_authorization`; "shown before granted" for the hook; the
SPA callback signs in without a trust). Not declared: `requested_trust_type`
is set but never stored (`oauth2_server.py:160`; `client_registry.py:106-117`
copies fixed fields); an `admin` request is logged at WARNING without
naming the configuration call (`oauth2_server.py:275`; plan: ERROR naming
it); the plan's "one warning per process for a custom template without the
hidden input" has neither code nor test; a sign-in slower than ten minutes
ends in "Invalid or expired state" (`state_manager.py:38`), not the
confirmation the plan describes.

**Missing tests:** the 61-minute expiry; a client disabled or its
`session_generation` changed before confirm; "the next `tools/list`
reflects the re-type"; the `__Host-` cookie name over https; an isolated
registration with `admin` (WG14 sends `admin` with `client_credentials`);
Flask cookie handling (declared); the SPA "listed type passes" test
swallows every exception (`tests/test_spa_trust_type.py:36-39`).

Issues 5, 6 and 10 below are Phase 3's.

### Phase 4: the trust lifecycle, and the grant-delete callback - ISSUES FOUND

**Changes verified:** conditional delete on both backends
(`db/dynamodb/trust.py:502-510`, `db/postgresql/trust.py:696-707`,
`db/protocols.py:839`); `Trust.delete(only_if_secret=)` compares before
the client disable (`trust.py:171`, `:212`, `:265`);
`delete_reciprocal_trust(expected_secret=)` checks before the remote
DELETE and before the cascade, raising `TrustReplaced`
(`actor.py:3070-3073`, `:3135-3138`, `:3278-3279`); the handler 404 on a
lost race and the pre-hook secret check (`handlers/trust.py:1268-1313`);
the grant DELETE reads first, 404 on none, notifies the default
(`:1533-1543`); the PUT stores silently, restores in `finally`, notifies
after the trust write (`:1036-1093`); `fire_approved`/`fire_deleted`
(`trust_manager.py:210-254`); async create drops its row on any exception
(`actor.py:2509-2517`); the demo registers `trust_fully_approved_local`;
the invariants reference, `fanout.py` and the docs listed below.

**Tests verified:** `test_grant_delete_callback.py::test_a_deleted_grant_sends_the_default_once_then_404`
(`len(sender.sent) == 1`, then 404),
`test_trust_conditional_delete.py::test_a_row_replaced_before_the_cascade_keeps_everything`
and `::test_a_row_replaced_inside_the_window_keeps_its_row` (both sides of
the second check), `::test_the_creator_loses_to_a_re_pair_with_a_404`,
`test_trust_hooks_once.py::test_each_approving_route_fires_the_canonical_hook_once`
(rest, api, api_async; repeat fires nothing),
`::test_with_both_registered_only_the_canonical_one_fires`,
`::test_a_hook_without_kwargs_is_named_once`,
`test_trust_handler_permissions.py::TestThePutOrder`,
`test_trust_notify_url.py`.

**Deviations from plan:** declared and matching (`TrustReplaced` instead of
"skip"; `modify_and_notify` fires nothing; public `fire_*` names). Not
declared: the notify URL is the `baseuri` argument or the row read before
the write, not a re-read after it (`actor.py:2055`); the `trust_approved`
deprecation is logged at the first fire, not at registration
(`trust_manager.py:224-229`; the docs follow the code); `sync_peer` still
fires `trust_deleted` itself (`subscription_manager.py:1662-1668`,
`:2765-2771`), not through `fire_deleted`.

**Missing tests:** `create_or_update_oauth_trust` sends nothing (planned in
`test_grant_delete_callback.py`); `tests/integration/test_trust_lifecycle.py`
was named by the plan and not changed (coverage came through `WG19` and
`test_trust_hooks_once.py` instead); the replaced-row test does not assert
the OAuth2 client survives; hooks on `delete_relationship_async`, the
client sweep and `sync_peer`; the restore-itself-faults branch of the PUT;
the demo test drives `fire_approved` on a mock, not a web-UI approval.

**Docs missing** from `docs/guides/trust-relationships.rst`: "the owner's
base-URI change is unchecked by design", "the DELETE's 404 on a lost race",
"a bearer on an unknown id is 403", "a deleted grant notifies the peer" (the
CHANGELOG and migration guide carry them). `docs/sdk/handler-architecture.rst:142-143`
says the trust hooks are "fired through `TrustManager`", which is not true
for `trust_fully_approved_remote` (`handlers/trust.py:826`) or `sync_peer`.
The `auto_delete_on_revocation` limit sits under the trust-delete entry
(`CHANGELOG.rst:791-796`), not under the revocation entry the plan named.

Issues 7, 8, 9 and 11 below are Phase 4's.

### Security properties the plan claims, and the test that pins each

| Property | Pinned by |
| --- | --- |
| An exclusion covers its node and descendants on REST reads | `test_property_grants_flow.py:94-107` (parent read without the child) |
| A stated rule that does not match denies; only an unmentioned category falls to the table, never for a client | `test_access_decision.py:95-97` (`d.reason == "not_granted"`), `:137` |
| A bulk POST is refused whole | `test_property_grants_flow.py:145-155` |
| Pull of a now-excluded list delivers nothing | `test_subscription_grants_flow.py::test_an_old_subscription_to_a_now_excluded_list_delivers_nothing` |
| No `admin` for a client without a list | `test_oauth2_trust_type_list.py:47` |
| A form the client posted waits for the user | `test_oauth2_trust_binding.py::test_a_form_the_client_posted_waits_for_the_user` (`user_rows() == []` before Approve) |
| A delete removes only the row it was authorised against | `test_trust_conditional_delete.py::test_the_creator_loses_to_a_re_pair_with_a_404` |
| A deleted grant tells the peer | `test_grant_delete_callback.py:66-79` |

**Not demonstrated, and contradicted:** "a peer reads a value without its
excluded parts at any depth (... the developer views)" and "pushed and
pulled diffs" (CHANGELOG `:11-25`): Issues 1 and 2 are counterexamples.

## Remaining Tasks

- [ ] Fix Issues 1 and 2 (High) before the PR, with tests on a store that
      returns JSON text.
- [ ] Decide Issues 3 to 9 (fix, or accept and document); see each.
- [ ] Add the missing tests listed per phase, or record them as accepted.
- [ ] The four `trust-relationships.rst` doc items and the
      `handler-architecture.rst` wording.
- [ ] Browser walk of the authorize form and the confirmation page needs a
      way to reach them without a real provider (a stub-provider QA mode
      for the demo); until then they are verified over HTTP only.
- [ ] `thoughts/todo/callback-concurrency-test-sequential-postgresql.md`
      (filed; not this plan's).

## Issues Found

### 1. The developer views leak and overwrite excluded parts
**Severity:** High
**Description:** `AuthenticatedPropertyStore` filters with `drop_excluded`
and refuses writes with `holds_excluded`, both of which act on objects
only. The store hands back the database's JSON text on a fresh read
(`property.py:357-365` `self.__dict__["_db"].get(...)`;
`db/dynamodb/property.py:157` `return str(self.handle.value)`;
PostgreSQL `db/postgresql/property.py:125`). So a peer or client reading
through `as_peer`/`as_client` gets excluded parts, and its write replaces
a stored value holding them. REST parses first (`properties.py:685`
`jsonblob = json.loads(lookup)`) and refuses. Found by the outside voice,
the code review and the Phase 1 check independently; re-read here.
**Location:** `actingweb/interface/authenticated_views.py:205`
`return self._readable(key, self._store[key])`; `:218`
`values = [v for v in (self._store.get(key, None), value) if isinstance(v, dict)]`
**Scenario:** grant allows `settings`, excludes `settings/private`; the
owner stored `{"theme":"x","private":"s"}`; a later request's
`actor.as_client(...).properties["settings"]` returns the whole text, and
`... ["settings"] = {"theme":"y"}` is accepted and drops `private`.
`tests/test_grant_edges.py:110` uses a store of dicts, so it passes.
**Recommendation:** parse the stored value (`_parsed`, as REST does) in
`_readable`, `to_dict` and `_refuse_excluded_parts`; add view tests over a
store that returns JSON text.

### 2. A diff whose value is JSON text skips the exclusion filter
**Severity:** High
**Description:** the push/pull filter parses the diff blob, but a
property's value inside it can itself be JSON text (a form-posted value,
`properties.py:1372-1400` `pair[name] = val`; an SDK set of a JSON string).
`_diff_part` passes it to `drop_excluded`, which returns non-objects
unchanged, and the subtarget branch returns the text as it is. A direct
GET parses the stored text and filters it.
**Location:** `actingweb/actor.py:3967` `kept = drop_excluded(rules, path, value)`;
`:4039-4040` `if not isinstance(parsed, dict): return as_text`
**Scenario:** the owner form-posts `settings={"theme":"x","private":"s"}`;
F (excluded from `settings/private`) with a whole-target or `settings`
subscription is pushed and pulls `private`.
**Recommendation:** parse a string value that is a JSON object before
filtering, as `_filter_full_state` does (`actor.py:4141-4147`); add a test
with a form-posted object.

### 3. Subscriptions to other targets are never re-checked at delivery
**Severity:** Medium
**Description:** creation is decided by the grant (Phase 2), but a
`resources`, `methods` or application subscription is delivered as stored
after the grant narrows. The plan documents that the content of other
targets is the application's to filter; it does not say the path is not
re-checked.
**Location:** `actingweb/actor.py:4018` `if sub.get("target") != "properties": return as_text`
**Scenario:** F subscribes to `resources/x` while allowed; the owner
excludes `x`; every later diff is still pushed and served, while
`GET /resources/x` is 403.
**Recommendation:** re-run `subscription_allowed` on the subscription's
path at push and pull (no content filtering needed), or document the limit.

### 4. A bare collection route skips a stated rule
**Severity:** Medium
**Description:** with an empty path, `decide` goes to the access table even
when the grant mentions the category, so bare `POST /<A>/methods` (no
JSON-RPC), JSON-RPC with `"method": ""`, bare `/actions` and `/resources`
are decided by the table, and a `*` hook runs with an empty name.
**Location:** `actingweb/access_decision.py:169` `if snapshot.mentions(kind) and path:`
**Scenario:** Emm's subscriber shape (`"methods": []`, row
`("subscriber","methods","POST","a")`) sends `POST /<A>/methods` with
`{"x":1}`: admitted, every `*` method hook runs with `method_name == ""`.
**Recommendation:** for a mentioned category and an empty path, refuse a
call (there is no name to grant) and admit only a listing when the rule
reads something; test both.

### 5. The confirmation page shows a spoofable host
**Severity:** Medium
**Description:** the host shown as the place the code goes is `netloc`,
which includes userinfo; registered redirect URIs are not checked for it.
**Location:** `actingweb/oauth2_server/oauth2_server.py:1042`
`"redirect_host": urlparse(str(record.get("redirect_uri") or "")).netloc`
**Scenario:** an anonymous client registers
`https://claude.ai@evil.test/cb`; the page reads "access at
claude.ai@evil.test" and the code goes to `evil.test`.
**Recommendation:** show `hostname` (and port), and refuse redirect URIs
with userinfo at registration.

### 6. A code can be issued with no trust row
**Severity:** Medium
**Description:** when the client's row is deleted between the read and the
modify, `create_or_update_oauth_trust` logs and returns True, so `_complete`
issues a code; the plan says a code only when the trust was written.
**Location:** `actingweb/interface/trust_manager.py:649-651`
`logger.warning(f"OAuth trust for {peer_id} was deleted while being updated")`
**Recommendation:** return False there (and on the `db.get` miss), with a
test.

### 7. `trust_deleted` can fire for a row that survives
**Severity:** Medium
**Description:** the handler checks the secret, fires the hook, then calls
the delete, which can still lose to a re-pair and answer 404. The
application's cleanup has run for the surviving row. This window is before
the documented one (second check to row delete) and is not documented.
**Location:** `actingweb/handlers/trust.py:1284` `actor_interface.trust.fire_deleted(relationships[0], initiated_by_peer=is_peer)`
then `:1307` `except TrustReplaced:`
**Recommendation:** document it in the invariants reference with the
accepted window, or fire the hook inside `delete_reciprocal_trust` after its
last check.

### 8. The PUT's restore uses a cached snapshot
**Severity:** Medium
**Description:** the previous override is read through the cache; a stale
entry (another process changed it) makes a failed modify write a stale
grant back, or delete a live one.
**Location:** `actingweb/handlers/trust.py:1036`
`previous_override = permission_store.get_permissions(actor_id, peerid)`
**Recommendation:** `get_permissions_uncached`, as the DELETE uses.

### 9. Custom `DbTrust` backends break without a Breaking lead
**Severity:** Medium
**Description:** `DbTrust.delete(only_if_secret=)` and
`modify(relationship=)` are new protocol keywords the library now always
passes on the trust DELETE and the client re-type; a backend without them
raises `TypeError`. The CHANGELOG mentions `only_if_secret` inside a
SECURITY entry only; the project's rule asks for a **Breaking:** lead under
CHANGED for an API change, and the migration guide's "Custom database
backends" section does not list them.
**Location:** `actingweb/trust.py:265` `self.handle.delete(only_if_secret=...)`;
`actingweb/db/protocols.py:839`
**Recommendation:** a Breaking entry and a line in the backends section.

### 10. Smaller Phase 3 defects
**Severity:** Low
- The client description is renamed only on a re-type now
  (`trust_manager.py:630-638` moved under `if retyped:`): a client
  re-authorised at the same level keeps "OAuth2 client: <email>".
- A re-type modifies the row before removing the override
  (`trust_manager.py:640-648`); if the removal fails, the old override
  (whose `trust_type` wins, `permission_evaluator.py:836-837`) still
  decides for existing tokens.
- The confirm cookie is cleared before the store is read
  (`oauth2_endpoints.py:688`): a 503 leaves the retry a 400.
- Unverified: the confirmation page sends `Referrer-Policy: no-referrer`
  (`:595`); a browser without `Sec-Fetch-Site` may send `Origin: null` on
  Approve, which `cross_site.py:70` refuses (fails closed).
- `_decided_type` (`oauth2_server.py:1027`) does not re-check acceptability
  for a caller passing its own `decide_trust` to the public methods.

### 11. Smaller Phase 4 and Phase 1-2 defects
**Severity:** Low
- `Trust.delete(only_if_secret=)` on an absent row returns True before the
  permission and cache cleanup the unconditional path runs (`trust.py:176`).
- `sync_peer` fires `trust_deleted` with `{}` and `"friend"` when the row is
  already gone (`subscription_manager.py:1645-1668`), against
  `hooks-reference.rst:440`.
- A list diff object is walked by `drop_excluded` (`actor.py:4112`): a
  wildcard exclusion matching `<list>/items` or `<list>/operation` would
  strip a key of the diff itself. Not reproduced.
- `shared_properties` refuses `approved=None` (`handlers/trust.py:1591`)
  while `GrantSnapshot` treats it as approved.
- `PUT /properties/<list>?index=` answers 404 for a missing list before
  the permission check (`properties.py:973-976`), an existence probe; the
  bulk pre-pass's 400 likewise (`:1486-1492`).
- `POST /properties` with a non-object JSON body is a 500 (`_post_entries`
  returns `None`, `properties.py:1456-1457`, then `:1517`).
- The form-arguments branch and an early 400/413/403 in the JSON apply
  register no diffs for keys already written (`properties.py:1384-1400`,
  `:1425-1426`).
- Hygiene: the per-item validation in `_apply_post_params` duplicates
  `_items_problem` (`properties.py:1511`); `_peer_of` exists in four places
  (`properties.py:184`, `access_decision.py`, resources, methods/actions);
  `auth_obj` is unannotated on the new methods (`properties.py:339`), and
  the contract requires type hints; the FastAPI OpenAPI text still says
  "shared and excluded properties" (`fastapi_integration.py:1134`); the
  `_apply_cookies` docstring says `SameSite=Strict` while the code sets
  None/Lax (`fastapi_integration.py:97-111`).

## Overall Assessment

The plan is implemented phase by phase as written, with its deviations
declared, and the branch is green on both backends (DynamoDB 6411 passed,
PostgreSQL 6208 passed in parallel; the one sequential PostgreSQL failure
predates the branch) with Emm's suite at its `master` baseline. The REST
routes, the OAuth2/MCP level binding and the trust lifecycle hold the
properties the plan claims, each pinned by a named test, and no security
reviewer found a way for a client to get a level the user did not choose.

It is not ready for its PR. Two of the plan's central claims fail off the
REST path: the developer views (`as_peer`/`as_client`, which MCP tools use)
read and overwrite excluded parts because the store returns JSON text
(Issue 1), and a diff carrying an object as text reaches subscribers
unfiltered (Issue 2). Both need fixes with tests over real stored text.
Issues 3 to 9 each need a decision (fix or documented acceptance), and the
UI pages were checked over HTTP only, never in a browser. Run
`/iterate_plan` against this document.
