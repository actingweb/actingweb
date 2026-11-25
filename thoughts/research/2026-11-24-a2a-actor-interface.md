# Research: Actors reachable over A2A

**Date:** 2026-11-24
**Feature:** thoughts/features/2026-11-24-a2a-actor-interface.md
**Branch:** master
**Commit:** a74ae35

Sources: the library tree at `a74ae35`, the consumer `../actingweb_mcp` (read
only), the living specs `trust-permissions`, `mcp-server`,
`trust-establishment` and `oauth-client-registration`,
`thoughts/todo/mcp-cache-lifecycle-and-revocation.md`, and the A2A 1.0.0
specification and SDKs as published on 2026-11-24. External quotes were
returned by a fetch tool that caps quotes at about 125 characters and
sometimes paraphrases; text marked *(paraphrase)* or **[inference]** is not
the specification's own wording.

## Owner decision recorded 2026-11-24: who each surface's caller is

Made after this document was written; the plan carries it. Earlier owner
decisions of the same day (uptake, per-caller card, long-running tasks,
one actor at a time) are in the sibling `…a2a-actor-interface.tasks.md`.

| Surface | Caller | Acts on behalf of the actor? |
| --- | --- | --- |
| `/mcp` | a third-party client holding an OAuth2 grant from the actor | **always yes** |
| REST, OAuth2 | the actor (its own sessions and clients) | yes |
| REST, trust secret | a third party in a trust relationship | **never** |
| `/a2a` | a third party | **never**, and never OAuth2-authorised to act for the actor |

**Refined by the owner 2026-11-25:** an `/a2a` caller may hold OAuth2
credentials, issued by an owner-created A2A client, but always as a third
party on trust types of its own, never the `mcp_client` ones and never acting
as the actor. Findings and the open choices: `…a2a-actor-interface.auth.md`.

What the code says about this rule (verified 2026-11-24):
- **The library already tells the two kinds of trust row apart.**
  `established_via` in `OAUTH2_SOURCES` (`"oauth2"`, `"oauth2_client"`,
  `"oauth2_interactive"`; `oauth2_server/trust_lookup.py:15`) marks a row an
  OAuth2 flow wrote, with `legacy_oauth2_row` for rows older than the field
  (`actor.py:71-86`). **Correction (same day):** the shared REST
  authenticator does not use it. `check_token_auth` admits any row whose
  secret matches, OAuth2-written rows included (they hold a secret,
  `interface/trust_manager.py:767-771`), and it tries an SPA token and the
  OAuth2 provider before the trust row (`auth.py:309-343`).
  `check_authorisation(peer_caller_only=True)` (`auth.py:788-823`) refuses
  only callers with no peer id, so it does not refuse OAuth2 rows either. A
  classifier exists; the gate that refuses OAuth2 rows on `/a2a` is new
  code.
- **Today's client-credentials clients are on-behalf principals.**
  `client_registry.py:719-731` writes their trust as type `mcp_client`,
  `established_via="oauth2_client"`, and their `aw_` token is the MCP
  bearer. Under the rule they belong to `/mcp`, so Decision 1, option 2
  as built would admit an on-behalf principal on `/a2a` **[inference]**.
- **The handler acts for a peer [inference].** An `/a2a` caller is checked
  as a peer, never as a client or the owner. The proven way to do that is
  the `/methods` path: `named_route_allows` → `decide` →
  `_check_hook_permission` (`handlers/methods.py`, `access_decision.py:147-302`,
  `interface/hooks.py:978-1029`). `as_peer` (`AuthenticatedActorView`) has
  no production caller and covers neither methods, actions nor attributes;
  using it would be a new pattern (Decision 6).

## Owner decisions recorded 2026-11-24: simplifications before planning

Answers to the decision list built from `…a2a-actor-interface.reuse.md`
(numbers are that list's). Made after this document was written; the plan
carries them.

1. **Release and split:** 4.1.0, A2A off by default, protocol spec 1.6;
   three plans (core A2A, long-running tasks, docs and spec), one PR each.
2. **No per-actor per-type layer** (feature layer b): two layers, the
   trust type's defaults and the per-relationship override (S3). AC-6 and
   AC-14 are reworded accordingly.
3. **Attributes stay private.** No per-trust attribute grants; the
   handler reads attributes as the owner. AC-8 covers properties only.
4. **No new `actor.trust.X` accessor.** The handler gets the owner's
   `ActorInterface` plus the peer's identity and grant; skill calls go
   through the existing hook permission check.
5. **Skills are existing method/action hooks**, granted through the
   `methods`/`actions` categories (S1). No new category.
6. **A2A admission per trust type through app configuration**
   (`acl_rules`, nothing stored); per peer, off by denying all methods and
   actions or by deleting the trust (S2, AC-12).
7. **403 for a bearer that matches no trust**, as on REST (S4, AC-11).
   **Replaced for `/a2a` on 2026-11-25** by `…auth.md` A3: 401 with a
   `Bearer` challenge for a missing, invalid or expired credential.
8. **The card is per actor** at `/<actor_id>/.well-known/agent-card.json`,
   no app-level card, and no host-root `/.well-known/agent-card.json`
   redirect (investigated in `…a2a-actor-interface.reuse.md`: it helps a
   signed-in human only; dropped by the owner).
9. **Hand-written JSON-RPC**, modelled on `/methods`; `a2a-sdk` as a test
   dependency at most.

10. **Out of the A2A plans** (Decisions 7 and 7b), recorded 2026-11-25:
    - **10a, per-relationship grant editing:** stays as it is for A2A,
      which grants skills through the existing `methods`/`actions`
      categories and reads only the actor's own grants. The generic
      editing a consumer carries today goes to a separate library
      feature: `thoughts/todo/per-name-grant-editing.md`.
    - **10b, the synchronised copy:** no library check of the peer's
      grant at the receiving actor, and no A2A change. Actors sit on
      different servers and only the protocol crosses between them: the
      publisher filters what it sends by its own grant, and its control
      ends at the wire. Its grant says what the subscriber may read, not
      whom it may show it to; the protocol states no terms for passing
      data on, and adding them would be a protocol change. A peer's copy
      (`remote:<peer>`) is private to the receiving actor; A2A gives no
      path to it (decision 3, attributes private), and a skill hook that
      reads it is the application's own code, which the A2A docs say.
      The stored peer grant keeps its role: reconciliation (fetch on
      widening, the opt-in `auto_delete_on_revocation`).
    - **The revocation default stays** as it is: a copy is kept after the
      publisher narrows its grant unless the application opts into
      `auto_delete_on_revocation`. No feature document.

11. **Tasks are a general actor feature; A2A is one way in** (recorded
    2026-11-25, with item 13). A task may also be the actor's own, with no
    trust behind it: AI processing the user asked for that runs for
    minutes, a restore, a full data snapshot for download. The actor's own
    tasks are created and followed through a library API only
    (`actor.tasks`, from the app's own code such as its web UI, SPA
    backend or an MCP tool); the library adds no route for them, and the
    app's own sign-in decides who may start or follow one. Peer tasks
    arrive over `/a2a`.
    **Storage (T1, S5):** attributes under the actor in one bucket, a
    small status row per task (status, origin, `version`, deadline, latest
    message) and larger output in an attribute list per task. Row names
    start with the origin: the caller's peer id for A2A, a reserved
    marker that cannot be a peer id (for example `_self`) for the actor's
    own tasks. `ListTasks` reads only its caller's prefix; deleting a
    trust removes that peer's tasks, deleting the actor removes all. Needs
    a prefix read on `Attributes` and one bucket in PostgreSQL's expiry
    list; paging is in memory over one origin's rows. A result larger than
    an attribute list's ceiling (a full snapshot) is stored by the
    application, and the task's result holds a reference.
12. **The worker builds the same `ActingWebApp` and opens a task handle
    with its token** (T2/T2b, S7). The handle takes no actor id: the
    library resolves the actor and the task from the token. It offers
    start, heartbeat, update and complete/fail, plus the actor's data as
    the task needs it. A worker with database access could still call
    `get_by_id`; the handle guides, it does not isolate. Calling back over
    HTTP may follow behind the same handle interface.
13. **A new task token and a `task_dispatch` hook** (T3/T4). A random
    token per task, its hash in one bucket on the system actor (the
    pending-authorisation pattern, `token_manager.py:164-230`). It stops
    working at a terminal state and at its deadline (a heartbeat moves
    it), and for a peer task when the trust is deleted. `task_dispatch`
    receives the task kind (for example `a2a:<skill>`, `snapshot`), the
    task id and the token; the app starts the worker there. The library
    imports no cloud SDK, suggests `ACTINGWEB_TASK_ID` and
    `ACTINGWEB_TASK_TOKEN` and gives a helper that reads them. New code on
    an authentication path: the plan carries a security review.
    MCP verified 2026-11-25 (tasks note, "MCP tasks"): the store fits
    MCP's 2026-07-28 tasks extension. MCP tasks are served only under
    that extension, after dual-era support
    (`thoughts/todo/mcp-tasks.md`). The plan stores results as opaque
    JSON with the kind, writes the task row before dispatch, and draws
    task ids from a secure random source; `input_required` is a scope
    line for the plan.

14. **`SendMessage` returns at once for a handed-off skill** (T5, S10).
    A skill whose hook finishes in the request answers straight away (a
    Message or a completed Task); a handed-off skill returns the task in
    `SUBMITTED` or `WORKING` and the caller polls `GetTask`. This departs
    from A2A's MUST-block rule for handed-off skills only; the docs and
    the spec chapter say so.
15. **Cancel always wins; no takeover; 7 days' retention** (T6, S6).
    `CancelTask`, or the owner's cancel through `actor.tasks`, sets an
    unfinished task to `CANCELED`; the worker's next write is refused (a
    terminal state and the version check), and a `task_cancel` hook tells
    the app so it can stop the worker. A missed deadline fails the task;
    no second worker takes it over, and no lease logic is copied from
    deletion. A retry is a new task. Finished tasks expire after 7 days by
    default, configurable by the app, the same for every kind; unfinished
    ones expire through their deadline. Deleting a trust deletes that
    peer's tasks and stops their tokens (item 11).
16. **Polling only** (T7, S8): `GetTask`/`ListTasks` for A2A callers,
    `actor.tasks` for the actor's own tasks. The Agent Card states
    `pushNotifications` and `streaming` false. No new delivery mechanism.

