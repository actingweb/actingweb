# Verification: validating the release after 3.15.1 (4.0.0rc1)

**Date:** 2026-11-18
**Plan:** thoughts/plans/2026-11-15-3-16-release-validation.md
**Research:** thoughts/research/2026-11-18-3-16-release-validation.md
**Branch:** release/3.16.0-release-validation
**Commit:** `5c94b0b` (`Pre-release v4.0.0rc1`)

## Automated Check Results

- **Browser QA:** ran, provider: gstack browse (headless Chromium). The
  demo in local QA mode on a fresh DynamoDB Local prefix (first start
  stopped with `UniqueCreatorNotReady`, `enable --apply` reported
  `outcome=backfilled`, the second start served). The pages changed after
  Phase 3's walk: factory, created, trust help, the properties list
  labels, at 375 px too. Console empty on every page. Two Low findings
  (Issues Found, 11 and 12). Throwaway actors deleted (each `/meta` 404),
  the demo stopped, its tables dropped.
- **Second opinion:** outside-voice with codex (`codex review --base
  master`: "No discrete, actionable correctness regressions") and a
  fresh-context claude (7 findings, folded below).
- **Code review** (built-in, high, scoped to `actingweb/`): 10 findings,
  folded below.
- **Security review** (built-in): no finding at confidence 6 or above;
  each changed decision was found to narrow access, not widen it.
- `ruff check actingweb tests`: pass.
- `ruff format --check actingweb tests`: pass.
- `pyright actingweb tests`: 0 errors, 0 warnings.
- `tests/integration/verify_groups.py`: registry consistent; every changed
  recording's `Wire-Phase` trailer matches its owners.
- `make test-all-parallel` (DynamoDB): 8,160 passed, 1 failed, 212
  skipped, 2 xfailed. The failure,
  `tests/test_verification_fetch.py::TestLateAndFull::test_a_full_pool_refuses_at_once`,
  passed three times when run alone (sequential rerun, this session): a
  parallel-load flake, also seen at the Phase 4 checkpoint.
- `make test-all-parallel` (PostgreSQL): 7,933 passed, 440 skipped, 2
  xfailed, 0 failed.
- `sphinx-build -W ...`: build succeeded.
- Earlier on the same version (before the last two docs-only commits):
  the Fast tier under Python 3.11, 6,274 passed; Emm's suite on both
  lanes, the baseline's five failures by name and nothing new.

## Phase Verification

### Phase 1: what the release is, and that it is 4.0.0 - VERIFIED

**Changes verified:**
- `tests/integration/_wire.py` writes the library version as
  `<library-version>`; the bump to `4.0.0rc1` changed no recording (the
  wire suite passed on both backends after it).
