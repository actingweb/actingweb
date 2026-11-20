# Verification: What 4.0.0rc1 takes from its first consumer's read (third run)

**Date:** 2026-11-20
**Plan:** thoughts/plans/2026-11-19-emm-4-0-adoption-findings.md
**Research:** thoughts/research/2026-11-19-emm-4-0-adoption-findings.md
**Branch:** fix/4.0.0rc1-adoption-findings
**Commit:** 725ee3a plus the uncommitted working tree (iterations 1-19)

Scaled to the delta (owner's rule): the second opinion covered iterations
14-19, and the browser recheck covered the default sign-in page they
changed. Phases 1-3 and iterations 1-13 were verified in the two earlier
runs.

## Automated Check Results

- **Browser QA:** ran, gstack browse (headless Chromium). The library's
  default template on FastAPI (`:5062`) and Flask (`:5063`), provider
  configured, factory closed. `/` and `/login` on both show one "Sign in
  with Google" link (host accounts.google.com) and the email form, with no
  horizontal scroll at 375 px. The form POST answers 302 to the provider
  with `login_hint=qa%40example.test`, and JSON `POST /` answers 403 naming
  `with_open_factory(True)`. No console messages. No findings. QA tables
  removed.
- **Second opinion:** outside-voice with codex (the CLI's default model,
  read-only) and a fresh-context Claude (Opus 5.5), on iterations 14-19.
  1 Medium and 3 Lows, below.
- **Built-in code and security review:** not re-run (one iteration; the
  second opinion had a security brief).
- `ruff check`, `ruff format --check`: pass. `pyright`: 0 errors, 0 warnings.
- Fast tier unit tests: 6488 passed, two runs in a row. An earlier parallel
  run had one failure that did not recur.
- `verify_groups.py`: pass.
- `make test-all-parallel` (DynamoDB): **8385 passed**, 0 failed.
- `make test-all-parallel` (PostgreSQL): **8155 passed**, 0 failed.
- `sphinx-build -W`: pass.

The Full tier ran on this working tree after the last code change of
iteration 19. Since then only the specs and this document changed.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-20-emm-4-0-adoption-findings-2.md
**Iterations since:** entries 14-19 of the iterations log

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1 (High) cleanup deletes another start's marker | Fixed for authorship; a narrower residue remains (issue 1 below) | iteration 14; `tests/integration/test_unique_creator_empty_store.py::test_a_failing_enable_never_removes_another_starts_marker` |
| 2 (High) trust-type crash on PostgreSQL | Fixed | iteration 15; `::test_a_trust_type_registered_before_the_start_on_a_fresh_store` now runs and passes on both backends |
| 3 (High) dry run looks like a write | Fixed | iteration 16; `tests/test_mark_actors_vouched.py::test_a_dry_run_says_so_in_its_summary`; no run instruction without `--apply` remains (the second opinion swept it) |
| 4 (Medium) bypass by creator alone | Fixed | iteration 15; `::test_only_the_system_actors_own_ids_skip_the_record` |
| 5 (Medium) late scan ignored system actors | Fixed | iteration 14; `::test_a_system_actor_written_during_the_enable_is_recorded` |
| 6 (Medium) form shown when its POST cannot sign in | Fixed for a disabled default; one edge left (issue 3 below) | iteration 17; `tests/test_factory_open_switch.py::TestSignInPageValues` |
| 7 (Low) one throwing provider removes all | Fixed | iteration 17 |
| 8 (Low) FastAPI with UI off | Accepted | iterations log after entry 18 |
| 9 (Low) save outside the guard | Fixed within the new design: a failed conditional save raises before any marker exists | iteration 14 |
| 10 (Low) check-ready, missing properties table | Accepted | iterations log after entry 18 |
| 11 (Low) wrong comment | Fixed | iteration 18 |
| Consumer: exempt-creator collision as a known issue | Done | iteration 19; the note lacks one way out (issue 4 below) |

## Acceptance Criteria

ACs unchanged since the second run keep its table and the first run's.
Tests added by iterations 14-19, all passing on both backends where they
apply:

| AC | Test | Asserts the behaviour? | Result |
| --- | --- | --- | --- |
| AC-50 | `tests/integration/test_unique_creator_empty_store.py::test_a_failing_enable_never_removes_another_starts_marker` - `assert Creator.get(BACKFILL_KEY, consistent_read=True)`; `::test_a_system_actor_written_during_the_enable_is_recorded` - `assert Creator.get("system", consistent_read=True).actor_id == (ACTINGWEB_SYSTEM_ACTOR)` | Yes (both seen failing first) | Pass |
| AC-13 | `::test_a_trust_type_registered_before_the_start_on_a_fresh_store` (both backends; PostgreSQL: `assert unique_creators.postgresql_index_state() == "valid"`); `::test_only_the_system_actors_own_ids_skip_the_record` - `pytest.raises(DbError)` | Yes (seen failing first on both backends) | Pass |
| AC-55 | `tests/test_mark_actors_vouched.py::test_a_dry_run_says_so_in_its_summary` - `assert "dry run: nothing written; re-run with --apply" in caplog.text` | Yes | Pass |
| AC-47 | `tests/test_factory_open_switch.py::TestSignInPageValues` - `assert values["email_form"] is False` (default disabled), `assert [p["name"] for p in values["oauth_providers"]] == ["google"]` (one failing); browser recheck | Yes | Pass |

## Remaining Tasks

- [ ] Issues 1 to 4 below: fix or accept each one (owner's call; none is
  peer-reachable).
- [ ] Commit the iterations (the working tree is uncommitted).

## Issues Found

### 1. A start can accept a marker whose writer later removes it
**Severity:** Medium (operator-side: two first starts of an empty store
at once, plus an older process creating an actor meanwhile, plus a fault;
not reachable by a peer)
**Description:** start B's conditional write finds A's marker, caches
"complete" and serves. If A's late pass then fails (an unrecordable late
actor, or a fault), A removes its own marker and refuses. B keeps serving
behind no marker, over an actor with no record, and could let a sign-in
for that creator create a second actor. Later starts refuse, as they
should. Separately, a start killed between its save and the end of its
late pass leaves "complete" with no late pass.
**Location:** `actingweb/maintenance/unique_creators.py` `enable_empty_store`: the early `return` after `creators_backfill_state()  # another start's marker: remember it`, and the `Creator(creator=BACKFILL_KEY).delete()` in the cleanup.
**Recommendation:** on finding another start's marker, run the same late
pass (it is idempotent) and refuse without deleting if it fails; or publish
the marker only after the late pass, with an in-progress item. A test with
two starts, one faulting after the other accepted.

