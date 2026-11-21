---
status: active
approved: 2026-11-21 by Greger Wedel
---

# Implementation Plan: 4.0.0rc2 — the trust request's answer, and a consumer's rc1 findings

**Date:** 2026-11-21
**Research:** thoughts/research/2026-11-21-trust-request-answer-secret.md (phase 1), thoughts/research/2026-11-21-emm-4-0-rc1-feedback.md (phases 2-5)
**Branch:** `fix/4.0.0-rc2-consumer-fixes` (from `master` at `add5a4d`)

## Overview

4.0.0rc1 failed the demo's BlazeMeter trust suite. It also produced four
observations from a consumer's migration (Emm, triaged in the research note).
This plan is what 4.0.0rc2 takes for them.

- **Phase 1.** Puts `secret` back into the answer to a peer's trust request,
  keeps the verification token out of an unapproved answer, makes sure the
  answered secret is always the one written for that request, gives the
  peer-facing refusals of a trust request a reason the peer can read, and
  covers the peer's request path in the integration suite.
- **Phase 2.** Stops a warning per OAuth2 client on every permission change.
- **Phase 3.** Lets an application announce its own MCP server version.
- **Phase 4.** Proves that a disconnected MCP client cannot reconnect without
  the user, and closes the one route by which tokens from before a
  disconnect could come back: the disconnect now removes the client's
  authorization codes too.
- **Phase 5.** Adds a supported way to record one actor's creator after a
  restore.

## Decisions Made

- **The answer always carries `secret`** (option b, owner 2026-11-21): the
  secret the request sent, or the one generated for it. It never carries
  `verification_token` while this actor has not approved the row. `secret`
  is carried as in 3.x; 3.x also carried the token, which stays out.
- **A request without a secret stays accepted** (owner 2026-11-21). It is a
  protocol path no known implementation uses: the library's own initiator
  always sends a secret (`actor.py:2347`). The spec says requesters SHOULD
  send one.
- **A lost answer to a request without a secret is documented, not handled**
  (owner 2026-11-21). The requester cannot retry, because 4.0 replaces a
  pending row only with a request that verifies (`actor.py:3117`). The owner
  deletes the row.
- **Protocol spec 1.5 is amended in place** (owner 2026-11-21): 4.0.0 is not
  final.
- **The peer-facing refusals of `POST /<id>/trust/<rel>` answer a JSON
  `{"error": …}` body** (owner 2026-11-21). They are: missing attributes,
  reserved relationship, invalid id or base URI, no trust to re-pair,
  re-pair not proven. The other bare refusals in `handlers/` become a todo.
- **The answer is fixed before anything else can touch it** (evaluation). A
  creation's answer is built from the row it wrote, before
  `trust_request_received` runs, and the hook gets a copy. A re-pair answers
  only when its read-back row holds the secret it sent.
- **An OAuth2/MCP client peer is not notified of permission changes**
  (owner 2026-11-21). It has no base URI by construction, so the skip logs
  at DEBUG. Any other trust without a base URI keeps the WARNING.
- **The skip covers every OAuth2 peer id** (phase-2 review): the
  `OAUTH2_SOURCES` prefixes (`oauth2:`, `oauth2_client:`,
  `oauth2_interactive:`), on both the sync and the async notify path. A peer
  cannot choose these prefixes (`trust.py:28-33`).
- **`with_mcp(server_version=…)`** is an optional keyword that defaults to
  the library's version (owner 2026-11-21). `with_app_version()` does not
  feed `serverInfo.version` (owner, phase-3 review): an application that
  already sets it announces nothing new unless it opts in. The keyword is
  validated as `with_app_version` validates (a non-empty string).
- **A disconnect sweeps the client's authorization codes** (owner,
  2026-11-21, phase-4 review; supersedes the grant-time trust check). The
  sweep that already revokes the actor's tokens for the client also removes
  its codes from the actor's `mcp_auth_codes` bucket, fail closed. An
  exchange checks after it mints that its consumed code was not swept, and
  removes what it minted if it was. The grants do not look up a trust, so
  nothing changes for an application that mints codes itself.
- **The single-actor creator record** is a public function plus
  `actingweb-unique-creators record --actor ID [--previous ADDR] [--apply]`
  (owner 2026-11-21).
  - The caller names the orphan's address with `--previous`; there is no
    scan.
  - It answers `not-enforced` before `enable`.
  - It refuses a creator stored with capitals, and a reserved `#…` value.
  - It answers `held-by` when another actor holds the address.
  - PostgreSQL checks only, and answers `verified`, never `recorded`
    (phase-5 review: automation must not read a check as a write).
  - `--previous` is released only after the record step succeeded, and only
    when the record names this actor (phase-5 review).
  - Kept in rc2 (owner, phase-5 review): `enable` refuses `--creator`, so
    without `record` one restored actor costs two full-store scans.
- **One plan, one PR, one commit per phase** (owner 2026-11-21). Before a
  phase commit re-records a wire row, an earlier commit reserves this plan
  and makes that phase an owner of the row
  (`docs/contributing/testing.rst`, "Wire Recordings"). That ownership
  commit is never squashed into a phase commit on the branch.

## What We're NOT Doing

- Relaxing the peer `id`/`baseuri` check, or letting an owner approve an unverified request - 4.0 security fixes; the BlazeMeter test is changed instead.
- Returning `verification_token` in an unapproved answer - the mirrored-request hole rc1 closed.
- Letting a request without a secret replace a pending row - owner decision: documented instead.
- JSON bodies for the other bare refusals across `handlers/` (about 240) - a todo; too wide for an rc.
- Closing the duplicate-secret 403/202 difference in `Trust.create` - existing, not widened; a bearer GET gives the same signal, and generated secrets are 160-bit.
- Rejecting a non-string `secret` with a 400 - existing behaviour; a todo.
- A trust check at the code exchange or the refresh grant - owner decision: the disconnect sweep closes the route without one. A check would not have refused a code exchanged after a reconnect (any row for the client matches, `trust_lookup.py:111-113`), and it would break applications and about 90 tests that mint codes without a trust.
- Sweeping pending confirmations at disconnect - a confirmation issues a code only after the user approves on an ActingWeb page, which is the consent AC-18 pins.
- Feeding `with_app_version()` into `serverInfo.version` - owner decision: it would change what existing applications announce without their opting in.
- `record` without `--previous` finding orphans by scan or a GSI - owner decision; `report` still lists them.
- `record` lowercasing capitals, or writing before `enable` - `resolve` and `enable` already do those.
- Filtering reserved `#…` values in `enable` - outside the consumer's ask; recorded in the todo with the non-string `secret`.
- Editing the BlazeMeter test, releasing rc2 - Follow-up.

## What Already Exists

