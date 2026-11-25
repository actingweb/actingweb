# Research: A2A actor interface — reuse map and simplifications

**Date:** 2026-11-24
**Feature:** thoughts/features/2026-11-24-a2a-actor-interface.md
**Companions:** `2026-11-24-a2a-actor-interface.md` (main),
`2026-11-24-a2a-actor-interface.tasks.md` (long-running tasks)
**Branch:** master
**Commit:** a74ae35

The owner asked, before `/create_plan`: where can the plan simplify, use
shared functionality, and avoid new paradigms or patterns that are expensive
or risky? This note sorts every moving part into three classes:
- reusable as-is
- exists but embedded in one place (reuse needs a copy or an extraction)
- nothing exists

For each part it names the lowest-cost route.

It also lists the simplifications that change an acceptance criterion.
Those are the owner's call, not settled here.

**[inference]** marks a conclusion the code does not state.

## The governing simplification

**Model `/a2a` on `/<actor_id>/methods`, not on MCP.**
- **MCP is a different shape.** It is a single global `/mcp`
  (`flask_integration.py:371`, `fastapi_integration.py:996`), outside the
  shared handler table, with its own dispatcher and its own bearer.
- **`/methods` matches what `/a2a` needs:**
  - a per-actor route in the shared handler table
    (`base_integration.py:91-148`)
  - authenticated by the REST trust path
  - speaks JSON-RPC (`handlers/methods.py:182-386`)
  - checks a peer's grant on a named hook through
    `named_route_allows` → `decide` → `_check_hook_permission`
    (`access_decision.py:147-302`, `interface/hooks.py:978-1029`)
- **Effect:** the A2A handler becomes "the methods handler with a
  different envelope". That is the main reason the earlier size estimate
  (route at MCP scale, 1,000–1,500 lines) is high **[inference]**.

## Reusable as-is

| Need | Existing piece | Evidence |
| --- | --- | --- |
| Per-actor route in both frameworks | One handler-table entry plus one Flask and one FastAPI route, following `/methods` | `base_integration.py:91-124`, `flask_integration.py:647-656`, `fastapi_integration.py:1354-1367` |
| Peer authentication by trust secret | `BaseHandler.require_authenticated_actor` / `AuthResult.authorize`; the trust row is read on every request (revocation is immediate in every process, AC-13) | `base_handler.py:217-312, 373-410`, `auth.py:309-331` |
| Skills | Existing `method_hook` / `action_hook` with metadata; `get_hook_metadata` already merges explicit metadata. A skill is a hook the actor already offers over REST. | `interface/hooks.py:289-348, 1518-1572, 1699-1754` |
| Grant per skill | The `methods` / `actions` categories. These are the peer categories, they are in `STATED_RULE_CATEGORIES`, and the built-in types already grant them | `permission_evaluator.py:168-175`, `trust_type_registry.py:334-441` |
| Turning a category off for one peer | Override `{"denied": ["*"], "allowed": []}`; `denied` is checked first and replaces the type's list | `trust_permissions.py:988-1025`, `permission_evaluator.py:1140-1145` |
| Grant change propagation | The override store: this process's cache is updated at once, other processes within 300 s, and a permission callback goes to the peer | `trust_permissions.py:263-272, 325-327, 417-499, 822-830`; spec TPM-1, TPM-2 |
| Per-type admission with nothing stored | `add_trust_type(acl_rules=…)` puts rows in the in-memory `config.access` for the `a2a` path | `permission_integration.py:317-412` |
| Option tag | One line in `Config._supported_options`, gated on an attribute set by `with_a2a`, as `mcp` is | `config.py:583-621`, `interface/app.py:677` |
| Worker configuration | `app.get_config()` carries hooks, delivery settings, indexed properties, list limits and the service registry | `interface/app.py:1669-1738` |
| Task row with optimistic concurrency | Attribute compare-and-set with a `version` inside the data (the documented pattern) on both backends | `attribute.py:495, 596, 661`; `docs/sdk/attributes-buckets.rst:132-149` |
| Large artifacts | An attribute list per task; items over the row limit span | `docs/migration/v4.0.rst`, "Spanned list items" |
| Expiry on DynamoDB | Native TTL on `attributes.ttl_timestamp` is already a one-time operator step; tasks add none | `docs/reference/database-backends.rst:55, 257` |
| One-time consume | `single_use.consume_once` (marked internal) | `single_use.py:100-191` |
| Dispatch to the consumer | A hook through the existing hook registry, the way lifecycle hooks are registered | `interface/hook_registry.py` |
| Telling an ActingWeb peer about a change | `notify_subscribers(target, data)` takes any target string | `subscription_manager.py:724-761` |

