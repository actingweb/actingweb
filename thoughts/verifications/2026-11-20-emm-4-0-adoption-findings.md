# Verification: What 4.0.0rc1 takes from its first consumer's read

**Date:** 2026-11-20
**Plan:** thoughts/plans/2026-11-19-emm-4-0-adoption-findings.md
**Research:** thoughts/research/2026-11-19-emm-4-0-adoption-findings.md
**Branch:** fix/4.0.0rc1-adoption-findings
**Commit:** 725ee3a

First verification of this plan; there is no previous one. The plan has no
feature document, so there are no success measures to check.

## Automated Check Results

- **Browser QA:** ran (gstack browse, headless Chromium) against the demo
  twice: factory closed (fake OAuth client, `:5055`) and open (QA basic auth,
  `:5056`). No console errors or warnings on any page. `POST /` with JSON on
  the closed factory answered 403 naming `with_open_factory(True)`, and a
  form `POST /` redirected to the provider with `login_hint` (sign-in, not
  creation). The demo ships its own `aw-root-factory.html`, so the library's
  template change was not rendered there. I checked it separately with
  Flask's test client: the default `/login` with a provider and the factory
  closed has **no form and no provider button** (issue 1). Two
  pre-existing findings, not from this plan: an open factory accepts a
  creator that is not an address through a form POST, and a JSON `POST /`
  with an empty or missing creator creates an actor whose creator is
  `creator` (both outside the plan; see Notes). Screenshots:
  `/private/tmp/claude-501/-Users-wedel-src-actingweb-actingweb/a49e9e4a-ca50-4d67-9e4d-ef94c478b2ae/scratchpad/qa-factory/`.
  All QA actors and `qa_verify_*` tables were removed.
- **Second opinion:** outside-voice agent, with codex (gpt-5.6-sol,
  read-only) and a fresh-context Claude read of `ee068fb..725ee3a`. Findings
  are folded into Issues Found.
- **Built-in code review** (high, branch target): 9 findings. 5 confirmed
  (issues 1, 3, 4, 5, 6). The changelog-in-rc1-section finding is rejected:
  `v4.0.0rc1` is not tagged and the plan rewrites that section on purpose.
  The `client_credentials`-in-discovery finding is rejected: AC-36 by design.
  The other two are Lows (issues 12 and 16).
- **Built-in security review:** no finding rated 7 or higher. Pre-existing
  note: `complete_client_authorization` accepts a `plain` challenge method
  (issue 9).
- `poetry run ruff check actingweb tests`: pass.
- `poetry run ruff format --check actingweb tests`: pass (627 files).
- `poetry run pyright actingweb tests`: 0 errors, 0 warnings.
- `poetry run python tests/integration/verify_groups.py`: pass.
- `make test-all-parallel` (DynamoDB): **8367 passed**, 215 skipped,
  2 xfailed, in 5:21 (parallel run, no failures to re-run).
- `make test-all-parallel` (PostgreSQL): **8140 passed**, 442 skipped,
  2 xfailed, in 3:32 (parallel run, no failures).
- `sphinx-build -W ...`: pass.
- Benchmarks (`-m benchmark`, alone; the plan touched list storage):
  26 passed.

## Phase Verification

### Phase 1: Commands, small defects, MCP and OAuth - VERIFIED (test gaps)

**Changes verified:** the operator-command preflight
(`actingweb/maintenance/_common.py`), the `report` name source, marking
`--ids-file`/`--show-addresses` and the system skip, the PostgreSQL backfill
counts and collision output, the logout 503 code, `require_auth_for_initialize`,
`resources/templates/list`, `/.well-known/openid-configuration` on both
integrations, keep-first client names, the Flask SPA session route,
`client_credentials` out of discovery, PKCE at authorise, callback,
`_complete`, `complete_client_authorization`, the token request and the
exchange (`oauth2_server.py:1153`, `:1287`, `:707`; `token_manager.py:308`),
and `with_mcp()` keeping earlier options. All match the plan.