- `actingweb/handlers/trust.py:261` `_trust_request_answer` - builds the answer for a creation (`:609`) and a re-pair (`:664`).
- `actingweb/handlers/trust.py:913` `_refuse_unverified_approval` - the existing JSON `{"error": …}` refusal pattern that phase 1 reuses.
- `actingweb/trust.py:136` `Trust.get` - on a creation it returns the dict `create` built (`actor.py:3163`).
- `actingweb/actor.py:3236-3238` `replace_trust_secret` - a re-pair reads its row back after the conditional swap.
- `actingweb/actor.py:2737` `reverify_pending_trust` - the check repeated at approval (GET with the stored secret, an approved row naming this actor, then `/meta` at `:2776`); unchanged.
- `actingweb/trust_lookup.py:15` `OAUTH2_SOURCES` - the OAuth2 peer-id prefixes phase 2 skips (`trust_permissions.py:163` `is_client_peer` covers only `oauth2_client:`).
- `actingweb/trust_permissions.py` `_notify_peer` (`:406`, warns at `:466` through `aw_proxy.py:275`) and `_notify_peer_async` (`:482`, warns at `:524-530`) - the two paths phase 2 changes.
- `actingweb/interface/app.py:675` `with_mcp` - stores its options as `_mcp_*` attributes, re-applied in `_apply_runtime_changes_to_config` (`:287-290`); phase 3 adds one the same way. `with_app_version` (`:429`) has the validation phase 3 reuses.
- `actingweb/oauth2_server/token_manager.py:1766` `_revoke_matching_tokens` - the disconnect sweep (reached from `Trust.delete` through `revoke_connection_tokens` and `disable_client`, before the row goes); phase 4 adds the code bucket to it. `:231` `exchange_authorization_code` with its post-mint check `_generation_still_matches` (`:1064`), the pattern phase 4's check follows. `delete_confirmed` (`:2067`) is the fail-closed delete; `_remove_auth_code` (`:1211`) swallows faults and is not used by the sweep.
- `actingweb/db/dynamodb/actor.py:1006-1104` `release_stale_record`, `record_for_actor_as_read`, `move_stale_record`, `actor_as_read` - the conditional record writers phase 5 builds on.
- `actingweb/maintenance/unique_creators.py` - `_settle_record` (`:610-666`, refactored and reused by phase 5), `main`/`_run` (`:1365-1458`), `_backfill_state`, `creator_rules` (`normalise_creator`, `is_exempt`, `is_reserved`, `is_system_actor`). `collect` (`:390`) folds `DbError` into `StoreUnavailable`; phase 5 does the same.
- Tests reused:
  - `tests/test_trust_re_pair.py` (`Receiver`, `_reverse_answers`, the approval `_put`);
  - `tests/integration/test_trust_flow.py` and its `http_client` fixture;
  - `tests/integration/test_oauth2_trust_binding.py` (`Flow`, `wire_oauth`);
  - `tests/integration/test_unique_creators_command.py` (`_raw_actor`, the `unique_creator_store`/`enforced_store` fixtures, xdist group `unique_creator`);
  - `tests/test_unique_creators_command.py`.

## Acceptance Criteria

Phase 1 — the trust request's answer and refusals

- **AC-1** (main: request without a secret) — When a peer's trust request carries no `secret` key, the 202 answer carries the secret the actor generated for the row.
- **AC-2** (main: request with a secret) — When a peer's trust request carries a `secret` and waits for approval, the 202 answer carries that same secret.
- **AC-3** (edge: the token) — When the answer to a trust request (a creation or a re-pair) is for a row this actor has not approved, it carries no `verification_token`.
- **AC-4** (protocol: pairing without a secret) — When a requester that sent no secret serves, at its base URI, an approved row naming this actor that accepts the answered secret as bearer, the owner's approval answers 204 and the row is approved and verified.
- **AC-5** (edge: re-pair) — When a proven re-pair of an unapproved row answers 202, the answer carries the new secret the re-pair sent.
- **AC-6** (edge: invalid peer, integration) — When a peer's trust request's `baseuri` is not a plain http(s) URL, or its `id` is not a plain id, the answer is 400 and no trust row exists afterwards.
- **AC-7** (edge: unverified approval, integration) — When the owner approves a trust request that did not verify, the answer is 403 and the row stays unapproved.
- **AC-8** (edge: pending status, integration) — When a peer reads its own pending row with the answered secret as bearer, the answer is 202 with the row and no `verification_token`.
- **AC-9** (docs) — Protocol spec 1.5, the `Unreleased` CHANGELOG, the v4.0 migration guide and `docs/reference/security.rst` say that the answer to a trust request carries `secret` and, while unapproved, no `verification_token`.
- **AC-10** (added in plan: evaluation) — When the stored row or the hook's `trust_data` changes between a creation's write and its answer, the answer still carries the secret written for this request.
- **AC-11** (added in plan: evaluation) — When a re-pair's read-back row holds a secret other than the one the re-pair sent, the answer is 403 and carries no secret.
- **AC-12** (added in plan: owner decision, error bodies) — When `POST /<id>/trust/<rel>` is refused for missing attributes, a reserved relationship, an invalid id or base URI, a missing trust to re-pair, or an unproven re-pair, the answer carries a JSON body with an `error` that names the reason.
- **AC-13** (added in plan: outside voice, docs) — The protocol spec and the CHANGELOG say that a requester SHOULD send a secret, that one whose answer to a request without a secret was lost cannot retry and the owner deletes the pending row, and that pending rows rc1 created from such requests are the owner's to delete. `docs/reference/hooks-reference.rst` says that `trust_request_received` gets a copy of the row and that the answer reflects the row as written.

Phase 2 — permission-change notifications

- **AC-14** (main) — When a permission change concerns a peer whose id has an OAuth2 prefix (`oauth2:`, `oauth2_client:`, `oauth2_interactive:`) and whose trust has no base URI, no notification is attempted and nothing is logged above DEBUG, on both the sync and the async notify path.
- **AC-15** (edge) — When a permission change concerns any other peer whose trust has no base URI, the WARNING is logged as before, on both paths.

Phase 3 — the MCP server version

- **AC-16** (main) — When the application sets `ActingWebApp.with_mcp(server_version="2.3.1")`, the MCP `initialize` answer's `serverInfo.version` is `"2.3.1"`.
- **AC-17** (edge: default) — When `server_version` is not set, `serverInfo.version` is the library's version, also when the application calls `with_app_version()`.
- **AC-33** (added in plan: phase-3 review) — When `server_version` is empty or not a string, `with_mcp` raises the error `with_app_version` raises for the same value.

Phase 4 — reconnecting a disconnected MCP client

- **AC-18** (main) — When a user's connection to an MCP client is deleted and the client then posts the authorization form itself, the user's browser is shown the confirmation page and no trust or code exists until the user approves.
- **AC-19** (edge: fresh grant) — When the user reconnects the client through the sign-in form, the new trust has the level chosen then, and a permission override stored before the disconnect is gone.
- **AC-20** (edge: orphan code) — When an authorization code issued before the disconnect is exchanged after it, the answer is `invalid_grant`, no token is issued, and the code, its index row and its provider-token row are gone.
- ~~**AC-21**~~ — dropped (owner, phase-4 review): the refresh grant gets no trust check; a disconnect already revokes the client's refresh tokens and marks their chains. AC-22 pins that.
- **AC-22** (edge: after reconnect, regression) — When the user has reconnected the client, a refresh token issued before the disconnect still answers `invalid_grant`.
- **AC-34** (added in plan: phase-4 review) — When an authorization code issued before the disconnect is exchanged after the user has reconnected the same client, the answer is `invalid_grant`.
- **AC-35** (added in plan: phase-4 review, race) — When a disconnect's sweep runs while an exchange is between consuming its code and returning, the exchange answers `invalid_grant` or the tokens it minted are revoked; no token it minted works afterwards.
- **AC-36** (added in plan: phase-4 review, fault) — When the sweep cannot confirm a code removed, the disconnect raises `DbError` and the trust row stays, as for a token it cannot revoke.

Phase 5 — one actor's creator record

- **AC-23** (main) — When `record --actor ID --apply` runs on an enabled DynamoDB store for an actor whose creator has no record, the record is written naming that actor and the command exits 0.
- **AC-24** (main: restore) — When `--previous ADDR` names an orphaned record that names this actor under another address, `--apply` removes it, and a following `report` is clean and `enable` does not refuse.
- **AC-25** (edge: dry run) — When `record` runs without `--apply`, it reports what it would write or remove and writes nothing.
- **AC-26** (edge: held) — When another actor holds the creator's record, `record` answers `held-by <id>`, writes nothing and exits 1.
- **AC-27** (edge: not enforced) — When uniqueness is not enabled (DynamoDB marker missing, PostgreSQL index not valid), `record` answers `not-enforced`, writes nothing and exits 1.
- **AC-28** (edge: capitals) — When the actor's creator is stored with capitals, `record` refuses, writes nothing and exits 1.
- **AC-29** (edge: reserved) — When the actor's creator is a reserved `#…` value (not `#dup-`) or a system creator on a non-system actor, `record` refuses, writes nothing and exits 1.
- **AC-30** (main: PostgreSQL) — On PostgreSQL, `record` answers `verified` when no other actor has the same lowercased creator and `held-by <id>` when one does, and never writes.
- **AC-31** (edge: race) — When the actor row changes between `record`'s read and its write, `record` answers `changed`, writes nothing and exits 1.
- **AC-37** (added in plan: phase-5 review) — When the actor does not exist, `record` answers `missing` and exits 1. When its creator is exempt or a `#dup-` value, it answers `exempt`, writes nothing and exits 0.
- **AC-38** (added in plan: phase-5 review, `--previous`) — `--previous` is normalised as creators are. When it equals the actor's current creator, or is exempt or reserved, `record` refuses before it reads anything (exit 1). When no record exists for it, the previous step answers `absent` (exit 0). When its record names another actor, it answers `not-this-actor`, removes nothing and exits 1.
- **AC-39** (added in plan: phase-5 review) — When the record step answers anything but `recorded` or `written`, `--previous` is not released (`skipped`), and the exit code is the record step's.
- **AC-40** (added in plan: phase-5 review) — When the store faults (`DbError` or `StoreUnavailable`), `record` exits 2 and prints the fault.

