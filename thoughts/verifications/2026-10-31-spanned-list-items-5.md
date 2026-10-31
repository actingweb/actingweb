# Verification: Spanned list items (Phases 1 and 2), fifth run

**Date:** 2026-10-31
**Plan:** thoughts/plans/2026-10-30-spanned-list-items.md
**Research:** thoughts/research/2026-10-26-v3.16-scope-oauth-adoption-vouching-and-spanned-list-items.md
**Branch:** release/3.16.0-spanned-list-items
**Commit:** d9dd9b4

**Scope.** Iteration entries 43-49 (the fifth batch, `72de736..d9dd9b4`),
which answer the fourth verification's X1-X15. Phase 3 is not implemented,
so the plan's `verified:` link is not set and the plan stays
`status: active`. No feature document. **No todos** (owner, 2026-10-31):
every finding below is open work for this plan.

## Automated Check Results

- **Browser QA:** Ran at this tree, headless Playwright (Node, Chromium
  headless shell, outside the sandbox; no window), local QA mode on
  `localhost:5055`, three throwaway actors (an owner and two peers), all
  deleted afterwards (204 then 404). Passed: the shipped trust page's
  Approve (302, trust approved) and new Delete (302, trust gone); a
  `?_method=DELETE` typed into the address bar answers 403 on
  `/properties/<p>` and `/www/properties/<p>`; `GET /<id>?_method=DELETE`
  with `Sec-Fetch-Site: cross-site` answers 403 and the actor stays; the
  properties page's own Delete answers 204; list add, edit and delete keep
  LF and é; no console errors; the trust page fits at 375, 768 and
  1280 px with its actions inside the card (after the follow-ups in
  iteration 49).
- **Second opinion:** outside-voice agent, providers codex
  (`codex exec -s read-only`) and a fresh-context Claude reviewer: 10
  findings.
- **Built-in code review** (`/code-review high 72de736..d9dd9b4`, no
  `--fix`): 10 findings.
