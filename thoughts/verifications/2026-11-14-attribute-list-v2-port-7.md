# Verification: one list implementation for properties and attributes, and list diffs that reach a replica (re-run 7)

**Date:** 2026-11-14
**Plan:** thoughts/plans/2026-11-13-attribute-list-v2-port.md
**Research:** thoughts/research/2026-11-05-attribute-list-v2-port.md
**Branch:** release/3.16.0-attribute-list-v2-port (pushed when the PR opens)
**Commit:** the iteration-9 follow-up commit on top of `f0fe2b1`

Scope: the reviews the owner asked for before the PR: the outside voice on
iteration 27, then on iteration 28, then a narrow regression check on
iteration 29 (the plan's Iterations entries 28 and 29). The stop rule
applies: clean means no peer-reachable Medium or higher.

## Automated Check Results

- **Browser QA:** not run (no page changed).
- **Second opinion**, all runs by codex (`codex exec -s read-only`) and a
  fresh-context reviewer:
  - Iteration 27 (`cd4bda3..dbbc776`): 1 High, 6 Medium, 3 Low. Fixed in
    iteration 28.
  - Iteration 28 (`dbbc776..a98690a`): 4 Medium peer-reachable, 3 Low; two
    of them went to the owner. Fixed in iteration 29 on the owner's
    decisions.
  - Iteration 29 (`a98690a..f0fe2b1`, narrow): no regression; 3 Low in the
    new lines, fixed in the follow-up commit.
- ruff, ruff format, pyright, `verify_groups.py`: pass.
- `make test-all-parallel`:
  - On the final tree: **DynamoDB** 7,500 passed, **PostgreSQL**
    7,269 passed.
  - On `f0fe2b1`: DynamoDB 7,497, PostgreSQL 7,266.
  - On `a98690a`: DynamoDB 7,491, PostgreSQL 7,260. This was after `WS1`,
    `WS2` and `WS9` at subtarget level were re-recorded; a subtarget delete
    reaches the hook as `""`, not `{}`.
- Docs build: pass.
- **Emm's suite on `a98690a`** (environment 9):
  - PostgreSQL: 3 failed, 7,405 passed. DynamoDB lane: 3 failed, 54 passed.
  - These are the baseline's failures by name: Emm's date-dependent
    `test_trial_state_pure` case on PostgreSQL, and nothing new.
  - Emm's one subscription data hook (`hooks/actingweb/callback_hooks.py:143`)
    assumes `data` is a dict. Emm subscribes only to whole `properties`
    targets, and iteration 29 keeps a malformed body of such a target from
    the hooks. Iteration 29 itself changes no shape Emm reads.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-14-attribute-list-v2-port-6.md

| Issue then | Status now |
| --- | --- |
| The owner: open the PR, or one outside-voice pass on iteration 27 first | Pass run (owner); its findings fixed in iterations 28-29 |

## Issues Found

None open at Medium or above.

Accepted with a record (plan, entries 27 to 29):
- **Pre-3.16 reading kept:**
  - JSON `null` reads as a failed fetch.
  - The permission callback's fetch still reads the old way.
- **Edge cases of the single-property fetch:**
  - A list deleted between two fetches is stored once as an array.
  - `application/*+json` is not JSON for a body that did not parse.
  - A metadata answer of `{}` confirms no list.
  - A body carrying both `url` and a falsy `data` is fetched.
- **Redirects:**
  - The async client does not follow redirects; the sync one does.
  - The same-host comparison ignores the port.
- **Subscriptions:**
  - A polled whole-target subscription delays a pushed subtarget
    subscription's values until the poll.
  - Subscribe skips the metadata refresh on a falsy baseline.

## Remaining Tasks

- [ ] Open the PR (owner: "When we have a clean run, open a PR").

## Overall Assessment

Clean by the stop rule: the last review found no regression and nothing
peer-reachable at Medium or above, and its three Lows are fixed. The Full
tier passes on both backends, and Emm's suite shows nothing beyond its
baseline. Two decisions in this round were the owner's:
- No 400 for a target-level body that is not an object.
- A redirect on the trust's own host is the publisher's answer, logged as a
  configuration warning.