**Tests verified:** every test named for AC-1 to AC-10, AC-12 and AC-30 to
AC-38, AC-49, AC-51 to AC-54 exists and passed. The weak ones are listed
under Acceptance Criteria.

**Deviations from plan:** the PKCE client-evidence gate was dropped (owner,
recorded in the plan). Acceptable.

### Phase 2: Start-up, API and storage - ISSUES FOUND

**Changes verified:** the empty-store self-enable (`unique_creators.py:1195`
`enable_empty_store`), the retry `_probe` and `_store_answered`
(`interface/app.py:86-97`), `actingweb-check-ready`, the factory default as a
read-time property, `is_vouched()`, `DbErrorAfterWrite`, list-all raising,
the 2 MiB ceiling, the `need`/`format` rule, and the newer-format 409 on every
handler path. All match the plan, but issues 1 and 3 to 6 are defects in this
phase's code.

**Tests verified:** every named test exists and passed. Red-before-green was
not kept for the storage group, the start-up integration tests or
`check-ready`; the plan records which.

**Deviations from plan:** the list-level `format` is refused by `delete()`
and `clear()` too (plan decision). On 2026-11-20 the owner confirmed it:
**keep the refusal**. Deleting an actor and revoking a trust remove rows
directly and are not affected; a peer's list clear/delete callback and a
resync on such a replica list are refused until the process is upgraded.

### Phase 3: Guide and bookkeeping - VERIFIED