- `CONTRIBUTING.rst`, "Which number a release gets", and `CLAUDE.md`
  "Release" state the same rule (major: "when an unchanged application
  upgrades (an opt-in call or an operator's step does not count)").
- `scripts/live_pair.py` and the research note's table: 18 of 18 cells.

**Tests verified:** `tests/test_docs_api_consistency.py:268`
`test_release_notes_name_only_what_exists`, `:292`
`test_release_notes_removed_list_is_current` (they read the newest section
with entries, so they still read the release after the bump).

### Phase 2: the release read from a consumer's side - VERIFIED

**Changes verified:** `tests/integration/test_consumer_sdk_calls.py`
(11 tests), `tests/integration/test_wire_v315.py:64-122` (WV1-WV4), the
helper's hook fallback (`actingweb/oauth2_server/oauth2_server.py:1025`,
`:1051`).

### Phase 3: the demo, actingwebdemo and agent discoverability - VERIFIED

**Changes verified:** `tests/integration/test_demo_first_run.py:65`;
`skills/actingweb-app/SKILL.md` front matter is a folded block
(`tests/test_agent_skill.py:29`); `actingweb/trust_permissions.py:358-387`
(the awaited notification and its budget); the MCP quickstart's fixes
(`actingweb/handlers/mcp.py:916-927`, the default `inputSchema`).

**Deviations:** the MCP quickstart (AC-17) ran after Phase 3's commit with
the owner and landed in Phase 4's checkpoint; recorded in the plan.

### Phase 4: the guide and the changelog, and the bump - VERIFIED (deviations accepted by the owner)

**Changes verified:**
- `actingweb/migration_guide.py:10-16`; no message spells a guide path
  (`tests/test_migration_guide.py`, third test).
- `docs/migration/v4.0.rst`: "Start here" checklist, "What stops a start",
  "The operator commands", "Rolling back to 3.15.1", "Other versions
  beside this one", six audience parts with labels.
- `CHANGELOG.rst`: `v4.0.0rc1` section under an empty `Unreleased`; opening
  note; Breaking entries first in `CHANGED`; 261 entries.
- `pyproject.toml:3` and `actingweb/__init__.py:31` at `4.0.0rc1`.
- Todos: `emm-suite-against-master.md` deleted with its `INDEX.md` row;
  `rc-pass-against-real-consumers.md` and `flask-spa-session-route.md` each
  have a file and a row; the discoverability todo keeps Context7 only.

**Deviations from plan (owner, 2026-11-18: accepted):** AC-3 checked
row by row instead of refilling the inventory's column; four Python
samples checked against the library's signatures instead of run; the
changelog not re-sorted by audience. Also: the branch history was
rewritten twice (the wire appendix, then one `SECURITY` row's 3.15.1
citation) before any push.

## Acceptance Criteria

| AC | Test | Asserts the behaviour? | Result |
| --- | --- | --- | --- |
| AC-1 | manual: the inventory (301 rows) | n/a | Pass |
| AC-2 | `tests/test_docs_api_consistency.py:268`, `:292` | Yes: every code name the notes use exists or is on the removed list, and the list is current | Pass |
| AC-3 | manual: 137 must-act rows against the guide; 28 gaps filled | n/a | Pass (by another route; accepted) |
| AC-4 | manual: the checklist against the command table | n/a | Pass; success signals given where a tool prints one |
| AC-5 | `tests/test_migration_guide.py:85` `test_guide_commands_exist_and_parse` - `pytest.fail(... "is refused by its parser")` on `SystemExit`; 37 command lines | Yes (a refused argument was shown to fail) | Pass; samples checked, not run (accepted) |
| AC-6 | `tests/test_migration_guide.py:123` - `assert not missing, ... "quoted sections that are not headings"` | Yes | Pass |
| AC-7 | manual: "Rolling back to 3.15.1" | n/a | Pass (corrected after the closing review: what 3.15.1 keeps) |
| AC-8 | manual: `.emm-questions.md` | n/a | Pass (Phase 2) |
| AC-9 | `tests/integration/test_consumer_sdk_calls.py` | Yes | Pass on both backends |
| AC-10 | manual: Emm's suite | n/a | Pass: the baseline's five, nothing new (Phase 3, checkpoint, bumped tree) |
| AC-11 | `tests/integration/test_demo_first_run.py:65` - first start `assert first.returncode != 0` and `"UniqueCreatorNotReady" in first.stderr`, then the second start serves create/meta/www/delete | Yes (coverage: the sequence worked before the plan) | Pass |
| AC-12 | manual: browser walk | n/a | Pass (Phase 3, and this verification for the changed pages) |
| AC-13 | manual: `actingwebdemo`'s tests | n/a | Pass (5 passed after `enable --apply`) |
| AC-14 | manual: the live pair, 18 cells | n/a | Pass |
| AC-15 | `tests/integration/test_wire_v315.py:64`, `:75`, `:99`, `:122` | Yes: each compares with its recording | Pass on both backends |
| AC-16 | manual: "Other versions beside this one" | n/a | Pass |
| AC-17 | manual: the owner, Claude Code, Google, through ngrok | n/a | Pass (`create_note` stored a note after four fixes) |
| AC-18, AC-19 | manual: claude and codex CLIs | n/a | Pass (both read the skill first, kept the defaults, served) |
| AC-20 | `tests/test_docs_api_consistency.py:364` `test_taught_names_are_not_removed` | Yes | Pass |
| AC-21 | `tests/test_version_consistency.py:18`, `:72` | Yes | Pass at `4.0.0rc1` |
| AC-22 | the wire suite after the bump | Yes | Pass, no recording changed |
| AC-23 | manual: `CONTRIBUTING.rst`, CLAUDE.md | n/a | Pass |
| AC-24 | manual: 285 entries to 261, each against `v3.15.1` | n/a | Pass |

The Spec Delta's own tests: `tests/test_trust_permissions_unit.py:613`,
`:653`, `:677`; `tests/integration/test_consumer_sdk_calls.py:172`;
`tests/integration/test_oauth2_trust_binding.py:517`, `:560`;
`tests/integration/test_oauth2_flows.py:349`;
`tests/test_mcp_permissions.py:209`; `tests/test_spa_trust_type.py:71`,
`:88`; `tests/test_spa_redirect_refresh_token.py:88` - each was seen
failing before its change. One gap: Issue 2.

**Security properties the plan claims, demonstrated:** a sign-in's
`trust_type` cannot get a level the hook declined or changed
(`tests/test_spa_trust_type.py:71`: `assert _decide(decline) is None`;
`:88`: `assert _decide(lambda actor, **info: "viewer") is None`), at the
decision method (its wiring: Issue 2); the helper and a direct
confirmation ask the hook (`test_oauth2_trust_binding.py:517`, `:560`:
`assert "error=access_denied" in ...`); no refresh token is minted where
none is handed out (`tests/test_spa_redirect_refresh_token.py:88`:
`session_mgr.create_refresh_token.assert_not_called()`).

## Remaining Tasks

- [ ] The rc pass against real consumers, including 3.15.1 on a
  PostgreSQL database at `a7b8c9d0e1f2`
  (`thoughts/todo/rc-pass-against-real-consumers.md`).
- [ ] Context7 after the stable tag
  (`thoughts/todo/ai-agent-discoverability-followups.md`).
- [ ] The issues below, through `/iterate_plan` before the PR or as the
  owner decides.

## Issues Found

### 1. The awaited permission notification gets a new budget, not what the request has left
**Severity:** Medium
**Description:** under `with_sync_callbacks()` with a budget, the
notification waits up to a whole `callback_delivery_budget_seconds`,
while a request's callbacks share one deadline (`callback_sender.py:301`
`deadline = _Deadline.for_request(settings.budget)`). A request that
spends its budget on callbacks and then calls `store_permissions_async`
can run to twice the budget and past a gateway's limit, which the
setting's documentation says it caps.
**Location:** `actingweb/trust_permissions.py:370`
`budget = settings_for(self.config).budget`, `:375`
`await asyncio.wait_for(_notify_with_error_handling(), budget)`
**Recommendation:** take the time left from the request's deadline and
skip the send, logged, when none is left; add a test that spends the
budget first.

