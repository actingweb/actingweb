---
status: active
approved: 2026-11-19 by Greger Wedel
---

# Implementation Plan: What 4.0.0rc1 takes from its first consumer's read

**Date:** 2026-11-19
**Research:** thoughts/research/2026-11-19-emm-4-0-adoption-findings.md
**Branch:** `fix/4.0.0rc1-adoption-findings` (from `master` at `acfa13c`; `v4.0.0rc1` is not tagged)

## Overview

A consumer read 4.0.0rc1 before adopting it, measured its production store
against the operator commands, and reported defects, asks and two features
it will build on 4.x. Nobody runs 4.0 yet, so everything that is cheaper
before the first 4.0 process and the first 4.0 row exist goes in now: the
defects, the start-up behaviour, the defaults only a major can move, the
storage rules later features depend on, and the small MCP and OAuth
conformance items. The tag follows this plan's merge. Its changelog entries
join the existing `v4.0.0rc1` section, and an existing rc1 entry that a
change here reverses is rewritten in place, not contradicted.

## Decisions Made

By the owner on 2026-11-19. The reasons for the first group are in the
research note (sections 5 to 7 and "Owner's answers"); the second group was
decided on the evaluation's findings.

- **Scope rule**: work 4.x is known to need, and that we know how to do,
  goes in now; additive API with an open design waits.
- **Factory default (M3)**: closed where a sign-in provider is configured;
  `with_open_factory(True)` opens it.
- **`list_all_with_rows()` (A9)**: raises `DbError` on a fault.
- **Default item ceiling (M4)**: 2 MiB where a row cap exists. Raising it
  later strands nothing; lowering it later would.
- **PKCE**: required from every client of the built-in authorisation
  server, at authorise, callback and exchange;
  `with_mcp(require_pkce=False)` opts out to exactly rc1's behaviour (a
  public client is refused at authorise only; no check at callback or
  exchange), so an upgrade with the opt-out changes no sign-in (owner,
  2026-11-19, after the consumer said it will upgrade with the opt-out and
  enforce in a later change).
- **Discovery (3.5)**: `client_credentials` is removed from
  `grant_types_supported`; the grant stays for owner-created clients.
- **Operator commands (A2)**: print the store before reading; refuse to
  write on DynamoDB when `AWS_DB_PREFIX` is not set.
- **A14**: a guide line (mark before the deploy and again straight after),
  no 3.15.2.
- **Publishing**: rc1 goes to TestPyPI; the guide gives the Poetry
  second-source form.
- **Data freeze**: every shape rc1 writes is read by 4.0.0 final without an
  operator step.
- **Key-prefix scheme**: not in 4.0; its design is written between rc1 and
  4.0.0 final.
- **Design choices**: `with_mcp(require_auth_for_initialize=True)`, off by
  default; `DbErrorAfterWrite(DbError)`; envelope field `need`; three
  start-up attempts and `StoreNotReady.unavailable`.
- **Specs**: no `/create_spec` first; the capabilities without a spec start
  as `partial` specs from this plan's delta.
- **Phasing**: three phases, one PR, a commit per phase.

On the evaluation:

- **The bounded list read (V1) is cut**: its design turned out open (a
  PostgreSQL index revision, the handle contract for paging across
  requests, four wrapper layers). It is the first item after rc1.
  `DbErrorAfterWrite` stays.
- **"A provider is configured"** means any provider builder was called
  (`with_oauth`, `with_github`, `with_apple_sign_in`,
  `with_google_native`), whatever the credential values: a missing secret
  cannot open the factory.
- **Self-enable on DynamoDB needs an explicit `AWS_DB_PREFIX`**: on the
  default prefix the start refuses as today, so a wrong prefix with table
  auto-creation cannot start an empty store.
- **`AttributeListStore.list_all()` raises by default**, as
  `PropertyListStore.list_all()` does.

On the consumer's read of this plan (2026-11-19):

- **`resources/templates/list` is added; `resources/list` keeps listing
  templated resources**: nobody has seen the connectors call the templates
  method, and a client that calls only `resources/list` must lose nothing.
  The strict split is a todo.
- **rc1 stays on TestPyPI** (asked again, kept).
- **An application with its own authorise form** is told what PKCE for
  every client asks of it (AC-52), and the "no older process writes" rule
  is scoped to the self-enable of an empty store.

During implementation (2026-11-19):

- **No PKCE client gate**: the library does not collect evidence about a
  consumer's clients before requiring PKCE. The spec sets the default, the
  opt-out covers a consumer that has not checked, and the per-client check
  is the consumer's (Phase 1, finding 47 superseded).
