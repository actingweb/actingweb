# Research: Emm's suite run against `master`, the 3.16 baseline

**Date:** 2026-11-07
**Branch:** docs/3-16-rollup-records
**Commit:** bf4c2a3 (records); the library under test is `master` at `5a7e07f`
**Emm:** `../actingweb_mcp` at `dd5e2ccb` (`main`, v2026.11.03)

The first run the todo [`emm-suite-against-master.md`](../todo/emm-suite-against-master.md)
asks for: Emm's Full tier, the Python lines, on the library as `master` is
before any of the six 3.16 plans starts. Everything here was run, not read;
where a cause is from reading it says so. The run is gate 1 of
[`todo/INDEX.md`](../todo/INDEX.md), "Planned for 3.16".

## Research Questions

1. **What in 3.16 as merged breaks Emm as it is?** One call refuses at
   configure time, one store readiness step is missing from every way Emm
   starts a server, and five tests fail; none is a library regression. See
   "Result" and "Triage".
2. **Does the migration guide name every change Emm has to make?** It named
   all of them, but two in a way a reader following "Start here" would miss,
   and one IAM action it tied to a setting it does not depend on. Corrected
   in this commit; see "What the run changed in this repository".
3. **What is the baseline for the runs on each plan's branch?** The five
   tests below, plus the pin guard deselected by design. See "Baseline".

## Summary

- `master` resolves cleanly into Emm's dependency set (`poetry lock` with
  the path dependency; no conflict from the dependency security roll-up).
- Emm does not start on `master` until `.with_legacy_property_index(enable=False)`
  is removed (`application.py:566`; the method always raises since 3.16) and
  `actingweb-unique-creators enable --apply` has run on the store. With
  those two, it starts on both backends.
- **PostgreSQL, Emm's full pytest line:** 2 failed, 7406 passed, 14 skipped,
  179 deselected, 3 min 13 s. **DynamoDB lane (`scripts/test-backends.sh`):**
  3 failed, 54 passed. `ruff`, `pyright` (against `master`'s types) and
  `build_seed_history.py --check` clean.
- **Library regressions: none.** Every failure is a documented 3.16 change
  Emm has to adopt. Two were already-passing-for-the-wrong-reason tests
  (a write that silently returned `False` on 3.15.1).
- Two adoption items the run surfaced that Emm's own pin todo
  (`../actingweb_mcp/thoughts/todo/actingweb-3-16-pin.md`) does not have:
  the readiness step in every server start (CI's two jobs, the preview and
  test scripts, the deploy), and two IAM actions production's Lambda role
  lacks (`BatchGetItem`, `ConditionCheckItem`). The second would stop the
  deployed application from starting.

## How the run was done

As the todo prescribes: two worktrees and a virtualenv of Emm's own, so
neither main checkout moved and Emm's working environment stays on 3.15.1.

- Library: `git worktree add --detach .claude/worktrees/master-5a7e07f 5a7e07f`
  (this repository; `.claude/worktrees/` is ignored by both repositories).
- Emm: `git worktree add -b actingweb-3-16-adoption .claude/worktrees/emm-3-16 main`
  in `../actingweb_mcp`. Into it: a copy of `.env` without
  `USE_PROPERTY_LOOKUP_TABLE` (see item 3 below), a copy of `static/dist`
  (so no frontend build; the Python lines never load the bundle),
  `pyproject.toml` switched to the path form with the **absolute** path of
  the library worktree (from `.claude/worktrees/`, `../actingweb` does not
  resolve), `poetry env use python3.14`, `poetry lock && poetry install`.
  The venv is poetry's cache one; a `.venv` symlink to it makes `pyright`
  find it.
- PostgreSQL: environment 8 (`actingweb_mcp_8`, port 5008; 1–7 already
  existed). The database was created and migrated by hand, then
  `actingweb-unique-creators enable --apply` built `ux_actors_creator`,
  then `scripts/preview-start.sh 8 --no-ngrok`. The order matters:
  `preview-start.sh` runs uvicorn with `--reload`, and a refusal at import
  leaves the reloader parent alive. Emm's container was started from the
  main checkout's directory (its data directory is `./postgres_data`).
- `scripts/with-preview-env.sh 8 poetry run pytest --timeout=180 --deselect tests/test_dependency_pin_guard.py`,
  sequential (no `-n`, so the baseline carries no parallel flakes).
- DynamoDB: `scripts/test-backends.sh 8`, with the readiness step added to
  the script on Emm's branch (item 2 below); without it the script dies at
  "The DynamoDB server did not start".
- One run at a time; nothing of this repository's suite ran meanwhile.

The two worktrees stay in place, uncommitted on Emm's side
(`application.py`, `scripts/test-backends.sh`, `pyproject.toml`,
`poetry.lock`), for the runs on each plan's branch: point the library
worktree at the plan's commit (`git -C .claude/worktrees/master-5a7e07f checkout <sha>`,
or add a second worktree), `poetry install` in Emm's worktree, repeat the
lines above on a fresh environment number.