## Exists but embedded

**Rule applied:** a small helper local to A2A is cheap. An extraction that
moves MCP, `/methods`, deletion or auth onto shared code touches security
paths while 4.0 is being validated with consumers. That is the expensive,
risky pattern to avoid in this feature. The extraction can follow as its
own plan.

| Piece | Where it lives | Lowest-cost route |
| --- | --- | --- |
| JSON-RPC envelope (parse, -32700/-32600, error object) | Two inline copies: `handlers/mcp.py:1006-1140, 2180-2188`; `handlers/methods.py:21, 182-386` | A small A2A-local module; MCP and `/methods` stay as they are. Its error codes differ anyway (A2A -32001…-32009). |
| Refusing OAuth2-written trust rows | Classifiers exist: `_has_peer_endpoint` (`actor.py:71-85`, private), `legacy_oauth2_row` (`trust_lookup.py:25-36`), and an inline test in `Actor.delete_reciprocal_trust` (`actor.py:3292-3297`). None is called from `auth.py`. `peer_caller_only` refuses only callers with no peer id (`auth.py:788-823`), so it does not cover this. | One check in the A2A handler after authentication, on `auth_obj.trust["established_via"]` with the legacy fallback. Do not change `check_token_auth`. |
| Lease (claim, renew, take over, fence) | Hard-wired to deletion tombstones (`deletion.py:305-550`); a second copy in `callback_processor.py:296-317` | Avoid needing it: see simplification S6. |
| Token index keyed by digest on the system actor | Written by hand per token kind; the closest is pending authorisations keyed by `sha256` with a TTL (`token_manager.py:164-230`) | One more bucket of the same shape for the task token. No generic token store. |
| Cleanup when a trust is deleted | Inline try-blocks in `Actor.delete_reciprocal_trust` (`actor.py:3363-3495`) | One more block of the same shape. No cleanup registry. |
| PostgreSQL expiry sweep | Hard-coded bucket lists at each call site (`token_manager.py:2225-2261`, `oauth_session.py:1315`, `maintenance/deletions.py:357`) | Add the task bucket to an existing throttled call site. |
| Prefix read | `get_attr_prefix` / `get_attr_range` exist in the backend protocol (`db/protocols.py:1630-1655`). Only `AttributeListStorage` uses them; `Attributes` does not expose them. | Expose a prefix read on `Attributes` (small, both backends already implement it). |

## Nothing exists

| Need | Smallest addition | Risk |
| --- | --- | --- |
| Owner creates a trust for an outside A2A caller and gets its secret (AC-5) | A thin public wrapper over `trust.Trust(...).create(baseuri="", approved=True, only_if_absent=True, …)`, which already generates the secret (`trust.py:466-559`) | **Deletion breaks for such a row today (verified by reading).** `delete_reciprocal_trust` builds `"" + "/trust/…"` (`actor.py:3309`). `requests.delete` raises on the schemeless URL, and the `except` sets `failed_once` and `continue`s past the local delete (`actor.py:3313-3325`). The row stays. A local-only class (no `baseuri` → no remote call) is needed in that branch, next to `is_oauth2_trust`. Each permission change for such a peer also logs a missing-`baseuri` WARNING (TPM-4). |
| A per-actor, per-type configuration layer (feature layer b) | None. Trust types are global (`trust_type_registry.py:85-86, 181-183`), and the evaluator reads only the registry and the per-relationship override (`permission_evaluator.py:991-1047`). | A third layer in the evaluator is a new paradigm on the permission path. See S3. |
| Paging for `ListTasks` | None anywhere in the library | See S5. |
| A task-scoped token | None | See the tasks note, T3. |
| Grant/revoke-one-name helpers (Emm-style) | None. `update_permissions` replaces whole categories (`trust_permissions.py:843-890`). | Leave out (main note, Decision 7). |

