# Verification: 4.0.0rc2 — the trust request's answer, and a consumer's rc1 findings

**Date:** 2026-11-21
**Plan:** thoughts/plans/2026-11-21-trust-request-answer-secret.md (and its iterations log, entries 1-4)
**Research:** thoughts/research/2026-11-21-trust-request-answer-secret.md, thoughts/research/2026-11-21-emm-4-0-rc1-feedback.md
**Branch:** fix/4.0.0-rc2-consumer-fixes
**Commit:** dec374e

## Automated Check Results

- **Browser QA:** N/A. No phase touches a page a user sees: the trust request is a peer's JSON API, and the OAuth2 pages are unchanged (phase 4 changes the disconnect sweep and the code exchange only). The demo's BlazeMeter flow was replayed over HTTP instead (research note, "Replay of the whole flow on the rc2 branch").
- **Second opinion:**
  - outside-voice: codex (`codex review --base master`, default brief only; the CLI refuses a custom prompt with `--base`) found nothing; a fresh-context Claude review gave the three findings below as issues 1-3.
  - built-in code review (high, no `--fix`): seven findings, folded in as issues 1, 2, 4, 5, 6 and 7; one rejected (see Issues Found, "Rejected").
  - built-in security review: no vulnerability above the confidence bar; it checked the answered secret, the re-pair reasons, body validation, the basic-auth parse, the OAuth2 notification skip, the code sweep and the CLI.
  - Per-phase diff reviews (codex and fresh-context Claude) ran during implementation for phases 1, 4 and 5; their findings were folded before each commit (plan, phase notes).
- `poetry run ruff check actingweb tests`: pass
- `poetry run ruff format --check actingweb tests`: pass
- `poetry run pyright actingweb tests`: pass (0 errors, 0 warnings)
- `poetry run python tests/integration/verify_groups.py`: pass (44 groups documented, wire registry consistent, Wire-Phase trailers match)
- `make test-all-parallel` (DynamoDB): pass, 8510 passed, 217 skipped, 2 xfailed (run on `dec374e`, this verification)
- `make test-all-parallel` (PostgreSQL): pass, 8264 passed, 463 skipped, 2 xfailed (same run)
- `sphinx-build -W ...`: pass
- Benchmarks: not run; no phase touched list storage or the attribute layer.

## Phase Verification

### Commit 0: reservation and wire ownership - VERIFIED

- `tests/integration/wire/rows.toml`: `"trust-request-answer-secret" = []` under `[reserved]`; `trust-request-answer-secret:1` added to the owners of WT2, WT3, WV4, in `97ca3a9`, before the re-record in `0b54881` (trailer `Wire-Phase: trust-request-answer-secret:1`). The dry run moved exactly those rows, as the plan predicted.

### Phase 1: the trust request's answer, its refusals, and the peer request path - VERIFIED

