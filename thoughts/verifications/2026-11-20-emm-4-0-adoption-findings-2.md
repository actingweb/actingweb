# Verification: What 4.0.0rc1 takes from its first consumer's read (re-run)

**Date:** 2026-11-20
**Plan:** thoughts/plans/2026-11-19-emm-4-0-adoption-findings.md
**Research:** thoughts/research/2026-11-19-emm-4-0-adoption-findings.md
**Branch:** fix/4.0.0rc1-adoption-findings
**Commit:** 725ee3a plus the uncommitted working tree (iterations 1-13)

This re-run checks the iterations against the first verification. Per the
owner's rule (scale reviews to the delta), the second opinion and the
browser walk covered the iteration diff (`git diff HEAD`, 25 files), not the
whole branch again.

## Automated Check Results

- **Browser QA:** ran, provider gstack browse (headless Chromium). Two
  minimal apps on the library's **default** template, with a provider
  configured and the factory closed: FastAPI on `:5062` and Flask on `:5063`
  (Chromium refuses `:5061`). On `/` and `/login` of both, the page shows
  "Sign in with Google" and the email form. The form POST answers 302 to
  the provider with `login_hint=qa%40example.test`, special characters are
  encoded, and an empty submit is blocked by the browser (bypassed, the
  server re-renders "Email is required"). JSON `POST /` answers 403 naming
  `with_open_factory(True)`. Fine at 375 px. No console messages. Three Low
  findings concern the form-POST redirect, which this branch did not change
  (no server-side address check, whitespace-only accepted, no length
  limit): Notes. Screenshots:
  `/private/tmp/claude-501/-Users-wedel-src-actingweb-actingweb/a49e9e4a-ca50-4d67-9e4d-ef94c478b2ae/scratchpad/qa-signin/`.
  QA tables removed.
- **Second opinion:** outside-voice with codex (gpt-5.6-sol, read-only) and a
  fresh-context Claude read of the iteration diff. 11 findings; the ones
  checked here are folded into Issues Found.
- **Built-in code and security review:** not re-run. The delta is one
  iteration, and the second opinion covered it with a security brief.
- `ruff check`, `ruff format --check`, `pyright`: pass (0 errors, 0 warnings),
  run after the last code change.
- Fast tier unit tests: 6485 passed.
- `verify_groups.py`: pass.
- `make test-all-parallel` (DynamoDB): 8378 passed, **1 failed**
  (`tests/test_verification_fetch.py::TestLateAndFull::test_a_full_pool_refuses_at_once`).
  Run alone three times, the file passed 12/12 each time; the file is
  untouched by this branch. A parallel-isolation flake.
- `make test-all-parallel` (PostgreSQL): **8150 passed**.
- `sphinx-build -W`: pass.

The Full tier ran on this working tree after the last code change. Only
plan text changed afterwards.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-20-emm-4-0-adoption-findings.md
**Iterations since:** entries 1-13 of the iterations log

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1 (High) default page with a provider | Fixed | iteration 1; `tests/test_factory_open_switch.py::TestClosedByDefaultWithAProvider::test_with_a_provider_the_default_page_signs_in`; browser walk above. New edge cases: issues 6 and 7 below |
| 17 (High) trust type before integrate on a fresh store | **Fixed on DynamoDB only** | iteration 2; still open on PostgreSQL (issue 2 below), and it opened issue 4 |
| 2 (Medium) per-list 409 in the listing | Fixed | iteration 3; `tests/test_list_newer_format_http.py::test_a_newer_list_layout_fails_its_own_entry_in_the_listing` |
| 3 (Medium) self-enable marker on a fault | Fixed, but the fix is wrong under concurrency | iteration 4; see issues 1 and 9 |
| 4 (Medium) check-ready denial read as empty | Fixed | iteration 5; `tests/test_check_ready_command.py::test_a_denied_permission_is_not_an_empty_store` |
| 5 (Medium) check-ready lookup gate | Fixed; one edge left | iteration 6; issue 10 below |
| 18 (Medium) marking writes by default | Fixed; output and docs incomplete | iteration 7; issue 3 below |
| 6 (Low) damaged meta blocks attribute delete | Fixed (attribute lists) | iteration 10; the `ListCore.delete()` comment overclaims (issue 11) |
| 7 (Low) remedy text | Fixed | iteration 9 |
| 8 (Low) Spec Delta wording for `clear()` | Fixed | iteration 11 |
| 13 (Low) AC-34 test that could not fail | Fixed | iteration 8 |
| 9, 10, 11, 12, 14, 15, 16 (Low) | Accepted | iterations log, "Accepted without code". Issue 10 (two first starts) is made worse by iteration 4: issue 1 below |
| Traceability references | Fixed | iteration 12 |
| Consumer report point 2 (exempt collision) | Documented | iteration 13 |

## Phase Verification

Phases 1 to 3 were verified in the previous run. This run checks only the
iteration changes. Each one matches its log entry, except where an issue
below says otherwise.