## Simplifications that avoid new paradigms

Each is a choice among options already in the two research notes. **Bold
AC** marks those that change an acceptance criterion: the owner's call.

- **S1. Skills are existing method/action hooks; grants are the `methods`
  / `actions` categories.**
  - Replaces: a new `a2a` category (main note, Decision 5, option 2) and a
    new skill registry.
  - A2A adds only card metadata on the hook, the way `mcp_tool` does.
  - Consequence: a peer allowed method X over REST may also call it over
    A2A. It is one capability on two transports.
  - Under the owner's principal rule a trust row is either a peer row or an
    OAuth2 row, never both, so the categories cannot leak between MCP and
    A2A **[inference]**.
- **S2. "A2A allowed" per trust type through `acl_rules` (in memory), not
  a new `TrustType` field.**
  - This avoids the `from_dict(**data)` rollback hazard (main note,
    Decision 2, option 1).
  - Per peer, A2A is off when its `methods` and `actions` deny everything,
    or when the trust is deleted.
  - **AC-12** then reads "no A2A access" as "the type is not admitted, or
    no skill is granted". There is no separate switch for one peer.
- **S3. Drop the per-actor, per-type layer, or apply it once at trust
  creation.**
  - Applying it at creation means the owner's per-type preference seeds
    the new relationship's override.
  - The evaluator then keeps its two layers. Nothing new is read per
    request.
  - The cost: a later change to the owner's preference does not reach
    existing relationships.
  - **Feature layer (b) and AC-6/AC-14 wording.**
- **S4. Keep REST's 403 for a bearer that matches no trust.**
  - The shared authenticator answers 401 only when the header is missing
    (`auth.py:165-178`).
  - 401 for a bad bearer was deferred once as a library-wide change
    (`plans/2026-11-06-peer-authorisation-fixes.md:444`). The spec allows
    either (`actingweb-spec.rst:1046-1052`).
  - **AC-11.**
- **S5. One task bucket, row names prefixed by the caller's peer id**
  (`<peerid>:<taskid>`), read with an exposed prefix read.
  - `ListTasks` reads only the caller's tasks, which gives visibility by
    construction.
  - Deleting the trust removes the prefix: one more cleanup block.
  - PostgreSQL expiry needs one fixed bucket name.
  - Paging is applied in memory over that one caller's rows. That fits
    while one caller's live tasks stay small.
  - The owner's cross-caller view is a whole-bucket read, a rare owner-only
    path.
  - It avoids a dedicated table (tasks note, T1, option 3): no model, no
    migration, no readiness check.
- **S6. No lease to extract.**
  - A lapsed deadline fails the task (tasks note, T6, takeover option 1).
  - A heartbeat is a compare-and-set that moves `deadline` forward.
  - Fencing comes from the `version` in the row plus the token being
    refused once the task is terminal.
  - Deletion's lease code stays untouched.
  - **Takeover by a second worker is then not offered.**
- **S7. Hand the worker task context, not a new kind of process.**
  - The worker builds the same `ActingWebApp` and calls `app.get_config()`
    and `check_ready()`.
  - The library's task handle takes the token and resolves the actor and
    the task (tasks note, T2b, option 2).
  - A worker that calls back over HTTP (T2b, option 3) adds a route and a
    third kind of bearer. It can follow later behind the same handle
    interface.