**Changes verified:**
- `actingweb/handlers/trust.py` `_trust_request_answer`: pops only `verification_token` while unapproved (matches plan).
- `TrustRelationshipHandler.post`: `answer`, `location` and `created` are computed before the hook; the hook gets `copy.deepcopy(new_trust)` (matches plan).
- `_re_pair`: a read-back holding another secret is refused with its own WARNING and `{"error": "Trust was replaced; pair again"}` (deviation from "refuses as an unproven re-pair": acceptable, the plan's review asked for a truthful reason).
- `_refuse_request`: the refusals carry a JSON `error` (matches plan; widened by iteration 3).
- Docs: protocol spec 1.5 (`docs/protocol/actingweb-spec.rst`, the creation-response paragraph, the paragraph on requests without a secret, the request table, the change list), `CHANGELOG.rst`, `docs/migration/v4.0.rst` (table row and prose), `docs/reference/security.rst:127`, `docs/reference/hooks-reference.rst` (`trust_data` is a copy; a hook's approval still answers 202).

**Tests verified:** listed under Acceptance Criteria; each was seen failing on the behaviour before the change (plan, phase 1 notes).

**Failure scenarios:** the hook or a concurrent request changing the row → `tests/test_trust_re_pair.py:2652` `test_the_answer_is_the_row_written`; a re-pair read-back of another row → `:2679`; a lost answer → documented (spec, CHANGELOG **Check:**); an unowned wire row → `verify_groups.py` passes; port 9 → `test_006` passes in both backend runs.

**Deviations:** one todo file instead of two (since renamed `handler-refusal-bodies.md`); the spec keeps "MUST send `secret`" and adds "SHOULD therefore send a secret". Both acceptable, recorded in the plan.

### Phase 2: no permission notification for OAuth2/MCP clients - VERIFIED

- `actingweb/trust_permissions.py` `is_oauth2_peer`: `prefix:` with the prefix in `OAUTH2_SOURCES`; both `_notify_peer` and `_notify_peer_async` return after a DEBUG line before the proxy or the trust read (matches plan).
- Failure scenario "a real peer silenced": `tests/test_trust_permissions_notify.py:92` covers `my-oauth2:peer`, which still warns.

### Phase 3: `with_mcp(server_version=…)` - VERIFIED

- `actingweb/interface/app.py` `with_mcp`: keyword-only, `_UNSET` sentinel, validated as `with_app_version`, re-applied in `_apply_runtime_changes_to_config` and passed to `Config(...)`; `actingweb/config.py` `mcp_server_version`; `actingweb/handlers/mcp.py` `serverInfo.version` is `config.mcp_server_version or __version__` (matches plan; sentinel instead of `None` default noted in the plan).
- `docs/quickstart/configuration.rst`: names `server_version` and that `initialize` discloses it.

### Phase 4: a disconnected MCP client needs the user again - VERIFIED

- `actingweb/oauth2_server/token_manager.py` `_revoke_matching_tokens`: reads the code bucket before the token snapshots; `_remove_auth_code_confirmed` removes the provider-token row, the index row, then the code row last, each with `delete_confirmed`; unconfirmed codes are counted apart and raise. `exchange_authorization_code` re-reads its consumed code (`_consumed_code_still_there`) after `_generation_still_matches`, and revokes what it minted when the row is gone or the read faults (matches plan and the phase review).
- `disable_client` reaches the sweep through `revoke_client_tokens` (`client_registry.py`), confirmed in implementation.
- `CHANGELOG.rst` FIXED entry and `docs/reference/security.rst` disconnect paragraph.

### Phase 5: one actor's creator record - VERIFIED (issue 3)

- `actingweb/maintenance/unique_creators.py` `record_creator`, `RecordOutcome`, `_run_record`, the `record` subparser branched before `collect` (matches plan). Deviation: `_settle_record` is not reused (its group semantics differ); acceptable, recorded.
- `docs/quickstart/deployment.rst` "Restoring one actor": outcomes, exit codes, dry run, quiet sign-ins, never beside `disable`.
- `tests/integration/XDIST_GROUPS.md`: the new file joins `unique_creator`.

### Iterations 1-4 - ISSUES FOUND (issue 1)

- Entry 1 (`actingweb/auth.py` `_parse_basic_credentials`): verified, `tests/test_auth.py:225` `TestMalformedBasicAuthorization`.
- Entries 2-3 (`actingweb/handlers/trust.py` body validation, `_RE_PAIR_REASONS`): verified with issue 2.
- Entry 4 (reserved creators): `enable`, the first start, `_record_lone_holder` and `report`'s unrecorded list skip them, but `resolve`'s group path does not (issue 1).

## Acceptance Criteria

| AC | Test | Asserts the behaviour? | Result |
| --- | --- | --- | --- |
| AC-1 | `tests/test_trust_re_pair.py:2590` - `assert body["secret"] == w.row(peer)["secret"]`; `tests/integration/test_trust_flow.py:716` - `assert data["secret"]`, `"verification_token" not in data` | Yes | Pass |
| AC-2 | `tests/test_trust_re_pair.py:2602` - `assert body["secret"] == sent` | Yes | Pass |
| AC-3 | `tests/test_trust_re_pair.py:2168` - `assert "verification_token" not in body`; `tests/test_trust_answer_flags.py:25` | Yes | Pass |
| AC-4 | `tests/test_trust_re_pair.py:2616` - `assert put.response.status_code == 204`, `row["approved"] is True and row["verified"] is True`; negative leg `:2635` - 403, notification not sent | Yes | Pass |
| AC-5 | `tests/test_trust_re_pair.py:2510` - `assert body["secret"] == new` | Yes | Pass |
| AC-6 | `tests/integration/test_trust_flow.py:699` - 400 with `{"error": "Invalid id or baseuri"}`; search answers `[]` | Yes | Pass |
| AC-7 | `tests/integration/test_trust_flow.py:755` - 403, then `approved in (False, "false")` (regression) | Yes | Pass |
| AC-8 | `tests/integration/test_trust_flow.py:736` - 202, `peerid`, no `verification_token` | Yes | Pass |
| AC-9 | manual: spec 1.5, CHANGELOG, migration guide, `security.rst:127` read against the AC | n/a | Pass |
| AC-10 | `tests/test_trust_re_pair.py:2652` - stored secret is the hook's, `body["secret"] == sent`, `body["approved"] is False` | Yes | Pass |
| AC-11 | `tests/test_trust_re_pair.py:2679` - 403, the stranger's secret not in the body (stubbed read-back) | Yes (handler-only) | Pass |
| AC-12 | `tests/test_trust_re_pair.py:2710` - five refusals, `json.loads(body) == {"error": reason}`; widened by `TestTheLastRefusalsSayWhy` (`:2811`) | Yes | Pass |
| AC-13 | manual: spec, CHANGELOG **Check:**, hooks reference read against the AC | n/a | Pass |
| AC-14 | `tests/test_trust_permissions_notify.py:72` - proxy, `Trust` and HTTP client not called; nothing above DEBUG; 3 prefixes x 2 paths | Yes | Pass |
| AC-15 | `tests/test_trust_permissions_notify.py:92` - a WARNING naming the peer, both paths (regression) | Yes | Pass |
| AC-16 | `tests/test_mcp_server_name.py:176` - `serverInfo.version == "2.3.1"` through `ActingWebApp.with_mcp` | Yes | Pass |
| AC-17 | `tests/test_mcp_server_name.py:186` - `== __version__`, also with `with_app_version("9.9")` (regression) | Yes | Pass |
| AC-18 | `tests/integration/test_oauth2_trust_binding.py:702` - no rows until Approve, then one (regression) | Yes | Pass |
| AC-19 | `tests/integration/test_oauth2_trust_binding.py:714` - relationship `mcp_client`, no override (regression) | Yes | Pass |
| AC-20 | `tests/integration/test_oauth2_trust_binding.py:744` - 400 `invalid_grant`, code, index and provider rows gone; `tests/test_oauth2_disconnect_sweeps_codes.py:45` | Yes | Pass |
| ~~AC-21~~ | dropped (owner, phase-4 review): the refresh grant gets no trust check; nothing in the code claims one | - | - |
| AC-22 | `tests/integration/test_oauth2_trust_binding.py:770` - 400 `invalid_grant` after a reconnect (regression) | Yes | Pass |
| AC-23 | `tests/integration/test_unique_creators_record.py:65` - exit 0, `_record_of(creator) == actor_id`; move branch `:89` | Yes | Pass |
| AC-24 | `tests/integration/test_unique_creators_record.py:75` - older recorded, newer gone, `report` 0, `enable --apply` 0 | Yes | Pass |
| AC-25 | `tests/integration/test_unique_creators_record.py:104` - `would-write`/`would-release`, records unchanged | Yes | Pass |
| AC-26 | `tests/integration/test_unique_creators_record.py:116` - exit 1, `outcome=held-by holder=<id>`, record unchanged | Yes | Pass |
| AC-27 | `tests/integration/test_unique_creators_record.py:128` - exit 1, `not-enforced` (both backends) | Yes | Pass |
| AC-28 | `tests/integration/test_unique_creators_record.py:136` - exit 1, `refused`, no record | Yes | Pass |
| AC-29 | `tests/test_unique_creators_command.py:91` - exit 1, `refused`, `_dynamodb_record_step` not called; system actors at their ids not refused | Yes | Pass |
| AC-30 | `tests/integration/test_unique_creators_record.py:146` - `verified`, `not-kept`, provider ids exact, `held-by` for an `@` case variant (PostgreSQL) | Yes | Pass |
| AC-31 | `tests/integration/test_unique_creators_record.py:168` - exit 1, `changed`, no record | Yes | Pass |
| AC-32 | manual: four CHANGELOG entries, `configuration.rst`, `deployment.rst` read against the AC | n/a | Pass |
| AC-33 | `tests/test_mcp_server_name.py:199` - `ValueError` for `""`, `"   "`, `5`, `None` | Yes | Pass |
| AC-34 | `tests/integration/test_oauth2_trust_binding.py:782` - held code 400 `invalid_grant`, fresh code 200 | Yes | Pass |
| AC-35 | `tests/test_oauth2_disconnect_sweeps_codes.py:66` - `result is None`, token buckets empty; fault path `:127` | Yes | Pass |
| AC-36 | `tests/integration/test_oauth2_trust_binding.py:798` - `DbError`, the row stays, the retry refuses the code; `tests/test_oauth2_disconnect_sweeps_codes.py:103` half-removed retry | Yes | Pass |
| AC-37 | `tests/test_unique_creators_command.py:117` - `missing` exit 1; four exempt values exit 0 | Yes | Pass |
| AC-38 | `tests/integration/test_unique_creators_record.py:194` - five cases with exit codes and lines | Yes | Pass |
| AC-39 | `tests/integration/test_unique_creators_record.py:219` - exit 1, `previous outcome=skipped`, orphan kept | Yes | Pass |
| AC-40 | `tests/test_unique_creators_command.py:136` - exit 2 and the printed fault, read and write paths | Yes | Pass |
| iter. 1 | `tests/test_auth.py:225` - eight malformed headers 403; a colon passphrase authenticates; `tests/test_trust_re_pair.py:2735` - 403 not 500 | Yes | Pass |
| iter. 2 | `tests/test_trust_re_pair.py:2759` `TestTheRequestBodyIsChecked` - 400 naming the field, no row, re-pair unchanged | Yes | Pass |
| iter. 3 | `tests/test_trust_re_pair.py:2811` `TestTheLastRefusalsSayWhy` | Yes | Pass |
| iter. 4 | `tests/integration/test_unique_creators_record.py:234` - listed, not recorded, marker intact, `report` clean | Yes (not for `resolve`: issue 1) | Pass |

**Security properties** (addendum): the token strip is pinned by AC-3's `assert "verification_token" not in body`; the answer's binding to the row written by AC-10 and AC-11; the code revocation at disconnect by AC-20 (`r.json()["error"] == "invalid_grant"` plus the three rows gone), AC-34 and AC-35 (`assert result is None`, both token buckets empty).

## Remaining Tasks

- [ ] Issue 1 before the PR: `resolve` must not record a reserved creator (the CHANGELOG and OPC-12 say no command does).
- [ ] Issues 2-6: small; `/iterate_plan` before the PR.
- [ ] Follow-up (plan): the owner's BlazeMeter edits; check BlazeMeter step 34 on the rc2 deploy; `/release` 4.0.0rc2; tell the consumer the triage outcome (no message is drafted in the plan; the four items and where each landed are in the research note's table and this document).

## Issues Found

### 1. `resolve` can still record a reserved creator, and overwrite the backfill-complete item
**Severity:** Medium
**Description:** `_group_in_memory` appends a reserved actor to `report.reserved` but does not `continue`, so two actors sharing a reserved value still form a duplicate group. `resolve --apply` then calls `_settle_record(key, …)`, which writes the kept actor's record. For `#meta#backfill`, `Creator.get` returns the backfill-complete item (empty `actor_id`), `""` is not in the group, and `move_stale_record` moves that item to the kept actor. The CHANGELOG ("Such a creator is now never recorded") and OPC-12 overstate the fix. It needs two legacy or restored rows sharing a reserved value; the library refuses reserved values at creation since 4.0.
**Location:** `actingweb/maintenance/unique_creators.py:303` `if is_reserved(creator) and _wanted(creator, only):` (no `continue`); `_settle_record`.
**Recommendation:** `continue` after appending to `report.reserved` (as for `#dup-`), and have `_settle_record` return `"skip"` for a reserved key and treat an empty `actor_id` as not a record; a test with two actors sharing `#meta#backfill` through `resolve --apply`.

### 2. Two re-pair reasons are not mapped for a proven peer
**Severity:** Low
**Description:** `replace_trust_secret`'s "no trust row" (a delete between the handler's read and the swap) and "the row could not be read back" (the swap committed, then the row went) fall back to "Existing trust not verified", and the second is logged as "the trust is unchanged" although the swap was written. A proven peer is told its secret was wrong instead of to pair again.
**Location:** `actingweb/handlers/trust.py:699` `told = _RE_PAIR_REASONS.get(reason) if proven else None`
**Recommendation:** map both to "The trust was deleted meanwhile; pair again"; log "unchanged" only when the swap did not commit.