Every decision the research raised is now answered. The plan's split
(item 1) gains a consequence of item 11: the long-running-tasks plan
builds a general actor task store and API, which the A2A handler uses.

## Research Questions

Codebase:

1. **How is a trust created for an MCP client today, and what credential does
   the caller hold? Which primitives serve an A2A caller unchanged?** —
   `OAuth2ClientManager.create_client` writes an `oauth2_client:` trust row
   and returns `client_id`/`client_secret`. The caller trades them for a
   1-hour `aw_` token (client credentials or code flow). No owner-side
   primitive mints a static credential for a non-ActingWeb caller. See
   [Admission](#admission-and-credentials).
2. **How are per-type permissions and per-peer overrides evaluated? Can they
   express what A2A needs? Is a new category needed?** — Six categories.
   "These properties, read" and "these actions/methods" are expressible
   today. A seventh category (`a2a`) does not fit `TrustPermissions`, the
   enum, the callback payload or the spec text. See
   [Permissions](#permissions-and-the-grant).
3. **What decides access to an attribute today?** — Only application code
   holding the actor. No permission category, evaluator path, view or route
   covers attributes. See [Attributes](#attributes).
4. **Where would per-trust-type configuration or a prompt live?** — Nowhere
   today. `TrustType` has no free metadata field (an unknown key breaks
   `from_dict`). There is no owner-level per-type storage. The trust row has
   a fixed column set, and the override row has only `notes`. See
   [Configuration layers](#configuration-layers).
5. **What would `actor.trust.X.properties/.attributes` offer, and what would
   it replace?** — A permission-filtered view already exists:
   `as_peer`/`as_client` → `AuthenticatedActorView`. It covers properties
   and property lists, keyed by peer, not attributes, and has no production
   caller. `actor.trust` is already the `TrustManager`. See
   [Scoped accessor](#the-scoped-accessor).
6. **Should the accessor offer writes?** — The existing views already
   enforce writes against the grant (excluded parts refused). The feature's
   "writes are the consumer's" does not match that default. This is a
   decision. See [Scoped accessor](#the-scoped-accessor).
7. **Where do an owner's per-type and per-relationship configurations live,
   and what would one primitive returning three layers look like?** —
   Per-relationship: only the override row (`TrustPermissions`). Per-type
   owner level: nothing. No primitive returns layers. See
   [Configuration layers](#configuration-layers).
8. **How long can a removed trust or narrowed permission stay in force in
   another process?** — It depends on the credential. A trust-secret bearer
   is read from storage on every request, so the next request is refused in
   every process. An `aw_` token and its trust are cached up to 300 s per
   process. Overrides are cached up to 300 s. Base trust-type permissions
   are cached with no expiry. See [Revocation](#revocation-and-staleness-bounds).
9. **Which inbound choices make outbound A2A calls harder later?** — The
   trust row assumes an ActingWeb peer: one symmetric secret, `baseuri`
   plus `/meta`, and the `aw_proxy` URL scheme. A remote A2A agent has a
   card URL, an interface URL and an asymmetric credential. See
   [Outbound](#outbound-later).
10. **How does `/mcp` reach application hooks on Flask and FastAPI, and can
    A2A reuse that?** — Flask runs the sync `MCPHandler`. FastAPI awaits
    `AsyncMCPHandler`, and async hooks only work there. JSON-RPC helpers are
    handler methods, not free functions. See [The bridge path](#the-bridge-path).
11. **How does Emm AI differentiate memory access, and what is
    application-only?** — Mostly library pieces: `TrustPermissions` rows plus
    `check_property_access`. Emm's own code holds two editing rules,
    per-type bulk views and list-lifecycle upkeep. There is no per-trust
    prompt. See [Emm AI](#the-consumer-reference-emm-ai).
12. **What per-relationship access exists where a peer's properties are
    synchronised into attributes?** — The `remote:<peer>` copy. The
    publisher filters what is sent by its grant. The subscriber stores the
    received grant but uses it only for opt-in cleanup. See
    [Per-relationship sync](#per-relationship-access-and-the-synchronised-copy).
13. **What does the protocol spec already say about per-relationship
    access?** — Permission structure, query and callback are in 1.5
    (OPTIONAL). The subscriber's copy is mentioned only as an OPTIONAL
    cleanup step. See [Protocol specification](#protocol-specification).
14. **Does an A2A chapter make the spec 1.6, and what does the version rule
    require?** — The spec has no rule for its own number. History: each new
    optional feature bumped the minor. 1.5 is being amended in place until
    4.0.0 is final. The library number follows `CONTRIBUTING.rst`, not the
    spec's. See [Release shape](#release-shape).
15. **Do the request deadline and callback budget constrain a blocking
    `SendMessage` on serverless?** — Nothing bounds a handler's run time.
    The callback budget bounds only callback delivery, and the gateway limit
    (about 29–30 s) is the real bound. See
    [Deadlines](#deadlines-on-serverless).
16. **Does anything serve `/.well-known/` per actor or per application?** —
    Four app-level documents (OAuth/OIDC). Nothing per actor. See
    [The bridge path](#the-bridge-path).

Outside world:

17. **May `SendMessage` answer with a bare Message and keep no task state?
    What must `GetTask`/`ListTasks`/`CancelTask` answer?** — Yes for the
    Message. The three task operations are listed as core with a lowercase
    "must support" and no capability flag. **[inference]** answer
    `TaskNotFoundError` and an empty list. Whether that is compliant is
    open. See [A2A protocol](#a2a-10-what-a-minimal-server-is).
18. **Is any binding mandatory? Which first?** — None is mandatory. Both
    official clients default to JSON-RPC. See [A2A protocol](#a2a-10-what-a-minimal-server-is).
19. **Where should a per-actor card live? Should `tenant` carry the actor
    id?** — The well-known URI is per host only. Per-agent cards are
    reached by direct configuration or a sub-path interface URL; `tenant`
    is the alternative. See [Card location](#card-location-and-multi-agent-hosting).
20. **May the extended card differ per caller?** — The spec says "MAY
    return different details based on client authentication level".
    Per-caller variation is not forbidden but not stated: **[inference]**.
21. **How are bearer secrets and OAuth2 client credentials expressed in
    `securitySchemes`?** — `httpAuthSecurityScheme` (`scheme: Bearer`) and
    `oauth2SecurityScheme.flows.clientCredentials.tokenUrl`.
22. **What must an extension specification contain, and where is it
    published?** — URI (versioned, a new URI for breaking changes), params
    schema, any added data and flows, hosted at the URI. Official ones live
    under `a2a-protocol.org/extensions/`. See [Extensions](#extensions).
23. **Is there a conformance kit, and can it be scoped?** — `a2aproject/a2a-tck`
    runs against a live URL and can be scoped by `--level must` and
    `--transport`. It requires TCK-specific `messageId`-prefix behaviour and
    reads the host-root well-known card. See [Ecosystem](#ecosystem-sdk-conformance-counterparts).
24. **How could uptake be observed without phoning home?** — No clean
    signal. PyPI BigQuery likely does not record extras (unverified).
    Root-path card scans miss per-actor sub-path cards. There is no official
    registry. Unanswered beyond that.
25. **Hand-write the wire layer, or depend on `a2a-sdk`?** — The SDK is
    protobuf-typed and pulls protobuf, google-api-core, httpx and pydantic
    in its core install. Its HTTP dispatchers are Starlette-only, and there
    is no Flask support. See [Ecosystem](#ecosystem-sdk-conformance-counterparts).
26. **Which clients can be a first counterpart?** — A2A Inspector (1.0,
    bearer), the `a2a-sdk` 1.x client, Google ADK and Microsoft Agent
    Framework. CrewAI and BeeAI are still on 0.3.
27. **What do streaming and push require of a server?** — Streaming: a task
    store plus an event bus with ordered SSE and resubscribe. Push: a
    persistent config store, an outbound delivery worker with retries,
    webhook authentication and SSRF guards. See [Streaming and push](#streaming-and-push).

The three items the feature left undecided are answered as far as the code
goes under [Undecided items](#the-features-undecided-items).

## Summary

The hypothesis models A2A on the `/mcp` bridge with admission "reusing what
exists for MCP clients". The code supports the parts *after* authentication:
- A shared decision layer (`access_decision.decide`) and per-category
  evaluation already exist.
- Read-only property grants and named action/method grants are expressible
  today.
- A permission-filtered view of an actor already exists (`as_peer` /
  `as_client`).
- Fixed-text error mapping, correlation-id logging and option tags computed
  from configuration are all in place to copy.

Admission is where the code contradicts the hypothesis. There are two bearer
paths that share no code:
- **The REST path** accepts a trust secret. It reads the trust row on every
  request, so revocation takes effect everywhere at once, and it answers 403
  for a bearer that matches nothing.
- **The MCP path** accepts only an `aw_` OAuth2 token. It caches the token
  and the trust up to 300 s per process, and it answers 401.

AC-15 (an ActingWeb peer's secret) lands on the first, AC-5 (an owner-created
credential) on the second. AC-11's "401" holds only on the second. A "401 for
a bearer that matches no trust" was deliberately left out of
`plans/2026-11-06-peer-authorisation-fixes.md:444` as a library-wide change.
No owner-side primitive issues a static credential for a non-ActingWeb
caller. The nearest is an owner-created OAuth2 client used with client
credentials, which is undiscovered by design (OCR-7). Its ids and scope are
named for MCP (`mcp_…`, scope `mcp`).

Three layers of configuration have no home today:
- `TrustType` cannot carry metadata.
- There is no owner-level per-type store.
- Per relationship there is only the override row. `patterns` and
  `excluded_patterns` are unioned with the type's, while `operations`,
  `allowed` and `denied` are replaced (`trust_permissions.py:988-1025`);
  because `denied` is checked first (`permission_evaluator.py:1140-1145`),
  an override such as `{"denied": ["*"], "allowed": []}` narrows a
  category for one peer (corrected same day; this line first said
  overrides can only add). Re-authorising a client deletes its override
  on creation or a type change.

Attributes are outside the permission model entirely. The feature's belief
that per-relationship access exists "where one actor's properties are
synchronised into another actor's attribute cache" is half right:
- The `remote:<peer>` copy exists, and the publisher filters what it sends by
  its grant.
- The subscriber's stored grant gates nothing except an opt-in cleanup.
- The spec mentions the copy only as an OPTIONAL cleanup step.
- Emm AI's per-trust memory access is mostly library `TrustPermissions` plus
  Emm's editing rules, not an application-level mechanism.

On the A2A side, a server that answers `SendMessage` with a Message and keeps
no tasks is allowed. The specification names `GetTask`, `ListTasks` and
`CancelTask` as operations all implementations "must support" (lowercase),
with no capability flag, so whether a Message-only server is compliant is
open. A request without `A2A-Version` must be read as 0.3. Per-actor cards
are outside the well-known URI: the conformance kit and the SDK's card
resolver both start from a host URL plus `/.well-known/agent-card.json`. Of
the three success measures:
- **Unmodified client exchange:** observable with A2A Inspector or the
  `a2a-sdk` 1.x client against a per-actor card URL.
- **Conformance:** needs a test-mode executor answering the TCK's
  `messageId` prefixes, plus a card the kit can find.
- **Developer effort:** observable as a line count in `examples/demo/`.

## Detailed Findings

### Admission and credentials

**MCP/OAuth2 client trust rows.**
- `OAuth2ClientManager.create_client` (`actingweb/interface/oauth_client_manager.py:40-105`)
  → `MCPClientRegistry.register_client` (`actingweb/oauth2_server/client_registry.py:66-204`).
  - It mints `client_id = "mcp_<hex>"` and a `client_secret` (:125-126).
  - It writes the trust row first, then the client row (:160-172; OCR-D1).
- The row (`actingweb/interface/trust_manager.py:756-850`):
  - peer id `oauth2_client:<id>:<id>` (`trust_manager.py:146-159`)
  - `peer_type="mcp"`, `relationship=<trust_type>`, `baseuri=""`
  - `approved=True`, `verified=True`, `established_via="oauth2_client"`
  - a generated `secret` that no response returns
- The code flow binds a second row on the user's actor
  (`oauth2_server.py:1163-1216`), after the `oauth2_trust_requested` hooks
  decide (OCR-3, OCR-4).
- What the caller holds:
  - `client_id` + `client_secret`
  - 1-hour `aw_` access tokens (`token_manager.py:83-84`)
  - with the code flow, a rotating 30-day refresh token
- The `client_credentials` grant (`oauth2_server.py:783-851`):
  - It works for an owner-created confidential client and ignores the stored
    `grant_types`.
  - It is refused for the system actor's clients and not offered in
    discovery (OCR-7).
- `OAuth2ClientManager.generate_access_token` mints the same token from the
  owner's side (`oauth_client_manager.py:377-435`).

**ActingWeb peer on REST.** `Auth.check_token_auth` (`actingweb/auth.py:264-333`)
tries in this order:
1. The SPA session token.
2. External provider validation.
3. Trustee passphrase.
4. `Trust(actor_id, token=…).get()`, a lookup by secret on both backends
   (`db/dynamodb/trust.py:147-152`, `db/postgresql/trust.py:128-141`) with
   no filter on `established_via`.

`verified` is not checked. `approved` is checked at authorisation
(`auth.py:846-855`). A failed bearer answers **403** (`auth.py:760-763`).
Only a missing `Authorization` header under basic auth answers 401
(`auth.py:165-171`).

**The two paths share nothing.**
- The REST path never calls the token manager, so an `aw_` token fails there.
- The MCP path rejects anything without the `aw_` prefix
  (`token_manager.py:422`), so a trust secret fails there.

**Entry points a new route could call.**
- `BaseHandler.authenticate_actor` / `require_authenticated_actor`
  (`handlers/base_handler.py:217-312`) return `AuthResult` with
  `auth_obj.acl["peerid"]`, `acl["relationship"]` and `auth_obj.trust`.
- `MCPHandler.authenticate_and_get_actor_cached` (`handlers/mcp.py:2386-2565`)
  resolves token → actor → trust via `find_client_trust`
  (`oauth2_server/trust_lookup.py:94-120`).
- No single function accepts both credential kinds.

**Owner-created static credential for a non-ActingWeb caller.** None exists.
The candidates:

| Primitive | Why it does not fit |
|---|---|
| `create_relationship` / `create_verified_trust` (`actor.py:2315-2514`, `3004-3163`) | Both need a peer `baseuri` that serves `/meta` and `/trust`. |
| `create_or_update_oauth_trust` | Writes a local row with a generated secret and no handshake, but returns no secret, and its peer id is always OAuth2-shaped. |
| Low-level `Trust(...).create()` (`trust.py:466-591`) | Accepts an empty `baseuri` and generates a secret. It is not a public owner API. |

The owner can read any row's secret through the per-relationship trust GET
(`handlers/trust.py:837-850`).

### Permissions and the grant

**Trust types.** `AccessControlConfig.add_trust_type` (`actingweb/permission_integration.py:317-394`).
- **Fields:** `TrustType` (`actingweb/trust_type_registry.py:30-58`) has
  name, display_name, description, base_permissions, allow_user_override,
  oauth_scope, created_by and acl_rules.
- **Storage:** JSON in system-actor property `trust_type:<name>` (:181-183).
- **Unknown keys:** `from_dict` is `cls(**data)` (:65-67), so a stored
  unknown key makes `get_type` return `None` (:222-224).
- **`allow_user_override`:** has no reader anywhere in `actingweb/`.
- **Built-in types:** associate, viewer, friend, partner, admin, mcp_client.
- **Exposure:** `aw_trust_types` in `/meta`, plus
  `/meta/actingweb/trust_types` and `/meta/trusttypes` (`handlers/meta.py:35-126`).

**Categories and rules.**
- `PermissionType` has PROPERTIES, METHODS, ACTIONS, TOOLS, RESOURCES and
  PROMPTS (`permission_evaluator.py:153-161`).
- The rule shapes:
  - `{allowed, denied}`
  - `{patterns, operations, excluded_patterns}`
- Glob matching, with exclusions covering descendants (`:190-303`).
- "These properties, read only" is `{"patterns": […], "operations": ["read"]}`.
  "These actions/methods" is `{"allowed": […]}`.
- Shared decision: `access_decision.decide` (`actingweb/access_decision.py:147-230`).
  - Not approved → deny.
  - A category the grant mentions answers.
  - An unmentioned category denies a client and falls to the access table
    for a peer.

**Merge.** `merge_permissions` (`actingweb/trust_permissions.py:952-1031`,
checked):
- `patterns` and `excluded_patterns` union with the base.
- `operations`, `allowed` and `denied` replace the base.

An override can therefore add patterns or exclusions but cannot remove a
base pattern. Narrowing works through `excluded_patterns` or a replaced
`operations`.

**A seventh category.**

| Place | What happens to an `a2a` category |
|---|---|
| `TrustType.base_permissions` | Accepts it |
| `AccessControlConfig._convert_simple_permissions` (`permission_integration.py:428-457`) | Drops it silently |
| `TrustPermissions` (`trust_permissions.py:77-97`, checked) | Fixed fields, `from_dict(**data)`; cannot store it |
| `update_permissions` | Logs "Unknown permission field" |
| Callback payload, `GET …/permissions` and the spec text (spec 2978-3005) | Name exactly six categories |
| `evaluate_permission` | Needs an enum member |

**Shorthand inconsistency.** A plain property list passed to
`add_trust_type` becomes `["read","write"]` (`permission_integration.py:430-435`),
although its docstring says read-only. The same list as an override becomes
`["read"]` (`peer_permissions.py:41-43`).

**MCP per-peer filtering (precedent for AC-6).**
- `tools/list` filters in this order (`handlers/mcp.py:1323-1535`):
  1. `allowed_clients`
  2. `visibility_predicate`
  3. `evaluate_permission(..., TOOLS, name, "use")`
- `resources/list` and `prompts/list` do the same with RESOURCES and
  PROMPTS (`:1585-1790`).
- The call gates evaluate again.
- The hook then receives the **unscoped** `ActorInterface`
  (`hook(actor, name, args)`, `:1867`). It learns the peer only through
  `RuntimeContext`.

### Attributes

- **What they are:** `Attributes(actor_id, bucket)` entries and
  `AttributeListStore` lists (`actingweb/attribute.py:300-775`,
  `actingweb/attribute_list_store.py:41`).
- **Permissions:** no `PermissionType`, evaluator, `decide` or view
  references them.
- **HTTP:** none outside `/devtest`. `PUT /properties` with an attribute
  payload answers 403 (`handlers/properties.py:2089`).
- **What the docs promise:** attributes are "for data no peer may read or
  subscribe to" (`docs/guides/property-lists.rst:69-78`) and "should never
  be reachable through a trust relationship" (`docs/sdk/index.rst:55-60`).
- **Owner memory** ("attributes are private properties, same list
  interface"): parity is a design goal. A grant on attributes would be new
  in both the code and the spec.

### Configuration layers

| Layer | Storage today |
|---|---|
| Application, per trust type | `TrustType` fields only; free text in `description`; no metadata dict. The only app-level prompt precedent is `with_mcp(instructions=…)`, one value per server, not per type (`handlers/mcp.py:1249-1251`). |
| Owner, per trust type | None. No per-actor, per-type settings exist anywhere. |
| Owner, per relationship | `TrustPermissions` row in the actor's `_trust_permissions` bucket: six categories, `created_by`, `updated_at`, `notes` (`trust_permissions.py:64-111`). The trust row has fixed columns on both backends (`db/dynamodb/trust.py:76-114`, `db/postgresql/trust.py:118-122`) and no JSON or custom column. |

Two existing behaviours bear on storing per-relationship configuration in
the override row:
- `create_or_update_oauth_trust` deletes the override unconditionally when
  it **creates** an OAuth2 trust row (`trust_manager.py:815-830`, checked).
- On an **update** (re-authorisation of an existing row), `_clean_client_override`
  (`trust_manager.py:492-530`, checked) removes it only when its
  `trust_type` differs from the row's new type. Such an override is not
  applied anyway (owner decision 2026-11-11, `override_applies`).
- `docs/guides/oauth2-setup.rst:238-239` ("A re-authorisation … removes its
  permission override") overstates this: a same-level re-authorisation
  keeps the override.
- MCP-10: a reconnect after a disconnect starts from a fresh grant.

So an owner's per-relationship configuration stored there would vanish on
reconnect and on a change of level.

### The scoped accessor

`actor.as_peer(peer_id, trust)` and `actor.as_client(client_id, trust)`
(`actingweb/interface/actor_interface.py:643-695`) return an
`AuthenticatedActorView` (`actingweb/interface/authenticated_views.py:894-1009`)
exposing `properties`, `property_lists` and `subscriptions`. `trust` is
passed through unscoped, and there are no attributes.

**What the view already does:**
- Every property read goes through `decide`.
- Iteration drops unreadable keys.
- `drop_excluded` strips excluded parts.
- Writes are refused when old or new values touch an excluded part
  (`:146-318`).
- Lists are bulk-filtered (`:529-773`).

**Find and query:**
- Lists offer only `find(identity_key, value)` and `find_all` on an identity
  key.
- There is no general filter or query on either the owner or the view
  stores (`interface/property_store.py:426-495`).

**Callers:**
- No production code builds these views. `BaseHandler._get_authenticated_view`
  (`handlers/base_handler.py:105-162`) has no caller and reads
  `acl["oauth2_client"]`, which nothing writes.
- The design came from `thoughts/research/2025-12-12-unified-handler-architecture.md`.
- `6569ff25` (CHANGELOG SECURITY, line 371) bound view subscriptions to
  their own peer.

**Hand-written checks the view could replace:**
- `handlers/properties.py` (`_decide_property`, 16 call sites, the
  `drop_excluded` calls at :1187, :1243, :1344, :1361)
- `TrustSharedPropertiesHandler` (`handlers/trust.py:1753-1910`)
- `Actor.filter_subscription_blob` (`actor.py:4251-4519`)
- `permission_integration.register_permission_hooks`, whose
  `_extract_peer_from_context` always returns `None`, so it always allows
  (`permission_integration.py:290-300`)

**Name collision:** `actor.trust` is the `TrustManager`
(`docs/sdk/developer-api.rst:66, 159-275`). `actor.trust.X.properties` would
add attribute access on that manager.

**Writes:** the existing view enforces the grant on writes. The feature's
AC-28 ("the library does not refuse a write because the request arrived over
A2A") holds when the handler writes through the owner's `ActorInterface`
(the MCP precedent) and fails if it writes through the view.

### Revocation and staleness bounds

| Credential path | Same process | Other processes |
|---|---|---|
| Trust-secret bearer (REST) | Next request refused (row read by secret every time, `auth.py:309-314`) | Next request refused |
| `aw_` token (MCP) | Next request refused (`evict_mcp_caches_for_actor`, `handlers/mcp.py:410-450`; tokens revoked in `Trust.delete`, `trust.py:200-309`) | Up to 300 s (`_token_cache`, `_trust_cache`; `handlers/mcp.py:129, 136`) |
| Per-peer override | At once (TPM-2) | Up to 300 s (TPM-1) |
| Trust-type base permissions | Registry cache, no expiry after `list_types()` (`trust_type_registry.py:198, 246, 303`) | No expiry (TPM-D1) |

**Grant evaluation reads the trust row on every call.** Checked: `snapshot`
(`permission_evaluator.py:873-885`) and `_approval` (`:949-979`) both call
`db_trust.get` uncached, and no row means DENIED. So on the MCP path a
deleted trust denies tool calls in every process at once, even while the
cached token still authenticates: an empty list or `-32003`, not a 401. This
holds for an A2A path only if it runs the evaluator (or `decide`) before the
handler, not just authentication.

**What AC-13 can promise depends on the credential path.** For an A2A caller
on the REST-style path: immediate everywhere. On a token path: 300 s
authentication, immediate grant.

**AC-14:**
- A narrowed override is in force after at most 300 s.
- A change to a trust type's base permissions is never seen by another
  process until restart.

`docs/reference/security.rst:120` states the MCP bounds; the todo proposes
documenting the fleet-wide bound there.

### Outbound later

The trust row's fields (`db/protocols.py:795-880`) carry one symmetric
`secret`, used as both the inbound and outbound bearer
(`actor.py:2441-2469`, `aw_proxy.py:127-133`).

What assumes an ActingWeb peer:
- `aw_proxy` needs `baseuri` + `secret` and builds `baseuri + "/" + path`
  (`aw_proxy.py:135-176, 210`).
- Trust creation needs `/meta` and `/trust` at `baseuri`.
- `is_valid_peer_id` refuses OAuth2-prefixed ids (`trust.py:15-37`).
- `delete_reciprocal_trust` sends a remote DELETE except for OAuth2-classed
  rows (`actor.py:3290-3346`).

A remote A2A agent would need a card URL, an interface URL (and maybe a
`tenant`), and an outbound credential separate from the inbound one. An
inbound design that stores A2A callers as `oauth2_client:` rows with
`baseuri=""` fits the "local-only" deletion rules. A design that stores
them as ordinary peers with a `baseuri` would trigger remote DELETE and
`/meta` checks.

### The bridge path

**Configuration.**
- `with_mcp()` stores builder state (`interface/app.py:177-182, 677-751`).
- `_apply_runtime_changes_to_config` copies it to `Config` (`:272-299`).
- **MCP is on by default** (`_enable_mcp = True`, checked).

**Routing.**
- `/mcp` is one app-level route on both integrations
  (`flask_integration.py:371-379`, `fastapi_integration.py:996-1005`).
- It is registered unconditionally. The handler answers 404 when
  `config.mcp` is false (`handlers/mcp.py:902-912`, checked at :941 and
  :1050), which is the AC-21 pattern.
- `/<actor_id>/a2a` would be the first optional feature at a path under the
  actor root. Flask's request-context middleware already extracts the actor
  id from such paths (`flask_integration.py:155-182`).

**Handler dispatch.**
- Flask runs the sync `MCPHandler` in the request thread.
- FastAPI awaits `AsyncMCPHandler`, which awaits async hooks
  (`async_mcp.py:224-227`).
- The sync handler cannot await an async hook
  (`tests/test_mcp_tool_failure_results.py:197-199`).
- `HookRegistry._execute_hook_in_sync_context` (`interface/hooks.py:686-734`)
  runs async hooks with `asyncio.run`, in a worker thread when a loop is
  running. This is the Flask route for an async A2A handler.

**Error mapping and logging.**
- `_tool_failure_result` and `_failure_response` (`handlers/mcp.py:2991-3111`)
  give fixed texts per fault class, `repr` only in logs, and `-32603` for
  unexpected errors (MCP-12 to MCP-20).
- JSON-RPC builders are handler methods (`mcp.py:2180-2188`; also
  `methods.py:305-386`, whose `-32603` *includes* `str(e)`).
- The correlation id reaches log lines only through `RequestContextFilter`
  (`log_filter.py:50-64`). The request id is set by both integrations
  (`flask_integration.py:155-197`, `fastapi_integration.py:540-586`).

**Option tags.**
- `Config._supported_options()` is recomputed on every read
  (`config.py:583-621`).
- `mcp` is added when `self.mcp` is set (`:613-614`).
- An `a2a` tag would follow the same pattern.

**Well-known documents.** Four app-level documents, none per actor, none
gated on `config.mcp`:
- `oauth-authorization-server`
- `openid-configuration`
- `oauth-protected-resource`
- `oauth-protected-resource/mcp`

They are served in `flask_integration.py:382-418` and
`fastapi_integration.py:1008-1039`.

**Invoking granted actions and methods (AC-9).**
- `ActorInterface` has no call-an-action API.
- `HookRegistry.execute_action_hooks` / `execute_method_hooks` (and
  `_async`) check `decide` when an `auth_context` with `peer_id` is passed
  (`interface/hooks.py:380-449, 978-1098`).
- A denied call returns `None`, the same value as "no hook ran". The handler
  cannot tell refusal from absence.
- Without `auth_context` the call is allowed.

**Test harness (AC-18).**
- The `:5555` integration server is FastAPI only (`tests/integration/conftest.py:483-549`).
- Same assertions on both frameworks run in process:
  - the `_Client(kind)` fixture with `params=["flask","fastapi"]`
    (`tests/integration/test_property_item_paths.py:62-136`)
  - also `test_callback_webhooks.py:143-157`
  - the parametrised factories in `tests/test_oauth2_logout_mcp_tokens.py:157-171`,
    used by `tests/test_flask_well_known.py`

### Deadlines on serverless

- `callback_delivery_budget_seconds` bounds only callback sends within a
  request (`callback_sender.py:110-167`).
- No `wait_for`, deadline or timeout bounds a handler or hook in the
  integrations.
- The documented gateway limits are "30 s, say" (`docs/quickstart/deployment.rst:108-178`)
  and "~29 s" (`docs/guides/subscriptions.rst:720-730`, `mcp-applications.rst:718-753`).
- A blocking `SendMessage` whose handler calls a model must finish inside
  that limit, and any callbacks its writes trigger share the same request
  deadline (TPM-3).
- A2A's default for `returnImmediately` is false: the server waits for a
  terminal or interrupted state (A2A §3.2.2).

### The consumer reference: Emm AI

Read in `../actingweb_mcp`.

**Storage.** Memories are property lists `memory_<type>`. Type metadata is
JSON in the list's description (`memory_config.py:403-446`).

**Differentiated access:**
- Three trust types through `AccessControlConfig.add_trust_type`
  (`application.py:723-903`):
  - `mcp_client_readonly`: read on `memory_*` and others
  - `mcp_client_readwrite`
  - `subscriber`: displayname and email only
- Every per-connection setting is a library `TrustPermissions` row written
  through `store_permissions[_async]`. Emm has no table or attribute of its
  own.
- Emm encodes two editing rules by relationship:
  - **MCP clients:** start at `memory_*` read/write and deny by adding to
    `excluded_patterns`.
  - **subscriber:** start empty, read only, and grant by adding to
    `patterns`.

  Owner-only endpoints apply them per relationship (`api/trust.py:276-563`)
  and per type across relationships (`api/memory_types.py:333-513`).
- **Enforcement:** Emm calls the library's `check_property_access` at every
  read (`hooks/mcp/tools/shared.py:294-390`).

**Application-only and plausibly generic:**
- the two default models for an override
- grant or revoke one name, grant-all and revoke-all
- a per-name view across all relationships
- "which list names may this peer read" (filtering names by prefix)
- keeping exclusions consistent when lists are created or deleted
- stripping grants when a subscription is deleted

**Emm-specific:**
- the `memory_` naming and built-in types
- system types
- gating remote memory by the MCP client's access to the *local* type name
  (`search.py:594`)

**Per-trust prompt:** none. Standing instructions are per actor, served
identically to every client (`hooks/mcp/tools/agent_run.py:63-69`).

**Connections:**
- **MCP client:** the SPA calls `create_client(client_name, trust_type)`
  (`api/oauth_clients.py:26-80`). The user receives `client_id` and
  `client_secret`, or a client-credentials token. The normal path hands
  over only the MCP URL and goes through `/oauth/authorize`.
- **Peer:** the user pastes a remote actor URL. Emm calls
  `create_relationship` with an empty secret (`api/trust.py:42-271`), and
  no credential is handed over.

**Relation to the feature:** the feature's statement that Emm's per-trust
access "was first built at application level" is accurate only for the
editing rules and bulk views. Storage and evaluation are the library's.

### Per-relationship access and the synchronised copy

**Storage.**
- With `with_subscription_processing(auto_storage=True)`, a subscriber
  writes what a publisher sends into bucket `remote:<peer_id>`
  (`actingweb/remote_storage.py:95-175, 439-682`).
- It is wired into the callback handler (`handlers/callbacks.py:1419-1484`)
  and into the first baseline (`interface/subscription_manager.py:553-583`).
- No route serves it.

**What controls what is synced.** The publisher's grant, applied by the
publisher: `Actor.filter_subscription_blob` (`actor.py:4301-4429`) filters
every pushed and pulled diff.

**What the subscriber learns.**
- It stores the grant it received (from a permission callback, or by query
  at subscribe time and in `sync_peer_async`) in `_peer_permissions`
  (`peer_permissions.py:239-497`).
- That grant filters nothing incoming or outgoing.
- `PeerPermissions.has_property_access` and its siblings have no callers.

**Where the stored grant is used:**
1. Opt-in `auto_delete_on_revocation` deletes names the new grant no longer
   allows (`replica_revocation.py:98-127, 239-296`). A grant shape it cannot
   evaluate is recorded as `NotEvaluated`.
2. On widening, newly granted patterns are fetched
   (`callbacks.py:1733-1995`).

**Where it stops:**
- No spec text defines the copy.
- No record of which subscription stored a key.
- `RemotePeerStore.apply_permission_data` has no caller.
- The synchronous `sync_peer` refreshes no permissions, although
  `app.py:1014-1015` says it does.
- The receiver handler ignores `peer_permissions_caching`, although
  `config.py:205-206` says cleanup depends on it.

**Relation to A2A.** This mechanism is "what a peer granted *us*", stored on
the receiving side. A2A admission needs "what *we* grant a caller",
evaluated on the serving side, which is the evaluator and override path
above. The two meet only where an A2A handler answers from replicated peer
data. Emm gates that by the caller's access to the local name, not by any
per-peer setting.

### Protocol specification

Locations in `docs/protocol/actingweb-spec.rst`:

| Topic | Location | Content |
|---|---|---|
| Permission structure | 2978-3005 | Six categories; `tools`/`prompts` "for MCP clients"; no attributes |
| Permission query | 2865-2976 | OPTIONAL, `permissionquery` |
| Permission callback | 4179-4338 | OPTIONAL, `permissioncallback`; receiver step "Clean up local data for revoked permissions (OPTIONAL)" at 4318 |
| Option tags | 770-863 | An actor MUST advertise the tag of each OPTIONAL path it serves (783-792); each OPTIONAL path has a same-named tag (1077-1081); `oauth` and `mcp` name capabilities, not paths (1132-1134) |
| MCP chapter | 2024-2084 | Overview, five MUSTs (2040-2049), transport and location not mandated, single-actor binding, security, guidance, tag. The template for an A2A chapter |
| Well-known | 786-792 | Not mentioned. Implementations MAY serve discovery documents at the root, and peers MUST NOT depend on undefined paths. An A2A chapter would have to define any card path it relies on |
| Trust types before trust | `aw_trust_types` (1276-1290), `/meta/trusttypes`, `/meta/actingweb/trust_types` | Names and descriptions only; no per-type permissions are advertised before trust exists |

**What a peer on another implementation could not rely on today:**
- an attribute grant
- any per-type configuration
- the subscriber-side copy's semantics

### A2A 1.0: what a minimal server is

From <https://a2a-protocol.org/latest/specification/> (labelled 1.0.0) and
`a2a.proto` at `v1.0.0`. Section numbers are the specification's.

- **Message-only replies.** §3.1.1: "The operation MUST return immediately
  with either task information or response message". The agent "MAY create
  a new `Task`". The life-of-a-task topic page names "Message-only" agents
  (non-normative). §3.7: "Messages SHOULD NOT be used to deliver task
  outputs."
- **Mandatory operations.** §3.1 says the core operations "define the
  fundamental capabilities that all A2A implementations must support". The
  "must" is lowercase, and there is no compliance matrix.
- **Capability gates (§3.3.4):**
  - streaming off → `UnsupportedOperationError`
  - push off → `PushNotificationNotSupportedError`
  - extended card off → `UnsupportedOperationError`; declared but not
    configured → `ExtendedAgentCardNotConfiguredError`
- **GetTask, ListTasks, CancelTask** have no gate. **[inference]** A
  task-less server answers `TaskNotFoundError` (-32001) and
  `{"tasks": [], "nextPageToken": ""}`.
- **Bindings.**
  - None is mandatory (§5.2, "Clients MAY choose any protocol declared by
    the agent").
  - JSON-RPC method names are PascalCase: `SendMessage`, `GetTask`,
    `ListTasks`, `CancelTask`, `GetExtendedAgentCard`, …
  - HTTP+JSON paths: `POST /message:send`, `GET /tasks/{id}`,
    `GET /extendedAgentCard`, each also under a `/{tenant}/` prefix in the
    proto.
  - The Python `a2a-sdk` client defaults to "JSONRPC only". The JS client
    defaults to JSON-RPC then REST.
- **Versioning (§3.6):**
  - "Clients MUST send the `A2A-Version` header".
  - "Agents MUST interpret empty value as 0.3 version."
  - An unsupported version gets `VersionNotSupportedError`: JSON-RPC
    -32009, HTTP 400.
  - So a 1.0-only server must refuse a header-less request as 0.3 (AC-24).
- **Errors (§5.4):**
  - -32001 TaskNotFound
  - -32004 UnsupportedOperation
  - -32005 ContentTypeNotSupported
  - -32009 VersionNotSupported
  - standard -32600/-32601/-32602/-32603
- **Authentication (§3.3.2).** "Servers MUST reject requests with invalid or
  missing authentication credentials". Example codes are HTTP 401 / 403 or
  a "JSON-RPC custom error". There is no numbered auth code. Servers "MUST
  NOT reveal the existence of resources the client is not authorized to
  access" *(paraphrase for the second half)*.
- **Security schemes (§4.5).** OpenAPI 3.2-based. A card carries
  `securitySchemes` and `securityRequirements`, and each skill can carry its
  own. Bearer: `{"httpAuthSecurityScheme": {"scheme": "Bearer"}}`
  **[inference from the field definitions]**. OAuth2 client credentials:
  `oauth2SecurityScheme.flows.clientCredentials.tokenUrl` plus `scopes`.
- **Extended card (§3.1.11).** Flag `capabilities.extendedAgentCard`.
  "MAY return different details based on client authentication level."
  Per-caller variation: **[inference]**, not stated.

### Card location and multi-agent hosting

**What the specification says:**
- §8.2 defines the well-known URI per host:
  `https://{server_domain}/.well-known/agent-card.json`.
- Other discovery mechanisms are registries and "Direct Configuration".
- There is no top-level `url` in 1.0. The endpoint is
  `supportedInterfaces[0].url`.
- `AgentInterface.tenant` is "An opaque string used for routing requests to
  a specific agent or tenant when multiple agents are served behind a
  single A2A endpoint". On `main` and the spec page: "clients MUST include
  this value". The `v1.0.0` proto comment is weaker.
- The multi-tenancy topic page lists three patterns: a sub-path per agent,
  routing by credentials, and `tenant`. "Each agent SHOULD have its own
  Agent Card published at an appropriate location."

**Community positions:**
- RFC 5785 forbids path segments before `/.well-known` (cited in A2A
  discussion #166).
- The host-level catalog proposal (#641) was closed in favour of the
  external AI Catalog (`/.well-known/ai-catalog.json`).
- The Python `A2ACardResolver` builds `base_url + "/" + path`, so a base URL
  `https://host/<actor_id>` resolves to
  `https://host/<actor_id>/.well-known/agent-card.json`. That is SDK
  behaviour, not RFC 8615.
- A Quarkus resolver silently falls back to the default agent on a tenant
  path (quarkus-langchain4j #3005).

### Extensions

- **Declaration:** `AgentExtension {uri, description, required, params}`
  in `capabilities.extensions` (§4.4.4).
- **Activation:** the `A2A-Extensions` request header (§9.2, §11.2).
- **Versioning (§4.6.3):** versions SHOULD be in the URI, and a breaking
  change MUST get a new URI.
- **What an extension specification contains** (non-normative topic page):
  - its URI(s)
  - the params schema
  - schemas for any added data
  - any new flows or methods
- **Hosting:** at the URI. Official extensions use the
  `https://a2a-protocol.org/extensions/` prefix under the `a2aproject`
  organisation.
- **Limits:** an extension cannot add fields to core objects (use
  `metadata`), and data-only extensions should not be `required`.
- **Overlap:** none of the published or experimental extensions checked
  defines persistent relationships or per-peer permissions.
  `experimental-ext-cratb-auth` (SD-JWT identity proof inside a task) and
  `experimental-ext-oid4vp-auth` are the closest.

### Streaming and push

**Streaming:**
- `SendStreamingMessage` over SSE. In the Message-only case the stream
  "MUST contain exactly one `Message` object and then close immediately".
- `SubscribeToTask` returns the Task first.
- Ordered delivery, several streams per task.
- **[inference]** This needs a task store and an event bus.
- The two integrations have no SSE today: `GET /mcp` with
  `text/event-stream` answers 405 (MCP-3).

**Push:**
- Four config operations. Configs persist until the task completes.
- At-least-once POST of a `StreamResponse`.
- "Agents MUST include authentication credentials in webhook requests".
- Agents SHOULD reject private address ranges.
- **[inference]** This needs a persistent task and config store, a delivery
  worker with retries, SSRF guards, and probably a JWKS endpoint.
- The callback sender (`callback_sender.py`) is the nearest existing
  outbound machinery.

### Ecosystem: SDK, conformance, counterparts

**`a2a-sdk` 1.3.1 (2026-11-17), Python 3.10–3.14, protobuf types:**
- Core dependencies (from `main`'s `pyproject.toml`, not the tag): httpx,
  pydantic, protobuf, google-api-core, json-rpc, googleapis-common-protos
  and packaging.
- Starlette and FastAPI are extras.
- `RequestHandler` is async and imports no web framework, but the
  JSON-RPC dispatcher takes a Starlette `Request`.
- There is no Flask support.

**Conformance:**
- `a2aproject/a2a-tck` is run as `./run_tck.py --sut-host URL --transport …
  --level must|should|may`.
- It produces JUnit XML.
- The server must react to `messageId` prefixes (`tck-complete-task`,
  `tck-message-response`, …), so a test-mode executor is needed.
- It reads `{sut-host}/.well-known/agent-card.json`.
- Its README and requirements docs disagree on the CLI, and exit codes are
  undocumented.
- `a2a-itk`/ACTS is a second, SDK-oriented suite.

**Counterparts:**

| Client | 1.0 | Bearer token | Notes |
|---|---|---|---|
| A2A Inspector | Yes | `--auth "Bearer …"` | |
| `a2a-sdk` 1.x client | Yes | Interceptors | |
| Microsoft Agent Framework A2A | Yes (`a2a-sdk>=1.0`) | `AuthInterceptor` | Beta |
| Google ADK 2.15 | 0.3 and 1.x | Not documented | |
| CrewAI | 0.3 only | | Would need a 0.3 interface |
| BeeAI | 0.3 only | | Would need a 0.3 interface |

**Uptake:**
- No official registry.
- PyPI BigQuery likely does not record extras (unverified).
- Public scans probe only `/.well-known/agent-card.json` at host roots.

### The feature's undecided items

- **Smallest scope (card, message in, answer out):** allowed by the
  specification for the Message reply. It may fall short of the
  lowercase-"must" core set unless `GetTask`/`ListTasks`/`CancelTask` are
  answered (see Decision 3). Streaming and push each imply a task store
  (see [Streaming and push](#streaming-and-push)).
- **What `X` names in `actor.trust.X`:** the existing views key on a peer
  (`permission_id`; a client resolves to its trust row's peer id). The
  evaluator needs a trust row for every entry point except
  `evaluate_rules_for(type, rules, …)`. A trust-type-keyed accessor would
  have no override to apply and no row to check `approved` against.
- **Where the card lives:** the specification fixes only the per-host
  well-known URI. See Decision 4.

## Acceptance Criteria Testability

| AC | Code path | Test level and harness |
|---|---|---|
| AC-1 | New route under `/<actor_id>/…` on both integrations; card built from config | Unit/in-process, two-framework `_Client(kind)` pattern (`tests/integration/test_property_item_paths.py:62-136`); schema check against `a2a.proto` JSON or A2A Inspector (manual) |
| AC-2 | Card builder filters skills marked restricted | Unit |
| AC-3 | Card `capabilities.extensions[]` with params (root URI, trust types from `aw_trust_types` / registry) | Unit |
| AC-4 | `Config._supported_options` (`config.py:583-621`) | Unit, as for `mcp` |
| AC-5 | No primitive today. Nearest: `OAuth2ClientManager.create_client` (+ client credentials) or a new owner call over `Trust.create` | Integration on the `:5555` FastAPI server or in-process; needs the new primitive |
| AC-6 | Filter like `tools/list` (`handlers/mcp.py:1323-1535`) over registered skills | Unit/in-process. The specification only says "authentication level"; per-caller variation is an inference |
| AC-7 | Authentication → `AuthResult.acl` / MCP context → handler call | In-process, both frameworks |
| AC-8 | `AuthenticatedActorView` (properties, lists) + new attribute coverage | Unit with real storage (both backends); attributes need a grant model first |
| AC-9 | `HookRegistry.execute_*_hooks` with `auth_context` (`hooks.py:380-449`) | Unit. A denial returns `None`, the same as no hook, so the test cannot observe a "refused" result without a change |
| AC-10 | New response mapper | Unit + Success Measure client run |
| AC-11 | REST path answers **403**, MCP path 401 | In-process, both frameworks. 401 on the REST-style path is a recorded deferral (`plans/2026-11-06-peer-authorisation-fixes.md:444`). Spec 1.5 allows either ("refused (401 or 403)", `actingweb-spec.rst:259, 1050`); A2A §3.3.2 gives 401 only as an example |
| AC-12 | `decide` with a new category or an existing one | Unit + in-process |
| AC-13 | Per credential path (see table above); grant evaluation before the handler makes a deleted trust refused at once on any path | Same-process: in-process test. Cross-process: the `tests/test_permission_cache_bounds.py` pattern (clock/TTL) for token paths; nothing needed for the secret path |
| AC-14 | Override cache 300 s (TPM-1); base permissions never expire (TPM-D1) | Existing `tests/test_permission_cache_bounds.py` pattern; a base-type change cannot be shown within any bound today |
| AC-15 | `auth.check_token_auth` by secret (`auth.py:309-331`) | In-process with two actors, or `:5555` + peer server `:5556` |
| AC-16 | Copy `_failure_response` / fixed texts (`handlers/mcp.py:2991-3090`) | Unit, sync and async handler side by side (`tests/test_mcp_tool_failure_results.py:109-150` pattern) |
| AC-17 | JSON-RPC -32004 / HTTP 400 | Unit |
| AC-18 | Both integrations | The `:5555` harness is FastAPI only; in-process two-framework fixtures exist. Async handler on Flask runs through `asyncio.run` (`hooks.py:686-734`) |
| AC-19 | Existing `POST /<id>/trust/<rel>` (TES-1 to TES-11) + A2A admission by secret | Integration, two actors (peer fixture `:5556`) |
| AC-20 | `_supported_options` | Unit |
| AC-21 | Handler-level 404 when disabled (MCP pattern, `handlers/mcp.py:902-912`) | In-process, both frameworks |
| ~~AC-22~~ | Dropped 2026-11-24 | — |
| AC-23 | `RequestContextFilter` (`log_filter.py:50-64`) + `logger.error(..., exc_info=True)` | Unit with `caplog` and the filter installed |
| AC-24 | New version check; a missing header means 0.3 (§3.6) | Unit |
| AC-25 | No storage for owner-per-type configuration today | Unit once a store exists |
| AC-26 | Override row (`notes` only) or a new store; wiped on OAuth2 re-authorisation (`trust_manager.py:815-830`) | Unit, both backends |
| AC-27 | Same-process freshness depends on the store chosen | Unit |
| AC-28 | Handler writes through the owner's `ActorInterface` (MCP precedent); fails if it writes through `AuthenticatedActorView` | Unit/in-process |
| AC-29 | `docs/protocol/actingweb-spec.rst` | Docs build (`sphinx-build -W`); manual review |

Success Measures:
- **Unmodified A2A client:** an in-process test with the `a2a-sdk` client
  needs the SDK as a test dependency, and A2A Inspector is a manual run.
  The Python client defaults to `streaming=True`. Whether it falls back to
  `SendMessage` against a card with `streaming: false` is untested here.
- **Conformance:** needs a TCK executor mode and a card at a host root (or
  a TCK option for a card path, not found).
- **Developer effort:** a line count in `examples/demo/`. The demo turns
  MCP off (`examples/demo/application.py:69-72`) and calls itself a pure
  protocol demo (`examples/demo/README.md:3-15`).

## Documentation Impact

### Option tag and `/meta`

**Protocol spec** (`docs/protocol/actingweb-spec.rst`):
- 770-863: needs an `a2a` entry after `mcp` (828-829).
- 1059-1134: endpoint table. A path-shaped `/<actor_id>/a2a` needs a row
  under the same-name rule (1077-1081). The sentence at 1132-1134 stays.
- 786-792: an A2A chapter must define any card path peers rely on.

**Other pages:**
- `docs/quickstart/configuration.rst:49, 1397-1398`: needs an `a2a` line.
- `docs/protocol/index.rst:36-46`: needs an A2A bullet. It already says
  "every actor exposes" optional paths, which is inaccurate.

### The A2A chapter, guides and configuration

- **Protocol chapter:** a new chapter between 2085 and the `/trust` chapter
  (2086), modelled on 2024-2084. The changelog pattern is at 137-174.
  "References and Endnotes" (4713) is empty and would cite A2A.
  "Security Considerations" (4642) has no MCP item.
- **Guide:** a new page in the `docs/guides/index.rst:31-32` toctree, after
  the MCP pages, plus a bullet at 60-66. `mcp-quickstart.rst` and
  `mcp-applications.rst` stay; they are the model.
- **Configuration:** `docs/quickstart/configuration.rst:1394-1433` needs a
  parallel A2A capability section.
- **Routing:** `docs/reference/routing-overview.rst:237-301` needs A2A
  routes. It already omits `/.well-known/*`, `/mcp/info` and
  `/<id>/permissions/<peer>`.
- **README.rst:** 26-37 lists three client kinds, and A2A would add a
  fourth. Also 85, 113-117, 157-167, 244-265 and 305-310.
- **Custom frameworks and handlers:** `docs/sdk/custom-framework.rst:128-160`
  and `docs/reference/handlers.rst` need A2A entries. Both already omit
  existing modules.
- **Async hooks:** `docs/guides/async-hooks-migration.rst:364-408` needs the
  A2A statement (native async on FastAPI, `asyncio.run` on Flask).
- **Troubleshooting:** `docs/guides/troubleshooting.rst` needs 401/403/404
  entries.

### Trust types, permissions, attributes and the scoped accessor

**Protocol spec:**
- 2978-3005 and 3007-3080, plus the callback body (4228-4262), name six
  categories. These become false if a category or an attribute grant is
  added.
- 3082-3103 stays. The changelog's "step 5" reference (244-247) is already
  inconsistent with the text.

**`docs/guides/access-control.rst`:**
- 26-56: needs a note on which type A2A callers get.
- 57-80: "six categories" becomes false with a new category.
- 255-273: storage. Needs a section on per-type and per-relationship
  configuration.
- 280-291: `established_via` values need `a2a` if one is added.
- 462-526: describes override merging. Check it against
  `merge_permissions` (patterns unioned; `allowed`/`denied` replaced, so
  `denied` can narrow one peer) before A2A docs rely on it.

**SDK pages:**
- `docs/sdk/index.rst:55-60` says attributes are never reachable through a
  trust. This becomes false with `actor.trust.X.attributes`.
- `docs/sdk/authenticated-views.rst:9-125, 287-340` needs a section relating
  any new accessor to `as_peer`/`as_client`.
- `docs/sdk/developer-api.rst:261-275` says per-peer permissions are not on
  `TrustManager` and recommends the views. This becomes false or needs a
  rewrite if `actor.trust.X` is added. The attribute list at 56-67 changes
  too.

### Connection creation

**`docs/guides/oauth2-setup.rst`:**
- 44-101 and 147-214: `create_client` with `mcp_` ids and scope `mcp`;
  `configure_oauth2_trust_types` limits OAuth2 clients only. Needs an A2A
  note on which applies.
- 238-239: says re-authorisation removes the override. This is already
  overstated: it is removed only on a change of type, or when the row is
  created new (`trust_manager.py:492-530, 815-830`). It bears on where
  per-relationship configuration is stored.
- 32-33 is already wrong: the registry uses attribute buckets, not
  properties.

**Other pages:**
- `docs/guides/mcp-applications.rst:1248-1541`: the parallel for owner-made
  connections. Already wrong in three places:
  - 1351-1397 tells readers to add a method that already exists.
  - 1338 uses the private `_load_client`.
  - 1476-1478 mixes two flows.
- `docs/reference/security.rst:98-119`: needs A2A wording.
- `docs/guides/web-ui.rst:302-326`: needs a note if the authorize and
  confirm templates are reused.

### Well-known documents

- `docs/guides/authentication.rst:1603-1635` lists three documents and says
  "All three". It omits `openid-configuration`, which is served. A card at a
  host-root well-known path would need a new subsection there.

### Revocation bounds

- `docs/reference/security.rst:120` ("Revocation is per process") needs an
  A2A clause per credential path. Its MCP figures match the code.
- `docs/guides/access-control.rst:533-539` names the caches without bounds,
  which is vaguer than security.rst.
- `docs/quickstart/deployment.rst:346-355` is about the received-grants
  cache. It stays, and must not be confused with the override cache.

### Hooks

- `docs/guides/hooks.rst:8-15`: the decorator list needs the A2A handler.
  It already omits `app_callback_hook` and `subscription_data_hook`.
- `docs/guides/hooks.rst:236-288`: needs an A2A section parallel to "MCP
  Decorators".
- `docs/guides/hooks.rst:290-371`: the runtime context types need an `a2a`
  context.
- `docs/reference/hooks-reference.rst`: needs a new section, for example
  after Action Hooks (839-897).

### Serverless limits

- `docs/quickstart/deployment.rst:108-178` needs a paragraph on a blocking
  `SendMessage` inside the gateway limit. The "30 s" here and the "29 s" in
  `subscriptions.rst:720-730`, `mcp-applications.rst:718-753` and
  `troubleshooting.rst:363-374` disagree cosmetically.

### Spec version, changelog and migration

- **If the spec goes to 1.6:**
  - spec title (line 2), 1251 and 1287
  - `docs/protocol/index.rst:7`
  - `actingweb/config.py:481` (`aw_version`)
  - a new changelog block above line 37
- **If a minor release:** `docs/migration/vX.Y.rst` plus a row in
  `docs/migration/index.rst:19-30`.
- `CHANGELOG.rst` "Unreleased" is empty today.
- Released migration guides and changelog sections stay.

### Demo

- `examples/demo/README.md:3-15` needs an A2A bullet and a run section.

## Decisions Needed

### Decision 1: How an A2A caller authenticates

**Narrowed by the owner's rule above:** an `/a2a` caller is always a
third party in a trust relationship, never on behalf of the actor. Option
2 as written reuses the MCP client registry, whose clients act for the
actor; it survives only as a separate, peer-typed client-credentials
issuer, which does not exist today. Option 3 narrows the same way. Every
option refuses a trust row whose `established_via` is an OAuth2 source.

**Options:**
1. **Trust-secret bearer on the REST path for everyone.**
   - The owner creates a local trust row with a generated secret and no
     `baseuri`, and hands the secret over. ActingWeb peers use theirs.
   - Pros:
     - one path
     - revocation immediate everywhere (row read per request)
     - AC-15 and AC-19 free
   - Cons:
     - needs a new owner primitive (`Trust.create` is not public, and
       `create_or_update_oauth_trust` returns no secret)
     - a long-lived static secret
     - 403, not 401, on a bad bearer (AC-11 changes, or the recorded
       deferral is reopened)
     - such a row must be classed local-only, or deletion sends a remote
       DELETE (`actor.py:3290-3346`)
2. **OAuth2 client + client credentials for outside callers, trust secret
   for ActingWeb peers.**
   - Pros:
     - `create_client` exists
     - short-lived tokens
     - expressible as `oauth2SecurityScheme.clientCredentials`
     - 401 with a challenge already on the MCP path
   - Cons:
     - two paths in one route
     - 300 s cross-process revocation on the token path
     - `mcp_` ids and scope `mcp`
     - client credentials is undiscovered by design (OCR-7)
3. **Accept both credential kinds in one new authenticator.**
   - Pros: one entry point; both schemes in the card.
   - Cons: new code on a security path; it has to keep both behaviours
     (cache versus per-request read).

### Decision 2: Where the three configuration layers live

**Options:**
1. **Application layer as a new `TrustType` field.**
   - Pros: one place.
   - Cons: `from_dict(**data)` makes an older library return `None` for a
     stored type carrying the new key (rollback hazard, `trust_type_registry.py:65-67, 222-224`).
2. **Application layer in app configuration only**, for example
   `with_a2a(trust_types={...})`, not stored.
   - Pros: no storage change.
   - Cons: not visible to peers.
3. **Owner layers in a new attribute bucket per actor**, keyed by type and
   by peer.
   - Pros: no schema change on either backend; survives re-authorisation.
   - Cons: new cache semantics to state.
4. **Owner per-relationship layer in the override row.**
   - Pros: exists and is cached (TPM-1, TPM-2).
   - Cons: deleted on OAuth2 re-authorisation (`trust_manager.py:815-830`);
     `TrustPermissions` has fixed fields.

### Decision 3: The minimal A2A surface

**Options:**
1. **Card + `SendMessage` (Message reply) only.** Anything else answers
   `-32601` or `UnsupportedOperationError`.
   - Pros: smallest.
   - Cons: falls short of the lowercase-"must" core set; may fail the TCK
     at `--level must`.
2. **Also answer `GetTask`/`CancelTask` with `TaskNotFoundError` and
   `ListTasks` with an empty list, keeping no task store.**
   - Pros: answers every core operation.
   - Cons: **[inference]** that this is compliant.
3. **A task store with `returnImmediately`.**
   - Pros: long model calls survive the gateway limit.
   - Cons: storage and lifecycle on both backends; the start of
     streaming/push scope.

**Binding:** JSON-RPC first matches both official clients' defaults.
HTTP+JSON is optional.

### Decision 4: Where the card lives and how the interface is addressed

**Options:**
1. **Card at `/<actor_id>/a2a` (GET) or `/<actor_id>/.well-known/agent-card.json`,
   interface URL `/<actor_id>/a2a`, no tenant.**
   - Pros:
     - per-actor, as the owner fixed
     - the Python resolver finds the second form from a base URL
       `https://host/<actor_id>`
   - Cons:
     - not RFC 8615
     - the TCK reads only `{host}/.well-known/agent-card.json`
     - invisible to root-path scans
2. **App-level `/a2a` + `tenant=<actor_id>`, plus per-actor cards.**
   - Pros: the specification's named multi-agent mechanism.
   - Cons:
     - the owner fixed `/<actor_id>/a2a`
     - the 1.0.0 proto comment on `tenant` is weaker than the spec page
     - one reported client mishandles tenant paths
3. **Option 1 plus an app-level `/.well-known/agent-card.json`** describing
   the application, or an AI Catalog, for discovery.
   - Pros: TCK and scanners find something.
   - Cons: that card is no actor's.

### Decision 5: Permission model for A2A access and attributes

**Options:**
1. **Reuse existing categories** (properties read, methods, actions) and
   gate "A2A allowed" by trust type configuration in `with_a2a(...)`.
   - Pros: no new category, wire or spec change.
   - Cons: no per-relationship on/off except through those categories.
2. **A new `a2a` category.**
   - Pros: an explicit grant.
   - Cons: touches `TrustPermissions`, the enum, the callback payload,
     `GET …/permissions` and spec 2978-3080.
3. **A per-type ACL row through `add_trust_type(acl_rules=…)`**
   (`permission_integration.py:396-420`): a `(type, path, methods, a|r)`
   row in `config.access` for the A2A path. Emm already uses `acl_rules`
   for its `subscriber` type.
   - Pros: exists.
   - Cons:
     - per type only, no per-relationship switch
     - consulted only on the REST auth path (`Auth.check_authorisation`),
       and by `decide` only when the grant does not mention the category
4. **An attribute grant** (a new category, or a pattern namespace under
   properties).
   - Pros: AC-8 for attributes.
   - Cons: contradicts what `docs/sdk/index.rst:55-60` and
     `property-lists.rst:69-78` promise; a new protocol concept.

### Decision 6: The scoped accessor's name, key and write behaviour

**Options:**
1. **Extend `AuthenticatedActorView`** (`as_peer`) with attributes and query
   helpers; keyed by peer.
   - Pros: exists, enforced, tested; no name collision.
   - Cons: enforces writes against the grant, so AC-28 holds only when the
     handler writes as owner.
2. **New `actor.trust.<X>` accessor.**
   - Pros: the feature's wording.
   - Cons: `actor.trust` is `TrustManager`; a second view type; X must be a
     peer to apply overrides and `approved`.
3. **Pass the handler both:** the view for reads, the owner `ActorInterface`
   for writes (the MCP precedent passes the owner interface).

### Decision 7: Library helpers for Emm-style per-relationship editing

Emm hand-codes these against `TrustPermissions`:
- two default override models
- grant or revoke one name
- grant-all and revoke-all
- a per-name view across relationships
- list-lifecycle upkeep

**Options:**
1. **Add them to the library** as owner primitives on `TrustManager` (or the
   permission store) in this feature.
2. **Leave them to the consumer** and state the pattern in the guide.
3. **A separate plan.**

The spec question (should a peer on another implementation rely on
per-relationship access?) is answered by the permission query and callback
already in 1.5 for "what was granted"; "what a peer may configure" is not
specified anywhere.

### Decision 7b: The synchronised copy as a supported capability

The feature makes "extend the per-relationship mechanism into supported
library functionality, and describe it in the spec" part of the evaluation.

**Facts:**
- The `remote:<peer>` copy is library code.
- The publisher-side filter and the opt-in cleanup are tested library
  behaviour.
- The spec mentions only the OPTIONAL cleanup step (4318).
- The subscriber's stored grant gates nothing.
- Several gaps exist (no provenance, a dead `apply_permission_data`, the
  `sync_peer` docstring).

**Options:**
1. **Out of this feature.** A2A admission uses the serving-side grant only.
2. **Document the copy in the spec as OPTIONAL subscriber behaviour.**
   What a subscriber keeps, when it must delete, how a narrowed grant
   applies.
3. **Make the stored grant enforce re-sharing.** An A2A or MCP caller
   reading replicated peer data is checked against what that peer granted.
   This is what Emm currently approximates by local name.

### Decision 8: Hand-written wire layer versus `a2a-sdk`

**Options:**
1. **Hand-write JSON-RPC (and optionally HTTP+JSON) with plain dicts.**
   - Pros:
     - Flask and FastAPI alike
     - no protobuf or google-api-core
     - consistent with the MCP handler
   - Cons: own validation against `a2a.proto`; drift risk.
2. **`a2a-sdk` as an optional extra for types and tests only.**
   - Pros: an authoritative schema in tests; a client for the
     "unmodified client" measure.
   - Cons: heavy test dependency; protobuf types.
3. **`a2a-sdk` server components.**
   - Cons: Starlette-only dispatchers leave Flask out (feature's own
     reason for not choosing the ideal).

### Decision 9: Release shape

**Facts:**
- The library is at `4.0.0rc3` (`pyproject.toml:3`).
- "Unreleased" is empty.
- Spec 1.5 is amended in place until 4.0.0 is final
  (`plans/2026-11-21-trust-request-answer-secret.md:49-50`).
- `CONTRIBUTING.rst:183-207`: a new route or configuration option is at
  least a minor. A default that changes what an unchanged application does
  on the wire is a major.
- MCP is on by default.

**Options:**
1. **Ship in 4.0.0 before final** (more release candidates; spec 1.5
   amended in place).
   - Pros: no extra minor; the spec chapter lands with the version already
     being rewritten.
   - Cons: widens a release under validation with consumers.
2. **4.1.0 after 4.0.0, A2A off by default, spec 1.6** (by history, each
   new optional feature bumped the spec minor).
   - Needs `docs/migration/v4.1.rst` and an index row.
   - Off by default keeps it a minor.
   - On by default (like MCP) would put a new route and tag on the wire for
     unchanged applications, which the rule counts as major.
3. **4.1.0 with the spec chapter as an amendment** to 1.5 without a bump.
   - Cons: contradicts the per-feature history and the
     `/meta/actingweb/version` meaning.

## Code References

**Admission and credentials**
- `actingweb/interface/oauth_client_manager.py:40-105, 377-435` - owner-created OAuth2 client, owner-minted token
- `actingweb/oauth2_server/client_registry.py:66-204, 691-753` - client and trust-row creation
- `actingweb/interface/trust_manager.py:146-159, 555, 756-850, 815-830` - OAuth trust rows; override deleted on (re)write
- `actingweb/oauth2_server/oauth2_server.py:783-851, 1163-1334` - client-credentials grant; authorization completion
- `actingweb/auth.py:165-178, 264-333, 750-763, 846-855` - REST bearer path; 401 and 403 answers
- `actingweb/handlers/mcp.py:129-143, 410-450, 902-912, 1323-1535, 2386-2565, 2991-3111` - MCP caches, eviction, disabled 404, list filtering, authentication, failure mapping

**Permissions and the accessor**
- `actingweb/trust_type_registry.py:30-78, 181-262, 303` - trust types and registry cache
- `actingweb/trust_permissions.py:36, 64-111, 952-1031` - override row, cache TTL, merge
- `actingweb/permission_evaluator.py:153-175, 190-303, 875-885, 981-1047, 1091-1207` - categories, tree rules, per-call trust read, effective permissions
- `actingweb/access_decision.py:147-342` - shared decision layer
- `actingweb/permission_integration.py:290-300, 317-457` - trust-type registration; inert hook scaffolding
- `actingweb/interface/authenticated_views.py:146-1009` - existing scoped views
- `actingweb/interface/hooks.py:380-449, 686-734, 978-1168` - hook permission check, sync/async execution

**Configuration, routing and logging**
- `actingweb/config.py:479-481, 583-627` - spec version announced; option tags
- `actingweb/interface/app.py:177-182, 272-299, 677-751, 1005-1060, 1511-1619` - MCP default and options, peer permissions, delivery settings
- `actingweb/interface/integrations/flask_integration.py:155-213, 371-418, 1712-1783` - request context, MCP and well-known routes
- `actingweb/interface/integrations/fastapi_integration.py:540-705, 996-1046, 2541-2631` - middleware, executor, MCP and well-known routes
- `actingweb/request_context.py:16-261`, `actingweb/log_filter.py:50-137` - correlation id
- `actingweb/callback_sender.py:110-167` - delivery budget

**Synchronised copy, protocol and tests**
- `actingweb/remote_storage.py:95-175, 439-682, 1054-1131` - subscriber's copy of peer data
- `actingweb/replica_revocation.py:59-296` - opt-in cleanup on narrowed grants
- `actingweb/peer_permissions.py:27-50, 109-194, 239-497, 772-815` - received-grant store
- `actingweb/actor.py:2315-2514, 3004-3187, 3290-3346, 4251-4519` - trust creation assumptions; subscription filter
- `docs/protocol/actingweb-spec.rst:770-863, 1059-1134, 2024-2084, 2865-3103, 4179-4338` - tags, endpoints, MCP chapter, permissions, permission callback
- `tests/integration/test_property_item_paths.py:62-136` - two-framework in-process harness
- `tests/test_mcp_tool_failure_results.py:109-199` - sync/async handler test pattern

**Consumer (Emm AI, `../actingweb_mcp`)**
- `application.py:723-903` - trust types
- `api/trust.py:276-563` - per-relationship editing
- `api/memory_types.py:333-513` - per-type editing
- `hooks/mcp/tools/shared.py:294-390` - enforcement through library checks
- `api/oauth_clients.py:26-80` - connection creation

**Recorded decisions this research ran into**
- `thoughts/plans/2026-11-06-peer-authorisation-fixes.md:444` - 401 for an unmatched bearer deferred as a library-wide change
- `thoughts/specs/trust-permissions.md` TPM-D1 - base permissions cached without expiry, nothing invalidated across processes
- `thoughts/specs/oauth-client-registration.md` OCR-7 - client credentials not offered in discovery
- `thoughts/specs/mcp-server.md` MCP-10 - a reconnect starts from a fresh grant
- `actingweb/interface/trust_manager.py:492-530` - an override of another type is removed on re-typing (owner decision 2026-11-11)
- `thoughts/plans/2025-12-12-unified-handler-architecture.md`, `2025-12-13-unified-handler-gaps.md`, `thoughts/reference/handler-refactoring-pattern.md` - where the authenticated views were designed. `research/2026-11-10-grant-enforcement-per-route.md` (A5 table) and `plans/2026-11-06-peer-authorisation-fixes.md` fixed their keys and subscription binding. No document records a decision to keep handlers on `decide` rather than the views; `allow_user_override` appears in no plan, spec or changelog

## External References

**Specification**
- <https://a2a-protocol.org/latest/specification/> - A2A 1.0.0 specification
- <https://raw.githubusercontent.com/a2aproject/A2A/v1.0.0/specification/a2a.proto> - proto at the 1.0.0 tag
- <https://raw.githubusercontent.com/a2aproject/A2A/main/specification/a2a.proto> - proto on main (tenant wording)
- <https://raw.githubusercontent.com/a2aproject/A2A/main/docs/whats-new-v1.md> - 0.3 → 1.0 changes

**Topic pages**
- <https://a2a-protocol.org/latest/topics/extensions/> - extension specification contents, activation
- <https://a2a-protocol.org/latest/topics/agent-discovery/> - discovery, no registry API
- <https://a2a-protocol.org/latest/topics/multi-tenancy/> - sub-path, credential and tenant routing
- <https://a2a-protocol.org/latest/topics/life-of-a-task/> - Message-only agents
- <https://a2a-protocol.org/latest/topics/streaming-and-async/> - streaming and push requirements

**Discussions**
- <https://github.com/a2aproject/A2A/discussions/166> - per-agent cards on one host
- <https://github.com/a2aproject/A2A/issues/641> - host catalog proposal, closed for AI Catalog
- <https://github.com/quarkiverse/quarkus-langchain4j/issues/3005> - a client mishandling tenant card paths

**SDKs**
- <https://pypi.org/project/a2a-sdk/> - 1.3.1
- <https://raw.githubusercontent.com/a2aproject/a2a-python/main/pyproject.toml> - dependencies
- <https://raw.githubusercontent.com/a2aproject/a2a-python/main/src/a2a/client/card_resolver.py> - resolver path building
- <https://raw.githubusercontent.com/a2aproject/a2a-js/main/src/client/factory.ts> - JS client defaults

**Conformance and test clients**
- <https://github.com/a2aproject/a2a-tck> - conformance kit
- <https://github.com/a2aproject/a2a-itk> - interop kit and ACTS
- <https://github.com/a2aproject/a2a-inspector> - Inspector, bearer support

**Extensions**
- <https://github.com/a2aproject/experimental-ext-cratb-auth> - closest extension (identity proof, not permissions)

**Adoption**
- <https://apievangelist.com/2026/09/21/a2a-adoption-is-421-of-27840-and-most-of-them-arrived-with-the-card/> - root-path card scan
