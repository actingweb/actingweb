# Verification: Spanned list items (Phases 1 and 2), seventh run

**Date:** 2026-10-31
**Plan:** thoughts/plans/2026-10-30-spanned-list-items.md
**Research:** thoughts/research/2026-10-26-v3.16-scope-oauth-adoption-vouching-and-spanned-list-items.md
**Branch:** release/3.16.0-spanned-list-items
**Commit:** 17e61b7

**Scope.** Iteration entries 57-63 (the seventh batch, `035510b..17e61b7`),
which answer the sixth verification's Z1-Z13. Phase 3 is not implemented,
so the plan's `verified:` link is not set and the plan stays
`status: active`. No feature document.

**Stopping rule.** Batches 5-7 hardened cross-site handling, peer input and
base paths across every handler and both integrations, found by reviews of
the web UI work rather than by the plan, and each fix batch has had a High
of its own. So from this run on, only a High or Critical is fixed in this
plan (entry 64 fixes the one found here). The Mediums and Lows below are
recorded and await the owner's scope decision: continue in this PR, move
to a separate branch and plan, or accept. No todo files (owner rule).

## Automated Check Results

- **Browser QA:** Ran at this tree (the seventh walk, entry 63), headless
  Playwright, an owner and a peer on `localhost:5055`, both deleted
  afterwards. Passed: the root redirect (302 to exactly `/<id>/www`); the
  trust page at 375 px with a pending row, Approve and Delete; a
  cross-site basic-auth `POST /<id>/properties` answers 401 and writes
  nothing, same-origin and header-less ones 201; simple property create,
  edit and delete; list add, multi-line edit and delete; no console errors.
- **Second opinion:** outside-voice agent, providers codex and a
  fresh-context Claude reviewer: 3 findings (one disputed by Claude).
- **Built-in code review** (`/code-review high 035510b..17e61b7`): 10
  findings.
- **Built-in security review:** no finding at or above the bar.
- Fast and full tier at `17e61b7`: ruff, format (458 files), pyright 0/0;
  `verify_groups.py` all 51 documented; DynamoDB 4874 passed, 40 skipped;
  PostgreSQL 4682 passed, 232 skipped; sphinx `-W` pass.

## Previous Verification

**Previous:** thoughts/verifications/2026-10-31-spanned-list-items-6.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| Z1 peer PUT of baseuri | Fixed | `test_trust_put_refuses_a_bad_baseuri` |
| Z2 root redirect doubled base path | Fixed | `test_root_browser_redirect_keeps_one_base_path`; browser walk |
| Z3 cached Basic on cross-site POSTs | Fixed; overreached to OAuth endpoints (V7-1, fixed in entry 64) | browser walk 401 |
| Z4 property names in URLs | Fixed for `?`/`#`; `/` remains (V7-3) | `test_library_templates_encode_property_names_in_urls` |
| Z5 dot-only ids | Fixed; such a row cannot be deleted from the UI (V7-5) | `test_dot_only_trust_ids_get_no_link` |
| Z6 outbound URL | Fixed; reported as 408 (V7-7) | `test_reciprocal_trust_refuses_an_invalid_url` |
| Z7, Z8, Z10 docs | Fixed | changelog, security.rst |
| Z9 trailing newline | Fixed | `fullmatch` |
| Z11 object rows' `peer_link` | Fixed | `www.py` |
| Z12 remaining base-path links | Fixed except a `{actor_id}` SPA `return_path` (V7-6) | entry 62 |
| Z13 efficiency | Fixed | entry 59, sweep |

## Issues Found

### V7-1. The Basic drop broke OAuth client authentication
**Severity:** High (regression from entry 59) — **fixed in entry 64**
**Description:** the drop ran for every route, so a browser-hosted client
using `client_secret_basic` on `/oauth/token` lost its credentials and got
`invalid_client`. Now `/oauth/*`, `/mcp` and `/.well-known/*` keep the
header.

### V7-2. A dropped Basic header leads to a Basic challenge
**Severity:** Medium — open, awaits the owner
**Description:** with the header gone, `auth.py:125-129` answers 401 with
`WWW-Authenticate: Basic`, so the browser shows a login prompt for the app
on the attacker's page, and a retry is dropped again. The handlers' "Cross-
site request refused" is never reached. A marker from the integration that
makes auth answer 403 without a challenge would fix it.

### V7-3. A property name containing `/` addresses a different property
**Severity:** Medium (from before this branch) — open
**Description:** `|urlencode` keeps `/`, and `www.py` takes the first
segment, so Delete on `a/b` deletes `a`. Refusing `/` in new property
names, or routing the full remainder, would fix it.

### V7-4. `{"approved": false}` on a trust PUT answers 500
**Severity:** Low (from before this branch) — open
**Location:** `trust.py:737` (`False.lower()`).

### V7-5. A dot-only trust row cannot be deleted from the web UI
**Severity:** Low — open
**Location:** `www.py:162`; the templates hide Delete with Approve.

### V7-6. A `{actor_id}` SPA `return_path` has no base path
**Severity:** Low — open
**Location:** `oauth2_callback.py:696,1280`.

### V7-7. An invalid outbound trust URL answers 408
**Severity:** Low — open
**Location:** `trust.py:173` maps every `False` from
`create_reciprocal_trust` to 408.

### V7-8. Cleanups
**Severity:** Low — open
**Description:** the ambient-Basic rule lives in two integrations, not the
auth layer (custom integrations get no protection); the verification-page
helpers are duplicated in both integrations; CRLF is normalised on update
but not on the creation form; a nested loop in the sweep could be one
union.

## Overall Assessment

The seventh batch fixes Z1-Z13, the security review finds nothing at its
bar, and the walk confirms the touched pages. One High regression it
introduced (V7-1) is fixed in entry 64. What remains is Medium and Low
residue of the hardening program, listed above for the owner to scope; the
spanned-list-items work itself (Phases 1-2) has had no new finding since
the fourth run.