**Changes verified:** the migration guide items, the deployment page
arithmetic, the changelog note, and the todos. Every new todo named in
Phase 3 exists with an `INDEX.md` row, `flask-spa-session-route.md` is
deleted, the key-prefix decision is in `prop-list-key-prefix-scheme.md`, and
`thoughts/inbound/` holds only `README.md` (checked by script: every todo
has a row, and every row's file exists).

**Consumer message** (plan, Phase 1 notes, still accurate after
implementation):

> (1) its lifecycle hook writes `email = creator` for an actor whose creator
> is not an address (the default creator `creator`), so two such actors
> collide in the email backfill and block the start; stop indexing a
> non-address, close the factory, and remove the duplicate before upgrading.
> (2) Before it removes `with_mcp(require_pkce=False)`, check each registered
> client name: all registrations public with a sign-in since, or one
> recorded authorise request with a `code_challenge`.

Issue 1 should go out with it if the consumer serves the library's default
`aw-root-factory.html` on Flask.

## Acceptance Criteria

Every test the Traceability table names exists and passed in both Full-tier
runs. "Partly" means the main behaviour is pinned and a clause is not (see
Issues 13 and 14).

| AC | Test | Asserts the behaviour? | Result |
| --- | --- | --- | --- |
| AC-1 | `tests/test_property_lookup_command.py:197`, `:217`, `:234` - `assert f"backfill --apply --properties {other}" in out` | Yes | Pass |
| AC-2 | `tests/test_mark_actors_vouched.py:197` - `assert seen == ["u1"]` / `assert counts["system"] == 1` | Yes | Pass |
| AC-3 | `:219`, `:229` - `assert creator not in out` / `assert "email=" in line` | Partly (stored email value not pinned) | Pass |
| AC-4 | `:246`, `:256`, `:283` - `assert counts["missing"] == 1` / `assert exc.value.code == 2` | Partly (`missing` not asserted through `--ids-file` in `main`) | Pass |
| AC-5 | `tests/integration/test_email_as_creator_sweep.py:280`; `tests/test_unique_creators_command.py:48` - `assert counts["unvouched"] == 1` | Yes (summary asserted through `caplog`) | Pass |
| AC-6 | `tests/test_oauth2_logout_mcp_tokens.py:64`, `:189`, `:202` - `assert out["code"] == "temporarily_unavailable"` | Yes | Pass |
| AC-7 | `tests/test_db_fault_callers.py:371`, `:379` - `pytest.raises(DbError)` through `seam_fault` | Yes | Pass |
| AC-8 | `:393` - `pytest.raises(DbError)` | Yes | Pass |
| AC-9 | `tests/test_operator_command_store.py:118` - `assert f"backend={backend}" in banner` | Yes (one mode per script) | Pass |
| AC-10 | `:154`, `:169`, `:182`, `:192` - `assert _run(script, argv) == 2` / `assert not first_read` | Yes | Pass |
| AC-11 | `tests/test_check_ready_command.py` (8); `tests/integration/test_check_ready_command.py:21` | Partly: `:131` patches every probe, so `create_table.assert_not_called()` cannot fail; writes nothing rests on the manual run of 2026-11-19. Issues 4 and 5 are behaviours no test catches. | Pass |
| AC-12 | `tests/test_adoption_log_line.py:58`, `:105` - `assert "@" not in message` | Yes | Pass |
| AC-13 | `tests/integration/test_unique_creator_empty_store.py:36` - `assert unique_creators.missing_enforcement(fresh_store) is None` | Yes | Pass |
| AC-14 | `:46`, `:55`, `:70`; `tests/test_unique_creator_default.py:148` | Partly (no timeout case) | Pass |
| AC-15 | `tests/test_unique_creator_default.py:98` - `enable.assert_not_called()` | Yes | Pass |
| AC-16 | `tests/test_startup_check_retry.py:61`, `:69`, `:75` - `assert probe.call_count == 3` | Partly (uniqueness check only) | Pass |
| AC-17 | `:88`, `:104`, `:112`, `:125` - `assert faulted.value.unavailable is True` | Partly (no DynamoDB permission-denied case) | Pass |
| AC-18 | `tests/test_factory_open_switch.py:183` class - `assert webobj.response.status_code == 403` | Yes | Pass |
| AC-19 | `:234`, `:237`, `:108` - `assert webobj.response.status_code == 201` | Partly (explicit open plus a provider asserts the flag only) | Pass |
| AC-20 | `tests/test_is_vouched_public.py:43`, `:54`, `:65`, `:72` - `assert _iface(config, actor).is_vouched() is expected` | Yes | Pass |
| AC-21 | `tests/test_list_prefix_with_rows.py:247` (and `:259` for attributes) - `pytest.raises(DbError)` | Yes | Pass |
| AC-22 | `tests/test_db_error_after_write.py:36`, `:46`, `:57`, `:69`, `:79`, `:107` - `assert resp.headers["X-ActingWeb-Error"] == "stored_not_notified"` | Yes | Pass |
| ~~AC-23~~, ~~AC-24~~ | struck: the bounded read is cut (`bounded-list-read.md`); nothing in code or docs claims it | n/a | n/a |
| AC-25 | `tests/test_property_list_span_codec.py:222` `TestNeed`; `tests/test_property_list_newer_format.py:89`, `:199`; `tests/test_list_newer_format_http.py:33` - `assert not isinstance(raised.value, ListCorruptionError)` | Partly ("do not repair" in the remedy not asserted) | Pass |
| AC-26 | `tests/test_property_list_newer_format.py:98`, `:114` - `assert _snapshot(store) == before` | Yes | Pass |
| AC-27 | `:124`; `tests/test_verify_property_lists.py:44` - `assert "NEWER FORMAT" in capsys.readouterr().out` | Yes (repair is pinned by the second, unnamed test) | Pass |
| AC-28 | `:156`, `:137`, `:147` - `assert store[future] == "later-version-row"` | Yes | Pass |
| AC-29 | `tests/test_list_item_limits.py:92` - `assert config.list_item_max_bytes == ITEM_MAX_BYTES_DEFAULT == 2 * 2**20` | Partly (the default value; no refusal under the default) | Pass |
| AC-30 | `tests/test_mcp_auth_challenge.py:224`, `:233`, `:244` - `assert handler.response.status_code == 401` | Yes | Pass |
| AC-31 | `:254` - `assert handler.response.status_code == 200` | Yes | Pass |
| AC-32 | `tests/test_flask_well_known.py:18`; `tests/integration/test_oauth2_flows.py:753` - `assert _json(openid) == _json(server)` | Yes | Pass |
| AC-33 | `tests/test_mcp_resource_templates.py:98`, `:108`, `:117`, `:126` - `assert [t["uriTemplate"] for t in templates] == ["notes://{id}"]` | Partly (`:119` is `all()` over a list that may be empty) | Pass |
| AC-34 | `tests/test_mcp_client_info_cache.py:359`, `:366`, `:373`, `:382` - `assert _written_names(actor) == ["claude-ai"]` | Partly: `:382` cannot fail (issue 13) | Pass |
| AC-35 | `tests/test_spa_session_retrieve.py:58` (`env` over both integrations) | Yes | Pass |
| AC-36 | `tests/test_oauth2_public_clients.py:218`, `:224` - `assert "client_credentials" not in doc["grant_types_supported"]` | Yes | Pass |
| AC-37 | `tests/test_oauth2_pkce_binding.py:367` - `assert resp["error"] == "invalid_request"` | Partly (the description is not asserted, and `invalid_request` also answers a bad redirect) | Pass |
| AC-38 | `:374`, `:385`, `:401` - `assert tm.exchange_authorization_code(code, cid, code_verifier=VERIFIER)` | Yes | Pass |
| AC-39 | docs `-W` build; manual read and sweep greps (2026-11-19) | n/a | Pass |
| AC-40, AC-41 | manual: `scripts/live_pair.py same-store` (2026-11-19, plan Phase 1 notes) | n/a | Pass (not re-run) |
| AC-42 | manual: inbound and todo checked against `INDEX.md` by script, re-run here | n/a | Pass |
| AC-43 | `tests/test_property_list_newer_format.py:173`; `tests/test_migrate_property_lists.py:33` - `pytest.raises(ListItemNewerFormatError)` for each operation | Yes ("lazy migration" has no distinct case) | Pass |
| AC-44 | `tests/test_attribute_list_store.py:105` - `pytest.raises(DbError)` | Yes | Pass |
| AC-45 | `tests/test_verify_property_lists.py:65` - `assert "list=gone: 2 side-partition row(s)" in out` | Partly (runs in a mode with no remover) | Pass |
| AC-46 | `tests/test_actor_peer_creation.py:26`, `:42` - `assert lines[0].levelno == logging.WARNING` | Yes | Pass |
| AC-47 | `tests/test_factory_open_switch.py:269` - `assert ('name="creator"' in page.text) is not closed` | Yes, but the AC itself is wrong for a configured provider (issue 1) | Pass |
| AC-48 | `tests/test_unique_creator_default.py:117` - `enable.assert_not_called()` | Yes (unset prefix only; empty prefix uses the same branch) | Pass |
| AC-49 | `tests/test_oauth2_pkce_binding.py:413`, `:419`, `:438` | Partly (`:436` accepts `invalid_grant` too) | Pass |
| AC-50 | `tests/integration/test_unique_creator_empty_store.py:89` - `assert record.actor_id == late["id"]` | Yes (the fault path is issue 3) | Pass |
| AC-51 | `tests/test_actingweb_app.py:538` - `assert config.mcp_require_pkce is False` | Yes | Pass |
| AC-52 | `tests/test_oauth2_pkce_binding.py:447`, `:467` - `assert "aw-oauth-authorization-form.html" in warning` | Yes | Pass |
| AC-53 | `tests/test_property_lookup_command.py:302` - `assert "matches=2 " in summary` | Partly (only live actors seeded) | Pass |
| AC-54 | `:282` - `assert f"mark-complete --force --properties {name}" in out` | Partly (unmarked is asserted at `:385`, another test) | Pass |

Security properties claimed by the plan, demonstrated:
- PKCE from every client: `tests/test_oauth2_pkce_binding.py:367`
  (`assert resp["error"] == "invalid_request"` for a confidential client
  without a challenge), `:413` (callback), `:419` (exchange), `:438`
  (`create_authorization_code` without a challenge then exchange `is None`).
- ACTOR_ADOPTED carries no address: `tests/test_adoption_log_line.py:105`
  `assert "@" not in message`.
- Closed factory: `tests/test_factory_open_switch.py:199`
  `assert webobj.response.status_code == 403`, and live (403 on `:5055`).

## Remaining Tasks

Per the owner's rule, a plan's verification findings are fixed in the
plan, so these go to `/iterate_plan`, not to todos.

- [ ] Issue 1 (High): the default root page with a provider configured.
- [ ] Issue 17 (High): trust-type registration before integrating on a
  fresh DynamoDB store.
- [ ] Issue 18 (Medium): the marking's dry-run default.
- [ ] Issues 2 to 6 (Medium).
- [ ] Issues 7 to 16 (Low): fix or accept each one.
- [ ] Traceability table: add class names to node ids and fix the stale
  line references (AC-6 `:75/:186/:195` → `:64/:189/:202`, AC-29 `:755`,
  AC-37 `:310` → `:328`). Name `tests/test_verify_property_lists.py:44`
  for AC-27 and `test_attribute_list_all_with_rows_raises_on_a_fault` for
  AC-21.

## Issues Found

### 1. The default sign-in page offers no way to sign in when a provider is configured
**Severity:** High
**Description:** AC-47 hides the email form whenever the factory is closed.
But with a provider configured, that form is a sign-in form: a form
`POST /` goes to `_handle_factory_post_with_oauth_redirect` and redirects to
the provider with `login_hint` (seen live on `:5055`: 302 to
`accounts.google.com/...&login_hint=qa%40example.test`). It never reaches the
factory. Closed is the default once a provider is configured, so on Flask
the library's default `/` and `/login` now render a "Sign in" heading with
no form and no provider button. Flask passes only `factory_open` to the
template, and the provider buttons need `oauth_enabled`/`oauth_providers`.
Checked with Flask's test client: closed → `form=False provider_button=False`,
open → `form=True`. On FastAPI the provider buttons remain, but the
email-hint path is gone.
**Location:** `actingweb/templates/aw-root-factory.html:25` `{% if factory_open is not defined or factory_open %}`;
`actingweb/interface/integrations/flask_integration.py:978-982` (`render_template("aw-root-factory.html", factory_open=...)`).
**Recommendation:** with a provider configured, show the form whatever the
factory state, because it signs in. Hide it only when the factory is closed
and no provider is configured, which can't happen under the default rule,
so in practice: never hide it when OAuth is configured. Also give Flask the
same provider template values as FastAPI (`RootFactoryHandler` values).
Restate AC-47 accordingly, with a test that renders both integrations'
default `/login` with a provider and asserts that a sign-in control is
present.

### 2. One newer-layout list makes the whole default `GET /properties` answer 409
**Severity:** Medium
**Description:** in the default and `short` formats, `len(list_prop)` sits
outside any per-list catch. A list whose meta `format` is newer raises
`ListItemNewerFormatError` there, and the outer handler turns the whole
response into 409. The `full` and `metadata` branches emit a per-list marker
instead, and the `prime_from_rows` comment promises the dump "fails for
this list only". During a rolling deploy of a later 4.x, a 4.0 node would
fail every baseline fetch of that actor.
**Location:** `actingweb/handlers/properties.py:1484-1489` (`"count": len(list_prop),`), caught at `:1490`.
**Recommendation:** catch per list and emit `{"_list": True, **NEWER_FORMAT_MARKER}`,
with a test on the default format.

### 3. The self-enable can leave its complete marker over an unrecorded actor
**Severity:** Medium
**Description:** after `Creator(creator=BACKFILL_KEY).save()`, the second
scan and `record_for_actor_as_read()` (which raises `DbError` on a fault)
are not wrapped. A fault there leaves the marker in place with a late actor
unrecorded. This start is refused with `unavailable=True`; the retried start
sees the marker and passes, and a later sign-in for that creator can create
a second actor. The docstring says "recorded, or the item is removed again".
It needs an older process creating an actor during the enable, which the
plan's decision forbids, plus a fault at that moment.
**Location:** `actingweb/maintenance/unique_creators.py:1247-1256` (`late, _ = scan()`).
**Recommendation:** wrap everything after the save, delete the marker on
any exception before re-raising (log CRITICAL if the delete fails), with a
test that injects a fault into the late scan.

### 4. `check-ready` reads a denied permission as an empty store
**Severity:** Medium
**Description:** `_store_empty` and `_email_marker` count any error
`_store_answered` accepts as "empty" or "no marker". That set includes
`AccessDeniedException`, `UnrecognizedClientException` and
`InsufficientPrivilege`. An operator role without Scan on the actors table
gets "ready at first start" and exit 0 on a populated store; the real start
then refuses.
**Location:** `actingweb/maintenance/check_ready.py:76-77` (`if _store_answered(e):` / `return True`), `:110`; `actingweb/interface/app.py:86-97`.
**Recommendation:** treat only a missing table (`ResourceNotFoundException`,
`UndefinedTable`) as empty, and report a denial as unreadable (exit 2).

### 5. `check-ready`'s lookup gate uses a different "empty" test from the start
**Severity:** Medium
**Description:** the command says "ready at first start" when there are no
user actors (`no_actors`), but the start marks names only when the
properties table is empty (`property_lookup.settle` → `properties_table_empty`).
Orphan property rows with no user actors: the command says green, the start
refuses. User actors with no properties: the command refuses, the start
serves.
**Location:** `actingweb/maintenance/check_ready.py:179` (`if store_empty():`); `actingweb/maintenance/property_lookup.py:164`.
**Recommendation:** use `properties_table_empty(database)` in `lookup()`,
as `cmd_report` does (`property_lookup.py:1094`).

### 6. `ListAttribute.delete()` no longer deletes a list with a damaged meta row
**Severity:** Low
**Description:** `delete()` and `clear()` now call `_read_meta_row()`
first, which raises `ValueError` on unparsable metadata. Before, a damaged
list could always be deleted, as the docstrings still promise. A replica's
`delete_list()` on such a list now raises. Deleting an actor and revoking a
trust are unaffected (they remove rows directly).
**Location:** `actingweb/attribute_list.py:796`, `:808` (`self._read_meta_row()`); `actingweb/list_core.py:3207`.
**Recommendation:** let only `ListItemNewerFormatError` refuse; catch
`ValueError` and continue the sweep and delete.

### 7. The newer-format remedy text points to `delete()`, which refuses a newer layout
**Severity:** Low
**Location:** `actingweb/list_core.py:259` (remedy "do not repair the list (delete() removes it whole)").
**Recommendation:** give the list-`format` case its own remedy (upgrade).

### 8. `clear()` removes newer-format items, which the Spec Delta says only a whole-list delete may
**Severity:** Low
**Description:** `_v2_clear` deletes every head, those with `need`
included (`test_clear_leaves_unrecognised_side_rows` asserts `not heads(store)`),
and their bodies are not cascaded. The Spec Delta says "nothing of it is
removed except by deleting the whole list".
**Location:** `actingweb/list_core.py:3160`.
**Recommendation:** name `clear()` as the second escape in the Spec Delta,
which matches the intent (clear empties the list).

### 9. A `plain` challenge, or no challenge under the opt-out, through `complete_client_authorization`
**Severity:** Low (predates this branch)
**Description:** the application's own sign-in route can pass
`code_challenge_method="plain"`, which is accepted at exchange
(`token_manager.py:1641`). Under `require_pkce=False` it can issue a code
with no challenge to a public client, and any `code_verifier` then redeems
it (`oauth2_server.py:707`, `token_manager.py:308`), which is rc1's
behaviour. Only the application itself can do either; no remote client can.
**Recommendation:** require S256 in `_complete` when a challenge is
present, and apply the public-client rule there under the opt-out.

### 10. Two first starts at once: the second can be refused with a wrong remedy
**Severity:** Low
**Location:** `actingweb/maintenance/unique_creators.py:1243` (`raise EnableRefused("the store holds user actors")`).
**Recommendation:** on `EnableRefused`, re-check `missing_enforcement()`
and accept if it is now None.

### 11. Start-up treats credential errors as temporary
**Severity:** Low
**Description:** `ExpiredTokenException`, `InvalidSignatureException` and a
psycopg authentication failure are not in the "answered" sets, so they are
retried and refused with `unavailable=True`.
**Location:** `actingweb/interface/app.py:86-95`.

### 12. `clear()` can answer `stored_not_notified` when nothing was deleted
**Severity:** Low
**Location:** `actingweb/interface/property_store.py:296` (`with after_write("diff registration in clear", self._actor.id):`).
**Recommendation:** use `after_write` only after a delete has landed.

### 13. AC-34's unauthenticated-seed test cannot fail
**Severity:** Low
**Description:** the seed handler uses session `s-ac34`, but `_update`
builds a fresh handler with no session and passes the client info directly,
so the seed never reaches the assertion.
**Location:** `tests/test_mcp_client_info_cache.py:382-398` (`assert _written_names(actor) == ["claude-ai"]`).
**Recommendation:** drive the authenticated request through the same session.

### 14. Loose or missing assertions on AC clauses
**Severity:** Low
- AC-11: `tests/test_check_ready_command.py:131` patches every probe, so
  "creates no table" cannot fail there.
- AC-49: `tests/test_oauth2_pkce_binding.py:436` accepts `("invalid_request", "invalid_grant")`, with no positive control at the token endpoint.
- AC-37: `:371` does not assert the "code_challenge is required" description.
- AC-33: `tests/test_mcp_resource_templates.py:119` is `all()` over a list
  that may be empty, and `tests/integration/test_mcp_resources.py:239` loops
  over a list that may be empty.
- AC-29: no refusal of an item over 2 MiB under the default ceiling.
- AC-14 (timeout), AC-16 (other checks), AC-17 (DynamoDB denial), AC-19
  (POST with an explicit open and a provider), AC-22 (a list write faulting
  before the write), AC-45 (a mode with a remover), AC-53 (rows of deleted
  actors): each clause has no case.

### 15. A `Config` built directly with OAuth keeps the factory open
**Severity:** Low
**Location:** `actingweb/config.py:129` (`return not self.provider_configured`); only the builders set the flag.
**Recommendation:** fall back to `oauth_providers`/`client_id` when no
builder ran, or document that the default rule applies to the builders.

### 16. New test functions without type hints
**Severity:** Low
**Location:** `tests/test_actingweb_app.py:538`, `:557`; `tests/test_attribute_list_store.py:105`; `tests/integration/test_oauth2_flows.py:753`.
These follow their files' existing style (59 untyped tests in
`test_actingweb_app.py` on `master`), but CLAUDE.md requires hints.