### 3. `record --previous` exits 0 when the release was skipped for an exempt creator
**Severity:** Low
**Description:** an actor whose creator is now exempt or `#dup-…` answers `exempt` with previous `skipped`, exit 0; the stale record for the `--previous` address still names this actor.
**Location:** `actingweb/maintenance/unique_creators.py` `_record_creator` (`out.previous = "skipped" if wanted_previous else None`) and `RecordOutcome.exit_code` (`if self.previous in (None, "skipped"): return 0`).
**Recommendation:** run the previous step for an exempt creator too (the release is conditioned by `release_stale_record`), or exit 1 when a requested release was skipped.

### 4. `revoke_client_tokens` / `revoke_actor_tokens` docstrings omit the code bucket
**Severity:** Low
**Location:** `actingweb/oauth2_server/token_manager.py` (the two docstrings: "one of the two token buckets could not be read")
**Recommendation:** name the authorization-code bucket and an unconfirmed code removal as causes of `TokenStoreUnavailable`.

### 5. `TestPeerTrustRequest` methods have no type hints
**Severity:** Low
**Description:** `CLAUDE.md` ("Type hints are required on all functions"); the seven methods match the untyped style of the class above them in the same file, and pyright passes.
**Location:** `tests/integration/test_trust_flow.py` (`TestPeerTrustRequest`, `def test_00N_…(self, http_client):`)
**Recommendation:** annotate `http_client: requests.Session` and `-> None`.