## Acceptance Criteria

Unchanged ACs keep the previous run's table. Rows added or changed by the
iterations:

| AC | Test | Asserts the behaviour? | Result |
| --- | --- | --- | --- |
| AC-47 (restated) | `tests/test_factory_open_switch.py::TestClosedByDefaultWithAProvider::test_with_a_provider_the_default_page_signs_in` - `assert 'name="creator"' in text, where` / `assert "Sign in with" in text, where` (both integrations, `/` and `/login`, open and closed); `::test_without_a_provider_a_closed_factory_offers_no_form`; browser walk | Yes | Pass |
| AC-55 (new) | `tests/test_mark_actors_vouched.py::TestApplyFlag` - `assert self._run(monkeypatch, [])["dry_run"] is True` / `["--apply"]` is False / both together exit 2 | Yes | Pass; output gap in issue 3 |
| AC-13 (extended) | `tests/integration/test_unique_creator_empty_store.py::test_a_trust_type_registered_before_the_start_on_a_fresh_store` - `assert Creator.get("system", consistent_read=True).actor_id == (ACTINGWEB_SYSTEM_ACTOR)` | Yes, DynamoDB only (the PostgreSQL skip is wrong, issue 2) | Pass |
| AC-50 (extended) | `::test_a_fault_after_the_marker_removes_it` - `assert unique_creators.missing_enforcement(fresh_store) is not None` | Yes for one process; nothing covers a second process's marker (issue 1) | Pass |
| AC-11 (extended) | `tests/test_check_ready_command.py::test_a_denied_permission_is_not_an_empty_store`, `::test_the_lookup_gate_follows_the_properties_table` | Yes | Pass |
| AC-25 (extended) | `tests/test_list_newer_format_http.py::test_a_newer_list_layout_fails_its_own_entry_in_the_listing` - `assert body["notes"] == {"_list": True, "error": "list_item_newer_format"}` | Yes | Pass |

## Remaining Tasks

- [ ] Issues 1 to 3 (High) and 4 to 6 (Medium), via `/iterate_plan`.
- [ ] Issues 7 to 11 (Low): fix or accept each one.
- [ ] Commit the iteration once the Highs are closed (the working tree is uncommitted).

## Issues Found

### 1. The self-enable's cleanup can delete another process's marker
**Severity:** High
**Description:** iteration 4 deletes the backfill-complete item on any
`BaseException` after `Creator(creator=BACKFILL_KEY).save()`. The save is
unconditional, so the item may be one another process wrote and is
serving behind. Two first starts at once (issue 10 of the first run): B
completes, caches "complete" and serves sign-ups. C's late scan faults, or C
gets `SystemExit` on shutdown, and C deletes B's item. Every later process
then finds "not backfilled" on a non-empty store and refuses to start until
an operator runs `enable --apply`. That is an outage path where there was
none.
**Location:** `actingweb/maintenance/unique_creators.py:1246` `Creator(creator=BACKFILL_KEY).save()` and the `except BaseException:` that follows it.
**Recommendation:** save with `condition=Creator.creator.does_not_exist()`
(an existing item means another process enabled the store: re-check and
accept). Delete only an item this call created, catch `Exception` rather
than `BaseException`, and put the save inside the guard (issue 9).

### 2. Issue 17 is still open on PostgreSQL
**Severity:** High
**Description:** a system actor's create on a fresh PostgreSQL store is
refused the same way: `_require_creator_index("actor create")` raises while
`ux_actors_creator` does not exist, and no migration builds it (only the
start-up enable does). An application that calls `add_trust_type()` at
import crashes before `check_ready()` on PostgreSQL. The test is skipped
there with a wrong reason ("the refusal is DynamoDB's").
**Location:** `actingweb/db/postgresql/actor.py:284-285` `if self.unique_creator and not is_exempt(creator):` / `_require_creator_index("actor create")`;
`tests/integration/test_unique_creator_empty_store.py` (the skip on the
iteration-2 test).
**Recommendation:** the same narrow exemption on PostgreSQL. The index
built at the enable then covers the row. Run the test on both backends.

### 3. A dry run of the marking looks like a write, and the docs still say to run it bare
**Severity:** High
**Description:** after iteration 7 the run without `--apply` writes
nothing, but its summary is the same line (`scanned=… marked=105 …`, exit
0). Several places still tell an operator to run the command with no
flag:
- `CHANGELOG.rst:15` "``actingweb-mark-actors-vouched`` where actors created before 4.0 are to be kept"
- `CHANGELOG.rst:603`
- `docs/migration/v4.0.rst:464` "run ``actingweb-mark-actors-vouched`` *before the application serves its first sign-in*"
- `docs/migration/v4.0.rst:317` "(writing)"
- the log line at `actingweb/maintenance/unique_creators.py:1512`

