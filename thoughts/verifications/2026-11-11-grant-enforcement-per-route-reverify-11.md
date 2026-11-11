# Verification: a peer's grant is the answer on every route (closing)

**Security, unpublished.** Keep local under the same rule as the plan: never
push before the fix.

**Date:** 2026-11-11
**Plan:** thoughts/plans/2026-11-10-grant-enforcement-per-route.md
**Research:** thoughts/research/2026-11-10-grant-enforcement-per-route.md
**Branch:** fix/3.16.0-grant-enforcement (local only)
**Commit:** 8e37e15 reviewed; closed at the commit that adds this document

Twelfth and closing verification. Scope: the whole branch since the first
verification, `10f9563..HEAD`, which no delta-scoped review had seen. Run
under the owner's stop rule (2026-11-11, plan Decisions Made): the branch
is clean when no Medium-or-higher finding is reachable by a peer or an
OAuth2/MCP client; owner-only, application-stored-data and Low findings are
recorded as accepted without code change.

## Automated Check Results

- **Full tier** on `8adb9d6` (the last code change; later commits add a
  test, documentation and a docstring): ruff, format, pyright clean;
  `verify_groups` OK; unit 5105 passed; DynamoDB 6560 and PostgreSQL 6357
  passed; docs build with `-W`; no wire recording changed.
- **After the closing edits:** ruff, format, pyright clean; unit 5105
  passed; docs build with `-W`; the new HTTP test
  (`test_a_grant_edit_cannot_name_another_actor`) passes on DynamoDB and
  PostgreSQL and fails with `master`'s `update_permissions` logic put back.
- **Emm's suite** on `8adb9d6`: PostgreSQL 2 failed / 7406 passed; DynamoDB
  lane 3 failed / 54 passed; the same five baseline failures as on `master`.
  Emm writes only well-formed overrides (objects, list-valued rule keys),
  so the malformed-rule reading does not touch it.
- **Browser QA:** not re-run since the walk of `10f9563` (the confirmation
  refusal page is covered over HTTP).
- **Second opinion (closing):** outside-voice agent, codex (unsandboxed,
  output in the session scratchpad `ov-final/`) and a fresh-context Claude
  reviewer, on the cumulative diff: section A (peer/client-reachable
  Medium+) empty.
- **Security review (closing, cumulative):** no peer- or client-reachable
  findings; a parser differential (`_parsed`, `as_json_object`,
  `json.loads(bytes)`) over BOM, double BOM, UTF-16 LE/BE text agreed on
  every input.
- **Code review (closing, built-in high, cumulative):** 10 findings, none
  peer/client-reachable at Medium+ beyond the owner's decisions.
- **Documentation consistency check:** 5 false claims, 2 contradictions,
  7 missing **Behavior change:** sentences, 5 patching leftovers; all
  corrected (plan entry 75).

## Previous Verification

**Previous:** thoughts/verifications/2026-11-11-grant-enforcement-per-route-reverify-10.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. Malformed allow keys and categories widened | Fixed; wording made exact against `master` | Entries 72, 75 |
| 2. Owner bytes 404 | Fixed | Entry 73 |
| 3. Leftovers | Fixed | Entry 73 |

The re-runs 1-10 and their fates are in the plan's Iterations (entries
23-74) and in each re-run document.

## Issues Found

None that block under the stop rule. Recorded as accepted (plan entry 76):
a hook's refusal part way through a write keeps what was written
(pre-existing, application hook); a JSON-RPC body with no `method` answers
`-32600` to a refused caller (Low); the owner/application/store-API items
(application targets on approval, malformed stored `patterns` or
`properties` list, duplicate-key PUT bodies forwarded raw, a client's
narrowing override across X→Y→X re-types); and the Lows (shutdown
`CancelledError`, the two client tests, a thin wrapper, per-request costs,
the methods POST parsing before its gate, override readers that report what
is stored).

## Overall Assessment

The plan's goal holds across the whole branch: a peer's grant is the answer
on every route, and an OAuth2/MCP client's level is the one the user
approved. No reviewer found a Medium-or-higher issue a peer or client can
reach. The cross-actor grant write found during the iterations (on
`master`) is fixed and tested over HTTP on both backends. The branch stays
local (security records rule) until the owner decides how it ships.