## Result

| Lane | Result |
| --- | --- |
| `ruff check .` | clean |
| `pyright` | 0 errors, 0 warnings |
| `pytest --timeout=180` on PostgreSQL, env 8 | **2 failed**, 7406 passed, 14 skipped, 179 deselected (`ai`, `e2e`, `backend_specific` by `addopts`; the pin guard by hand) |
| `scripts/test-backends.sh 8` (DynamoDB Local) | **3 failed**, 54 passed |
| `build_seed_history.py --check` | up to date |
| `tests/test_dependency_pin_guard.py` | fails on the path form by design (2 of its tests); deselected |

The 14 skips are Emm's usual ones (no live Bedrock, no webhook server, the
`describe_method` tests with no methods on the connection).

## Triage

Buckets as the todo defines them: a library regression, a documented 3.16
change Emm must adopt, or a test of Emm's that was already failing. The
third bucket was decided by reading 3.15.1's code and Emm's green CI on
`dd5e2ccb`, not by a control run.

| Test | Bucket | Cause | Fix belongs in |
| --- | --- | --- | --- |
| `tests/test_dynamodb_iam_coverage.py::test_role_grants_every_dynamodb_action_the_backend_uses` | documented change | Emm's `serverless.yml` Lambda role lists actions by name and lacks `dynamodb:BatchGetItem`, which `master` issues at every start (`check_ready` → `settle` → `PropertyLookupV2.batch_get` of the markers). The test also demands `dynamodb:TransactWriteItems` for the `TransactWrite` in `actor.py`; **that action does not exist in IAM**, a transaction is authorised through the item actions plus `dynamodb:ConditionCheckItem` ([AWS: Using IAM with DynamoDB transactions](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis-iam.html)). The role lacks `ConditionCheckItem` too, which the test's pattern map does not cover. Guide: named `ConditionCheckItem` correctly; tied `BatchGetItem` to "auto-create off", which is wrong (corrected here) | Emm: `serverless.yml` (+`BatchGetItem`, +`ConditionCheckItem`), the test's `TransactWrite` → `TransactWriteItems` mapping replaced by one that asks for `ConditionCheckItem` |
| `tests/test_stripe_integration.py::TestSubscriptionCreation::test_create_subscription_proceeds_with_expired_apple_subscription` | documented change (fault contract, guide item 11), and a test that passed for the wrong reason | The test's `MagicMock` subscription gives `plan.interval`, `plan.amount`, `status` as mocks; Emm writes them to the `subscription` attribute bucket, and `json.dumps` raises `TypeError: Object of type MagicMock is not JSON serializable`. 3.15.1's `set_attr` caught every exception and returned `False`, which Emm never checked, so the test passed with nothing stored. `master` raises `DbError("attribute set")`; Emm's `except Exception` answers 500. Reproduced in isolation against env 8 with a plain dict (succeeds) and a mock (fails) | Emm: concrete values in the test's mock; and the handler should let `DbError` through to the integration's 503 instead of its 500 (item 11) |
| `tests/integration/test_dynamodb_operation_profile.py::...::test_property_list_fetch_issues_query_and_no_scan` and `::test_repeated_construction_issues_no_describe_table` | documented change (guide item 17) | `DbProperty()` / `DbPropertyList()` constructed bare; both require the keyword-only `indexed_properties` since 3.16 | Emm: `get_property(config)` / `indexed_properties=[...]` in the two tests |
| `tests/integration/test_restore_actor_dynamodb.py::TestSnapshotThroughTheDbLayer::test_full_force_import_caps_and_confirms_the_wipe` | documented change (guide, "Direct Actor.create callers"; "Start here" item 4 now points at it) | `scripts/restore_actor.py` imports into a fresh table prefix the library auto-creates, builds `Config()` itself, and never runs `enable` on that prefix; with uniqueness on by default `Actor.create` raises `DbError("actor create")` because `<prefix>_creators` does not exist. The script also passes `Config(use_lookup_table=True)`, now a `DeprecationWarning` | Emm: `restore_actor.py` calls `check_ready()`/the enable path for the target prefix before importing, and drops `use_lookup_table` |

## Emm's adoption list, as the run established it

What Emm's `actingweb-3-16-adoption` branch has to carry. Items 1 and 2 are
already made in the worktree (uncommitted); the rest are not, since each is
a decision in Emm's repository, listed here for Emm's pin todo.