### 2. A system actor saved after the late pass is unrecorded, and `report` then exits 1
**Severity:** Low
**Description:** the exemption checks the backfill state, then writes. A
worker that read "not backfilled" can land `_actingweb_system` after the
enable's late pass. No duplicate can follow (the creator is refused from
callers), but `actingweb-unique-creators report` on DynamoDB lists it as
unrecorded and exits 1 on a healthy store.
**Location:** `actingweb/db/dynamodb/actor.py` `_system_actor_before_enable` (`return _backfill_probe.cached_backfill_state() != "complete"`); `actingweb/maintenance/unique_creators.py` `_collect_creators` (`report.unrecorded`).
**Recommendation:** have `report` (and `enable`) not count an
`is_system_actor` row as unrecorded, or record one on sight.

### 3. The email form checks the default provider's `is_enabled()`, not its URL build
**Severity:** Low
**Description:** if the default provider is enabled but its
`create_authorization_url()` raises, its button is dropped and the form
still shows; its POST then falls through to a closed factory (403).
**Location:** `actingweb/handlers/factory.py` `sign_in_page_values` (`provider_names and create_oauth2_authenticator(config).is_enabled()`).
**Recommendation:** base `form_signs_in` on whether the default provider's
URL was built.

### 4. The guide's known-issue note omits the second way out
**Severity:** Low
**Description:** the note says the collision blocks the start and is not
suppressed. The command's own output also offers accepting it with
`actingweb-property-lookup mark-complete --force --properties <name>
--apply`, after which a lookup of the shared value finds only the row's
holder.
**Location:** `docs/migration/v4.0.rst`, the "Known issue, by design" note under "Collisions".
**Recommendation:** one sentence naming `mark-complete --force`.

## Spec Merge

Merged (no High open):
- `thoughts/specs/operator-commands.md`: created (partial), OPC-1 to
  OPC-10, OPC-D1 to OPC-D3.
- `thoughts/specs/startup-readiness.md`: created (partial), SRD-1 to SRD-4,
  SRD-D1, SRD-D2. SRD-3 carries iterations 4 and 14. Issue 1's residue is
  listed under Untested.
- `thoughts/specs/actor-creation.md`: created (partial), ACR-1 to ACR-5,
  ACR-D1. ACR-1 carries iterations 1 and 17.
- `thoughts/specs/property-lists.md`: created (partial), PLS-1 to PLS-5 and
  PLS-D1 to PLS-D3 from the delta. PLS-D4 records the owner's 2026-11-20
  decision to keep the newer-layout refusal on `delete()`/`clear()`.
- `thoughts/specs/mcp-server.md`: 4 added (MCP-5 to MCP-8) and 2 decisions
  (MCP-D1, MCP-D2).
- `thoughts/specs/oauth-client-registration.md`: 3 added (OCR-5 to OCR-7)
  and 2 decisions (OCR-D2, OCR-D3). The accepted `plain`-method item is
  listed under Untested.
- `thoughts/specs/web-ui.md`: 2 added (WUI-4, WUI-5).
- `thoughts/specs/README.md`: four rows added.

## Overall Assessment

The plan is implemented, and every finding of the two earlier runs is fixed
or accepted. Emm's crash is fixed on both backends, the default sign-in
page works in a browser on both integrations, and the marking command now
writes only with `--apply` and says when it did not. The Full tier is green
on both backends with no failures, and the spec changes are merged.

What remains is one operator-side Medium (issue 1: a narrow residue of the
two-starts race, needing a concurrent older process and a fault) and three
Lows. By the owner's stop rule (clean = no peer-reachable Medium or worse)
this run is clean. Issue 1 is cheap to close, by running the late pass on
the accepting side too, and is worth doing before the tag if the owner
wants the first-start sequence airtight. Then commit, and the PR can open.
