# Verification: Spanned list items (Phases 1 and 2), fourth run

**Date:** 2026-10-31
**Plan:** thoughts/plans/2026-10-30-spanned-list-items.md
**Research:** thoughts/research/2026-10-26-v3.16-scope-oauth-adoption-vouching-and-spanned-list-items.md
**Branch:** release/3.16.0-spanned-list-items
**Commit:** 6ca9764

**Scope.** Iteration entries 31-42 (the fourth batch, `947e146..6ca9764`),
which answer the third verification's W1-W14. Phases 1 and 2 were verified in
the earlier runs; Phase 3 is not implemented, so the plan's `verified:` link is
not set and the plan stays `status: active`. No feature document. **No todos**
(owner, 2026-10-31): every finding below is open work for this plan.

## Automated Check Results

- **Browser QA:** Ran at this tree, with headless Playwright (Node, Chromium
  headless shell, outside the sandbox; no window opened), in the local QA
  mode (`DEMO_QA_BASIC_AUTH=true`, `localhost:5055` on loopback, a throwaway
  actor deleted afterwards, 204 then 404). All six checks passed: multi-line
  text and a leading newline survive an unchanged save, and typed line breaks
  are stored as `\n`; a v1 list edits by position, and a stale save or delete
  answers 409 with nothing changed; cross-site item posts (`Origin` foreign or
  `null`, `Sec-Fetch-Site` `cross-site` or `same-site`) and a cross-site
  `GET ?_method=DELETE` answer 403 with nothing changed, while the UI's own
  delete works; the error pages give the reason and Back keeps the typed
  text; the 500,000-character spanned item saves unchanged (same SHA-256);
  no console errors, and every page fits at 375 px. Three follow-ups it
  raised (preview line breaks, error-page style and wording, the create
  form's name rule) are iteration 42 and re-checked green. Not walked: a
  base-path deployment (it needs a proxy in front of the demo).
- **Second opinion:** outside-voice agent, providers codex
  (`codex exec -s read-only`) and a fresh-context Claude reviewer: 14
  findings after it rejected two codex claims (a proxy-injected Fetch
  Metadata header; an IPv6 root answering 500).
- **Built-in code review** (`/code-review high 947e146..6ca9764`, no
  `--fix`): 10 findings.
- **Built-in security review:** one High finding (the trust GET override),
  confirmed in the code and widened below to every REST handler.
- `poetry run ruff check actingweb tests`: pass.
- `poetry run ruff format --check actingweb tests`: pass (455 files).
- `poetry run pyright actingweb tests`: 0 errors, 0 warnings.
- `poetry run python tests/integration/verify_groups.py`: all 51 groups
  documented.
- `make test-all-parallel` (DynamoDB): 4655 passed, 40 skipped.
- `make test-all-parallel` (PostgreSQL): 4471 passed, 224 skipped.
- `sphinx-build -W ...`: pass (after the web-ui list got its blank line).

## Previous Verification

**Previous:** thoughts/verifications/2026-10-31-spanned-list-items-3.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| W1 Origin check refuses base-path edits | Fixed for `/www`; the rule's scope falls short (X1, X2) | `www.py` `_cross_site_refused`; iteration 34 |
| W2 damaged envelope reads as plain item | Fixed; overreaches for a marker other than 1 (X3) | `property_list_span.py` `_envelope_obj`; iteration 31 |
| W3 read-back fault deletes bodies | Fixed | iteration 32, `TestW3ReadBackFaultIsAnUnknownOutcome` |
| W4 single-list resync raises | Fixed; a size race remains (X14) | `Actor._resolve_list_heads`; iteration 33 |
| W5 multi-line text altered on save | Fixed for edits; add is not normalised (X8) | iteration 37; browser walk |
| W6 v1 items not editable | Fixed; out-of-range answers 400, not 409 (X7) | iteration 38; browser walk |
| W7 changelog and docs misdescribe | Fixed; the base-path claim overreaches (X10) | iteration 41 |
| W8 lost plain CAS reports success | Fixed | `TestW8LostPlainCasStaysLost` |
| W9 read-only probe duplicated | Fixed | iteration 36 |
| W10 links ignore the base path | Fixed in `/www`; trust redirects do not (X10) | iteration 35 |
| W11 QA mode under WSGI | Fixed | iteration 39, two demo tests |
| W12 sweep reads bodies twice | Fixed; health after the sweep regressed (X4) | iteration 40, paging test |
| W13 envelope decoded twice | Fixed | iteration 31 |
| W14 in-flight mark per instance | Fixed | `TestW14InFlightMarkIsPerThread` |

## Remaining Tasks

- [ ] Phase 3 (`append_once`), on its own branch after PR 1 opens.
- [ ] X1-X15 below, in the next iteration batch.

## Issues Found

### X1. Every REST handler performs a state change on a GET `_method` override
**Severity:** High
**Description:** the fourth batch guarded only the web UI handler. The REST
handlers still turn a plain GET into a mutation: `root.py:24`
(`_method=DELETE` deletes the whole actor), `properties.py:288,291`,
`trust.py:485,496` (approve or delete a trust), `subscription.py:290,293`,
`actions.py:93,96`, `methods.py:93,96`, `async_actions.py:34,37`,
`async_methods.py:37,40`, `callbacks.py:28,30`, `subscription.py:13,126`
and `trust.py:91,212`. The Flask integration turns the `oauth_token`
cookie, which is `SameSite=Lax` and so sent on a cross-site top-level GET,
into `Authorization: Bearer` on every route
(`flask_integration.py:633-636`); cached basic-auth credentials ride along
the same way. The shipped trust page sends Approve and Delete as GET forms
(`actingweb/templates/aw-actor-www-trust.html:45-56`).
**Failure:** a signed-in owner follows a link on another site to
`/<id>?_method=DELETE` and their actor is deleted; or to
`/<id>/trust/<rel>/<attacker>?_method=PUT&approved=true` and the attacker's
pending trust is approved.
**Recommendation:** one rule in `BaseHandler`, applied wherever a GET
carries `_method`, that requires positive same-origin evidence.

### X2. The web UI's GET override passes `Sec-Fetch-Site: none` and header-less requests
**Severity:** Medium
**Description:** `www.py:190` accepts `none`, which a browser sends for a
link opened from a mail or chat client; `www.py:197` passes a request with
no `Sec-Fetch-Site`, `Origin` or `Referer`, which a browser without Fetch
Metadata sends for a no-referrer link.
**Recommendation:** for a GET override, accept only `same-origin`, or
(without Fetch Metadata) a same-origin `Origin` or `Referer`.

### X3. A marker other than 1 turns a pre-3.16 user item unreadable
**Severity:** Medium
**Description:** `_envelope_obj` (`property_list_span.py:224`) raises for an
int marker other than 1. Before, `{"__aw_env": 2, ...}` was a plain item,
and `carries_library_marker` is false for it, so no sweep removes it either.
**Recommendation:** keep a valid-JSON head with a marker other than 1 a
plain item; raise only for invalid JSON after the prefix, which a user item
can never be.

### X4. `--repair --sweep-spans` can report a list healthy with a broken span left
**Severity:** Medium
**Description:** the verify after the sweep runs with `spans=False`
(`verify_property_lists.py:196`), so a broken span the sweep could not
remove is not counted; and a sweep that raises now skips that list's verify
and repair, since both share one `try`.
**Recommendation:** merge the sweep's found and removed counts into the
health decision, and give the sweep its own `try`.

### X5. The malformed-head warning names a remedy that no longer applies to every head
**Severity:** Low
**Location:** `verify_property_lists.py:223`. The sweep removes only heads
with the library marker. **Recommendation:** say which heads it removes, and
that others need `delete_by_handle()`.

### X6. A malformed head's bodies are kept, then the head is deleted in the same pass
**Severity:** Low
**Location:** `property_list.py:4386-4417`. **Recommendation:** keep the
bodies only for malformed heads the sweep leaves in place.

### X7. A v1 item removed since the page loaded answers 400, not 409
**Severity:** Low
**Location:** `www.py:219` (`_v1_item_changed` raises `IndexError`).
**Recommendation:** with a digest posted, a position past the end is a 409.

### X8. The add form stores CRLF
**Severity:** Low
**Description:** only an `update` with `item_format=text` normalises CRLF
(`www.py:1162`); the add form's textarea posts CRLF too, so an unchanged
edit later changes the value. An unchanged save of a REST-written CRLF item
also rewrites it (outside voice).
**Recommendation:** normalise every web UI textarea value, and say in the
changelog that the web UI stores line breaks as `\n`.

### X9. `redirect_to` accepts dot segments
**Severity:** Medium
**Location:** `www.py:1536-1540`. `/<id>/www/../../<other>/www` (or `%2e%2e`)
passes the prefix check, and the browser resolves it out of this actor's UI.
**Recommendation:** refuse any `.`/`..` segment and any `%` in the path.

### X10. The trust redirects drop the base path
**Severity:** Medium
**Location:** `trust.py:493,506` (`f"/{actor_id}/www/trust"`); the
changelog claims the web UI's redirects keep it. **Recommendation:** build
them from `config.root`.

### X11. The v1 stale guard is check-then-write, and is skipped without a digest
**Severity:** Low
**Location:** `www.py:1277-1284`, `:216`. **Recommendation:** document both
(best effort; needs `item_digest`).

### X12. `_www_path` drops the base path silently on a mismatch
**Severity:** Low
**Location:** `www.py:153-155`. **Recommendation:** log a WARNING.

### X13. A non-ASCII digit in `?edit_index=` raises
**Severity:** Low
**Location:** `www.py:93`: `"²".isdigit()` is true and `int("²")` raises.
**Recommendation:** require ASCII digits.

### X14. A resync's size decision can go stale before the bodies are read
**Severity:** Low
**Location:** `actor.py:3413-3415`. An item rewritten between the head read
and `item_at` can be larger than the head said, and the full state goes
inline over the threshold. **Recommendation:** compare the fresh head with
the one sized, and send the reference when they differ.

### X15. The sweep deletes a pre-3.16 unreadable head with the library marker
**Severity:** Low
**Location:** `property_list.py:4417`. Such a head already fails every read;
the sweep makes it gone. **Recommendation:** accept, log its rank and size at
WARNING before removing it.

## Overall Assessment

The fourth batch fixes W1-W14 as written, and the browser walk confirms the
web UI paths: multi-line text, v1 editing, stale guards, cross-site refusal
in `/www`, the spanned item, the phone layout. Both backends are green. But
the batch's own SECURITY entry describes a class of hole, a cross-site link
changing state through a GET override, that it closed only in the web UI
handler: X1 leaves the actor delete and trust approval open through the REST
handlers that the shipped trust page uses, and that is a High that must be
fixed before this branch is merged. X2-X4, X9 and X10 are Medium and belong
in the same batch; the Lows are small.