1. **Remove `.with_legacy_property_index(enable=False)`** (`application.py:566`).
   Done in the worktree.
2. **Run `actingweb-unique-creators enable --apply` before every server
   start on a store that has not had it**: CI's PostgreSQL job (after its
   `alembic upgrade head`), CI's DynamoDB job (after a pre-warm: importing
   `application` creates the tables and raises `UniqueCreatorNotReady`;
   `enable` refuses to create the actor table itself so a wrong prefix never
   reads as an empty store), `scripts/preview-start.sh` for a new
   environment number, `scripts/test-backends.sh` (done in the worktree,
   with the pre-warm), and the production deploy (Step 0 of the guide; the
   pin todo's step 3 covers the vouch marking but not this).
3. **`USE_PROPERTY_LOOKUP_TABLE=true` in `.env`** (and wherever the Lambda
   environment sets it) is ignored with a `DeprecationWarning`; remove it.
   Not in `serverless.yml`. `=false` would refuse to start.
4. **IAM:** `dynamodb:BatchGetItem` and `dynamodb:ConditionCheckItem` on the
   role in `serverless.yml` (its resource is already `<prefix>_*`, so the
   new `<prefix>_creators` table is covered); the coverage test's
   `TransactWriteItems` mapping replaced. Without `BatchGetItem` the
   deployed application does not start (`PropertyLookupNotReady`, "could
   not be checked").
5. **Fault contract:** the Stripe test's mock, and the `except Exception`
   around the subscription write (`api/stripe_subscription.py:514`) that
   turns a `DbError` into 500 where the integration would answer 503 with
   `Retry-After`. The pin todo's step 4 already names the broader sweep
   (`exists()`, the DynamoDB deletes).
6. **`DbProperty(indexed_properties=...)`** in `test_dynamodb_operation_profile.py`.
7. **`scripts/restore_actor.py`:** readiness on the target prefix before an
   import; drop `use_lookup_table`.
8. From the pin todo, unchanged by the run: `actingweb-mark-actors-vouched`
   before the first sign-in served, and the `with_open_factory(False)`
   decision.

## Baseline

What a run on a plan's branch is compared against, until Emm's branch
adopts the items above (after which the baseline is zero):

- `tests/test_dynamodb_iam_coverage.py::test_role_grants_every_dynamodb_action_the_backend_uses`
- `tests/test_stripe_integration.py::TestSubscriptionCreation::test_create_subscription_proceeds_with_expired_apple_subscription`
- `tests/integration/test_dynamodb_operation_profile.py::TestPerActorReadsUseQueryNotScan::test_property_list_fetch_issues_query_and_no_scan`
- `tests/integration/test_dynamodb_operation_profile.py::TestTableExistenceChecksAreMemoised::test_repeated_construction_issues_no_describe_table`
- `tests/integration/test_restore_actor_dynamodb.py::TestSnapshotThroughTheDbLayer::test_full_force_import_caps_and_confirms_the_wipe`
- `tests/test_dependency_pin_guard.py` (deselected while the path form is in)

A later run that fails anything else is a regression of that plan, or a
consumer-visible change its changelog must name and Emm's branch adapts to.
Any plan that changes which DynamoDB operations the library issues (the
`subs_list` plan removes a Query; the spec plan changes callback delivery)
will move the IAM coverage test one way or the other: read its diff, not
just its verdict.

## What the run changed in this repository

Docs only, in this commit:

- `docs/migration/v3.16.rst`, "One reverse-lookup mechanism", storage
  changes: `BatchGetItem` on `<prefix>_property_lookup_v2` is needed by
  the startup check at every start, not only "with auto-create off".
- `docs/migration/v3.16.rst`, "Start here" item 4: a process that creates
  actors without `integrate_*` must call `check_ready()` or run on an
  enabled store; it said such callers "need nothing".
- `docs/quickstart/configuration.rst`, IAM: `BatchGetItem` on the lookup
  table; and that IAM has no `TransactWriteItems` action.
- `conf.py`: `.claude` and `.claude/**` excluded from the Sphinx source
  tree, so a worktree under `.claude/worktrees/` does not make a local
  `sphinx-build -W` fail.

No library code changed: the run found no regression to fix before plan 0.

## Open Questions

- Whether the plans' changelog entries should carry the IAM actions a
  deployment needs as a standing list, so a consumer's role audit has one
  place to read; today they are spread over the guide and the
  configuration page.
- The Emm-side fixes above are not made on Emm's branch beyond items 1 and
  2; the owner decides whether this session does them or Emm's own
  workflow does (the branch exists for it).