### 6. CHANGELOG entries without a **Behavior change:** sentence
**Severity:** Low
**Description:** the refusal-body entry changes the wire (bodies, reason phrases such as the 403 "Forbidden"); the notification entry changes what is logged. `CLAUDE.md` asks for a bold **Behavior change:** sentence for every consumer-visible shift.
**Location:** `CHANGELOG.rst` `Unreleased`, "A refused trust request gave the peer no readable reason", "Every permission change logged one WARNING per OAuth2/MCP client".
**Recommendation:** add the sentence to both.

### 7. `with_mcp(server_version=None)` cannot reset to the library version
**Severity:** Low
**Description:** `None` raises `ValueError`, and a later `with_mcp()` keeps the earlier value (by design, MCP-D2).
**Location:** `actingweb/interface/app.py` `with_mcp`
**Recommendation:** accept as designed (consistent with `with_app_version`), or let `None` mean the library version; owner's call.

### Notes (unverified)
- `desc` and `secret` have no length limit; a body near DynamoDB's 400 KB item limit may raise `DbError` from `create_verified_trust` (503 through the integrations, not 500). Not run.
- `_postgresql_holder` compares `lower(creator)` for `@` values, which the raw-value index does not serve; one query per `record`, not a scan of the command's own.
- A code an authorization issues after the sweep's code snapshot and before the trust row goes is not swept (MCP spec Untested); the user acted for it.

