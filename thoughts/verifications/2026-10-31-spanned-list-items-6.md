# Verification: Spanned list items (Phases 1 and 2), sixth run

**Date:** 2026-10-31
**Plan:** thoughts/plans/2026-10-30-spanned-list-items.md
**Research:** thoughts/research/2026-10-26-v3.16-scope-oauth-adoption-vouching-and-spanned-list-items.md
**Branch:** release/3.16.0-spanned-list-items
**Commit:** b737efa

**Scope.** Iteration entries 50-56 (the sixth batch, `726b97d..b737efa`),
which answer the fifth verification's Y1-Y12. Phase 3 is not implemented,
so the plan's `verified:` link is not set and the plan stays
`status: active`. No feature document. **No todos** (owner, 2026-10-31).

## Automated Check Results

- **Browser QA:** Ran at this tree, headless Playwright, local QA mode on
  `localhost:5055`, an owner and a peer, both deleted afterwards (204 then
  404). Passed: hostile trust requests (a script-bearing id, a base URI
  with `?_method=DELETE`) answer 400; Visit Peer, Approve and Delete work,
  and every confirm reads its text from `data-confirm`; an address-bar
  `?_method=DELETE` with basic auth answers 403, and one with only a
  Bearer token is not refused as cross-site; no console errors; 375 px
  fits.
- **Second opinion:** outside-voice agent, providers codex and a
  fresh-context Claude reviewer: 8 findings.
- **Built-in code review** (`/code-review high 726b97d..b737efa`): 10
  findings.
- **Built-in security review:** no finding at or above the bar; it
  reported the root-redirect regression (Z2) as a non-security bug.
- `ruff check`, `ruff format --check` (458 files), `pyright`: pass.
- `verify_groups.py`: all 51 groups documented.
- `make test-all-parallel` (DynamoDB): 4863 passed, 40 skipped.
- `make test-all-parallel` (PostgreSQL): 4671 passed, 232 skipped.
- `sphinx-build -W ...`: pass.

## Previous Verification

**Previous:** thoughts/verifications/2026-10-31-spanned-list-items-5.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| Y1 inline-handler XSS | Fixed | `data-confirm` in five templates; `test_inline_handlers_carry_no_template_values` |
| Y2 path characters in peer ids | Fixed at creation; `%2E` quoting is no guard (Z5) | `is_valid_peer_id`, `_trust_uri` |
| Y3 peer base URI as a link | Fixed at creation; a later peer `PUT` bypasses it (Z1) | `is_valid_peer_baseuri`, `peer_link` |
| Y4 SPA Bearer refused | Fixed | `test_a_cross_origin_spa_with_its_own_bearer_token_is_dispatched` |
| Y5 ambient detection | Fixed; docstring contradiction (Z10) | `_session_cookie_auth` |
| Y6 base-path redirects | Mostly fixed; root redirect doubles it (Z2), some left (Z12) | `Config.actor_path` |
| Y7 whitespace in `redirect_to` | Fixed | iteration 53 |
| Y8 malformed heads' bodies | Fixed | iteration 54 |
| Y9 sweep accounting | Fixed | iteration 55 |
| Y10 callbacks override | Fixed | iteration 55 |
| Y11 docstring | Fixed | iteration 56 |
| Y12 cookie on same-site POSTs | Fixed in the integrations; cached Basic on real POSTs is not (Z3) | `may_use_session_cookie` |

## Remaining Tasks

- [ ] Phase 3 (`append_once`), on its own branch after PR 1 opens.
- [ ] Z1-Z13 below, in the next iteration batch.

## Issues Found

### Z1. A peer can rewrite its base URI after the door check
**Severity:** High
**Location:** `trust.py:728` (`baseuri = params["baseuri"]` in
`TrustPeerHandler.put`, which the peer itself may call: `config.py:300`).
**Failure:** a peer stores `javascript:...`, a `?_method=` URL or an
internal address; notifications, subscriptions and the proxy then send
requests to it (SSRF), and any template using `baseuri` links to it.
**Recommendation:** validate it there (400).

### Z2. The actor-root browser redirect doubles the base path
**Severity:** High (regression in this batch)
**Location:** `root.py:61` prefixes `config.root` to `actor_path()`, which
already carries the base path. **Recommendation:** prefix the origin only;
test the call site.

### Z3. A real cross-site POST with cached basic auth is still accepted
**Severity:** Medium
**Description:** only web UI POSTs and GET overrides are checked; a form on
another site can POST to `/<id>/properties` with the browser's cached Basic
header. The docs' new wording suggests otherwise.
**Recommendation:** in the integrations, drop a Basic header from a
state-changing request the browser reports as cross-site, as the cookie
already is.

### Z4. Library templates put property names unencoded into URLs
**Severity:** Medium
**Location:** `actingweb/templates/aw-actor-www-properties.html:22`,
`aw-actor-www-property.html:44`. A name such as `email?_method=DELETE`
(any JSON key is accepted) turns the link into a same-origin delete.
**Recommendation:** encode names as path segments in every URL.

### Z5. `%2E` does not stop dot segments; links for ids that fail validation
**Severity:** Low
**Location:** `www.py:162`. WHATWG URL parsing treats `%2e` as a dot.
**Recommendation:** render no Approve/Delete link for a stored id that
fails `is_valid_peer_id`.

### Z6. `create_reciprocal_trust` stores the given URL unchecked
**Severity:** Low
**Location:** `actor.py:1578,1700`. **Recommendation:** validate it.

### Z7. A header-less state change with the cookie still uses it
**Severity:** Low
**Location:** `cross_site.py:73`. Behind a proxy that strips Origin,
Referer and Fetch Metadata, a sibling-subdomain form authenticates.
**Recommendation:** document the dependency on those headers.

### Z8. The `oauth_completed` hook's `redirect_url` now carries the base path
**Severity:** Low
**Recommendation:** a **Behavior change** sentence.

### Z9. The peer-id pattern accepts a trailing newline
**Severity:** Low
**Location:** `trust.py:717` (`$`). **Recommendation:** `fullmatch`.

### Z10. Cookie plus explicit Bearer counts as ambient
**Severity:** Low
**Location:** `base_handler.py:48` against the `cross_site` docstring.
**Recommendation:** keep the stricter rule and correct the docstring.

### Z11. Object-like trust rows get no `peer_link`
**Severity:** Low
**Location:** `www.py:730`. **Recommendation:** set it there too.

### Z12. Remaining base-path-less links
**Severity:** Low
**Location:** `flask_integration.py:1265`, `fastapi_integration.py:2106`,
`templates/aw-verify-email.html:22`, `oauth2_callback.py:699`.
**Recommendation:** use `actor_path`.

### Z13. Hot-path and sweep efficiency
**Severity:** Low
**Description:** FastAPI lowercases every request's headers even without
the cookie; the sweep parses a removed head's generations twice.
**Recommendation:** pass the framework's case-insensitive lookup, only in
the cookie branch; collect generations once.

## Overall Assessment

The sixth batch closes Y1-Y12 and the walk confirms the trust and property
pages. No new security finding passed the security review's bar, but the
other two reviews found a peer path around the base-URI check (Z1) and a
regression this batch introduced (Z2); both are High and must be fixed, and
Z3 and Z4 are the remaining ways a browser's ambient credentials or a
peer-chosen name reach a state change.
