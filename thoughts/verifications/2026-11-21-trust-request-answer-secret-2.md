# Verification: 4.0.0rc2 — the trust request's answer, and a consumer's rc1 findings (re-run)

**Date:** 2026-11-21
**Plan:** thoughts/plans/2026-11-21-trust-request-answer-secret.md
**Research:** thoughts/research/2026-11-21-trust-request-answer-secret.md
**Branch:** fix/4.0.0-rc2-consumer-fixes
**Commit:** 021590b

A re-run after iterations 5-10, which addressed the first verification's
issues. Phases 1-5 and iterations 1-4 are unchanged since
`verifications/2026-11-21-trust-request-answer-secret.md`; its Phase
Verification and Acceptance Criteria tables stand, and this run checks the
delta `9bdb668..021590b` against them.

## Automated Check Results

- **Browser QA:** N/A (no phase touches a page a user sees).
- **Second opinion:** not run again (owner rule: reviews scale to the
  delta). The delta is about 40 lines of code: two refusal strings and a log
  word in the trust handler, a `continue` and a guard in the creator
  maintenance command, and docstrings; it was read line by line here. The
  first run's outside voice, code review and security review cover
  everything else.
- Full tier, run on the working tree committed unchanged as `021590b`:
  - `ruff check`: pass
  - `ruff format --check`: pass
  - `pyright`: pass, 0 errors
  - `verify_groups.py`: pass
  - `make test-all-parallel` (DynamoDB): pass, 8515 passed, 217 skipped, 2 xfailed
  - `make test-all-parallel` (PostgreSQL): pass, 8266 passed, 466 skipped, 2 xfailed
  - `sphinx-build -W`: pass

## Phase Verification

### Iterations 5-10 - VERIFIED

**Changes verified:**
- `actingweb/maintenance/unique_creators.py:303` `if is_reserved(creator):` ... `continue` — a reserved creator is listed and never grouped (DynamoDB's in-memory grouping).
- `actingweb/maintenance/unique_creators.py:665` `if not Creator.exists() or is_reserved(key):` — `_settle_record` never writes under a reserved key, also if a caller reaches it another way.
- `actingweb/maintenance/unique_creators.py:919` — an exempt actor's `--previous` runs the previous step (`not-kept` on PostgreSQL, `skipped` before `enable`); `:737` `if self.previous is None:` — `skipped` now exits 1.
- `actingweb/handlers/trust.py:273-274` — both unmapped reasons map to "The trust was deleted meanwhile; pair again"; `:696` the log says "the secret was swapped, then the row went" only for the read-back reason, the one `replace_trust_secret` returns after a written swap (`actor.py`, `return (updated or None), "" if updated else "the row could not be read back"`).
- `token_manager.py` docstrings, `test_trust_flow.py` hints, `CHANGELOG.rst`, `docs/quickstart/deployment.rst` — match the iterations log entries 8-10 and 6.

**Tests verified** (each seen failing on the behaviour before its fix):
- `tests/integration/test_unique_creators_record.py:259` `test_resolve_never_records_a_reserved_creator` — `assert not Creator.get("#meta#backfill", consistent_read=True).actor_id` (`:275`), both actors keep their creator, `resolve --apply` exits 0 with `groups=0`.
- `tests/integration/test_unique_creators_record.py:283` `test_previous_is_released_for_an_exempt_creator[True|False]` — `assert unique_creators.main(argv) == (0 if ours else 1)` (`:293`), and the record is gone when it named this actor.
- `tests/test_trust_re_pair.py:2868` `test_a_trust_deleted_meanwhile_says_pair_again` — the body is `{"error": "The trust was deleted meanwhile; pair again"}` and the log names the outcome for each reason.

**Deviations from plan:** none; issue 7 accepted as designed (below).

## Acceptance Criteria

Unchanged from the previous run: every AC covered by an asserting test, all
passing in this run's Full tier. AC-12's refusal wording gained one reason
(iterations entry 7), asserted by `test_a_trust_deleted_meanwhile_says_pair_again`.
AC-33 (`server_version=None` refused) stands.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-21-trust-request-answer-secret.md
**Iterations since:** entries 5-10 of the iterations log

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. `resolve` can record a reserved creator (Medium) | Fixed | `unique_creators.py:303`, `:665`; entry 5 |
| 2. Two re-pair reasons unmapped | Fixed | `handlers/trust.py:273-274`, `:696`; entry 7 |
| 3. `record --previous` exits 0 when skipped for an exempt creator | Fixed | `unique_creators.py:919`, `:737`; entry 6 |
| 4. Revoke docstrings omit the code bucket | Fixed | `token_manager.py` `revoke_client_tokens`; entry 8 |
| 5. `TestPeerTrustRequest` without type hints | Fixed | `tests/integration/test_trust_flow.py:688`; entry 9 |
| 6. CHANGELOG without **Behavior change:** | Fixed | `CHANGELOG.rst` Unreleased; entry 10 |
| 7. `server_version=None` cannot reset | Accepted as-is | AC-33; iterations log, batch heading |
| Remaining task: issue 1 before the PR | Done | as issue 1 |

## Remaining Tasks

- [ ] Push and open the PR (owner's go-ahead).

## Issues Found

### 1. OPC-12 said reserved creators form no group on either backend
**Severity:** Low (spec wording only; fixed in this run's spec check)
**Description:** on PostgreSQL `UNIQUE_INDEX_PREDICATE` does not exclude reserved values (`creator_rules.py:31` `"lower(creator) NOT IN ('trustee', 'creator', '')"`), so `resolve` still groups two legacy actors sharing one and renames the extra; PostgreSQL has no records, so nothing reserved is recorded. The spec now says the grouping rule is DynamoDB's.
**Location:** `thoughts/specs/operator-commands.md` OPC-12.
**Recommendation:** none further.

### Notes (unverified)
- The exempt branch's PostgreSQL (`not-kept`) and before-`enable` (`skipped`, exit 1) outcomes have no test of their own; both are one-line assignments beside tested siblings.
- Releasing `--previous` for an actor renamed to `#dup-…` leaves the address unrecorded until `record` runs for the actor that kept it, as the deployment guide's sequence already says for any release.

## Spec Merge

- Already merged (`spec_merged: 2026-11-21`); the iterations' spec edits were checked against the code. `thoughts/specs/operator-commands.md` OPC-12 corrected (issue 1 above). `trust-establishment.md` TES-8 matches.

## Overall Assessment

Every issue of the first verification is fixed or accepted, each fix has a
regression test that failed before it, and the Full tier is green on both
backends. No peer-reachable Medium or worse is open, so by the owner's stop
rule the loop is clean: the plan is verified and ready for its PR.
