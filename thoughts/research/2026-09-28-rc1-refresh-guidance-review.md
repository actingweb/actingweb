# Triage: the Emm AI client's review of the 3.15.0rc1 refresh guidance

**Date:** 2026-09-28
**Source:** `thoughts/inbound/rc1-refresh-guidance-review-from-emm.md`, filed
2026-09-28 by the actingweb_mcp (Emm AI) project in answer to our request to
review PR #149 (`release/3.15.0-refresh-grace` at `6b9b02e`) before rc1. The
report came out of their #109 dropped-rotation lockout work (Mac app,
Designed for iPad, Capacitor/WKWebView). The inbound file is deleted with
this note; this note carries its content and attribution.
**Plan:** thoughts/plans/2026-09-27-refresh-grace-setting.md (Iterations 15–17)

## Claims, what the check found, and what was done

### 1. A store fault on the SPA refresh grant answers 401, and our rule 7 turns that into a sign-out (they would hold rc1 for it)

**Verified.**
- The consume: `oauth_session.py` `try_mark_refresh_token_used` caught
  `StoreFault` and returned `(False, None)`, which
  `handlers/oauth2_spa.py` answered with 401 "Invalid or expired
  refresh_token".
- The read: DynamoDB `get_attr` ends in a bare `except Exception: return
  None` (`db/dynamodb/attribute.py`), so the SPA read turned a throttle into
  "absent" and then the same 401.
- The write: `create_refresh_token` ignored `set_attr`'s return value.
  `Attributes.set_attr` and the DynamoDB `set_attr` do return `False` on
  failure, so an unstored token could be handed out.
- Our CHANGELOG said the SPA endpoint "still answers 401 on such a fault",
  and our rule 7 said a 401 on refresh is final. A client following it
  signed out on a throttle.
- This was item 1 of `thoughts/todo/token-store-fault-contract-gaps.md`,
  deferred from 3.15. The consumer's addition is that our own guidance turns
  it into a sign-out.

**What the check changed:**
- The report's read-fault claim was about DynamoDB. The PostgreSQL
  `get_attr` has the same shape; the strict read covers both backends.
- One more gap the report did not name: neither integration passed the
  handler's headers through. FastAPI and Flask copied only the status code,
  so a `Retry-After` set by the handler never reached the client.

**Done** (owner: fix in code for rc1):
- The read is strict, the consume and the write raise
  `TokenStoreUnavailable`, and the grant answers 503 with `Retry-After: 5`.
- Both integrations pass `Retry-After` through.
- Rule 7 now says a 503 is not final.
- A new troubleshooting entry covers the symptom.
- Item 1 is removed from the todo; items 2 (the SPA theft response) and 3
  (auth-code reads) stay there.

### 2. Rule 5 ("a failed store is a failed refresh") strands the client

**Verified, by reasoning against the ladder.** The server consumes the
presented token before the client stores the new pair. Falling back to the
old token is the reuse the server answers as theft once the grace period
has passed.

**Done:** rule 5 now uses their suggested wording: keep the new tokens in
memory, retry the store, never fall back to the old refresh token. The one
case this cannot cover, the process dying before the store succeeds, is
stated. The troubleshooting entry is corrected to match.

### 3. Rule 6: a timeout does not settle the outcome, and does not help across a sleep

**Verified.** A request may reach the server before the client's timeout
fires, and a timer does not run while the device sleeps.

**Done:**
- Rule 6 now asks for a timeout short enough that one immediate retry still
  lands inside the grace period, about 15–20 s against the 60 s default, and
  says the timeout helps only while the device is awake.
- Rule 3 now says to retry once, at once, while awake; a retry after a
  sleep is the case that is answered as theft.

### 4. Rule 1 asks for signals a WebView or Designed-for-iPad client may not have

**Not verifiable in this tree**; these are platform facts. They agree with
the APIs as documented:
- `NSWorkspace` notifications are posted on
  `NSWorkspace.shared.notificationCenter`.
- An iOS binary has no `NSWorkspace`.
- A dark wake does not activate an app.

**Done:** rule 1 is now "refresh only while the app is active or the page is
visible, and not from a timer". The macOS notification stays as an example
for native AppKit apps, and the rule says an iOS binary has no such signal.

### 5. Rule 2 names APIs that may not do what the rule needs

**Not verifiable in this tree**; these are platform facts:
- An idle-sleep assertion does not stop lid-close or a menu Sleep.
- IOKit is not available to an iOS binary.
- WKWebView runs `fetch` in WebKit's networking process.

**Done:** rule 2 says the assertion must cover the process that owns the
connection, names the WKWebView case, and the section calls rules 1 and 2 a
mitigation, not a guarantee.

### The #109 note

The expired-token fix (`c280bcf`) is correct but does not cover any of the
four #109 events (gaps of 336–2950 s against a 14-day TTL). This is
**accepted**. The troubleshooting entry now says that fix is separate and
does not address the sleep symptom.

## Not blocking, from the report

- The consumer will bump to 3.15.0 for the public-client `invalid_client`
  fix.
- They will surface the migration guide's "remove and re-add the connector"
  step to their Codex and ChatGPT users.

Nothing to do here.

## Open on the consumer's side

Two spikes are still open:
- Does a dark wake deliver an app-active or visibility change in their
  WKWebView?
- Does any assertion from a Designed-for-iPad process hold a dark wake?

Their answers may refine rules 1 and 2 later.