### 2. Nothing tests that the sign-in callback calls the new hook decision
**Severity:** Medium
**Description:** the tests build the handler with `__new__` and call
`_decided_client_trust_type` directly; removing the call in `get()`
would leave them green. The Spec Delta tags the statement `[test]`, and
the spec now lists this under Untested.
**Location:** `actingweb/handlers/oauth2_callback.py:728`
`trust_type = self._decided_client_trust_type(`;
`tests/test_spa_trust_type.py` `handler = OAuth2CallbackHandler.__new__(...)`
**Recommendation:** a handler-level test that drives `get()` with
`trust_type` in the state and a declining hook, asserting that
`create_oauth2_trust_relationship` is not called and the sign-in still
completes.

### 3. The budget applies only to the async path nothing in the library calls
**Severity:** Low
**Description:** `store_permissions_async` has no caller in `actingweb/`
(consumers call it); `store_permissions`, `notify_default_grant` and
`notify_stored_grant`, which the routes use, block on `_notify_peer`
without a budget, as in 3.15.1. Not a regression; the docstring's budget
sentence can be read as covering them.
**Location:** `actingweb/trust_permissions.py:733`, `:755`
**Recommendation:** bound `_notify_peer` by the same deadline, or say in
the docstring and the deployment guide that the synchronous routes are
not bounded.

### 4. `decide_trust=None` no longer means "no hooks"
**Severity:** Low
**Description:** a consumer route that asked its hooks itself and passes
`decide_trust=None` now runs them again; a hook with a side effect (an
audit row, a quota) runs twice. The docstring says to pass an identity
`decide_trust`; the changelog entry does not.
**Location:** `actingweb/oauth2_server/oauth2_server.py:1051-1052`
**Recommendation:** one sentence in the changelog entry and
`hooks-reference.rst`.

### 5. A hook written for the OAuth2 server meets `client_id=None` on the sign-in path
**Severity:** Low
**Description:** owner-decided behaviour (decline on another type); a
hook that assumes `client_id` raises, and the trust is silently not
created while the sign-in succeeds, so the client fails later.
**Location:** `actingweb/handlers/oauth2_callback.py` (`_decided_client_trust_type`)
**Recommendation:** the hooks reference already names the arguments on
this path; add "do not assume `client_id`" and log the decline at the
level a client author will see.