- **A backfill collision still leaves the name unmarked** (owner,
  2026-11-19, on the consumer's second read): fail closed is kept, because a
  reverse lookup on a shared value is ambiguous. The output names every
  colliding actor and the holder, and both ways out (remove the duplicates,
  or `mark-complete --force` after review). The guide's pre-upgrade steps
  say to close the factory and remove duplicates first. A consumer whose own
  hook indexes a non-address value (such as the default creator) stops doing
  that; this goes in the Phase 3 consumer message (AC-54).
- **CI coverage on 3.14 only**: `fix/4.0.0-ci-coverage-on-3-14` (`4255054`)
  is merged into this branch and ships in this PR.

Taken without asking, as the smaller change (say if wrong):
`actingweb-mark-actors-vouched` keeps `--dry-run` and writing by default;
the write guard is defined on "any writing mode", not on `--apply`.

## What We're NOT Doing

- **The bounded list read (V1)** - cut on the evaluation (above); a todo,
  first after rc1.
- **A deferred start-up check that serves 503 while it repeats (rest of
  M2)** - a new start mode with its own failure cases; wait for the
  consumer's report of what a failed function initialisation does.
- **M5, the attribute-list conversion** - accepted on 2026-11-18; no new
  evidence.
- **A4, expiring client registrations, and CIMD** - the retention decision
  comes first; existing todo.
- **A10, A11, A12, A13** - unverified (A10), no subject in any known store
  (A11), waiting for measurements (A12), an undesigned public API (A13).
- **V2 with `require_actor`, V3, V4** - additive list features whose design
  is open; Phase 2's storage rules keep them possible in a 4.x.
- **The rest of A1, A3 and A6** - a list of IAM actions is a document
  (`check-ready` points at the deployment page's role paragraph); "no sign
  of a sign-in" has no definition; a file of creators (ids only here);
  telling peers about a cleaned actor is a protocol question.
- **Refusing a default region** - the banner prints the resolved region;
  only the default prefix is refused.
- **A list incarnation id in the meta row** - a later row kind can add one
  when it is designed; the naming rule and the report (AC-45) are what
  4.0.0 must carry.
- **The post-authentication MCP hook** - the option covers the consumer's
  need; a hook name deserves its own design.
- **A writer token on every list item** - nothing a 4.0 process appends
  would be readable after a roll-back to 3.15.1.
- **Batch receive or dropping MCP 2025-03-26, `output_schema` advertised by
  default, Unicode normalisation of names** - no client behind the first,
  the second is tied to validation work, the third migrates 3.15 names.
- **A second envelope marker value** - `need` is the extension point; a
  marker other than `1` keeps reading as a pre-4.0 user item
  (`property_list_span.py:219-224`).
- **A 3.15.2** - the guide line closes all but a seconds-wide window whose
  cost is one reconnect.
- **A redirect for the PKCE refusal** - every authorise refusal answers 400
  today (`handlers/oauth2_endpoints.py:375`); changing that is its own
  conformance item.
- **PostgreSQL mixed-version evidence** - the live pair is DynamoDB; the
  PostgreSQL rows stay "Not tested" and point at
  `rc-pass-against-real-consumers.md`, item 4.

## What Already Exists

- `maintenance/verify_property_lists.py:143-176` `_log_target` (copies in `migrate_property_lists.py:143-170`, `verify_orphans.py:329-337`) - the store banner with the unset-prefix warning. Moved to `_common.py`, the copies deleted.
- `maintenance/property_lookup.py:186-209` `_require_tables`, `:64` `StoreUnavailable`; `unique_creators.py:408-413` - "a wrong prefix is not an empty store", exit status 2. Reused.
- `db/dynamodb/property_lookup.py:113-139` `read_readiness`; `db/dynamodb/_backfill_probe.py:26` `creators_backfill_state`; `db/postgresql/actor.py:38` `creator_index_state` - read-only gate probes. `check-ready` is built on them.
- `interface/app.py:1645-1648, 1699` - the pre-warm already creates the creators table when auto-creation is on.
- `interface/app.py:130-132, 275-276` - `_open_factory` is already tri-state on the builder; only `Config` and the handler default open.
- `tests/integration/test_harness.py:86`, `examples/demo/application.py:70` - both set the factory explicitly, so the default's blast radius on the suite is nil.
- `oauth2.py:1846` `is_vouched_store`, `:1880` `classify_store`, `:1808-1811` (the `store.loaded` rule) - the marker rules `is_vouched()` wraps.
- `oauth2.py:3180-3182` - an adoption log line exists; it becomes the documented one.
- `constants.py:309` `ERROR_CODE_HEADER`; `handlers/oauth2_spa.py:2051-2065` `_json_error` - the header-plus-`code` shape for AC-6.
- `handlers/mcp.py:656` `mcp_www_authenticate`, `:1057-1071` - the challenge and the token-store 503 for `initialize`.
- `mcp/uri.py:15` `match_uri_template` - what a template is, for the split.
- `list_core.py:1096` `_parse_head` - the single mapping point from envelope errors to list errors.
- `tests/_adoption_helpers.py` (`seam_fault`, `backend_fault`), `tests/_attribute_parity.py:198` (both list kinds) - fault injection and parity fixtures for the new tests.

## Acceptance Criteria

Phase 1

- **AC-1** — When `actingweb-property-lookup report --properties a,b` runs,
  its verdict, exit status and fix line (which echoes `--properties a,b`)
  are about exactly those names, and the header says where the name set
  came from (the flag, `INDEXED_PROPERTIES`, or the library default); with
  no flag and the library default it prints the hint to pass the
  application's names.
- **AC-2** — When `actingweb-mark-actors-vouched` runs, no `_actingweb_*`
  actor is marked, and the summary counts them as `system`.
- **AC-3** — When the marking runs with `--dry-run`, each actor it would
  mark is printed (stdout, not the logger) with its current marker, and
  with its creator and stored email when `--show-addresses` is given.
- **AC-4** — When `--ids-file` is given (one actor id per line), only the
  listed ids are considered and an id not in the store is counted as
  `missing`; an unreadable file is a usage error before any read.
- **AC-5** — When `creator-to-email` passes an actor that is not vouched
  for its creator, the summary's `unvouched` count includes it, and a
  non-zero count prints that the marking comes first.
- **AC-6** — When `/oauth/logout` answers 503 for a revocation that hit a
  store fault, the response carries `X-ActingWeb-Error` and a `code` key
  with the same value, on Flask and FastAPI.
- **AC-7** — When the store faults under `ActorInterface.get_by_id` or
  `get_by_creator`, `DbError` is raised (not `None`), and their docstrings
  and `get_deletion_status`'s say so.
- **AC-8** — When the store faults under `PropertyListStore.exists()`,
  `DbError` is raised.
- **AC-9** — When any operator command starts, it prints (stdout) the
  backend and, on DynamoDB, the table prefix, endpoint and resolved
  region; on PostgreSQL, the host, database, schema and prefix; before its
  first read.
- **AC-10** — When a command is run in any writing mode (`--apply`,
  `--migrate`, `--repair`, `--downgrade`, the marking without `--dry-run`)
  on DynamoDB and `AWS_DB_PREFIX` is unset or empty, it refuses with exit
  status 2, names the resolved prefix and the fix, and writes nothing;
  dry runs and PostgreSQL are not refused.
- **AC-12** — When a sign-in cleans or replaces an actor, exactly one
  WARNING line `ACTOR_ADOPTED: actor=<id> mode=<cleaned|replaced>
  previous_auth_method=<marker> previous_actor=<id|->` is logged, with no
  creator or email, including for an adoption announced later.
- **AC-30** — When `with_mcp(require_auth_for_initialize=True)` is set, an
  unauthenticated `initialize` answers 401 with the `WWW-Authenticate`
  challenge, and a token-store fault answers 503, on both MCP handlers.
- **AC-31** — When the option is not set, `initialize` behaves as before.
- **AC-32** — When `/.well-known/openid-configuration` is requested, it
  serves the same document as `oauth-authorization-server`, on Flask and
  FastAPI.
- **AC-33** — When `resources/templates/list` is called, it returns the
  resources declared with a URI template (as `uriTemplate`), filtered by
  the same permissions as `resources/list`, whose own answer is unchanged.
- **AC-34** — When a trust row already has a client name that an
  authenticated request set, a later request with another name does not
  change it and causes no trust write for the name.
- **AC-35** — When a Flask application's browser requests
  `GET /oauth/spa/session/<id>`, it gets what FastAPI serves at that
  route.
- **AC-36** — When the authorisation-server document is read,
  `grant_types_supported` does not list `client_credentials`; an
  owner-created client still obtains a token with that grant.
- **AC-37** — When an authorisation request carries no `code_challenge`,
  it is refused with 400 `invalid_request` whatever the client's
  authentication method.
- **AC-38** — When `with_mcp(require_pkce=False)` is set, sign-in behaves
  as in rc1 before this plan: an authorisation request without a challenge
  is accepted from a confidential client and refused from a public one, and
  a code or callback state without a challenge is accepted for any client
  (a challenge that was sent is still checked).
- **AC-40** — When `actingweb-mark-actors-vouched` runs against a store a
  3.15.1 process is serving requests on, the 3.15.1 side keeps answering
  and every actor it creates or signs in during the run is readable by
  both versions afterwards; the guide's table says what was seen.
- **AC-41** — When `actingweb-property-lookup backfill --apply` runs
  against such a store, likewise, and a reverse lookup of a value written
  by 3.15.1 during the run finds its actor after the run.
- **AC-49** (added in plan: PKCE was enforced only at authorise) — When a
  code that carries no challenge reaches the callback or the token
  exchange, it is refused, unless the opt-out is on.

- **AC-52** (added in plan: the consumer's own authorise form) — When the
  authorise form is posted without a `code_challenge`, the 400 is logged
  with a WARNING saying the form posted none and naming the two hidden
  fields a custom `aw-oauth-authorization-form.html` must carry.

- **AC-53** (added in implementation: the consumer's second read) — When
  `actingweb-property-lookup backfill` runs on PostgreSQL, its summary's
  `scanned` and `matches` count the rows of the names it covered and those
  of live actors, not 0.
- **AC-54** (added in implementation: the consumer's second read) — When
  backfill leaves a name unmarked for a collision, its output (stdout)
  names each colliding actor and the actor holding the lookup row, and the
  two ways out; the name stays unmarked.

Phase 2

- **AC-11** — When `actingweb-check-ready` runs (with `--properties`,
  `--no-unique-creator`, `--email-as-creator` for what the application
  sets in code), it prints the configuration it assumed and each gate as
  ready, ready at first start (empty store), or refused with its fix line;
  it writes nothing and creates no table; exit status 1 if any gate
  refuses, 2 if the store could not be read.
- **AC-13** — When an application with creator uniqueness on starts on a
  DynamoDB store with no user actors and `AWS_DB_PREFIX` set, it records
  the creators backfill itself and starts.
- **AC-14** — When it starts on a PostgreSQL store with no user actors, it
  creates the unique index and starts; when its role may not, or the build
  fails or times out, it refuses with the message naming
  `actingweb-unique-creators enable --apply`.
- **AC-15** — When the store holds a user actor and no enforcement, the
  start is refused as before.
- **AC-16** — When a start-up check faults, it is tried three times in all
  before the start is refused; a check that answers on a later attempt
  lets the application start; a "not ready" answer is not retried.
- **AC-17** — When a start is refused because the store did not answer,
  the raised `StoreNotReady` has `unavailable` true; when the store
  answered "not ready" (a missing table and a denied permission included),
  false; a combined refusal is `unavailable` only if every part is.
- **AC-18** — When a provider builder was called and `with_open_factory`
  was not, `POST /` answers 403 (naming `with_open_factory(True)`),
  whatever order the builder calls came in, and one start-up WARNING
  states that the factory is closed and how to open it.
- **AC-19** — When no provider builder was called, or
  `with_open_factory(True)` was, `POST /` creates an actor as before.
- **AC-20** — When `ActorInterface.is_vouched()` is called, it answers
  whether a provider, the operator or the application vouched for the
  actor's current creator, and raises `DbError` when the marker could not
  be read.
- **AC-21** — When the store faults under `list_all_with_rows()`, on a
  property or an attribute list store, `DbError` is raised.
- **AC-22** — When a property or list write is stored and the fault comes
  after it (registering its diff), the exception is `DbErrorAfterWrite`;
  when the fault comes before the write, it is a plain `DbError`.
- ~~**AC-23**~~ — dropped: the bounded read is cut (Decisions Made).
- ~~**AC-24**~~ — dropped: as AC-23.
- **AC-25** — When a stored envelope's `need` names a feature the process
  does not implement, reading the item raises `ListItemNewerFormatError`
  (not a `ListCorruptionError`), whose remedy says to upgrade and not to
  repair; over HTTP it answers 409 with a fixed `code` and no stored text.
- **AC-26** — When such an item is the target of `update_by_handle`,
  `delete_by_handle`, a positional write, or is in a list being compacted,
  the same error is raised before any row is written or removed.
- **AC-27** — When the sweep or `actingweb-verify-property-lists --repair`
  meets such a head, it reports it on a line of its own, removes neither
  it nor any side row of that list, and returns instead of raising.
- **AC-28** — When a list is swept, cleared or deleted, side-partition
  rows under its prefix whose name the process does not recognise are left
  in place; a list holding a newer-format head can still be deleted whole.
- **AC-29** — When no ceiling is configured on a backend with a row cap,
  an item over 2 MiB encoded is refused.
- **AC-43** (added in plan: the outside voice found the list-level format
  unguarded) — When a list's meta row carries a `format` other than 1 or
  2, reading, writing, clearing, migrating or sweeping it raises
  `ListItemNewerFormatError` and removes or rewrites nothing.
- **AC-44** (added in plan: owner's decision on the evaluation) — When the
  store faults under `AttributeListStore.list_all()`, `DbError` is raised.
- **AC-45** (added in plan: rows AC-28 leaves need a report) — When
  `actingweb-verify-property-lists` meets side-partition rows named for a
  list that has no meta row, it reports them and removes nothing.
- **AC-46** (added in plan: the closed factory also closes trustee
  creation) — When a peer's factory answers 403 to a trustee creation, the
  calling side logs a WARNING naming the factory and the status.
- **AC-47** (added in plan: the default page would offer a form that
  answers 403) — When the factory is closed, the default `GET /` page does
  not render the creation form.
- **AC-48** (added in plan: owner's decision on the evaluation) — When the
  store is empty on DynamoDB and `AWS_DB_PREFIX` is unset or empty, the
  start is refused as before, naming the prefix and the command.
- **AC-50** (added in plan: the empty verdict was not re-checked) — When a
  user actor appears between the empty verdict and the backfill marker,
  the actor gets its creator record or the start is refused; it is never
  left unrecorded behind a complete marker.
- **AC-51** (added in plan: owner's decision on the evaluation) — When
  `with_mcp()` is called again without naming an option, the options set
  earlier keep their values.

Phase 3

- **AC-39** — When the documentation is built with `-W`, it passes, the
  guide carries each item of Phase 3's list, and no document or docstring
  still states a default this plan reversed.
- **AC-42** — When the plan closes, each deferred ask is a todo with an
  `INDEX.md` row and `thoughts/inbound/` holds only its README.

## Traceability

| AC | Phase | Test | Status |
| --- | --- | --- | --- |
| AC-1 | 1 | `tests/test_property_lookup_command.py::test_report_verdict_follows_the_passed_names` (`INDEXED_PROPERTIES` differing from the flag; replaces the test at `:203`), `::test_report_names_the_source_and_echoes_the_flag`, `::test_default_names_print_the_hint` | Passing |
| AC-2 | 1 | `tests/test_mark_actors_vouched.py::test_system_actors_are_never_marked` (an `_actingweb_*` id in an `--ids-file` scope) | Passing |
| AC-3 | 1 | `tests/test_mark_actors_vouched.py::test_dry_run_prints_marker_and_hides_addresses`, `::test_show_addresses_prints_creator_and_email` | Passing |
| AC-4 | 1 | `tests/test_mark_actors_vouched.py::test_ids_file_limits_the_run`, `::test_a_listed_id_not_in_the_store_is_counted_missing`, `::test_unreadable_ids_file_is_a_usage_error` | Passing |
| AC-5 | 1 | `tests/integration/test_email_as_creator_sweep.py::test_sweep_counts_unvouched` (both backends); `tests/test_unique_creators_command.py::test_creator_to_email_summary_names_the_order` | Passing |
| AC-6 | 1 | `tests/test_oauth2_logout_mcp_tokens.py`: the three existing 503 tests (handler `:75`, FastAPI `:186`, Flask `:195`) extended to assert the exact header and `code` | Passing |
| AC-7 | 1 | `tests/test_db_fault_callers.py::TestActorInterfaceLookups::test_get_by_id_raises_on_a_fault`, `::test_get_by_creator_raises_on_a_fault` (through `seam_fault`) | Passing |
| AC-8 | 1 | `tests/test_db_fault_callers.py::TestListStoreLookups::test_exists_raises_on_a_fault` | Passing |
| AC-9 | 1 | `tests/test_operator_command_store.py::test_every_command_prints_the_store_first` (parametrised from `pyproject.toml`'s scripts, both backends, `capsys`) | Passing |
| AC-10 | 1 | `tests/test_operator_command_store.py::test_writing_without_a_prefix_is_refused` (parametrised over every writing mode, `delenv`), `::test_an_empty_prefix_is_unset`, `::test_dry_runs_are_not_refused`, `::test_postgresql_is_not_refused` | Passing |
| AC-11 | 2 | `tests/test_check_ready_command.py::test_each_gate_is_reported_with_its_fix`, `::test_assumed_configuration_is_printed`, `::test_email_gate_needs_its_flag`, `::test_an_empty_store_is_ready_at_first_start`, `::test_it_writes_nothing_and_creates_no_table`, `::test_a_store_fault_is_exit_2`; `tests/integration/test_check_ready_command.py::test_fresh_and_populated_store` (both backends) | Passing |
| AC-12 | 1 | `tests/test_adoption_log_line.py::test_one_line_per_adoption` (parametrised: cleaned, replaced, announced later), `::test_the_line_carries_no_address` | Passing |
| AC-13 | 2 | `tests/integration/test_unique_creator_empty_store.py::test_dynamodb_empty_store_starts` (real probes, `unique_creator` xdist group) | Passing |
| AC-14 | 2 | `tests/integration/test_unique_creator_empty_store.py::test_postgresql_empty_store_starts`, `::test_postgresql_without_ddl_refuses_with_the_command`, `::test_two_first_starts_at_once_both_start`; `tests/test_unique_creator_default.py::test_a_failed_index_build_refuses` | Passing |
| AC-15 | 2 | `tests/test_unique_creator_default.py::test_a_store_with_a_user_actor_still_refuses` | Passing |
| AC-16 | 2 | `tests/test_startup_check_retry.py::test_a_faulting_check_is_tried_three_times`, `::test_a_check_that_recovers_lets_the_app_start`, `::test_a_not_ready_answer_is_not_retried` (sleep patched) | Passing |
| AC-17 | 2 | `tests/test_startup_check_retry.py::test_unavailable_is_true_only_for_a_fault`, `::test_a_missing_table_is_not_unavailable`, `::test_a_fault_while_counting_actors_is_unavailable`, `::test_the_combined_refusal` | Passing |
| AC-18 | 2 | `tests/test_factory_open_switch.py::test_closed_by_default_with_a_provider`, `::test_with_oauth_after_get_config_still_closes`, `::test_an_empty_client_id_still_closes`, `::test_apple_only_closes`, `::test_the_closed_default_is_warned_once`; `tests/integration/test_factory_default.py::test_post_root_is_403_with_oauth_and_no_switch` | Passing |
| AC-19 | 2 | `tests/test_factory_open_switch.py::test_open_without_a_provider`, `::test_explicit_open_wins`, `::test_a_bare_config_is_open` | Passing |
| AC-20 | 2 | `tests/test_is_vouched_public.py::test_vouched_and_unvouched_markers`, `::test_a_renamed_creator_is_unvouched`, `::test_a_marker_without_a_bound_address`, `::test_an_unread_marker_raises` (through `backend_fault`) | Passing |
| AC-21 | 2 | `tests/test_list_prefix_with_rows.py::test_list_all_with_rows_raises_on_a_fault` (replaces `:256`; both stores) | Passing |
| AC-22 | 2 | `tests/test_db_error_after_write.py::test_a_diff_fault_after_a_property_write`, `::test_a_diff_fault_after_a_list_write`, `::test_clear_faults_before_its_write_is_plain`, `::test_handler_paths_that_fold_keep_folding`, `::test_the_wire_answer_has_its_own_code_and_no_retry_after`, `::test_append_once_repeat_does_not_duplicate` | Passing |
| AC-25 | 2 | `tests/test_property_list_span_codec.py::test_need_is_checked_before_the_shape`, `::test_a_malformed_need_is_malformed`; `tests/test_property_list_newer_format.py::test_reading_raises_and_is_not_corruption`, `::test_http_answers_409_with_a_fixed_code` (both list kinds) | Passing |
| AC-26 | 2 | `tests/test_property_list_newer_format.py::test_writes_by_handle_and_position_change_nothing`, `::test_compact_stops_before_its_first_write` | Passing |
| AC-27 | 2 | `tests/test_property_list_newer_format.py::test_sweep_and_repair_keep_the_head_and_every_side_row` | Passing |
| AC-28 | 2 | `tests/test_property_list_spans.py::test_unrecognised_side_row_names_survive_sweep_clear_and_delete`, `tests/test_property_list_newer_format.py::test_the_whole_list_can_be_deleted` | Passing |
| AC-29 | 2 | `tests/test_list_item_limits.py::test_default_ceiling_is_2_mib_with_a_row_cap` (replaces `:95`); `tests/test_actingweb_app.py` `:755`, `:784` updated | Passing |
| AC-30 | 1 | `tests/test_mcp_auth_challenge.py::test_initialize_is_challenged_when_required`, `::test_an_authenticated_initialize_passes`, `::test_a_token_store_fault_is_503` (each over `post` and `post_async`) | Passing |
| AC-31 | 1 | `tests/test_mcp_auth_challenge.py::test_initialize_is_open_by_default` (both handlers) | Passing |
| AC-32 | 1 | `tests/integration/test_oauth2_flows.py::test_openid_configuration_serves_the_server_document` (FastAPI); `tests/test_flask_well_known.py::test_openid_configuration` (parametrised: Flask and FastAPI) | Passing |
| AC-33 | 1 | `tests/test_mcp_resource_templates.py::test_templates_are_listed_with_uri_template`, `::test_resources_list_is_unchanged`, `::test_a_denied_template_is_left_out`, `::test_no_trust_row_is_an_empty_list` (both handlers); `tests/integration/test_mcp_resources.py:236` made unconditional | Passing |
| AC-34 | 1 | `tests/test_mcp_client_info_cache.py::test_a_second_name_does_not_replace_the_first`, `::test_repeated_requests_from_the_second_client_write_nothing`, `::test_the_placeholder_is_not_a_first_name`, `::test_an_unauthenticated_seed_is_not_a_first_name` | Passing |
| AC-35 | 1 | `tests/test_spa_session_retrieve.py`: `env` parametrised over FastAPI and Flask, the seven existing tests run on both | Passing |
| AC-36 | 1 | `tests/test_oauth2_public_clients.py::test_discovery_does_not_offer_client_credentials`, `::test_an_owner_created_client_still_uses_the_grant` | Passing |
| AC-37 | 1 | `tests/test_oauth2_pkce_binding.py::test_a_confidential_client_without_a_challenge_gets_400`; `tests/integration/test_oauth2_flows.py:310` updated | Passing |
| AC-38 | 1 | `tests/test_oauth2_pkce_binding.py::test_the_opt_out_restores_the_confidential_exception`, `::test_the_opt_out_keeps_binding_a_challenge_that_is_sent`, `::test_the_opt_out_accepts_a_public_clients_code_without_a_challenge` | Passing |
| AC-39 | 3 | the Full tier's docs build; manual: read each guide item against Phase 3's list, and the sweep greps of Phase 3's Verification return only intended hits (prose has no assertion) | Not run |
| AC-40 | 1 | manual: `scripts/live_pair.py --same-store` with the marking run (two library versions in one run are outside the suite) | Passing (manual, 2026-11-19: see the Phase 1 notes) |
| AC-41 | 1 | manual: the same with `backfill --apply` | Passing (manual, 2026-11-19: see the Phase 1 notes) |
| AC-42 | 3 | manual: `ls thoughts/inbound thoughts/todo` against `INDEX.md` | Not run |
| AC-43 | 2 | `tests/test_property_list_newer_format.py::test_an_unknown_list_format_is_refused_everywhere` (read, append, clear, lazy migration, sweep), `tests/test_migrate_property_lists.py::test_the_command_skips_and_reports_an_unknown_format` | Passing |
| AC-44 | 2 | `tests/test_attribute_list_store.py::test_list_all_raises_on_a_fault` | Passing |
| AC-45 | 2 | `tests/test_verify_property_lists.py::test_side_rows_of_a_list_without_meta_are_reported_not_removed` | Passing |
| AC-46 | 2 | `tests/test_actor_peer_creation.py::test_a_closed_factory_is_warned` | Passing |
| AC-47 | 2 | `tests/test_factory_open_switch.py::test_the_default_page_hides_the_form_when_closed` (both integrations) | Passing |
| AC-48 | 2 | `tests/test_unique_creator_default.py::test_the_default_prefix_does_not_self_enable` | Passing |
| AC-49 | 1 | `tests/test_oauth2_pkce_binding.py::test_the_callback_refuses_a_state_without_a_challenge`, `::test_the_exchange_refuses_a_code_without_a_challenge`, `::test_a_directly_created_code_follows_the_rule` | Passing |
| AC-50 | 2 | `tests/integration/test_unique_creator_empty_store.py::test_an_actor_created_during_the_enable_is_recorded` | Passing |
| AC-51 | 1 | `tests/test_actingweb_app.py::test_a_second_with_mcp_keeps_earlier_options` | Passing |
| AC-53 | 1 | `tests/test_property_lookup_command.py::TestBackfill::test_the_summary_counts_what_it_read` (both backends) | Passing |
| AC-54 | 1 | `tests/test_property_lookup_command.py::TestBackfill::test_a_collision_names_the_actors_and_the_ways_out` (both backends) | Passing |
| AC-52 | 1 | `tests/test_oauth2_pkce_binding.py::test_a_form_post_without_a_challenge_warns_about_the_form`, `::test_the_default_form_carries_the_challenge_back` | Passing |

## Spec Delta

### `thoughts/specs/operator-commands.md` (new spec, partial)

- **ADDED** (Common) — When any operator command starts, it prints the store it will read before its first read. (AC-9)
- **ADDED** (Common) — When a command would write on DynamoDB with `AWS_DB_PREFIX` unset or empty, it refuses with exit status 2. (AC-10)
- **ADDED** (Reverse lookup) — When `report` is given `--properties`, its verdict and fix line are about those names and it says where the set came from. (AC-1)
- **ADDED** (Vouching) — When the marking runs, system actors are never marked; a dry run shows the marker and, on request, the addresses; `--ids-file` limits it. (AC-2, AC-3, AC-4)
- **ADDED** (Email as creator) — When the sweep passes an unvouched actor, it counts it and says the marking comes first. (AC-5)
- **ADDED** (Readiness) — When `actingweb-check-ready` runs, it reports each gate in one of three states with its fix line, writes nothing, and exits 0, 1 or 2. (AC-11)
- **ADDED** (List verification) — When side rows are named for a list with no meta row, they are reported and kept. (AC-45)
- **DECISION** — An operator command never treats a missing table or the default prefix as an empty store.
- **DECISION** — A command cannot see what an application sets in its builder; each such setting has a flag, and the command prints what it assumed.

### `thoughts/specs/startup-readiness.md` (new spec, partial)

- **ADDED** (Creator uniqueness) — When the store has no user actors, the application enables enforcement itself (on DynamoDB only with an explicit prefix); with user actors and no enforcement it refuses. (AC-13, AC-14, AC-15, AC-48, AC-50)
- **ADDED** (Faults) — When a check faults, it is tried three times; a refusal for a fault has `unavailable` true. (AC-16, AC-17)
- **DECISION** — A start is still refused when the store does not answer after the retries; `unavailable` is not permission to serve.
- **DECISION** — While an empty store enables itself, no older process may create actors in it; the second scan catches one that does. A start on a store that already enforces has no such rule.

### `thoughts/specs/actor-creation.md` (new spec, partial)

- **ADDED** (Factory) — When a provider builder was called and the application did not call `with_open_factory`, `POST /` answers 403 and the default page offers no form; otherwise it creates an actor. (AC-18, AC-19, AC-47)
- **ADDED** (Factory) — When a peer's factory refuses a trustee creation, the caller logs a WARNING. (AC-46)
- **ADDED** (Vouching) — When `is_vouched()` is called, it answers for the actor's current creator and raises when the marker could not be read. (AC-20)
- **ADDED** (Adoption) — When a sign-in cleans or replaces an actor, one `ACTOR_ADOPTED:` line records it. (AC-12)
- **ADDED** (Faults) — When the store faults under `get_by_id` or `get_by_creator`, `DbError` is raised. (AC-7)
- **DECISION** — A marker being present does not mean vouched; `is_vouched()` is the test. A marker with no bound address is vouched for any creator (written before the address was recorded).

### `thoughts/specs/property-lists.md` (new spec, partial; covers attribute lists)

- **ADDED** (Faults) — When the store faults under `exists()`, `list_all()` or `list_all_with_rows()`, on either store, `DbError` is raised. (AC-8, AC-21, AC-44)
- **ADDED** (Faults) — When a write is stored and a later step faults, the exception is `DbErrorAfterWrite`: the value is stored, its diff is not registered. (AC-22)
- **ADDED** (Stored format) — When an envelope's `need`, or a list's `format`, names something the process does not implement, the item or list cannot be read, written or repaired by it, and nothing of it is removed except by deleting the whole list. (AC-25, AC-26, AC-27, AC-43)
- **ADDED** (Stored format) — When a list is swept, cleared or deleted, side rows with an unrecognised name are left. (AC-28)
- **ADDED** (Limits) — When no ceiling is configured on a backend with a row cap, the ceiling is 2 MiB. (AC-29)
- **DECISION** — Every stored shape 4.0.0rc1 writes is read by 4.0.0 final without an operator step.
- **DECISION** — A later 4.x that changes how an item is stored names the change in `need`; one that changes a list's layout raises its `format`. Neither reuses a field 4.0.0 ignores for something a writer must maintain.
- **DECISION** — A later side-row kind is named `list:{name}-$<kind>-...`, so that it is reaped with the actor and reported when its list is gone.

### `thoughts/specs/mcp-server.md`

- **ADDED** (Transport and tool listing) — When `require_auth_for_initialize` is on, an unauthenticated `initialize` is challenged with 401; off, it is answered. (AC-30, AC-31)
- **ADDED** (Capabilities) — When `resources/templates/list` is called, it returns the templated resources under the permissions `resources/list` applies; `resources/list` still lists them too. (AC-33)
- **DECISION** — Templated resources stay in `resources/list` until the connectors are seen calling `resources/templates/list`.
- **ADDED** (Capabilities) — When a trust row has a client name from an authenticated request, a later name does not replace it. (AC-34)
- **ADDED** (Discovery) — When `/.well-known/openid-configuration` is requested, the authorisation-server document is served. (AC-32)
- **DECISION** — Calling `with_mcp()` again changes only the options it names. (AC-51)

### `thoughts/specs/oauth-client-registration.md`

- **ADDED** (Authorising) — When an authorisation request, a callback state or a code has no `code_challenge`, it is refused for every client unless `require_pkce=False`, which restores rc1's behaviour: a public client is refused at authorise only, and the callback and exchange accept a code without a challenge. (AC-37, AC-38, AC-49)
- **DECISION** — `require_pkce=False` means the rc1 behaviour exactly, so an application can upgrade with it and change no sign-in, then enforce in a later change.
- **ADDED** (Authorising) — When the authorise form is posted without the challenge it was shown with, the refusal is logged with what a custom form must carry. (AC-52)
- **DECISION** — The challenge travels through the authorise form's hidden fields; an application's own form, and any code it creates itself with `create_authorization_code`, must pass it on.
- **ADDED** (Discovery) — When the server document is read, `client_credentials` is not offered; an owner-created client can still use it. (AC-36)

### `thoughts/specs/web-ui.md`

- **ADDED** (SPA sign-in) — When a browser requests `GET /oauth/spa/session/<id>`, both integrations serve the pending session. (AC-35)
- **ADDED** (Logout) — When `/oauth/logout` answers 503 for a fault, it carries `X-ActingWeb-Error` and `code`. (AC-6)

## Phase 1: Commands, small defects, MCP and OAuth

~~First task, before any code: evidence for every client name with
registrations in the consumer's production store.~~ Dropped (owner,
2026-11-19: a library cannot enumerate the clients in the wild). PKCE from
every client is what MCP's authorisation rules and OAuth 2.1 require, and
`with_mcp(require_pkce=False)` restores rc1 exactly. An application that
has not checked its clients upgrades with the opt-out. Checking which
clients send a challenge is the application's step before it removes the
opt-out (Phase 3 guide line; the per-client check goes to the consumer in
Phase 3's message).

### Changes

- `actingweb/maintenance/_common.py` (new) - `_log_target` moved here from its three copies, printing (not logging) the AC-9 fields from the environment and `Model.Meta` only (no `DescribeTable`); the write guard, called by every `main` before it parses a subcommand, with a per-command "is this a writing mode" predicate. `main()` of `migrate_property_lists`, `verify_orphans` and `verify_property_lists` gain an `argv` parameter.
- `actingweb/maintenance/property_lookup.py` - `report`: verdict, fix line and the "every name is marked" line follow the passed names; the source of the set; the hint from `interface/app.py:1765-1767` when the library default is used; a note when the flag differs from `INDEXED_PROPERTIES`.
- `actingweb/maintenance/mark_actors_vouched.py` - skip and count `_actingweb_*`; dry-run detail on stdout, addresses behind `--show-addresses` (the flag `unique_creators.py:1267` has); `--ids-file`, combinable with `--start-after`, exclusive with `--creator`.
- `actingweb/maintenance/email_as_creator.py`, `unique_creators.py` - the `unvouched` count and the order hint in `creator-to-email`'s summary.
- `actingweb/handlers/oauth2_endpoints.py` - the logout 503 through the `ERROR_CODE_HEADER` shape; the `.well-known/openid-configuration` branch beside `:191`.
- `actingweb/interface/actor_interface.py` - docstrings of `get_by_id`, `get_by_creator`, and the stale sentence at `:206-207`.
- `actingweb/oauth2.py` - the line at `:3180` becomes `ACTOR_ADOPTED: ...` at WARNING, emitted from one helper that both fire sites (`:2696`, `:3198`) and the deferred announcement (`:2722`) call.
- `actingweb/interface/app.py`, `actingweb/config.py` - `with_mcp(*, require_auth_for_initialize=, require_pkce=)` and the three existing options through an unset sentinel (the pattern at `:668-673`), carried at `:233-235`, `:1570-1572` and `config.py:455-457`.
- `actingweb/handlers/mcp.py`, `actingweb/handlers/async_mcp.py` - the `initialize` check at the top of `_handle_initialize`, before the client-info cache write, using the `:1056-1071` sequence (no actor: 401; token store down: 503) and reusing the actor for the client-info block; `resources/templates/list` routed after authentication in both dispatchers; one filtered enumeration shared with `resources/list`, whose answer does not change; a resource is templated when its declared `uri_template` contains a `{...}` expression, a regex-declared resource is in `resources/list` only; `_update_trust_with_client_info` computes the effective name (`existing or incoming`) before its skip test, never treats `"MCP Client"`, an empty name or an entry cached by an unauthenticated `initialize` as a first name, and leaves version and platform as today.
- `actingweb/oauth2_server/oauth2_server.py`, `token_manager.py` - one helper reads `require_pkce`, used at authorise (`:242`), at the callback (`:438`), at code creation (`:1129`) and at exchange (`token_manager.py:306`, `oauth2_server.py:661`); the refusal text no longer says "public clients"; a server-side WARNING names the client id and the opt-out, and on a form POST says the form posted no challenge and names the hidden fields (`templates/aw-oauth-authorization-form.html:15-16`); `client_credentials` out of `grant_types_supported`.
- `actingweb/handlers/oauth2_spa.py`, `interface/integrations/fastapi_integration.py`, `flask_integration.py` - the body of FastAPI's `_handle_spa_session_retrieve` (`:2472`) extracted into the handler module, called by both integrations; `/.well-known/openid-configuration` on both; the comments saying `initialize` is unauthenticated (`flask_integration.py:336-340`, `fastapi_integration.py:981-985`).
- `scripts/live_pair.py` - a `--same-store` mode: the 3.15.1 side serves on one prefix under a small request loop (create an actor, sign in, write an indexed property) while a 4.0 command runs against that prefix.
- `CHANGELOG.rst` (`v4.0.0rc1`) - entries; **Behavior change** for PKCE, discovery, the write guard and the marking skip.
- `docs/quickstart/deployment.rst` ("Operator commands", `:226-286`), `docs/migration/v4.0.rst` ("Reading the output", `:1791-1848`, which also gains `email_reset` and `email_differs`), `docs/guides/spa-authentication.rst`, `docs/reference/hooks-reference.rst` (the line beside `actor_adopted`), `docs/guides/oauth2-setup.rst` (`:170-176`: PKCE is for every client).

### New Tests (written first)

The Phase 1 rows of the Traceability table. Existing tests rewritten, not
deleted: `test_property_lookup_command.py:203`,
`integration/test_oauth2_flows.py:310`,
`integration/test_mcp_resources.py:236`.

### Failure Scenarios

- Write guard - an operator's shell has no prefix and the default names a real store - refused with exit 2 before any read; `test_writing_without_a_prefix_is_refused`.
- Banner - production `LOG_LEVEL=WARNING` hides a logged banner - it is printed; the AC-9 test uses `capsys`.
- `initialize` with the option on - the token store is down - 503, not an answered `initialize`; `test_a_token_store_fault_is_503`.
- PKCE - a state minted before the deploy, or by a process with the opt-out, reaches a process without it - refused at callback and exchange; AC-49's tests.
- Keep-first name - an unauthenticated `initialize` seeds a session id with a name before the real client - not a first name; `test_an_unauthenticated_seed_is_not_a_first_name`.
- Templates list - the permission evaluator is down - same answer as `resources/list` gives today (the documented fail-open listing); covered by sharing the enumeration.
- PKCE - an application's own authorise form drops the hidden challenge fields, so every sign-in through it answers 400 - the WARNING names the form (AC-52); the guide says what the form and a self-made code must carry, and that `require_pkce=False` is the way to upgrade first and fix the form after.
- Live pair - the 4.0 command makes a 3.15.1 request fail - that is the failing outcome of AC-40/41; the code is fixed in this phase, before its commit.

### Verification

- [x] Run the contract's `### Checks` fast tier verbatim
- [x] Full tier, both backends, before the phase's commit (2026-11-19: DynamoDB 8263 passed, PostgreSQL 8035 passed, 0 failed; docs `-W` clean)
- [x] `poetry run python tests/integration/verify_groups.py` (no new group)
- [x] `scripts/live_pair.py same-store`: the marking, then `backfill --apply`, on DynamoDB; outcomes noted above for Phase 3's table

### Implementation Notes

- AC-7, AC-8: the tests passed before any change, on both backends: the
  backends already raise `DbError` through `get_by_id`, `get_by_creator`
  and `PropertyListStore.exists()`. The tests stay as regression guards;
  the change is the docstrings (and `get_deletion_status`'s, which answers
  `UNKNOWN` instead).
- AC-2/AC-4: `test_unreadable_ids_file_is_a_usage_error` and
  `test_ids_file_and_creator_are_exclusive` passed before the change for
  the wrong reason (argparse refused the unknown flag); they pass for the
  right one now.
- AC-9/AC-10: the guard covers all eight commands, including
  `actingweb-deletions` and `actingweb-peer-state`, which the plan did not
  name. `verify_orphans`, `verify_property_lists` and
  `migrate_property_lists` gained an `argv` parameter. The test stops at
  PynamoDB's and botocore's API call and at psycopg's connect and pool,
  because several modules import `get_connection` by name.
- AC-12: the line also carries `provider=` and, at the main site, the
  counts; an announced-later line carries `announced_later=true`.
- AC-37/AC-49 broke 85 unit tests that mint a code directly with
  `create_authorization_code` and exchange it without a verifier (token
  store, rotation, single use, logout, session generation). They are not
  about PKCE: each such call now carries `tests.mcp_token_double.PKCE_VERIFIER`
  as a `plain` challenge and its exchange sends it, instead of turning
  the opt-out on in a shared helper and hiding the rule from every test.
- AC-33: `_permitted_resources()` is the one enumeration both list
  methods use; the plan's failure scenario said "fail-open", but the
  listing has been fail-closed since 4.0, and the templates list inherits
  that.
- AC-34: the unauthenticated-seed case was already safe (the session cache
  never reaches a trust write); its test is a guard.
- AC-6's `code` key changed one exact-body assertion in
  `tests/test_oauth2_spa_logout_revokes_chain.py`.
- AC-40/AC-41 (manual, `scripts/live_pair.py same-store`, DynamoDB Local,
  prefix `pairsame1`, `INDEXED_PROPERTIES=email`): 3.15.1 from PyPI under
  Python 3.11 serving a loop of create, authenticated read and indexed
  property write, while this tree ran the command on the same prefix.
  `actingweb-mark-actors-vouched`: exit 0 in 0.5 s, 24 actors created by
  3.15.1 across the run, 0 loop failures, every one readable by both
  versions, 0 reverse lookups missed. `actingweb-property-lookup backfill
  --apply`: exit 0 in 1.9 s (`scanned=42 matches=36 written-or-present=36`,
  marked complete), 29 actors, 0 loop failures, 0 unreadable, 0 lookups
  missed. Both rows go into Phase 3's mixed-version table; the commands are
  short, so the overlap is a few loop rounds. PostgreSQL stays "Not tested".
- `complete_client_authorization` (an application's own sign-in route)
  reached the PKCE refusal through `_complete`; it now refuses a call
  without `code_challenge` before any hook or write, says so in its
  docstring, and the guide and changelog name it beside the own form and
  `create_authorization_code`. Found by the full run
  (`tests/integration/test_oauth2_trust_binding.py`).
- For the Phase 3 consumer message: (1) its lifecycle hook writes
  `email = creator` for an actor whose creator is not an address (the
  default creator `creator`), so two such actors collide in the email
  backfill and block the start; stop indexing a non-address, close the
  factory, and remove the duplicate before upgrading. (2) Before it removes
  `with_mcp(require_pkce=False)`, check each registered client name: all
  registrations public with a sign-in since, or one recorded authorise
  request with a `code_challenge`.
- The consumer re-ran rc1 plus this branch (2026-11-19) and confirmed the
  banner, the name-set source, the unvouched count, the dry-run lines and
  the system skip. Its two new findings are AC-53 and AC-54.

### Implementation Status: Complete

---

## Phase 2: Start-up, API and storage

### Changes

**Start-up**

- `actingweb/interface/app.py` - inside each `_check_*`'s own `try`: a fault is retried (three attempts, back-off sleeps of about two seconds in all, one deadline shared by the whole of `check_ready()`; once one check ends unavailable the others get one attempt; the pre-warm at `:1699` is not repeated); the `except` branches set `unavailable`; a missing table or denied permission is "not ready"; the combined raise at `:1714` follows AC-17. `StoreNotReady` and `check_ready` docstrings.
- `actingweb/maintenance/unique_creators.py` - `no_actors` gains a raising, strongly consistent form (the folding one stays for the message choice); a dedicated application enable path, not `_enable_*`: DynamoDB - only with an explicit prefix; `ensure_table(Creator)`; consistent scan; records for the system actors; the backfill item; a second consistent scan whose user actors are recorded through `record_for_actor_as_read` or cause a refusal with the marker removed; the probe cache set after the write. PostgreSQL - a plain `CREATE UNIQUE INDEX IF NOT EXISTS` on the empty table in a transaction with short lock and statement timeouts, never a drop; any failure becomes `UniqueCreatorNotReady`; `reset_index_probe()`; `_unique_creator_checked` is set only after `missing_enforcement()` reads clean again.
- `actingweb/maintenance/check_ready.py` (new), `pyproject.toml`, `docs/requirements.txt` - `actingweb-check-ready`: the read-only probes of "What Already Exists", the raising `no_actors`, the email gate's read half without constructing a `DbAttribute`, the attribute schema probe; flags for the three builder settings; never calls `check_ready()`.

**Factory**

- `actingweb/config.py` - `open_factory` becomes a property: unset means "closed if a provider builder was called"; an assigned value wins. `actingweb/interface/app.py` records that a provider builder was called (`:353`, `:1083`, `:1095`, `:1160`, `:1228`) and logs the resolved state at WARNING when closed by default, from `integrate_*`. `actingweb/handlers/factory.py:215` reads the property (no second default), the 403 names `with_open_factory(True)`, and `template_values` carries the state; the default `aw-root-factory.html` hides the form when closed.
- `actingweb/actor.py:1923-1946` - a 403 from a peer's factory is logged at WARNING.
- `examples/demo/application.py:67-70` - call `with_open_factory` only when `OPEN_FACTORY` is set, so the demo shows the default; `examples/demo/README.md`, `tests/test_demo_example.py`.

**API**

- `actingweb/interface/actor_interface.py` - `is_vouched()`: a fresh store, `store.loaded` checked before any attribute (`DbError` when false), then `is_vouched_store`. Docstrings say the two `oauth2` functions are internal.
- `actingweb/property.py`, `actingweb/attribute_list_store.py` - `list_all_with_rows()` raises on both stores; `AttributeListStore.list_all()` raises by default, `strict=` kept as an accepted no-op keyword.
- `actingweb/db/exceptions.py` - `DbErrorAfterWrite(DbError)`, same constructor; docstring: the value is stored, the diff is not registered, a repeat of a plain set is safe, a repeat of an unkeyed append duplicates, `append_once` does not. Raised from `interface/property_store.py` (`_register_diff` at `:122-125` and `:400-403`; `_clear_snapshot`'s later `register_diffs` at `:291`, while the one at `:277` precedes the write and stays plain) and the direct `register_diffs` calls after a write in `handlers/properties.py` and `handlers/www.py`. Handler paths that fold an after-write fault today (`properties.py:499`, `:886`) keep folding; one that reaches the wire answers 503 with its own `code` and no `Retry-After` (`interface/integrations/_errors.py:113`).

**Storage**

- `actingweb/property_list_span.py` - `need`: a field of its own on `Envelope` and in `wrap()`, a list of 1 to 8 names matching `[a-z0-9_-]{1,32}` (anything else is malformed and stays removable); `IMPLEMENTED_NEEDS` (empty); checked first in `parse()`, before the "neither v nor span" error; `NewerFormatError`. `ITEM_MAX_BYTES_DEFAULT = 2 * 2**20`, with the comment and `default_limits` docstring restated (6 body rows, about half the read units).
- `actingweb/list_core.py` - `ListItemNewerFormatError(Exception)` with `remedy`; `_parse_head` maps it; each `EnvelopeError` catch site decided: re-raise as newer-format at `:1127` (`_read_head_tolerant`), `:1136`, `:1787`, `:3353`, `:3665`, `:4518` (compact's copy); treated as "not mine" at `:1057` and `:2694` (post-commit, nothing to undo); collected and reported at `:4034`, `:4068`. `delete_by_handle` parses before `:3623`; `compact` parses every head before its first write; `_v2_clear` and `_v2_delete` delete heads without parsing (the whole-list escape) and leave unrecognised side-row names; a key-shaped row whose content does not parse is kept when the list holds any newer-format head (`:3090`); the sweep skips orphan removal for such a list (`:4553`, `:4597`).
- `actingweb/property_list.py` - a meta `format` outside {1, 2} raises `ListItemNewerFormatError` before `sweep_foreign_format_rows()` (`:1031`), `_maybe_lazy_migrate()` (`:2100`) and `clear()` (`:1052`); `actingweb/attribute_list.py` likewise in `_settle_layout`. `actingweb/maintenance/migrate_property_lists.py` skips and reports such a list.
- `actingweb/maintenance/verify_property_lists.py` - newer-format heads and lists on lines of their own with their own exit status; side rows named for a list with no meta row reported, never removed.
- `actingweb/handlers/properties.py`, `handlers/www.py` - the newer-format error answers 409 with a fixed code beside each `ListItemSpanError` catch (`properties.py:401, 1379, 1407, 1653, 3148, 3198`; `www.py:1518, 1622, 1648`), detail to the log only.

**Sweep of stated defaults** (each rewritten in this phase, with the changelog)

- Empty-store start: `docs/quickstart/getting-started.rst:192`, `docs/guides/mcp-quickstart.rst:74`, `docs/guides/p2p-quickstart.rst:124`, `docs/quickstart/deployment.rst:249`, `examples/demo/README.md:73`, `interface/app.py:587`, `scripts/live_pair.py:30`, `CLAUDE.md` ("App").
- Factory: `docs/quickstart/overview.rst:115`, `docs/reference/routing-overview.rst:27`, `docs/reference/security.rst:95`, `docs/quickstart/getting-started.rst:159, 229`, `docs/quickstart/local-dev-setup.rst:153`, `docs/quickstart/configuration.rst:46-48`, `docs/contributing/testing.rst:269`, `interface/app.py:392`, `config.py:137-140`, `CHANGELOG.rst` (the `open_factory` entry).
- Fault fold and ceiling: `docs/guides/property-lists.rst:602, 673`, `property.py:160-163`, `interface/app.py:682`, `config.py:217-219`, `examples/demo/application.py`, `CHANGELOG.rst` (4 MiB, twice).
- `docs/guides/authentication.rst` ("How an Actor Was Created": `is_vouched()`), `docs/reference/database-backends.rst`.
- `CHANGELOG.rst` - **Breaking** for the factory default, `list_all_with_rows()` and `AttributeListStore.list_all()`; **Behavior change** for the ceiling and the empty-store start; ADDED for the rest.

### New Tests (written first)

The Phase 2 rows of the Traceability table. Existing tests that assert
what this phase removes are rewritten in it:
`tests/test_unique_creator_default.py:86-89` (patch the enable step: the
shared store holds deliberate duplicates),
`tests/integration/test_unique_creator_default.py:42-44`,
`tests/integration/test_unique_creator_http.py:261, 269`,
`tests/integration/test_demo_first_run.py:106-107`,
`tests/test_factory_open_switch.py:116, 141, 152-154`,
`tests/test_list_prefix_with_rows.py:256`,
`tests/test_list_item_limits.py:95`. The empty-store and retry tests use
the real probes, not the stubs of `tests/_lookup_probe.py:79-154`. Any
integration test storing an item between 2 and 4 MiB at the default sets
its ceiling explicitly.

### Failure Scenarios

- Self-enable - a 3.15.1 process creates an actor between the scan and the marker - second consistent scan; `test_an_actor_created_during_the_enable_is_recorded`.
- Self-enable - a wrong prefix with auto-creation - refused on the default prefix (AC-48); with an explicit wrong prefix the start succeeds on an empty store and one WARNING names backend, prefix and region.
- Self-enable on PostgreSQL - two first starts at once - `IF NOT EXISTS` in a transaction; the loser reads the index as present; `test_two_first_starts_at_once_both_start`.
- Retry - the store is down for the whole start - the shared deadline bounds the back-off; the refusal has `unavailable` true and the function platform retries the initialisation.
- Factory - `with_oauth()` after an early `get_config()` - resolved at read time; `test_with_oauth_after_get_config_still_closes`.
- Factory - a peer application lists this one as a trustee factory - the caller gets a WARNING (AC-46) and the guide says to open the factory.
- `is_vouched()` - the marker bucket did not load - raises; `test_an_unread_marker_raises`.
- Newer-format head - an operator runs `--repair` from a 4.0.0 install on a store a later 4.x wrote - reported, kept, exit status non-zero; `test_sweep_and_repair_keep_the_head_and_every_side_row`.
- Newer-format head - a pre-4.0 user item that happens to be `{"__aw_env": 1, "need": [...]}` - unreadable by design; the owner deletes the list, and `actingweb-verify-property-lists` reports it before an upgrade.
- Unknown list `format` - `actingweb-migrate-property-lists --migrate` from a 4.0.0 install - skipped and reported, not rewritten; `test_the_command_skips_and_reports_an_unknown_format`.
- `DbErrorAfterWrite` - a consumer answers "saved" and does not retry - the subscriber's gap stays until the next diff; the docstring and changelog say so.

### Verification

- [x] Run the contract's `### Checks` fast tier verbatim
- [x] Full tier, both backends, before the phase's commit (2026-11-19: DynamoDB 8364 passed; PostgreSQL 8137 passed after the shared-store fix below; docs `-W` clean)
- [x] `poetry run python tests/integration/verify_groups.py`
- [x] Benchmarks alone (`-m benchmark`): 26 passed
- [x] Demo QA mode on a fresh DynamoDB Local prefix with no enable step starts and serves: `tests/integration/test_demo_first_run.py` (rewritten); with OAuth and `OPEN_FACTORY` unset the factory is closed: `tests/test_demo_example.py`
- [x] Each console script with `--help` from a wheel: all nine, `actingweb-check-ready` included
- [ ] The consumer's suite against this tree by path: not run here; the consumer runs it against the branch (see notes)

### Implementation Notes

- AC-12 follow-up (committed in Phase 1, fixed here): the `ACTOR_ADOPTED:`
  line printed up to ten trust peer ids, and an OAuth client's peer id is
  `oauth2_client:<email>:<client>`, so the line could carry an address.
  It now carries counts only (`trusts=`, `siblings=`); the AC-12 test
  plants such a trust and asserts no `@`.
- Red before green was not kept for the storage group: the
  `ListItemNewerFormatError` sites, the meta-format guard and the two
  command changes were written before their tests
  (`tests/test_property_list_newer_format.py`,
  `tests/test_migrate_property_lists.py`, `tests/test_verify_property_lists.py`).
  The codec tests (AC-25) were red first. The tests assert on snapshots of
  every row in both partitions.
- `NewerFormatError` (codec) is a sibling of `EnvelopeError`, not a
  subclass: every `except EnvelopeError` means "malformed, removable", so a
  missed site fails loudly instead of sweeping a newer head. `need` is
  checked right after the marker, before any field's shape.
- Decision (taken here, as the smaller rule): a list whose meta `format` is
  not 1 or 2 is refused by `delete()` too, not only read/write/clear/
  migrate/sweep: the format check sits where the meta row is parsed, and
  `delete()`'s foreign-row sweep would otherwise read format 3 as v1 and
  delete the real rows. The whole-list escape is for a newer *item* in a
  known layout.
- The 409 for `ListItemNewerFormatError` is answered by the handlers beside
  each `ListItemSpanError` site, by `map_db_error`, and by app-level
  handlers in both integrations (a consumer route), with a fixed body.
- `actingweb-verify-property-lists` exits 3 when the only finding is
  newer-format data; AC-45's side-row report runs under `--spans` /
  `--sweep-spans` (it pays the side-partition read those already pay).
- `AttributeListStore.list_all_lists()` (via `RemoteStorage`) raises by
  default too; its callers already re-raise or treat a fault as a fault.
- `actor.get_peer_trustee()` read `if response:`, which is false for any
  4xx, so a 403 left the previous call's code; fixed for AC-46. Three other
  peer calls in `actor.py` share the pattern (todo for Phase 3).
- Two integration fixtures fixed: `test_mcp_resource_regression.py`'s app
  (OAuth, posts to `/`) now opens its factory; `test_property_list_collision.py`
  depended on test order for the creators table (it failed alone on the
  Phase 1 commit too) and now creates its actor without uniqueness.
- The demo calls `with_open_factory` only when `OPEN_FACTORY` is set, so it
  shows the default (closed with OAuth, open in QA mode).
- Start-up: `_probe()` retries a fault (three attempts, 0.5 s then 1.5 s
  from a 2 s budget shared by the whole `check_ready()`; one attempt for
  the remaining checks once a check ended unavailable); `_store_answered()`
  classifies a missing table or denied permission (DynamoDB codes,
  `TableDoesNotExist`, psycopg `UndefinedTable`/`InsufficientPrivilege`/
  `UndefinedColumn`/`InvalidSchemaName`) as an answer, never retried.
  `unique_creators.no_actors(strict=True)` scans strongly and raises;
  `enable_empty_store()` is the dedicated path (DynamoDB: `ensure_table`,
  system actors recorded, marker, second consistent scan with each late
  actor recorded or the marker removed and the start refused; PostgreSQL:
  `CREATE UNIQUE INDEX IF NOT EXISTS` in a transaction with 5 s lock and
  30 s statement timeouts, a lost race reading the index valid counts as
  done). The start-up integration tests and `check-ready`'s tests were
  written after the code; the retry unit tests were red first.
- `actingweb-check-ready` reads the email marker through the static
  `DbAttribute.get_attr_strict` on DynamoDB (constructing the backend
  creates a missing table) and treats a missing actor table as an empty
  store. It is in `test_operator_command_store.py`'s map (read-only).
- Verification: wheel built, every console script answers `--help` from a
  scratch venv (Python 3.14); benchmarks alone, 26 passed. The consumer's
  suite against this tree was not run here: the consumer runs it against
  the branch itself (its second read, 2026-11-19).
- Found by the first PostgreSQL Full tier: a unit test with the real
  uniqueness probe (`tests/test_demo_example.py`) reached the empty-store
  self-enable on the shared PostgreSQL schema, which is empty early in a
  run, and built `ux_actors_creator` there, breaking every later test that
  holds deliberate duplicates. `tests/_lookup_probe.py` now has an autouse
  guard: outside `tests/integration` the enable step refuses unless a test
  patches it. The stray index was dropped from the test container.
- For Phase 3 (todos), the consumer's round-two candidates (2026-11-19),
  to be verified against the tree when filed: an unserialisable value is
  reported as a store fault (`DbError("attribute set")`), so a caller that
  retries on 503 would retry forever; and a public call to record one
  actor's creator, only if the narrowed enable command does not serve.

### Implementation Status: Complete

---

## Phase 3: Guide and bookkeeping

### Changes

- `docs/migration/v4.0.rst`:
  - "Rows to review" (`:2343`): exclude rows held by `_actingweb_oauth2` (registrations, not approvals); a DynamoDB form (3.4).
  - "Spanned list items": a bare `Config()` takes the backend's limits, so every process sets them (3.9); the 2 MiB default (`:402`, `:1230`).
  - "OAuth sign-in": a marker being present no longer means vouched; `is_vouched()`; `actor_adopted` and the `ACTOR_ADOPTED:` line for telling a user why their connectors are gone.
  - The checklist (and the same steps in `docs/quickstart/deployment.rst:235-286`), as sub-steps so the numbers cited elsewhere do not move: each step's reason; step 5 (marking) stays; 8a, the marking again as the last write before the deploy; 8b, `actingweb-check-ready`; after the deploy and before step 9, the marking once more (A14). `check-ready` gets a row in the commands table.
  - "A fresh store" (`:150-160`), the table row at `:125-127` and `:395`: the start-enable-start sequence is gone; what remains on the default prefix and for PostgreSQL without DDL rights; no older process creates actors while an empty store enables itself.
  - The factory default (`:356`, `:772-777`): the rule, the trustee case, tests and harnesses that post to `/`; PKCE, with what it asks of an application that has its own authorise form or creates codes itself (carry `code_challenge` and `code_challenge_method` through; `require_pkce=False` to upgrade before the form is fixed, or before the application has checked its clients; how to check before removing the opt-out: a client whose registrations are all public and that has signed in since sends a challenge, otherwise one recorded authorise request with a `code_challenge`); `list_all_with_rows()` and `AttributeListStore.list_all()`; discovery; `resources/templates/list`; the write guard for scripts on the default prefix.
  - "Custom database backends": nothing new to implement; the `need` and `format` rules for a backend that stores list rows itself.
  - Installing the candidate (a note removed at final): the Poetry second source (`priority = "explicit"`) for TestPyPI.
  - The data-freeze statement, naming the stored shapes it covers and the two extension rules.
  - The mixed-version table (`:186-217`): the two rows from AC-40 and AC-41; the PostgreSQL rows stay "Not tested".
- `docs/quickstart/deployment.rst` - the payload arithmetic behind a gateway with a response limit (a quote-heavy item can more than double on the way out, so 2 MiB is not a guarantee), and `with_list_item_limits(max_bytes=...)`.
- `CHANGELOG.rst` - the note at the top of `v4.0.0rc1` names the first steps as they now are.
- `thoughts/todo/` - new files with `INDEX.md` rows: `bounded-list-read.md` (V1, with the evaluation's findings: the PostgreSQL index, the cursor contract, the wrapper layers), `list-items-conditional-create-ttl-and-retained-bodies.md` (V2 with `require_actor`, V3, V4), `consumer-test-fault-injection.md` (A13), `marking-and-adoption-followups.md`, `attribute-conditional-delete-on-dict-values.md` (A10), `key-prefix-scheme-design-before-4-0-final.md`, `startup-check-served-503-mode.md`; additions to `dcr-registrations-and-client-trust-rows-never-expire.md` (A4, the measured numbers), `outbound-callback-backpressure.md` (A11), `mcp-cache-lifecycle-and-revocation.md` (A12), `mcp-oauth-connector-conformance-followups.md` (the items closed here removed; the PKCE redirect and the strict `resources/list` split added), `rc-pass-against-real-consumers.md` (the demo's fresh-store CI step removed; `AWS_DB_PREFIX` explicit for the demo's commands); `flask-spa-session-route.md` deleted.
- `thoughts/inbound/emm-4-0-adoption-findings-and-asks.md` - deleted.

### New Tests (written first)

None: the phase is prose.

### Failure Scenarios

- A reversed default still stated somewhere `-W` cannot see - the sweep greps below.

### Verification

- [ ] The Full tier's docs build (`-W`); fast tier (a docs-only phase)
- [ ] `grep -rn "stops with\|open by default\|4 MiB\|(\[\], {})\|required for public clients" docs actingweb examples CLAUDE.md CHANGELOG.rst`: every hit is intended
- [ ] `ls thoughts/inbound` shows only `README.md`; every new todo has its row

### Implementation Status: Not Started

---

## Evaluation Notes

**Outside voice:** codex (gpt-5.6-sol, read-only) and a fresh-context reviewer (Fable 5.2).

| # | From | Finding (`file:line` quoted) | Disposition |
| --- | --- | --- | --- |
| 1 | Security, Architecture | `maintenance/unique_creators.py:1166` "`Actor.scan(page_size=25, attributes_to_get=["id"])`" not consistent; `:1048` "`Creator(creator=BACKFILL_KEY).save()`" unconditional | Folded: Phase 2 enable path, AC-50 |
| 2 | Security | `interface/app.py:1648` "`pool.submit(ensure_table, m)`" creates tables under any prefix before the checks | User decided: self-enable needs an explicit prefix (AC-48) |
| 3 | Architecture, Scalability | `unique_creators.py:966-973` "`SET statement_timeout = 0`" … "`CREATE UNIQUE INDEX CONCURRENTLY`"; `:968` drops an INVALID index | Folded: a dedicated start-up statement |
| 4 | Architecture | `db/creator_rules.py:28` "`SYSTEM_CREATORS = frozenset({"system", "oauth2-system"})`" not exempt | Folded: system actors recorded |
| 5 | Security, Architecture | `config.py:140` "`self.open_factory = True`"; `handlers/factory.py:215` "`getattr(self.config, "open_factory", True)`"; `app.py:216-218` config built before `with_oauth()` | Folded: a read-time property |
| 6 | Usability | `app.py:353-354` "`self._www_auth = "oauth"`" on any call vs `factory.py:168` "`self.config.oauth.get("client_id")`" | User decided: any provider builder |
| 7 | Usability | `examples/demo/application.py:70` "`.with_open_factory(enable=os.getenv("OPEN_FACTORY", "true")...`" | Folded: demo follows the default |
| 8 | Usability | `docs/migration/v4.0.rst:774` "A closed factory still renders the `GET /` page and its form" | Folded: AC-47 |
| 9 | Outside voice | `actor.py:1923-1946` trustee creation posts to the peer's factory and logs at INFO | Folded: AC-46, guide line |
| 10 | Architecture, Scalability | `app.py:1731` "`except Exception as e:  # folds DbError: fails closed, like absence`"; `db/postgresql/connection.py:165` "`PG_POOL_TIMEOUT", "30.0"`" | Folded: retry inside each check, one deadline, AC-17's rules |
| 11 | Architecture, Security | `list_core.py:3623` "`if not db.delete_if_value_equals(`" before `:3631` `_cascade`; `:4556` sweep removes a marked malformed head; `property_list_span.py:294` "neither v nor span" precedes any `need` check; `:296` known fields are dropped from `extra` | Folded: Phase 2 storage, per-site decisions |
| 12 | Usability, Security | `list_core.py:199-201` "the orphan sweep removes the broken head"; `handlers/properties.py:1383` "`"detail": str(e)`" | Folded: not a corruption error, fixed 409 body (AC-25) |
| 13 | Outside voice | `property_list.py:1031-1037` a `format` other than 2 is swept as v1; `:2100` lazy migration | Folded: AC-43 |
| 14 | Outside voice | `list_core.py:3105-3107` "resurrected inside the next list created under this name"; `maintenance/verify_orphans.py:215-221` | Folded: naming rule (Spec Delta), AC-45. Incarnation id rejected: a later row kind adds it when designed |
| 15 | Architecture | no `register_diffs(` in `property_list.py` or `list_core.py`; `interface/property_store.py:277` precedes its write | Folded: corrected raise sites |
| 16 | Security | `handlers/properties.py:886` "`# folds DbError: the item is stored; a 503 would invite a duplicate retry`"; `interface/integrations/_errors.py:113` `Retry-After` | Folded: folds kept, own code, no `Retry-After` |
| 17 | Scalability, Architecture, Usability, Outside voice | `db/postgresql/schema.py:73` no `COLLATE "C"` index on properties; `list_core.py:352` "never persist or transmit one"; `interface/property_store.py:471` wrappers | User decided: bounded read cut (AC-23, AC-24 dropped) |
| 18 | Architecture, Usability | `mark_actors_vouched.py:291` "`--dry-run`"; `verify_property_lists.py:648` "`--repair`"; `migrate_property_lists.py:438` "`--migrate`" | Folded: guard on any writing mode (AC-10); marking flags kept |
| 19 | Architecture, Tests | `verify_property_lists.py:143` "`def _log_target(`" in three copies; `:175` logged, not printed | Folded: moved, printed |
| 20 | Usability, Architecture | `maintenance/property_lookup.py:179-183` commands build `Config(unique_creator=False, force_email_prop_as_creator=False)`; `email_as_creator.py:99` returns ready when the flag is off; `db/dynamodb/attribute.py:842` "`ensure_table(Attribute)`" | Folded: flags, assumed configuration printed, no table creation; `check-ready` moved to Phase 2 |
| 21 | Usability, Tests | `property_lookup.py:1057` fix line without `--properties`; `tests/test_property_lookup_command.py:203` "narrows the printout, not the verdict" | Folded: AC-1, test rewritten |
| 22 | Security, Usability | `mark_actors_vouched.py:145` dry-run detail on the logger; `unique_creators.py:1267` "`--show-addresses`" | Folded: AC-3 |
| 23 | Security, Tests | `handlers/async_mcp.py:72-73` a second dispatcher; `handlers/mcp.py:1155-1162` faults swallowed in `initialize` | Folded: both handlers, 503 on a fault |
| 24 | Security | `oauth2_server.py:438` challenge from state unchecked; `token_manager.py:306` "`if stored_challenge:`"; `oauth2_server.py:661` | Folded: AC-49 |
| 25 | Architecture, Tests | `handlers/oauth2_endpoints.py:375` "`return self.error_response(400, ...)`" | Folded: AC-37 says 400; redirect is a todo |
| 26 | Outside voice | `oauth2_server.py:244` a registration row records the authentication method only | Folded: Phase 1's first task is a recorded authorise request per connector |
| 27 | Architecture, Usability | `app.py:626-628` `with_mcp` assigns every option on each call | Folded: AC-51 |
| 28 | Security, Scalability | `handlers/mcp.py:2796` "`or "MCP Client"`"; `:2823-2829` skip test compares the incoming name; `:2916` unauthenticated cache entry | Folded: AC-34 and its four tests |
| 29 | Architecture, Security | `handlers/mcp.py:1580-1581` one `uri_template` key; `:1587` permission filter; `mcp/uri.py:74-78` regex resources | Folded: AC-33 |
| 30 | Architecture, Tests | `fastapi_integration.py:2472` "`async def _handle_spa_session_retrieve(`" is integration code | Folded: extracted to the handler module; tests parametrised |
| 31 | Architecture | `oauth2.py:3180-3182` an adoption line exists; `:2696` and `:3198` both fire the hook | Folded: one helper, AC-12 |
| 32 | Security, Tests | `attribute.py:49-50` "`loaded` stays False after one"; `oauth2.py:1865-1866` True without a bound address | Folded: AC-20, the decision in the Spec Delta |
| 33 | Outside voice, Architecture | `attribute_list_store.py:88-92` "`# folds DbError: documented [] unless strict`" | User decided: raises by default (AC-44) |
| 34 | Tests | `tests/test_unique_creator_default.py:86-89`, `integration/test_unique_creator_http.py:261`, `integration/test_demo_first_run.py:106` assert the refusal; `tests/_lookup_probe.py:154` stubs the probe | Folded: Phase 2 New Tests |
| 35 | Usability, Outside voice | about thirty statements of reversed defaults, e.g. `docs/quickstart/overview.rst:115` "open by default as the protocol requires", `docs/guides/property-lists.rst:673` "4 MiB" | Folded: the sweep list and greps |
| 36 | Outside voice | `scripts/live_pair.py:28-32` runs the versions on separate prefixes | Folded: `--same-store`, runs moved to Phase 1 with a failing outcome defined |
| 37 | Usability | `docs/migration/v4.0.rst:104` two numbered step lists; `:125`, `:191` cite step numbers | Folded: sub-steps |
| 38 | Scalability | `maintenance/verify_orphans.py:329-331` banners read the environment only | Folded: no `DescribeTable` in the banner |
| 39 | Security | `mcp.py:2564-2576` a bridge-created actor (`oauth2_bearer`) reads as vouched for a synthesised address | Rejected for this plan: existing marker semantics, recorded in `marking-and-adoption-followups.md` |
| 40 | Tests | no file under `tests/integration/wire/` contains `grant_types_supported`, `resources/list` or `oauth/logout` | Folded: the re-record line removed |
| 41 | Outside voice (codex) | read "`client_credentials` leaves `grant_types_supported`" as "stays" | Folded: reworded to "is removed from" |
| 42 | Outside voice | a 2 MiB item of quotes escaped twice is about 8 MiB | Folded into the deployment page's arithmetic; the default is the owner's decision |
| 43 | Consumer | `tests/test_mcp_fail_closed_authorization.py:537` "`("resources/list", "resources", "notes://{id}")`": a client that calls only `resources/list` would lose templated resources | User decided: the method is added, the listing kept |
| 44 | Consumer | `templates/aw-oauth-authorization-form.html:15` "`<input type="hidden" name="code_challenge" ...`": the challenge rides in the form, so an application's own form can drop it | Folded: AC-52, guide |
| 45 | Consumer | Spec Delta "No older process may write to a store during its first 4.0 start" covers every start | Folded: scoped to the self-enable |
| 46 | Consumer | release candidates on PyPI instead of TestPyPI | User decided: TestPyPI kept |
| 47 | Consumer | Phase 1's gate "(claude.ai, Claude Code, ChatGPT, Codex)": production also has registrations from mcporter-cli (28), mcporter (6), Gemini CLI (1), MCP Inspector (2) | Folded: the gate covers every registered client name; a public registration with a completed sign-in counts as evidence (`oauth2_server.py:241-245` already refuses it without a challenge) |
| 48 | Consumer | "set `with_mcp(require_pkce=False)` in the minimal migration": as planned, AC-38/AC-49 still refused a public client's challenge-less code at callback and exchange, which rc1 does not (`token_manager.py:306` "`if stored_challenge:`"), so the consumer's password sign-in could break under the opt-out | User decided: the opt-out restores rc1's behaviour exactly |

**Unverified notes** (concerns that could not cite a line):

- PynamoDB's default timeouts and a function platform's initialisation limit were not read; the retry's worst case depends on them.
- Whether `/oauth/authorize` serves with `with_mcp(enable=False)`; if it does, `require_pkce` under `with_mcp` is an awkward home.
- Whether `demo.actingweb.io` runs on the default prefix; if so its commands need `AWS_DB_PREFIX` set explicitly (noted in the rc-pass todo).
- Whether a wire recording holds a `POST /` made with a provider configured.
- Whether any route stores a raw `list:` row past `encode_item` (devtest, replica writes into attribute lists), which would let a peer plant a `need`.
- Whether the MCP trust cache is refreshed after the client-info write.
- An in-flight `CREATE INDEX CONCURRENTLY` reading as INVALID to a second instance is general PostgreSQL behaviour, not shown in the tree.
