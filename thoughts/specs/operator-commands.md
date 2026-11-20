# Spec: Operator commands

**Status:** partial (covers: behaviour changed since 2026-11-19)
**Reviewed:** 2026-11-19 by Greger Wedel (with the plan)
**Last changed:** 2026-11-20 by thoughts/plans/2026-11-19-emm-4-0-adoption-findings.md
**ID prefix:** OPC

## Summary

The console commands an operator runs against an application's store
(`actingweb-property-lookup`, `actingweb-unique-creators`,
`actingweb-mark-actors-vouched`, `actingweb-check-ready`,
`actingweb-verify-property-lists` and the others in `pyproject.toml`).
This partial spec covers what the 2026-11-19 plan changed.

## Common

- **OPC-1** — When any operator command starts, it prints the store it will
  read before its first read. [plan+test] `tests/test_operator_command_store.py::test_every_command_prints_the_store_first` (plans/2026-11-19-emm-4-0-adoption-findings.md, AC-9)
- **OPC-2** — When a command would write on DynamoDB with `AWS_DB_PREFIX`
  unset or empty, it refuses with exit status 2. [plan+test]
  `tests/test_operator_command_store.py::test_writing_without_a_prefix_is_refused` (plans/2026-11-19-emm-4-0-adoption-findings.md, AC-10)

## Reverse lookup

- **OPC-3** — When `report` is given `--properties`, its verdict and fix
  line are about those names and it says where the set came from.
  [plan+test] `tests/test_property_lookup_command.py::test_report_verdict_follows_the_passed_names` (plans/2026-11-19-emm-4-0-adoption-findings.md, AC-1)
- **OPC-4** — When `backfill` runs on PostgreSQL, its summary counts the
  rows of the names it covered and those of live actors. [plan+test]
  `tests/test_property_lookup_command.py::TestBackfill::test_the_summary_counts_what_it_read` (plans/2026-11-19-emm-4-0-adoption-findings.md, AC-53)
- **OPC-5** — When a backfill collision leaves a name unmarked, the output
  names each colliding actor, the holder of the lookup row, and the two
  ways out. [plan+test] `tests/test_property_lookup_command.py::TestBackfill::test_a_collision_names_the_actors_and_the_ways_out` (plans/2026-11-19-emm-4-0-adoption-findings.md, AC-54)

## Vouching

- **OPC-6** — When the marking runs, system actors are never marked; a dry
  run shows the marker and, on request, the addresses; `--ids-file` limits
  it. [plan+test] `tests/test_mark_actors_vouched.py` (`test_system_actors_are_never_marked`, `test_dry_run_prints_marker_and_hides_addresses`, `test_ids_file_limits_the_run`) (plans/2026-11-19-emm-4-0-adoption-findings.md, AC-2 to AC-4)
- **OPC-7** — When the marking runs without `--apply`, it writes nothing,
  like every other writing command, and its summary says it was a dry run.
  [plan+test] `tests/test_mark_actors_vouched.py::TestApplyFlag`, `::test_a_dry_run_says_so_in_its_summary` (plans/2026-11-19-emm-4-0-adoption-findings.md, AC-55; iterations 7, 16)

## Email as creator

- **OPC-8** — When the sweep passes an unvouched actor, it counts it and
  says the marking comes first. [plan+test] `tests/integration/test_email_as_creator_sweep.py::test_sweep_counts_unvouched` (plans/2026-11-19-emm-4-0-adoption-findings.md, AC-5)

## Readiness

- **OPC-9** — When `actingweb-check-ready` runs, it reports each start-up
  gate as ready, ready at first start, or REFUSED with its fix line, writes
  nothing, and exits 0, 1 or 2; only a missing table reads as empty (a
  denied permission is unreadable, exit 2), and reverse lookup is "ready at
  first start" when no actor has a property row, the start's own test.
  [plan+test] `tests/test_check_ready_command.py` (plans/2026-11-19-emm-4-0-adoption-findings.md, AC-11; iterations 5, 6)

## List verification

- **OPC-10** — When `actingweb-verify-property-lists` runs with `--spans`
  or `--sweep-spans`, side rows named for a list with no meta row are
  reported and kept; a list holding newer-format data is reported on a line
  of its own (`NEWER FORMAT`), neither repaired nor swept, and the exit
  status is 3 when nothing else is wrong. [plan+test] `tests/test_verify_property_lists.py` (plans/2026-11-19-emm-4-0-adoption-findings.md, AC-27, AC-45)

## Decisions in force

- **OPC-D1** — A backfill collision leaves the name unmarked; the start stays
  refused until an operator removes the duplicates or accepts them with
  `mark-complete --force`. (plans/2026-11-19-emm-4-0-adoption-findings.md)
- **OPC-D2** — An operator command never treats a missing table or the
  default prefix as an empty store. (plans/2026-11-19-emm-4-0-adoption-findings.md)
- **OPC-D3** — A command cannot see what an application sets in its
  builder; each such setting has a flag, and the command prints what it
  assumed. (plans/2026-11-19-emm-4-0-adoption-findings.md)

## Untested

- OPC-9's "writes nothing" rests on a test that patches every probe and on
  the manual run of 2026-11-19.
