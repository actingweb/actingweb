# Verification: one list implementation for properties and attributes, and list diffs that reach a replica (re-run 6)

**Date:** 2026-11-14
**Plan:** thoughts/plans/2026-11-13-attribute-list-v2-port.md
**Research:** thoughts/research/2026-11-05-attribute-list-v2-port.md
**Branch:** release/3.16.0-attribute-list-v2-port (not pushed)
**Commit:** dbbc776

Scope: the round the owner asked for after re-run 5, on the owner's
decisions (1 keep the skip and fix its hole; 2-A a single property's
baseline as the specification reads properties; 3-A the repair tool owes
only a subscription that carries the list; `length` b, not consulted).
Iteration 26 (`7bda23f..cd4bda3`) was reviewed by the outside voice;
iteration 27 (`cd4bda3..dbbc776`) fixes that review's findings and was
checked by tests only.

## Automated Check Results

- **Browser QA:** not run (no page changed).
- **Second opinion:** outside-voice (codex, fresh-context reviewer) on
  iteration 26: no High; 3 Medium, 2 Low (below, all addressed in iteration
  27). Not run on iteration 27.
- **Specification check** (the owner's question): recorded in the plan,
  iteration 26 ("Checked against the specification"): properties are
  untyped values that may be JSON; no rule makes an array a list; lists are
  told apart by `_list` on `GET /properties` and by the metadata route for a
  single name; a list diff's `length` is advisory and receivers MUST NOT use
  it to address rows.
- ruff, pyright, `verify_groups.py`: pass.
- `make test-all-parallel` on iteration 27: **DynamoDB** 7,462 passed and
  **PostgreSQL** 7,231 passed, the 6 failures on each being `WS1`, `WS2` and
  `WS9` at subtarget level, which the fix changed (a string callback was
  answered 400) and which were then re-recorded and pass. On iteration 26:
  DynamoDB 7,465, PostgreSQL 7,234, no failure.
- docs build: pass.
- **Emm's suite on `cd4bda3`** (environment 9): the baseline's failures plus
  Emm's date-dependent `test_trial_state_pure` case, as on every run.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-14-attribute-list-v2-port-5.md

| Issue then | Status now |
| --- | --- |
| 1 duplicates branch bypassed the fetch | Fixed (iteration 26) |
| 2 granularity `none` excluded | Fixed: covers again (owner's decision 1); the consequence documented (iteration 27) |
| 3 repair tool over-marked | Fixed (decision 3-A) |
| 4 empty / falsy / text baselines | Fixed (decision 2-A, iteration 26), with callers completed (iteration 27) |
| 5, 6 (Low) | Accepted as recorded |
| `length` advisory (the specification check) | The receiver no longer consults it (decision b) |

## Issues found on iteration 26, and their fate

1. Medium: the callback log line took `len()` of a number. Fixed.
2. Medium: four callers still dropped falsy values. Fixed at subtarget level
   (target level unchanged: its recordings belong to other plans).
3. Medium: a non-JSON 2xx (a login page behind a proxy) was stored as the
   value. Fixed: only the publisher's own `application/json` answer, with no
   redirect, is read as text.
4. Low: `{ }` with whitespace stored as text. Fixed.
5. Low: a polled whole-target subscription silences a pushed subtarget one.
   Documented (a consequence of decision 1).
- Found by the Full tier: a string callback at subtarget level was answered
  400 (the processor's timestamp read). Fixed; three recordings updated.

## Remaining Tasks

- [ ] The owner: open the PR, or one outside-voice pass on iteration 27 first.

## Overall Assessment

On the owner's decisions the remaining review findings are fixed or
accepted with a record, the Full tier passes on both backends, and Emm's
suite shows nothing beyond its baseline. Iteration 27 has had tests but no
outside review; it is mechanical (callers brought onto iteration 26's
contract) apart from the proxy recording two response facts.