An operator following them (or an rc1-era script) sees `marked=105` and
believes the actors are vouched. Each is then cleaned at its next sign-in:
its passphrase is rotated and its trusts, sessions and MCP clients are
removed.
**Location:** `actingweb/maintenance/mark_actors_vouched.py:414-420` (the summary); the lines above.
**Recommendation:** say in the summary that it was a dry run
("dry run: nothing written; re-run with --apply"), with a test, and add
`--apply` at each place listed.

### 4. The system-actor bypass trusts the creator value alone
**Severity:** Medium
**Description:** any `DbActor.create(..., creator="system")` before the
enable is written without a creator record, whatever its id. A non-system
id then also makes the store count as non-empty, so the start refuses.
Only library code passes these creators (callers are refused at the
factory and trustee routes), so this needs a programming error, but the
rule should be exact.
**Location:** `actingweb/db/dynamodb/actor.py:97` `if creator not in SYSTEM_CREATORS:`.
**Recommendation:** match the exact pairs (`ACTINGWEB_SYSTEM_ACTOR`,
`system`) and (`OAUTH2_SYSTEM_ACTOR`, `oauth2-system`).

### 5. The late scan ignores system actors
**Severity:** Medium
**Description:** `late, _ = scan()` discards the system list. Iteration 2
lets a worker write `_actingweb_system` (no record) before the enable, so
one written between another worker's first scan and its marker save stays
unrecorded behind "complete". The enable is never re-run to fix it.
**Location:** `actingweb/maintenance/unique_creators.py:1253` `late, _ = scan()`.
**Recommendation:** record both lists in the late pass.

### 6. The email form can show when its POST cannot sign in
**Severity:** Medium
**Description:** `email_form` is true when any provider builds a URL, but
the form's POST uses only the default authenticator. If the default
provider is not enabled and another is, the form is shown, the POST falls
through to the factory, and a closed factory answers 403.
**Location:** `actingweb/handlers/factory.py:353` `"email_form": factory_open or bool(oauth_urls),`;
`actingweb/interface/integrations/flask_integration.py:1046`, `fastapi_integration.py:1852` (`create_oauth2_authenticator(self.aw_app.get_config())`).
**Recommendation:** derive the form from the authenticator the POST uses.

### 7. One provider that throws removes every button and the form
**Severity:** Low
**Location:** `actingweb/handlers/factory.py:337` (one `except` around the whole provider loop).
**Recommendation:** catch per provider.

### 8. FastAPI with the web UI off now serves the sign-in page with buttons
**Severity:** Low
**Description:** the fallback render at `fastapi_integration.py:1789`
(`context=factory.sign_in_page_values(...)`) runs when the handler answered
404 for `ui` off. Before, the same fallback rendered the template with only
`factory_open`, so a page was already served; it now also has provider
buttons. Not mentioned in the changelog.
**Recommendation:** decide whether `ui` off should render the page at all;
state the result in the changelog.

### 9. The marker save sits outside the new guard
**Severity:** Low (part of issue 1's fix)
**Location:** `actingweb/maintenance/unique_creators.py:1246`.

### 10. `check-ready` reads a missing properties table as "ready at first start"
**Severity:** Low
**Description:** `_properties_empty` treats a missing table as empty, but
the start's `properties_table_empty` raises `DbError` on a missing table
(`property_lookup.py:115`), so with table auto-creation off, or on
PostgreSQL before `alembic upgrade head`, the start refuses.
**Location:** `actingweb/maintenance/check_ready.py` `_properties_empty`.
**Recommendation:** report the missing table as REFUSED with the step that
creates it.

### 11. `ListCore.delete()`'s new comment overclaims
**Severity:** Low
**Location:** `actingweb/list_core.py` (the comment "an unparsable meta row is damage, and the list is still deleted whole"; `_require_v2()` next raises on that row).
**Recommendation:** say that only an attribute list's `delete()` passes.

### Notes
- Browser QA: the form-POST redirect has no server-side address check,
  accepts a whitespace-only address, and has no length limit. All three
  predate the branch.
- The second opinion's unverified points: `create_authorization_url()` now
  runs on every unauthenticated `GET /` and `/login` on Flask (CPU only, no
  state stored, as read). `_missing_table` follows `__context__`.
  `_refuse_newer_layout_only` treats a non-object meta row as damage, which
  holds while later layouts keep the meta row a JSON object (worth a line
  in the stored-format rule).

## Spec Merge

Not merged: issues 1 to 3 are open Highs. The previous run's plan stands:
four new partial specs and additions to three existing ones, merged by the
next clean verification.

## Overall Assessment

The iteration closed what the first verification found, and the browser
confirms the default sign-in page on both integrations. But the
adversarial pass found that two of the start-up fixes are not safe under
concurrency. The marker cleanup can delete another process's marker and
cause an outage (issue 1), and the late scan does not record system actors
the new bypass lets in (issue 5). The trust-type fix covers DynamoDB only
(issue 2). And the marking's new dry-run default prints a summary
indistinguishable from a write, while the changelog and parts of the guide
still say to run it bare (issue 3). These are small changes. A
third pass after them should cover the start-up sequence with a
two-process test, not only single-process faults.