All phases

- **AC-32** (docs) — The `Unreleased` CHANGELOG has an entry for each of phases 2-5. The MCP configuration docs name `server_version` and say that `initialize` discloses it. The operator docs for `actingweb-unique-creators` describe `record`, its outcomes, its exit codes and the quiet-sign-ins advice.

## Traceability

| AC | Phase | Test | Status |
| --- | --- | --- | --- |
| AC-1 | 1 | `tests/test_trust_re_pair.py::TestTheAnswerCarriesTheSecret::test_a_request_without_a_secret_gets_the_generated_one`; `tests/integration/test_trust_flow.py::TestPeerTrustRequest::test_003_request_without_secret_answers_its_secret` | Passing |
| AC-2 | 1 | `tests/test_trust_re_pair.py::TestTheAnswerCarriesTheSecret::test_a_request_with_a_secret_gets_it_back` | Passing |
| AC-3 | 1 | `tests/test_trust_re_pair.py::TestTheEdgesAfterReverify8::test_a_pending_requests_answer_carries_no_token` (changed); `tests/test_trust_answer_flags.py::test_an_unapproved_answer_has_booleans_and_no_token` (renamed) | Passing |
| AC-4 | 1 | `tests/test_trust_re_pair.py::TestTheAnswerCarriesTheSecret::test_a_generated_secret_pairs_on_approval` | Passing |
| AC-5 | 1 | `tests/test_trust_re_pair.py::TestTheRePairAnswerAfterReverify9::test_a_re_pair_of_an_unapproved_row_answers_without_its_token` (changed) | Passing |
| AC-6 | 1 | `tests/integration/test_trust_flow.py::TestPeerTrustRequest::test_002_request_with_invalid_peer_is_refused` (regression for the status; new for the body, AC-12) | Passing |
| AC-7 | 1 | `tests/integration/test_trust_flow.py::TestPeerTrustRequest::test_006_owner_cannot_approve_unverified_request` (regression) | Passing |
| AC-8 | 1 | `tests/integration/test_trust_flow.py::TestPeerTrustRequest::test_004_peer_reads_its_pending_row` | Passing |
| AC-9 | 1 | manual: read the four passages against the AC; `sphinx-build -W` passes — prose has no automated assertion | Done: passages read against the AC; `sphinx-build -W` passes |
| AC-10 | 1 | `tests/test_trust_re_pair.py::TestTheAnswerCarriesTheSecret::test_the_answer_is_the_row_written` | Passing |
| AC-11 | 1 | `tests/test_trust_re_pair.py::TestTheAnswerCarriesTheSecret::test_a_re_pair_answers_only_its_own_secret` (handler-only: the read-back is stubbed) | Passing |
| AC-12 | 1 | `tests/test_trust_re_pair.py::TestTheRefusalsSayWhy::test_each_refusal_has_an_error_body` (parametrized over the five refusals); `TestPeerTrustRequest::test_002_…` asserts the body end to end | Passing |
| AC-13 | 1 | manual: read the spec, CHANGELOG and hooks-reference passages — prose | Done: passages read against the AC; `sphinx-build -W` passes |
| AC-14 | 2 | `tests/test_trust_permissions_notify.py::test_an_oauth2_peer_is_not_notified` (parametrized: three prefixes × sync/async path; a trust row that exists with no base URI; caplog: nothing above DEBUG; no HTTP call) | Not run |
| AC-15 | 2 | `tests/test_trust_permissions_notify.py::test_a_peer_without_baseuri_still_warns` (regression; both paths) | Not run |
| AC-16 | 3 | `tests/test_mcp_server_name.py::test_the_app_announces_its_version` (through `ActingWebApp.with_mcp`, so the runtime re-apply is covered) | Not run |
| AC-17 | 3 | `tests/test_mcp_server_name.py::test_the_default_is_the_library_version` (regression; also with `with_app_version("9.9")`) | Not run |
| AC-33 | 3 | `tests/test_mcp_server_name.py::test_an_invalid_server_version_is_refused` | Not run |
| AC-18 | 4 | `tests/integration/test_oauth2_trust_binding.py::test_a_disconnected_client_needs_the_user_again` (regression: pins today's behaviour) | Not run |
| AC-19 | 4 | `tests/integration/test_oauth2_trust_binding.py::test_a_reconnect_starts_from_a_fresh_grant` (regression) | Not run |
| AC-20 | 4 | `tests/integration/test_oauth2_trust_binding.py::test_a_code_from_before_the_disconnect_is_refused` | Not run |
| ~~AC-21~~ | — | dropped | — |
| AC-22 | 4 | `tests/integration/test_oauth2_trust_binding.py::test_an_old_refresh_token_stays_dead_after_a_reconnect` (regression: passes today through the token sweep) | Not run |
| AC-34 | 4 | `tests/integration/test_oauth2_trust_binding.py::test_a_code_from_before_the_disconnect_is_refused_after_a_reconnect` | Not run |
| AC-35 | 4 | `tests/test_oauth2_disconnect_sweeps_codes.py::test_a_sweep_during_an_exchange_leaves_no_live_token` (the sweep is run from a wrapped `_create_refresh_token`, between the consume and the post-mint check) | Not run |
| AC-36 | 4 | `tests/test_oauth2_disconnect_sweeps_codes.py::test_a_code_that_cannot_be_removed_keeps_the_row` (`delete_confirmed` patched to fault) | Not run |
| AC-23 | 5 | `tests/integration/test_unique_creators_record.py::test_record_writes_a_missing_record` | Not run |
| AC-24 | 5 | `tests/integration/test_unique_creators_record.py::test_record_releases_the_previous_address` (the consumer's restore, end to end: `report` clean, `enable` does not refuse) | Not run |
| AC-25 | 5 | `tests/integration/test_unique_creators_record.py::test_a_dry_run_writes_nothing` | Not run |
| AC-26 | 5 | `tests/integration/test_unique_creators_record.py::test_a_held_address_is_reported` | Not run |
| AC-27 | 5 | `tests/integration/test_unique_creators_record.py::test_before_enable_it_is_not_enforced` (both backends) | Not run |
| AC-28 | 5 | `tests/integration/test_unique_creators_record.py::test_capitals_are_refused` | Not run |
| AC-29 | 5 | `tests/test_unique_creators_command.py::test_record_refuses_reserved_and_system_creators` | Not run |
| AC-30 | 5 | `tests/integration/test_unique_creators_record.py::test_postgresql_checks_only` (PostgreSQL leg) | Not run |
| AC-31 | 5 | `tests/integration/test_unique_creators_record.py::test_a_changed_row_is_not_recorded` (`record_for_actor_as_read` wrapped to rewrite the actor row before it calls through) | Not run |
| AC-37 | 5 | `tests/test_unique_creators_command.py::test_record_missing_and_exempt` | Not run |
| AC-38 | 5 | `tests/integration/test_unique_creators_record.py::test_previous_is_checked` (parametrized: equal to current, reserved, capitals normalised, absent, names another actor) | Not run |
| AC-39 | 5 | `tests/integration/test_unique_creators_record.py::test_previous_is_kept_when_the_record_step_fails` (a held address with `--previous`) | Not run |
| AC-40 | 5 | `tests/test_unique_creators_command.py::test_record_store_fault_exits_2` (a helper patched to raise `DbError`) | Not run |
| AC-32 | all | manual: read the CHANGELOG entries and the two docs passages; `sphinx-build -W` passes — prose | Not run |

The unit tests run on DynamoDB only (`tests/_adoption_helpers.py:30`). The
integration tests run on both backends in the Full tier and are each
phase's PostgreSQL coverage. In `test_unique_creators_record.py`, the tests
that assert a write (AC-23 to AC-26, AC-28, AC-31, AC-38, AC-39) carry
`skipif(not DYNAMODB)` as `test_unique_creators_command.py:127` does; AC-30
carries `skipif(DYNAMODB)`; AC-27 runs on both.

## Spec Delta

### `thoughts/specs/trust-establishment.md` (new spec, `partial`: the answer to a trust request, its refusals, the approval of an unverified request)

- **ADDED** (Answer to a trust request) — When a peer's trust request carries no `secret`, the actor generates one and the 202 answer carries it. (AC-1)
- **ADDED** (Answer to a trust request) — When a peer's trust request carries a `secret`, the 201 or 202 answer carries that secret. (AC-2)
- **ADDED** (Answer to a trust request) — An answer to a trust request (a creation or a re-pair) for a row this actor has not approved carries no `verification_token`. (AC-3)
- **ADDED** (Answer to a trust request) — A proven re-pair's answer carries the new secret it sent; one whose read-back holds another secret answers 403 with no secret. (AC-5, AC-11)
- **ADDED** (Answer to a trust request) — A creation's answer carries the secret written for that request, whatever the stored row or an application hook does before the answer is sent. (AC-10)
- **ADDED** (Pairing without a secret) — A requester that sent no secret and serves an approved row naming this actor that accepts the answered secret is approved, verified, by the owner's approval. (AC-4)
- **ADDED** (Refusals) — A peer's trust request whose `baseuri` is not a plain http(s) URL, or whose `id` is not a plain id, answers 400 and stores nothing. (AC-6)
- **ADDED** (Refusals) — Each refusal of a trust request carries a JSON `error` naming its reason. (AC-12)
- **ADDED** (Approval) — The owner's approval of a request that did not verify, and still does not, answers 403 and leaves the row unapproved. (AC-7)
- **ADDED** (Pending status) — A pending row's own peer, with its secret as bearer, reads the row: 202, without `verification_token`. (AC-8)
- **DECISION** — The answer to a trust request carries only a secret its receiver sent or was issued for that request, and never the verification token while unapproved (owner, 2026-11-21).
- **DECISION** — A request without a secret is accepted; requesters SHOULD send one, and a lost answer to such a request is the owner's to clear (owner, 2026-11-21).

### `thoughts/specs/trust-permissions.md`

- **ADDED** (Notifications) — A permission change is not sent to a peer with an OAuth2 peer id (`oauth2:`, `oauth2_client:`, `oauth2_interactive:`) and logs nothing above DEBUG for it, on the sync and the async path; any other peer whose trust has no base URI logs a WARNING. (AC-14, AC-15)

### `thoughts/specs/mcp-server.md`

- **ADDED** (Handshake) — `initialize` announces `serverInfo.version` from `with_mcp(server_version=…)`, or the library's version when it is not set; `with_app_version()` does not change it. An empty or non-string value is refused at configuration. (AC-16, AC-17, AC-33)
- **ADDED** (Authorization) — A client whose connection was deleted gets a new code only after the user acts on an ActingWeb page, and the reconnect starts from a fresh grant. (AC-18, AC-19)
- **ADDED** (Authorization) — A disconnect removes the actor's unexchanged authorization codes for the client along with its tokens, fail closed; a code from before the disconnect answers `invalid_grant`, also after a reconnect, and an exchange in flight during the disconnect leaves no working token. (AC-20, AC-22, AC-34, AC-35, AC-36)
- **DECISION** — The disconnect sweeps codes; the code exchange and the refresh grant do not look up a trust (owner, 2026-11-21).

### `thoughts/specs/operator-commands.md`

- **ADDED** (`actingweb-unique-creators record`) — `record --actor ID [--previous ADDR] [--apply]` records one actor's current creator. It never scans; a dry run writes nothing. (AC-23 to AC-31, AC-37 to AC-40)
  - On DynamoDB it writes the missing record. With `--previous`, after the record step succeeded, it releases that address's record when it names this actor.
  - On PostgreSQL it only checks, and `--previous` answers `not-kept`.
  - Record step: `recorded`, `written`, `verified` (PostgreSQL), `exempt` (exit 0); `missing`, `held-by <id>`, `not-enforced`, `changed`, `refused` (exit 1).
  - Previous step: `released`, `absent`, `not-kept` (exit 0); `not-this-actor`, `changed`, `skipped` (exit 1, or the record step's code when skipped). An invalid `--previous` is refused before any read (exit 1).
  - A store fault: exit 2.
- **DECISION** — `record` neither lowercases a stored creator, nor writes before `enable`, nor searches for orphans; `resolve`, `enable` and `report` do those (owner, 2026-11-21).

## Phase 1: the trust request's answer, its refusals, and the peer request path

### Changes

- **Commit 0 (before the phase commit): reservation and wire ownership.**
  1. Apply phase 1's handler change locally (the answer and the error bodies). Run the wire suite (`-m wire -p no:rerunfailures`) and list every row that differs. Expected: WT3, and the 403 rows of trust requests (WT2, WV4), in both topologies.
  2. Discard the change to `actingweb/handlers/trust.py` only, and delete `tests/integration/wire/*.actual.json`.
  3. In `tests/integration/wire/rows.toml`, add `"trust-request-answer-secret" = []` under `[reserved]`, and `trust-request-answer-secret:1` to the `owners` of each row listed.
  4. Commit `rows.toml` alone.
- `actingweb/handlers/trust.py`:
  - `_trust_request_answer` drops only `verification_token` while the row is unapproved. Its docstring says why the secret stays.
  - `TrustRelationshipHandler.post` builds the answer body and the status from a copy of the written row before `trust_request_received` runs, and passes the hook a copy.
  - `_re_pair` answers only when the returned row holds the secret the request sent. Otherwise it logs a warning and refuses as an unproven re-pair.
  - The five peer-facing refusals of `post` (`:497-544`, `_re_pair`'s 403) write `{"error": "<reason>"}` with `Content-Type: application/json`, the way `_refuse_unverified_approval` does.
- `tests/integration/wire/` - re-record the rows from commit 0 by id, each with the dated `reason` line "2026-11-21 the answer to a trust request carries its secret, never the verification token while unapproved; its refusals carry an error body (trust-request-answer-secret:1)". The phase commit carries `Wire-Phase: trust-request-answer-secret:1`.
- `docs/protocol/actingweb-spec.rst` (1.5, in place):
  - The creation-response paragraph (`:2274-2277`): while unapproved, the answer MUST NOT carry `verification_token`; it carries `secret`, the one sent or the one B generated.
  - The paragraph on requests without a secret (`:2282-2285`):
    - requesters SHOULD send a secret;
    - after a 202 to a request without one, the requester keeps the answered secret in its own relationship toward B, approved, and B's manual approval repeats the verification with it (an approved relationship naming B, and `/meta`; no `verify` match);
    - a lost answer cannot be retried, and B's owner deletes the pending row.
  - The request table's `secret` row (`:2344`): B MAY generate one and returns it.
  - The refusals carry a JSON `error`.
  - The 1.5 change-list line (`:195-196`) is corrected to match.
- `CHANGELOG.rst` `Unreleased`:
  - FIXED: in 4.0.0rc1 the answer to a trust request carried no `secret`, so a request sent without one could never be approved. Then the cause, then a **Behavior change:** sentence (relative to rc1; 3.15.1 answered the secret too). A **Check:** sentence: rows rc1 created from requests without a secret stay pending, and the owner deletes them; requesters SHOULD send a secret.
  - **Behavior change:** `trust_request_received` gets a copy of the row, and the answer and its status reflect the row as written, not anything the hook does.
  - The refusals' JSON body.
- `docs/migration/v4.0.rst`:
  - The table row "The answer to a trust request" (`:3480`): Before is the whole row (flags as strings, `secret`, `verification_token`). After is flags as booleans, `secret`, and no `verification_token` while unapproved.
  - The prose at `:3172-3175` and `:2842-2843` says the same, with a **Behavior change:** for the token.
- `docs/reference/security.rst:127` - the answer carries `secret`, never the token while unapproved.
- `docs/reference/hooks-reference.rst` (the `trust_request_received` entry, around `:557`) - `trust_data` is a copy.
- Sweep `docs/` (`grep -rn "verification_token\|trust request" docs/`) for any other statement that the answer withholds the secret. Read `docs/sdk/developer-api.rst:210-220` once.
- `tests/test_trust_re_pair.py`:
  - `Receiver.request(new_secret=None)` sends no `secret` key.
  - `_put` becomes a module-level helper.
- `tests/integration/test_trust_flow.py` - the new class `TestPeerTrustRequest` (xdist group `trust_peer_request`, uuid-suffixed creator, `http://127.0.0.1:9` as the requester's base URI; only the approval's re-check in `test_006` fetches, and it is refused at once).
- `tests/integration/XDIST_GROUPS.md` - a row for `trust_peer_request`.
- `thoughts/research/2026-11-21-trust-request-answer-secret.md` - the renamed test's name.
- `thoughts/todo/` - two todos, with `INDEX.md` rows:
  - JSON error bodies for the remaining bare refusals in `handlers/`;
  - a non-string `secret` answers 500, and `enable` records reserved `#…` creators.

### New Tests (written first: `/implement_plan` sees them fail before coding, except those marked regression)

- `tests/test_trust_re_pair.py::TestTheAnswerCarriesTheSecret`:
  - `test_a_request_without_a_secret_gets_the_generated_one` — AC-1: no `secret` key; 202; `secret` non-empty and equal to the stored row's; no token.
  - `test_a_request_with_a_secret_gets_it_back` — AC-2: the sent secret is bound to a local, the request goes under `_peer_answers` with auto-accept off; 202; `body["secret"] == sent`.
  - `test_a_generated_secret_pairs_on_approval` — AC-4:
    - a fake peer answers `{"peerid": <A>, "approved": true}` only for `Bearer <answered secret>` (404 otherwise), and serves `/meta` naming the peer;
    - `actingweb.actor.requests.post` is patched to 204;
    - the approving PUT answers 204, and the row is approved and verified.
    - Negative leg: a fake holding another secret gives 403, and the row stays unapproved.
  - `test_the_answer_is_the_row_written` — AC-10:
    - the hook overwrites the stored secret through a fresh `Trust(...).modify(secret=X)`, and mutates `trust_data["secret"]` and `trust_data["approved"]`;
    - afterwards the stored row holds X, `body["secret"] == sent != X`, there is no token, and the status is 202.
  - `test_a_re_pair_answers_only_its_own_secret` — AC-11: `replace_trust_secret` is stubbed to return another secret; 403, `secret` absent.
- `tests/test_trust_re_pair.py::TestTheRefusalsSayWhy::test_each_refusal_has_an_error_body` — AC-12: one case for each of the five refusals; JSON `error`, the expected status.
- Changed:
  - `TestTheEdgesAfterReverify8::test_a_pending_requests_answer_carries_no_token` — AC-3: `secret` present, no token.
  - `TestTheRePairAnswerAfterReverify9::test_a_re_pair_of_an_unapproved_row_answers_without_its_token` — AC-3, AC-5: `body["secret"] == new`.
  - `tests/test_trust_answer_flags.py::test_an_unapproved_answer_has_booleans_and_no_token` (renamed) — AC-3.
- `tests/integration/test_trust_flow.py::TestPeerTrustRequest`:
  - `test_001_create_actor` — setup.
  - `test_002_request_with_invalid_peer_is_refused` — AC-6, AC-12:
    - `baseuri: "testurl"` gives 400 with an `error` body;
    - a valid base URI with `id: "a/b"` gives 400;
    - `GET /trust?peerid=testid` is empty.
  - `test_003_request_without_secret_answers_its_secret` — AC-1: 202; `secret`; `approved` and `verified` false; no token; `Location` set.
  - `test_004_peer_reads_its_pending_row` — AC-8.
  - `test_005_wrong_secret_is_refused` — regression: 403.
  - `test_006_owner_cannot_approve_unverified_request` — AC-7 (regression).
  - `test_007_delete_actor` — cleanup; expects 2xx although the peer cannot be told.

### Failure Scenarios

- A concurrent request or a hook changes the row between the write and the answer - the answer is built first; `test_the_answer_is_the_row_written`.
- A re-pair's read-back returns a row another request wrote (the owner deleted it, then a stranger filed a request) - 403, no secret; `test_a_re_pair_answers_only_its_own_secret`.
- The answer to a request without a secret is lost - the requester cannot retry; documented (AC-13), the owner deletes the row.
- The change moves a wire row not listed in commit 0 - an unowned row fails `verify_groups.py` and CI; loud.
- A host on CI serves port 9 and never answers - the 5 s read timeout and the 15 s deadline bound `test_006`; it still passes.

### Verification

- [ ] Fast tier from `CLAUDE.md` `### Checks`, verbatim
- [ ] Wire suite: `poetry run pytest tests/integration -m wire -p no:rerunfailures`; after committing, `poetry run python tests/integration/verify_groups.py`
- [ ] Full tier before the phase commit (both backends; docs with `-W`)
- [ ] Manual (AC-9, AC-13): read the passages against the ACs
- [ ] Before handing the BlazeMeter edits over: replay the whole exported flow (37 steps, `associate`, with the edits below) against the branch's demo in local QA mode, and record it in the research note

### Implementation Status: Complete

### Notes (implementation, 2026-11-21)

- Commit 0 (`97ca3a9`): the dry run moved exactly WT2 and WT3 (both topologies) and WV4. WT3 gains `secret` in the 202 answer; WT2 and WV4 gain the 403's `{"error": "Existing trust not verified"}` body. Also corrected the stale `rows.toml` note on CI's checkout depth.
- The refusal helper is `TrustRelationshipHandler._refuse_request(status, reason)`; `TrustHandler.post`'s own "Reserved relationship name" (the initiator's `POST /trust`) is unchanged: not a peer-facing refusal of a trust request.
- The spec already said the requester MUST send `secret` (B MAY accept without); kept, with "SHOULD therefore send a secret" in the new paragraph on requests without one, rather than weakening MUST to SHOULD.
- `TestTheRefusalsSayWhy`'s unproven case first used `Bearer not the secret`, which crashed basic auth (`auth.py:156`, `authz.split(" ")` unpacked into two names): an existing 500 on a peer-reachable route. Filed with the plan's two deferred items in one todo, `handler-refusal-bodies-and-input-robustness.md` (the plan named two files; one covers all four items).
- `_put` stays a method on `TestTheEdgesAfterReverify8`, delegating to the new module-level `_owner_put`.
- Diff review (codex: no findings; fresh-context Claude): the re-pair read-back guard now has its own WARNING ("the secret was swapped, but the row read back holds another secret") and answers 403 `{"error": "Trust was replaced; pair again"}`, not "Existing trust not verified"; the spec's error-body sentence is narrowed to the refusals that carry one; `hooks-reference.rst` says a hook that approves still answers 202. Left to the todo: the 403 of a refused creation and the 400 for a body that is not JSON have no body yet, and a refused re-pair's reason is not mapped (each moves wire rows).
- Full tier on the pre-review diff: DynamoDB 8411 passed, PostgreSQL 8180 passed, docs clean; after the review fixes (one handler branch, docs): fast tier and a clean docs build.
- BlazeMeter replay on the branch: recorded in the research note ("Replay of the whole flow on the rc2 branch"). The selfproxy steps need `ENABLE_DEVTEST=true`; step 34 answers `200 {}` locally (not this branch's path), to check on the rc2 deploy.

---

## Phase 2: no permission notification for OAuth2/MCP clients

### Changes

- `actingweb/trust_permissions.py` - a helper (next to `is_client_peer`, `:163`) that matches any `OAUTH2_SOURCES` prefix (`trust_lookup.py:15`). Both `_notify_peer` (`:406`) and `_notify_peer_async` (`:482`) return after a DEBUG line at their top for such a peer, before the trust read and the proxy. Each store notifies one peer; there is no loop to move the skip into. The WARNINGs at `:466` (sync, via `aw_proxy.py:275`) and `:524-530` (async) stay for every other peer.
- `CHANGELOG.rst` `Unreleased` - FIXED: one WARNING per OAuth2/MCP client on every permission change; the cause; now skipped at DEBUG. A consumer who alerts on that WARNING sees it only for peers that should have a base URI.

### New Tests

- `tests/test_trust_permissions_notify.py::test_an_oauth2_peer_is_not_notified` — AC-14: parametrized over the three prefixes and both paths; a trust row that exists and has no base URI (otherwise it tests the "no trust relationship" warning); no HTTP call (patched), no record above DEBUG.
- `tests/test_trust_permissions_notify.py::test_a_peer_without_baseuri_still_warns` — AC-15 (regression), both paths, with a plain peer id that contains `oauth2` but not as a prefix.

### Failure Scenarios

- A real peer whose trust lost its base URI is silenced - prevented: only OAuth2 prefixes are skipped, which a peer cannot choose (`trust.py:28-33`); AC-15. A pre-4.0 row with such a prefix and a real base URI is not known to exist; were one to, it would stop being notified (accepted: the prefixes have named OAuth2 rows since they were introduced).

### Verification

- [ ] Fast tier; Full tier before the phase commit

### Implementation Status: Not Started

---

## Phase 3: `with_mcp(server_version=…)`

### Changes

- `actingweb/interface/app.py` `with_mcp` - an optional keyword-only `server_version: str | None = None`, validated as `with_app_version` (`:429-438`) validates, stored as `_mcp_server_version`, and re-applied in `_apply_runtime_changes_to_config` (`:287-290`) as `server_name` is.
- `actingweb/config.py` - an `mcp_server_version: str | None = None` default next to the MCP options (`:484`).
- `actingweb/handlers/mcp.py:1207` - `serverInfo.version` is `config.mcp_server_version or __version__`. It is read per request (`:1203-1207`); no singleton caveat in the docstring.
- `docs/` MCP configuration (the guide that documents `server_name`) - `server_version`, and that `initialize` answers it without authentication by default (`require_auth_for_initialize=False`), so it is public. `CHANGELOG.rst` `Unreleased` ADDED.

### New Tests

- `tests/test_mcp_server_name.py` (extended):
  - `test_the_app_announces_its_version` — AC-16, through `ActingWebApp.with_mcp`, not `make_mcp_config`.
  - `test_the_default_is_the_library_version` — AC-17 (regression), with and without `with_app_version("9.9")`.
  - `test_an_invalid_server_version_is_refused` — AC-33.

### Failure Scenarios

- A missing re-apply line leaves the keyword silently ignored on the cached config - AC-16 goes through the app. A wire recording of `initialize` (the `<library-version>` normalisation, `rows.toml` "2026-11-18 the library version recorded as <library-version>") is unchanged by the default.

### Verification

- [ ] Fast tier; Full tier before the phase commit

### Implementation Status: Not Started

---

## Phase 4: a disconnected MCP client needs the user again

### Changes

- `actingweb/oauth2_server/token_manager.py`:
  - `_revoke_matching_tokens` (`:1766`): before its token snapshots, it removes every row in the actor's `mcp_auth_codes` bucket whose `client_id` matches (used or not). Each removal deletes the code row, its system-actor index row (`AUTH_CODE_INDEX_BUCKET`) and its `google_token_<code>` row with `delete_confirmed` (`:2067`), not `_remove_auth_code` (`:1211`, which swallows faults). An unconfirmed removal counts as a fault, so the call raises `TokenStoreUnavailable` and `Trust.delete` keeps the row (AC-36). Both disconnect branches reach it: `revoke_connection_tokens` and `disable_client` (`trust.py:209-226`); the implementer confirms `disable_client`'s path, and the tests run on a connection to an anonymous client (the usual case).
  - `exchange_authorization_code` (`:231`): after it mints, and next to `_generation_still_matches` (`:356`), a strict read of its own consumed code row. If the row is gone (the sweep removed it), it revokes the access and refresh token it minted and answers `None` (`invalid_grant`). Ordering argument: if that read still sees the row, it ran before the sweep's removal, so the minted tokens were written before the sweep's token snapshots, which revoke them. A fault on that read raises `TokenStoreUnavailable`, never a token.
  - The refresh grant is unchanged.
- Before the phase commit, check that the change moves no wire row (a disconnect's HTTP exchange is unchanged; WG14-WG16 exchange codes with no disconnect). If one moves, take ownership in an earlier commit as in phase 1.
- `CHANGELOG.rst` `Unreleased` - FIXED: an authorization code issued just before a disconnect could still be exchanged afterwards, also after the user reconnected the client; a disconnect now removes the client's codes with its tokens. Also state that a reconnect always needs the user on an ActingWeb page (the consumer's question).
- `docs/reference/security.rst:119` (the disconnect paragraph) - the same, in one sentence.

### New Tests

- `tests/integration/test_oauth2_trust_binding.py`, reusing `Flow` and `wire_oauth`. Every disconnect goes through the owner's `DELETE /<id>/trust/<rel>/<peer>`, never a raw database delete, so the sweep runs:
  - `test_a_disconnected_client_needs_the_user_again` — AC-18 (regression): `honest()`, `token`, disconnect, then `paused()` shows "Confirm access" and there are no rows until Approve.
  - `test_a_reconnect_starts_from_a_fresh_grant` — AC-19 (regression): an override stored before the disconnect; after `honest()`, the default type and no override.
  - `test_a_code_from_before_the_disconnect_is_refused` — AC-20: a code issued and not exchanged, disconnect, the code exchanged: `invalid_grant`; the three rows are gone.
  - `test_an_old_refresh_token_stays_dead_after_a_reconnect` — AC-22 (regression).
  - `test_a_code_from_before_the_disconnect_is_refused_after_a_reconnect` — AC-34: a code held back, disconnect, `honest()` again, then the held code: `invalid_grant`. Fails today.
- `tests/test_oauth2_disconnect_sweeps_codes.py` (unit, `TokenManager` and `Trust.delete` on DynamoDB Local):
  - `test_a_sweep_during_an_exchange_leaves_no_live_token` — AC-35: `_create_refresh_token` wrapped to call `revoke_client_tokens` before it returns; afterwards neither minted token validates.
  - `test_a_code_that_cannot_be_removed_keeps_the_row` — AC-36: `delete_confirmed` patched to fault for the code bucket; `Trust.delete` raises `DbError` and the row is still there.

### Failure Scenarios

- A store fault while the sweep removes a code - raises; the row stays as the retry handle (AC-36).
- An exchange in flight during the disconnect - the post-mint read, or the sweep's token pass, revokes what it minted (AC-35).
- A fresh authorization the user approves while a disconnect runs - it writes a new trust and a new code; the user acted, so this is a reconnect, not a leak.
- The sweep reads an actor's whole code bucket - bounded by codes issued in the last 10 minutes; the token buckets it already reads are larger.

### Verification

- [ ] Fast tier; wire suite; Full tier before the phase commit

### Implementation Status: Not Started

---

## Phase 5: one actor's creator record

### Changes

- `actingweb/maintenance/unique_creators.py`:
  - `record_creator(config, actor_id, *, previous: str | None = None, apply: bool) -> RecordOutcome` (public, in `__all__`, documented). `RecordOutcome` carries the record step's outcome, the holder's id for `held-by`, and the previous step's outcome. It never scans. The rules use `creator_rules` (`normalise_creator`, `is_exempt`, `is_reserved`, `is_system_actor`), never restated.
    - **`previous`, first:** normalised as creators are. Equal to the actor's current creator, exempt, or reserved → refused before any read (AC-38).
    - **DynamoDB:**
      1. Consistent read of the actor → `missing` (AC-37).
      2. The creator rules: exempt or `#dup-` → `exempt`, exit 0; reserved or a system creator off a system actor → `refused`; capitals → `refused`.
      3. `_backfill_state()` → `not-enforced` unless `complete`.
      4. `_settle_record` (`:610-666`), refactored to return `held-by` and `changed` apart and reused here (the `enable` path keeps its behaviour): names this actor → `recorded`; absent → `record_for_actor_as_read` → `written`; held by an actor that holds it → `held-by`; naming an actor that does not hold it → `move_stale_record` → `written`; a failed condition → `changed`.
      5. With `previous`, only after `recorded` or `written` (else `skipped`, AC-39): a consistent read of that record. None → `absent`; names another actor → `not-this-actor`; names this actor → `release_stale_record(previous, actor_id)` → `released`, or `changed` when its condition fails.
    - **PostgreSQL:** the index state (`not-enforced`), the same rules, then `held-by` if another row has the same `lower(creator)`, otherwise `verified`. `previous` answers `not-kept`. Nothing is written.
    - Without `apply`, it reports what it would do (`would-write`, `would-release`) and writes nothing.
    - A store fault: the helpers' `DbError` is folded into `StoreUnavailable`, as `collect` does (`:390`).
  - `main`/`_run` - a `record` subcommand (`--actor` required, `--previous`, `--apply`), branched in `_run` before `collect`. One output line per step. Exit codes as in the Spec Delta; `StoreUnavailable` → 2 (`:1503`). `preflight(writing=apply)` applies.
  - `_raw_actor` moves from `tests/integration/test_unique_creators_command.py:66` to a shared helper both files import.
- Operator docs for `actingweb-unique-creators` (where `enable`/`resolve` are documented in `docs/`) - `record`, its outcomes, the exit codes, and the advice to run a restore and its `record` with sign-ins for that address quiet (`held-by` means another actor took it; use `resolve`).
- `CHANGELOG.rst` `Unreleased` - ADDED.
- `tests/integration/XDIST_GROUPS.md` - the new file joins the `unique_creator` group.

### New Tests

- `tests/integration/test_unique_creators_record.py` (xdist group `unique_creator`; `_raw_actor` seeds a restore-shaped row):
  - `test_record_writes_a_missing_record` — AC-23.
  - `test_record_releases_the_previous_address` — AC-24: rename *older* → *newer*, restore *older* by raw write, `record --previous newer --apply`; `report` clean; `enable --apply` not refused.
  - `test_a_dry_run_writes_nothing` — AC-25.
  - `test_a_held_address_is_reported` — AC-26.
  - `test_before_enable_it_is_not_enforced` — AC-27, both backends.
  - `test_capitals_are_refused` — AC-28.
  - `test_postgresql_checks_only` — AC-30 (`skipif(DYNAMODB)`).
  - `test_a_changed_row_is_not_recorded` — AC-31: `record_for_actor_as_read` wrapped to rewrite the actor row before it calls through (single-threaded, deterministic).
  - `test_previous_is_checked` — AC-38, parametrized.
  - `test_previous_is_kept_when_the_record_step_fails` — AC-39.
  - Write-asserting tests carry `skipif(not DYNAMODB)` (see Traceability).
- `tests/test_unique_creators_command.py`:
  - `test_record_refuses_reserved_and_system_creators` — AC-29; `_run` with `argparse.Namespace`.
  - `test_record_missing_and_exempt` — AC-37.
  - `test_record_store_fault_exits_2` — AC-40.

### Failure Scenarios

- A sign-in with the restored address before `record` runs creates a second actor - `held-by` (AC-26), `--previous` kept (AC-39), and the docs send the operator to `resolve`.
- The actor is renamed while `record` runs - the `actor_as_read` condition fails: `changed` (AC-31).
- `--previous` names a record that another actor holds - `not-this-actor`, nothing removed (AC-38); `release_stale_record`'s own condition (`actor_id == this actor`, `db/dynamodb/actor.py:1028`) is the second guard.
- A helper raises `DbError` - folded to `StoreUnavailable`, exit 2 (AC-40).
- An `--apply` run without an explicit `AWS_DB_PREFIX` - refused by `preflight`, as for every command.

### Verification

- [ ] Fast tier; Full tier before the phase commit (both backends)
- [ ] Manual: `actingweb-unique-creators record --help` shows the options

### Implementation Status: Not Started

---

## Follow-up (outside this plan)

- `/release` 4.0.0rc2 once the PR merges; `actingwebdemo` deploys the pin.
- The owner edits the BlazeMeter trust suite:
  - Both peer-style creates use `https://testurl.example` (trust1) and `https://test.example` (trust2) as base URIs; the ids stay.
  - "Approve the new trust relationship" expects 403.
  - "Get the new trust relationship as peer" after it expects 202 with `approved: false`.
  - The same GET before approval, with the right token, expects 202.
  - The "secret Not Empty" assertion and the `secret1`/`secret2` variables need no edit.
  - The steps after "Delete the changed trust relationship" passed on rc1 and are unaffected.
- Tell the consumer the triage outcome; its four items land in rc2.
- Success measures: the BlazeMeter trust suite passes on rc2; the consumer's suite on rc2 shows no new failure.

---

## Evaluation Notes

**Outside voice:** codex (`codex exec -s read-only`) and a fresh-context Claude reviewer, on the phase-1 draft.

| # | From | Finding (`file:line` quoted) | Disposition |
| --- | --- | --- | --- |
| 1 | Architecture | `tests/integration/verify_groups.py:143` "if owner.split(":", 1)[0] not in reserved" — commit 0 must reserve the plan | Folded: commit 0 adds the `[reserved]` entry |
| 2 | Architecture | `tests/integration/verify_groups.py:58-62` "verify_group_documented" — the new xdist group needs a row | Folded |
| 3 | Architecture, Tests | `tests/test_trust_re_pair.py:152` "answer = json.dumps({"verification_token": token, "approved": approved})"; `actor.py:2768` "body.get("peerid") == self.id" — AC-4 as drafted could not pass, and ignored the bearer | Folded: a bearer-checking fake, `requests.post` patched, a negative leg |
| 4 | Architecture, Tests | `tests/test_trust_re_pair.py:2499` "class TestTheRePairAnswerAfterReverify9:" — the node ID named the wrong class | Folded |
| 5 | Architecture, Security, Tests | `actingweb/actor.py:3238` "updated = trust.Trust(…).get()" — a re-pair answers a read-back | Folded: AC-11; DECISION and research corrected |
| 6 | Architecture, Security | `actingweb/handlers/trust.py:593` "trust_data=new_trust," — a hook could change the answer | Folded: AC-10 |
| 7 | Architecture, Tests, Scalability | `actingweb/actor.py:3049` "if not secret or len(secret) == 0:" — a request without a secret fetches nothing | Folded: rationale corrected |
| 8 | Architecture | `actingweb/handlers/trust.py:508` "if not is_valid_peer_id(peerid) or not is_valid_peer_baseuri(baseuri):" — the `id` refusal had no test | Folded: `test_002` |
| 9 | Architecture | `v3.15.1:actingweb/handlers/trust.py:199` "out = json.dumps(new_trust)" — "matches 3.x" overstated | Folded |
| 10 | Tests | `tests/test_trust_re_pair.py:898` "return w.request(peer, _new_secret())" — no handle on the sent secret | Folded |
| 11 | Tests | `tests/test_trust_re_pair.py:114-115` — the helper always sends a `secret` key | Folded |
| 12 | Tests | `tests/test_trust_re_pair.py:1797` "def _put(self, …" — reuse by subclassing collects tests twice | Folded |
| 13 | Tests | research run B (approve 403 today) vs "written first … fail" | Folded: regression tests marked |
| 14 | Tests | `tests/test_trust_re_pair.py:1765` — thinner integration assertions | Folded |
| 15 | Tests | `tests/_adoption_helpers.py:30` "database: str = "dynamodb"" — the unit tests are DynamoDB-only | Folded: the integration tests are the PostgreSQL coverage |
| 16 | Usability | `docs/reference/security.rst:127` "a trust request's 202 answer carries neither" | Folded |
| 17 | Usability | `docs/migration/v4.0.rst:3480-3482` — the token's removal was never told | Folded |
| 18 | Usability | `docs/protocol/actingweb-spec.rst:2284-2285` — the two-step pairing undescribed | Folded |
| 19 | Usability | `CHANGELOG.rst:308-310` — the symptom sentence was too narrow | Folded |
| 20 | Usability | research "first 16 steps were replayed" — the BlazeMeter follow-up was vague | Folded: exact values, a full replay |
| 21 | Usability | `actingweb/handlers/trust.py:516` "set_status(400, "Invalid id or baseuri")" — no reason reaches the peer | User decided: JSON error bodies on the trust request's refusals (AC-12); the rest is a todo |
| 22 | Security | research "the row's status and its deletion only" — misses the `peer_approved` notification (`handlers/trust.py:841`) | Folded: research corrected |
| 23 | Security | `actingweb/trust.py:519` "Found a non-unique token" — a duplicate-secret signal | Rejected: existing, not widened |
| 24 | Scalability | `tests/integration/test_trust_flow.py:14` — use a distinct xdist group | Folded |
| 25 | Usability | spec `:2449` vs `actor.py:2764-2769` — what B checks at approval | Folded into 18 |
| 26 | Outside voice | `actingweb/actor.py:3117-3120` "a pending row exists and the request did not verify" — a lost 202 to a request without a secret is a dead end | User decided: documented (AC-13) |
| 27 | Outside voice | `actingweb/actor.py:2347-2348` "if not secret … return False" — no implementation uses the path; "restored flow" overstated | Folded: framed as a protocol path; requesters SHOULD send a secret |
| 28 | Outside voice | plan CHANGELOG "an rc1 adopter … needs no change" — rc1's stuck rows | Folded: **Check:** sentence |
| 29 | Outside voice | `actingweb/handlers/trust.py:615` "if str(new_trust.get("approved")).lower() == "true":" — a hook could change the status | Folded: CHANGELOG **Behavior change:** and hooks-reference (AC-13) |
| 30 | Outside voice | `verify_groups.py` "a failed comparison's output is left over" — commit 0 leaves `.actual.json` files | Folded |
| 31 | Outside voice | research `:129` — the renamed test's old name | Folded |
| 32 | Outside voice (codex) | AC-11 stubs `replace_trust_secret` | Folded: marked handler-only |
| 33 | Outside voice (codex) | `verify_groups.py` "Owners are read at the commit's first parent" — commit 0 must stay separate | Folded: never squashed on the branch |
| 34 | Research (phase 4) | `token_manager.py:1845-1847` — codes are not swept; `exchange_authorization_code` checks no trust | User decided: refuse at exchange and refresh (AC-20 to AC-22) |
| 35 | Research (phase 5) | `db/dynamodb/creator.py:29-31` — no index by actor id | User decided: `--previous` |
| 36 | Security, Tests (2-5) | `handlers/mcp.py:1226-1247` cited for the trust lookup; it is `_require_mcp_peer_id` | Moot: phase 4 no longer looks up a trust |
| 37 | Security, Tests (2-5) | `trust_lookup.py:111-113` "if _tagged(trust, client_id): return trust" — a grant-time check passes after a reconnect; AC-22 passes today | User decided: sweep codes at disconnect; AC-21 dropped, AC-22 a regression, AC-34 added |
| 38 | Security, Outside voice (2-5) | `token_manager.py:339` "chain_id = self._new_chain_id()" — an exchange racing the disconnect mints an unswept chain | Folded: post-mint read of the consumed code; AC-35 |
| 39 | Tests (2-5) | `tests/integration/test_mcp_refresh_rotation_backend.py:29-30` — about 90 tests mint codes without a trust | Moot with the sweep (no grant-time check) |
| 40 | Tests (2-5) | `docs/migration/v4.0.rst:2657` "Codes it creates itself with create_authorization_code" — a grant check would break such apps | Moot with the sweep |
| 41 | Outside voice (2-5) | `token_manager.py:1211` "except Exception … TTL reaps the code" — the sweep must not swallow faults | Folded: `delete_confirmed`; AC-36 |
| 42 | Security, Tests (2-5) | `trust_permissions.py:406` sync `_notify_peer`; `:466` its WARNING — only the async path was planned | Folded: both paths |
| 43 | Tests (2-5) | `trust_lookup.py:15` "OAUTH2_SOURCES = (…)" — other OAuth2 prefixes still warn | Folded: all three prefixes |
| 44 | Outside voice (2-5) | `app.py:281` "self._config.version = self._app_version or __version__" — overlap with `with_app_version` | User decided: new keyword, then library; AC-17 also with `with_app_version` |
| 45 | Tests, Outside voice (2-5) | `app.py:287-290` re-apply warning; `app.py:438` validation | Folded: re-apply line; AC-16 through the app; AC-33 |
| 46 | Outside voice (2-5) | research `:102-104` "Today the fix is resolve --apply … then enable --apply" — phase 5 out of proportion | User decided: kept (`unique_creators.py:69` "--creator is refused" for `enable`: two full scans otherwise) |
| 47 | Security, Tests (2-5) | `db/dynamodb/actor.py:1020` "return False  # it holds the creator" — `--previous` outcomes mislabelled | Folded: `--previous` validated first; `absent`/`not-this-actor`; AC-38 |
| 48 | Security (2-5) | plan step 5 after step 4 "held-by" — release after a failed record step | Folded: `skipped`; AC-39 |
| 49 | Tests (2-5) | `unique_creators.py:610-666` `_settle_record` — step 4 duplicated | Folded: refactored and reused |
| 50 | Tests (2-5) | `unique_creators.py:1503` "except StoreUnavailable as e:" — `DbError` escapes exit 2 | Folded: folded as `collect` does; AC-40 |
| 51 | Tests (2-5) | `test_unique_creators_command.py:127` skipif — write tests on PostgreSQL | Folded: skip marks |
| 52 | Outside voice (codex, 2-5) | PostgreSQL `recorded` for a check | Folded: `verified` |
| 53 | Security, Tests (2-5) | spec delta outcome list lacked `missing`, `exempt` | Folded; AC-37 |
| 54 | Security (2-5) | phase-3 version disclosed by an unauthenticated `initialize` | Folded: docs say it is public |

**Outside voice (phases 2-5):** codex (`codex exec -s read-only`) and a fresh-context Claude reviewer, after a security and a tests evaluator; architecture, scalability and usability were not re-run for phases 2-5.

**Unverified notes:**
- A non-string `secret` in the body may answer 500; not run (todo).
- A CI host serving the discard port would slow `test_006`; not checked against the runner image.
- `rows.toml:36-38` says "(CI's shallow checkout skips it)", but CI checks out full history (`.github/workflows/tests.yml:195-198`); a stale comment, worth fixing in commit 0.
- Phase 4: that `disable_client` (the owner's branch) reaches `_revoke_matching_tokens` was claimed by the outside voice from `client_registry.py:408`, not traced; the implementer confirms it.
- Phase 4: how a TTL-expired code row reads through `get_bucket` on each backend was not checked; the sweep removes such rows too, harmlessly.
- Phase 2: no pre-4.0 row with an OAuth2 prefix and a real base URI is known; not searched in a production store.