### 17. A fresh DynamoDB store cannot start when the application registers a trust type before integrating
**Severity:** High
**Source:** the consumer's run against this branch (2026-11-20), reproduced
here.
**Description:** `AccessControlConfig.add_trust_type()` calls
`TrustTypeRegistry.register_type()` (`actingweb/permission_integration.py:390`),
which creates the system actor on first use (`trust_type_registry.py:130`
`sys_actor.create(...)`). On a fresh store with creator uniqueness on, the
creators table does not exist yet, so the create is refused
(`actingweb/db/dynamodb/actor.py:48` `_require_creators_backfill`) and
`register_type` raises `DbError("database error during actor create")`. An
application that registers its types at import time (before
`integrate_*()` and so before `check_ready()`) crashes before the
empty-store self-enable runs. Reproduced on DynamoDB Local with a fresh
prefix: `register_type raised DbError database error during actor create`.
`integrate_fastapi()` then succeeded and enabled the store. The plan's
promise (AC-13, the guide's "A fresh store", the `rc-pass` todo's "No
fresh-store step is needed any more") does not hold for this application
shape. `configure_oauth2_trust_types()` does not touch the system actor, so
the demo is unaffected.
**Location:** `actingweb/trust_type_registry.py:113-160` (`_get_system_actor`), `actingweb/db/dynamodb/actor.py:48`.
**Recommendation:** let the system-actor bootstrap run the empty-store
enable itself (or defer registration writes until `check_ready()`), with a
test that registers a type on a fresh prefix before integrating. At
minimum, the guide says to register types after `integrate_*()`.

### 18. `actingweb-mark-actors-vouched` writes by default; every other writing command needs `--apply`
**Severity:** Medium
**Source:** the consumer's run (2026-11-20). Confirmed:
`actingweb/maintenance/mark_actors_vouched.py:348`
`parser.add_argument("--dry-run", action="store_true")` and `:375`
`writing=not args.dry_run`.
**Description:** an operator who runs the marking expecting a dry run, as
with the other commands, writes markers. The consumer marked 105 actors
this way; the outcome was the one they intended next, but on another store
it need not be.
**Recommendation:** 4.0 is the release to align it: `--apply` to write, a
dry run by default, with the guide's checklist and the changelog updated
(the command is new in 4.0, so no released caller depends on the old
form).

### Consumer report, other points
- The exempt-creator collision (two actors with creator `creator` and the
  same indexed email block the backfill) is the behaviour the owner kept on
  2026-11-19 ("Keep it, explain better"): the output names both actors and
  the ways out (AC-54), and consumer message item 1 tells the consumer to
  stop indexing a non-address. Not a new issue.
- Results reported: PostgreSQL suite 7,757 passed with 1 known failure;
  DynamoDB lane with the 3 baseline failures; the factory switch and the
  PKCE opt-out adopted; all four `check-ready` gates ready on the migrated
  database.

### Notes (not this plan)
- The append handler folds a resync fault into 201
  (`actingweb/handlers/properties.py:914`). That was kept on purpose by the
  plan ("keep folding"); now that `stored_not_notified` exists, revisit it.
- Browser QA: an open factory accepts a creator that is not an address
  through a form POST, and a JSON `POST /` with an empty or missing creator
  creates an actor with creator `creator`. Both predate this branch. The
  second is the shape behind the consumer's collision (consumer message
  item 1).