- **S8. Polling only, no A2A push.**
  - `callback_sender` has no retries or persistence (`callback_sender.py`).
    A2A push would need both, which is a new delivery pattern.
  - An ActingWeb peer that wants events can use `notify_subscribers` on a
    task target later.
  - **Feature scope, if push was expected.**
- **S9. Hand-written wire layer** (main note, Decision 8, option 1).
  - It matches `/methods` and MCP and keeps Flask.
  - `a2a-sdk` stays a test-only extra at most.
- **S10. `SendMessage` blocking default, simplest compliant split**
  (tasks note, T5).
  - A skill whose hook returns inline answers synchronously: a Message, or
    a completed Task.
  - A dispatched skill answers with the task in `SUBMITTED`/`WORKING`.
  - No request-thread polling loop.
  - **Whether returning early without `returnImmediately` is an
    acceptable documented deviation** is the owner's call (A2A says the
    server MUST block).

## What each simplification is worth

| Area | Without simplifications | With S1–S10 |
| --- | --- | --- |
| Admission | Merging the two token checks, or a new authenticator | Existing REST path plus one origin check |
| Permissions | New category or third layer: protocol spec, callback body, `GET …/permissions`, evaluator | No protocol change; card metadata only |
| Tasks storage | Possibly a table on both backends | Attributes, one bucket, one exposed prefix read |
| Worker | Lease extraction, HTTP route, third kind of bearer | Token index bucket plus a task handle |
| Notification | Persistent push with retries | None |

**The remaining new code:**
- the A2A envelope and card
- the origin check
- the owner create-trust call, plus the local-only branch in trust deletion
- the task row's state machine
- the token bucket
- the task handle
- the dispatch hook
- one cleanup block
- one sweep entry
- the prefix read

**[inference]** This is closer to the size of the spanned-items feature
than to two or three features.

## Host-root card redirect for a signed-in browser (owner request, item 8)

The owner fixed the card per actor and asked whether
`/.well-known/agent-card.json` at the host root could redirect a browser
whose user is signed in to that user's own actor card.

**What exists:**
- **Root-level well-known routes** are already registered in both
  integrations (`flask_integration.py:383-417`, the OAuth2 metadata
  documents). One more is the same pattern.
- **The browser session is visible at the root.** The `oauth_token` cookie
  is set with `path="/"` and `SameSite=Lax` (`aw_web_request.py:65-73`).
  `session_manager.validate_access_token(cookie)` returns the token data
  with `actor_id` (`flask_integration.py:1808-1820`, used by
  `_check_authentication_and_redirect`).
- **Precedent for a browser-only branch.** `/<actor_id>` already treats an
  `Accept: text/html` request without credentials differently (a redirect
  to `/login`, `flask_integration.py:428-445`).

**What it does and does not reach:**
- It helps a person in a browser find their own card URL.
- It does not help agents or the conformance kit. They fetch without the
  cookie, and `SameSite=Lax` keeps the cookie off cross-site fetches.
  **[inference]** The redirect is a human convenience, not discovery.

**What the plan must state:**
- **The answer without a session.** Options: 404, a redirect to `/login`
  for `Accept: text/html`, or (excluded by decision 8) an app-level card.
  A scanner reads a 404 as "no A2A here".
- **Caching.** The answer depends on the cookie, so it needs
  `Cache-Control: private, no-store` and `Vary: Cookie`. Without them a
  shared cache or CDN in front of the app could serve one user's redirect,
  and so their actor id, to another.
- **Which tokens count.** Only an ActingWeb session token. The legacy
  fallback that validates the cookie as an OAuth provider token
  (`flask_integration.py:1828` onwards) should not resolve an actor here.
- **Cost.** One token-store read per request, as on every cookie-
  authenticated page.

**A cheaper alternative:** show the card URL on the actor's own page in
the web UI, and give it to the SPA through the existing actor metadata.
This needs no root route and no cache rules.

**Size:** one root route in each framework and a small handler. No new
paradigm: it reuses the well-known route pattern and session validation.