- **Built-in security review:** one High finding (the stored XSS in the
  demo trust page's confirm), confirmed, and widened below to three
  library templates.
- `ruff check`, `ruff format --check` (456 files), `pyright`: pass, 0
  errors and 0 warnings.
- `verify_groups.py`: all 51 groups documented.
- `make test-all-parallel` (DynamoDB): 4826 passed, 40 skipped.
- `make test-all-parallel` (PostgreSQL): 4634 passed, 232 skipped.
- `sphinx-build -W ...`: pass.

## Previous Verification

**Previous:** thoughts/verifications/2026-10-31-spanned-list-items-4.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| X1 REST GET overrides change state cross-site | Fixed for cross-site links; same-origin pages render peer-supplied links (Y2, Y3); explicit-Bearer SPAs refused (Y4) | iteration 43, `tests/test_get_override_cross_site.py` |
| X2 `none` and header-less pass | Fixed; Basic-only header-less still passes (Y5) | iteration 43 |
| X3 marker other than 1 unreadable | Fixed; `parse()` docstring stale (Y11) | iteration 46 |
| X4 sweep health and fault | Fixed; double count and leftovers on unhealthy lists (Y9) | iteration 47 |
| X5 malformed-head warning | Fixed | iteration 47 |
| X6 kept bodies, removed head | Fixed as asked; both reviewers find it now loses recoverable bodies (Y8) | iteration 47 |
| X7, X8, X11, X13 | Fixed | iteration 45 |
| X9 `redirect_to` dot segments | Fixed; tab/newline-prefixed dots pass (Y7) | iteration 45 |
| X10 trust redirects drop base path | Fixed for trust; other redirects still drop it (Y6) | iteration 44 |
| X12 `_www_path` swallowed mismatch | Fixed (no comparison left to fail) | iteration 44 |
| X14 resync size race | No change needed (`fit_full_state` guards it) | iteration 48 |
| X15 sweep deletes marker-1 heads | Logged with rank and size | iteration 47 |

## Remaining Tasks

- [ ] Phase 3 (`append_once`), on its own branch after PR 1 opens.
- [ ] Y1-Y12 below, in the next iteration batch.

## Issues Found

### Y1. Peer ids in inline confirm handlers are a stored XSS
**Severity:** Critical
**Description:** `examples/demo/templates/aw-actor-www-trust.html:86`
(`onsubmit="return confirm('Delete the trust with {{ trust.peerid }}?');"`,
added by this batch) and, from before it,
`actingweb/templates/aw-actor-www-trust.html:53`. Autoescape turns `'` into
`&#39;`, which the browser decodes before running the handler. The peer id
is chosen by whoever sends `POST /<id>/trust/<rel>` (no authentication,
`trust.py:396` takes `params["id"]` unchecked). The same pattern with a
property name, which a peer with write access chooses, is in
`actingweb/templates/aw-actor-www-properties.html:30` and
`aw-actor-www-property.html:53`.
**Failure:** a peer sends a trust request whose id closes the string; the
owner clicks Delete on the spam row and the script runs in the app's
origin, where every request is same-origin.
**Recommendation:** no template value inside an inline script string (use
a `data-` attribute read by the handler); validate the peer id's shape
when a trust is created.

### Y2. A peer id with path characters turns Delete into an actor delete
**Severity:** High
**Description:** `www.py:689-690` builds `approveuri` by interpolating the
raw peer id; a peer id of `../../../<victim>` makes the browser resolve the
Delete form's action to `/<victim>`, so it sends
`GET /<victim>?_method=DELETE` from the owner's own page.
**Recommendation:** refuse a peer id outside a safe character set when a
trust is created; URL-quote it when building links.

### Y3. A peer-supplied `baseuri` is a same-origin link the guard trusts
**Severity:** High
**Description:** the demo's "Visit Peer" link renders `trust.baseuri`
(`examples/demo/templates/aw-actor-www-trust.html:69`), which comes
unvalidated from the same unauthenticated POST. `https://<app>/<victim>?_method=DELETE`
deletes the actor on a click; `javascript:` is plain XSS.
**Recommendation:** require an `http(s)` base URI with no query, fragment or
user info when a trust is created, and render a link only for such a URI.

### Y4. A cross-origin SPA with its own Bearer token is refused
**Severity:** Medium
**Location:** `base_handler.py:88`. An explicit `Authorization: Bearer`
header cannot be forged cross-site, yet a cross-origin `?_method=` with one
answers 403, contrary to the changelog. **Recommendation:** check only
requests that carry ambient credentials (the session cookie, or Basic).

### Y5. Ambient-credential detection is incomplete
**Severity:** Medium
**Location:** `base_handler.py:99`. A header-less request with cached
Basic credentials passes (indistinguishable from `curl -u`; document), and
with the cookie and any other Authorization header the cookie is not
counted. **Recommendation:** when the cookie is present, require evidence
whatever the header says; document the Basic residue.

### Y6. Other redirects still drop the base path
**Severity:** Medium
**Location:** `oauth_email.py:698`, `root.py:53`, `oauth2_callback.py:703`,
`flask_integration.py:729`, `fastapi_integration.py:1516,1551`.
**Recommendation:** one base-path helper for handlers and integrations.

### Y7. `redirect_to` passes a tab- or newline-prefixed dot segment
**Severity:** Low
**Location:** `www.py:1503`. Browsers strip ASCII tab and newline from URLs.
**Recommendation:** refuse any control character or whitespace.

### Y8. The sweep now deletes bodies a repair could use
**Severity:** Medium
**Location:** `property_list.py:4386-4405`. A marker-1 head damaged in a
side field (`sha256`, `key`) may still have intact bodies; the head and,
an hour later, the bodies go in one run, with only rank and size logged.
**Recommendation:** keep the bodies of every malformed head for that run
(as before X6), and log the generations it named.

### Y9. Sweep accounting
**Severity:** Low
**Location:** `verify_property_lists.py:201,288`. A list whose sweep and
verify both fail counts twice as errored; leftovers count only when the
verify called the list healthy, so a rebalanced list can log "repaired"
with a broken span left; the `malformed_heads_kept` term is dead (verify
already marks a remaining malformed head unhealthy).
**Recommendation:** count each list once; leftovers make the list
unhealthy whatever else happens.

### Y10. `CallbacksHandler.get` runs the override and then the GET
**Severity:** Medium
**Location:** `callbacks.py:32-35` (no `return` after dispatch), from before
this branch. **Recommendation:** return after each dispatch.

### Y11. `parse()` docstring still says another marker raises
**Severity:** Low
**Location:** `property_list_span.py:255`. **Recommendation:** fix it. (The
outside voice suggested refusing other int markers again; see the plan's
entry for why the plain-item reading stays.)

### Y12. The changelog's `Lax` wording and same-site POSTs
**Severity:** Medium
**Description:** the SECURITY entry says a browser sends a `Lax` cookie
"only on top-level GET navigations"; it does so on any same-site request,
and the REST handlers accept form bodies, so a sibling subdomain can POST
with the owner's cookie (the integrations map it to Bearer on every
method). **Recommendation:** map the cookie to a Bearer header for a
state-changing request only when it is not cross-site, and correct the
wording.

Notes, not findings: the guard is copied into fourteen `get()` methods
(the code review's altitude point; Y12's integration-level check addresses
the cookie part centrally), and the base-path rule exists in three places
(Y6).

## Overall Assessment

The fifth batch closes the cross-site GET path it set out to close, the
browser walk confirms the shipped pages still work, and both backends are
green. But it added a stored XSS (Y1) to the demo, and the reviews found
that peer-controlled trust fields reach the owner's same-origin pages
(Y1-Y3), which gets past the new check entirely. Those must be fixed
before this branch is merged, together with Y4 (it breaks SPAs) and Y12.