### 6. A storage fault in a hook fails the sign-in, but the changelog says "an exception … still signed in"
**Severity:** Low
**Location:** `actingweb/interface/hooks.py:636` `except DbError:` /
`raise`; `CHANGELOG.rst` (the client-level entry folded into ADDED)
**Recommendation:** say "a storage fault fails the sign-in (503)" in the
entry (the spec's OCR-4 already says so).

### 7. Building the actor interface moved out of the guarded block
**Severity:** Low
**Description:** a non-database error while building `ActorInterface`
for the decision now fails the sign-in instead of being logged as
before.
**Location:** `actingweb/handlers/oauth2_callback.py:722-727`
**Recommendation:** keep it inside the decision's guard, or accept and
note it.

### 8. "Behavior change: none" for the hybrid-only refresh token is true only for the library's routes
**Severity:** Low
**Description:** an application serving the pending session itself (the
Flask case, `flask-spa-session-route.md`) that returned
`token_data["refresh_token"]` for `json` delivery now returns none.
**Location:** `CHANGELOG.rst` (the redirect sign-in entry)
**Recommendation:** name that case in the entry.

### 9. The guide's URL points at `latest`
**Severity:** Low
**Description:** correct for the rc (tagged on `master` after the merge)
but it will drift as later releases change the guide.
**Location:** `actingweb/migration_guide.py:11`
**Recommendation:** a version-pinned path once Read the Docs builds tags;
decide at the stable release.

### 10. Smaller code findings
**Severity:** Low
- `actingweb/handlers/mcp.py:923` `Allow: POST` while the resource also
  answers GET with another `Accept`: `GET, POST` would be exact.
- `actingweb/maintenance/property_lookup.py:61` `GUIDE` is defined and
  never used (it was dead on `master` too).
- The hook decision exists three times (`oauth2_server.py:1025`,
  `oauth2_endpoints.py:635`, `oauth2_callback.py`): one helper would
  keep the contract in one place.
- `actingweb/handlers/oauth2_endpoints.py:372` logs every authorize 400 at
  WARNING without the client: INFO with a truncated `client_id` would be
  both quieter and more useful.
- `examples/mcp_quickstart.py:113`: the docs should say a container needs
  `HOST=0.0.0.0`.

### 11. The factory accepts a creator longer than its form's limit
**Severity:** Low (browser)
**Description:** the form sets `maxlength="100"`; `POST /` with a
313-character creator created an actor (201). Present in 3.15.1 as well.
**Recommendation:** decide whether the factory bounds a creator's length.

### 12. The "Add property" button keeps the old icon
**Severity:** Low (browser, cosmetic)
**Description:** the renamed button on the created page still shows the
former "Initialize" icon and wraps at 375 px.
**Location:** `examples/demo/templates/aw-root-created.html`

### Unverified notes
- Python 3.11's `asyncio.wait_for` can lose a cancellation that arrives as
  the inner call completes (fixed in 3.12), at
  `actingweb/trust_permissions.py:375`; not reproduced.
- `docs/guides/spa-authentication.rst` "no trust is created for it at the
  callback (4.0)" may be read as covering a listed type on the browser
  redirect path, which creates no trust (as in 3.15.1).

## Spec Merge

- `thoughts/specs/trust-permissions.md` - merged: 1 added (TPM-3, under
  "Telling the peer"); Untested gains Issue 1's case.
- `thoughts/specs/mcp-server.md` - merged: 2 added (MCP-3, MCP-4, under
  "Transport and tool listing").
- `thoughts/specs/oauth-client-registration.md` - merged: 2 added (OCR-3,
  OCR-4, under "Deciding the level"); Untested gains
  `handle_oauth_callback()` and OCR-4's wiring (Issue 2).
- `thoughts/specs/subscriptions.md`, `thoughts/specs/web-ui.md` - nothing
  in the delta.

No High issue is open, so the delta is merged; `spec_merged: 2026-11-18`
is written to the plan.

## Overall Assessment

The plan is complete. The release is read whole and documented for a
3.15.1 user: an inventory, a changelog cut to what changed since 3.15.1,
a guide that starts with a checklist and says what stops a start, how to
roll back and what happens with 3.15.1 peers, all held by tests where a
test can hold them. Every consumer check that could be run was run with
real clients, and those runs found three defects review had not (Codex
could not load the skill; Claude Code got no MCP tools, twice over). The
Full tier is green on both backends, the docs build is clean, Emm's suite
is at its baseline, and the security review found nothing.

Before the PR: Issues 1 and 2 are Medium and small to fix (a shared
deadline, a handler-level test); the Lows are wording or tidying. None
blocks the rc on its own, but Issue 2 leaves a security-relevant call
untested, so fixing it through `/iterate_plan` before the merge is the
recommendation.