- The unverified items from the second opinion: an item of 2 to 4 MiB
  stored under rc1 gets 413 on rewrite, and the `format` parse treats `2.5`
  as 2. These were not traced; the first is a consequence of the new
  ceiling that the guide states.

## Spec Merge

Not merged: issue 1 is an open High, and its fix changes the actor-creation
spec statement (Factory, AC-47). The next verification merges the Spec
Delta: four new partial specs (`operator-commands`, `startup-readiness`,
`actor-creation`, `property-lists`) and additions to `mcp-server`,
`oauth-client-registration` and `web-ui`, with issue 8's wording.

## Overall Assessment

The plan is implemented as written. The Full tier passes on both backends
with zero lint and type findings, every acceptance criterion has a named,
passing test, and the security properties the plan claims are pinned by
tests that would fail without them. The owner's decision to keep the
newer-layout refusal on `delete()` and `clear()` is recorded.

Two Highs block the PR. The consumer's run of 2026-11-20 found the
second, reproduced here (issue 17): an application that registers a trust
type before integrating cannot start on a fresh DynamoDB store, so the
self-enable's promise does not hold for that shape. The first is below. The closed-by-default factory hides the email form
on the default sign-in page, but with a provider configured that form signs
in rather than creating an actor. On Flask's default template the sign-in
page is left with no way in. AC-47 asserted exactly that behaviour, so the
criterion itself needs restating. Four Mediums should be fixed in the same
iteration: the per-list 409 in the default `GET /properties`, the
self-enable's marker on a fault, and `check-ready`'s two wrong verdicts (a
denied permission read as empty, and the lookup gate's empty test), plus
the marking command's write-by-default (issue 18). They are all small. Then run `/iterate_plan`, then verify again.