### Rejected
- Code review: "a valid exchange in a code's last second is refused" (`token_manager.py:371`). Both backends store the deadline with `TTL_CLOCK_SKEW_BUFFER` (3600 s, `actingweb/db/dynamodb/attribute.py` and `actingweb/db/postgresql/attribute.py` `ttl_deadline`), so the strict re-read does not hide the row at `expires_at`.

## Todos

- `todo/rc-pass-against-real-consumers.md` (the plan's triage closed it): deleted with its `INDEX.md` row.
- `todo/handler-refusal-bodies.md` (the plan's deferral: the other handlers' bare refusals): present, with an `INDEX.md` row.

## Spec Merge

- `thoughts/specs/trust-establishment.md` - created (partial): TES-1 to TES-11, TES-D1, TES-D2; Untested: TES-4's stubbed read-back, issue 2. Row added to `thoughts/specs/README.md`.
- `thoughts/specs/trust-permissions.md` - merged: 1 added (TPM-4).
- `thoughts/specs/mcp-server.md` - merged: 3 added (MCP-9, MCP-10, MCP-11), 1 decision (MCP-D3); Untested: codes issued after the snapshot.
- `thoughts/specs/operator-commands.md` - merged: 2 added (OPC-11, OPC-12), 1 decision (OPC-D4); Untested: issue 1 (OPC-12 does not hold for `resolve`) and issue 3.

## Overall Assessment

The plan landed: all five phases and four iterations are implemented as planned or with recorded, acceptable deviations, and every acceptance criterion has a test that asserts its observable result and passed on both backends (DynamoDB 8510, PostgreSQL 8264) in this run. The security properties the plan claims (no verification token in an unapproved answer, an answer bound to the row written, codes revoked at disconnect) are each pinned by a named assertion; the security review found no vulnerability.

One Medium issue should be fixed before the PR: `resolve` still records a reserved creator that two legacy rows share, and for `#meta#backfill` would move the backfill-complete item, contrary to the CHANGELOG. The six Low issues are small and can go in the same `/iterate_plan` pass. No High issue is open, so the Spec Delta is merged.
