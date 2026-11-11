# Research: grant enforcement per route, re-verified at HEAD

**Security, unpublished.** Keep local until fixed, under the same rule as the
peer-authorisation records: never push this file before its fix.

**Date:** 2026-11-10
**Branch:** fix/3.16.0-peer-authorisation (local only), HEAD `6377a60`
**Input:** `thoughts/todo/grant-enforcement-per-route.md`, out of
`thoughts/verifications/2026-11-09-peer-authorisation-fixes-audit.md`
(written at `18a9bb5`)

The audit's items A5 to A8, A10 to A20 were re-read against HEAD by five
read-only passes (static; nothing was run), and the lines the fix shapes rest
on were re-read by hand. All line numbers are HEAD's. "On `master`" was
checked with `git show master:<file>`.

## What the re-read changed

- **A10 is worse than filed.** The trust type a client gets on a *user's*
  actor does not come from its registration at all: it is an unvalidated form
  field on `POST /oauth/authorize`, which the client can submit itself. The
  app's allow-list (`configure_oauth2_trust_types`) is read only by the form
  renderer.
- **A7 is wider than filed.** `POST /properties` has no handler-level grant
  check at all; its only gate is the hook check, which runs only when hooks
  exist, allows on NOT_FOUND and on an error, and for list operations
  evaluates a doubled path (`key/key`) that an exact exclusion never matches.
- **A6 cannot copy its siblings.** The methods/actions pattern would widen
  access (associate and viewer gain `public/*`) as well as narrow it, and the
  spec and guide define the `resources` grant as MCP's.
- **A18 is narrower than filed.** The evaluator already turns its own errors
  into DENIED; the fail-open branches fire only when the evaluator cannot be
  built. No recorded decision keeps them.
- **A8's cleanup is off by default** (`config.py:162`), and Emm does not turn
  it on.
- **A15 is half closed** (a missing row answers 404). **A4 is closed.**
  Everything else is open; all of it is on `master` except A19's pull half.

## A5: patterns have no hierarchy

Open (a, b); partly closed (c). On `master`.

- **Matcher.** `permission_evaluator.py:102` anchors the whole string; `*`
  crosses `/`. So `private/*` matches `private/a/b` and not `private`; an
  exact `L` does not match `L/x`. `_evaluate_rules` (`:721-837`) knows nothing
  of paths.
- **(a) Parent.** Friend's rule (`trust_type_registry.py:352-354`) is
  `patterns ["*"]`, read/write, excluded `private/*`, `security/*`,
  `_internal/*`; `mcp_client` (`:424-430`) and `partner` likewise. `GET` and
  `PUT /properties/private` pass the bare name (`handlers/properties.py:309-310`,
  `:923-926`) and serve or overwrite the whole object; the listing (`:573-575`)
  includes it. Mirror: `viewer` and `associate` allow `public/*`, so bare
  `public` is denied today.
- **(b) List tail.** `GET /properties/L/x` evaluates `L/x` (`:306-310`), then
  looks up `path[0]` only (`:330-339`) and returns `to_list()` (`:413`,
  `:451`). `PUT /properties/L/x?index=N` (`:780-782`) writes item N the same
  way. `/items` and `/metadata` pass the bare name and are safe (`:1958`,
  `:2002`, `:2164`, `:2217`). The spec wants `GET .../notes/0` to return that
  item (`actingweb-spec.rst:1004-1013`); HEAD serves items by `?index=` only.
- **(c) Push and pull** share `Actor.filter_subscription_blob`
  (`actor.py:3874-3965`) since iteration 50. Still open:
  - whole-target subscription, write to the parent `private`: top-level key
    only is evaluated (`:4005-4014`), whole object sent;
  - whole-target subscription, write to `settings/private` under an exclusion
    of that path: reshaped to `{"settings": {"private": v}}` (`:5106-5107`),
    only `settings` evaluated, so the child leaks where its direct GET is 403;
  - subtarget `P` with an object value: `P/<key>` is checked one level deep
    only (`:3934-3963`);
  - subtarget `L` (an exact-excluded list) with resource `item`, `items`,
    `value`, `old_item`, `index` or `action`: `L/item` is evaluated, the item
    is sent (`register_diffs` extracts `jsonblob[resource]`, `:5082`).
  - Subscription creation checks no grant (`handlers/subscription.py:323-325`).
- **Call sites of the property evaluation** (the place a single path rule has
  to cover):

| Site | Path handed over | NOT_FOUND | Error |
| --- | --- | --- | --- |
| `properties.py:310` GET, `:781`/`:924` PUT, `:1744` DELETE | full `a/b/c` | access table (`:199-207`) | deny |
| `properties.py:1073` POST | none: access table only | | |
| `:573`, `:629` listing (bulk) | top-level names | included | empty |
| `:1958`/`:2002` metadata, `:2164`/`:2217` items | bare list name | access table | deny |
| `interface/hooks.py:416` hook check (`:617`, async `:1056`) | `name` + caller's `path`: doubled or wrong for most callers (below) | allow | allow |
| `actor.py:3944` subtarget filter | `P`, `P/R`, `P/<key>` | deny | deny |
| `actor.py:4013` whole-target filter | top-level keys | deny | deny |
| `handlers/trust.py:1613` `shared_properties` | top-level names, operation `subscribe` | excluded | raises |
| `interface/authenticated_views.py:132`, `:474`, `:556` | developer's key | allow | deny |
| `authenticated_views.py:687` subscribe check | `properties/<subtarget>` (wrong) | allow | deny |

- **Hook-check paths per caller** (`properties.py`): list index GET `:368`
  `L/<i>`; nested GET `:479-496` drops a segment (`a/b/c` → `a/c`); PUT with
  index `:840` `L/L/<i>`; form POST `:1110`, `:1137` and list creation `:1220`
  `name/name`; bulk list update `:273` `key/key`; DELETE `:1792`, `:1828`,
  `:1862` `name/name[/…]`. A denied `get` or `delete` returns the value
  unchanged (`hooks.py:622`). De-doubling alone turns the accidental denial
  of a form POST creating `private` into an allow, so it must land with the
  path rule.
- **Documented semantics.** `docs/guides/access-control.rst:353-355`:
  "`public/*` - Matches all paths under `public/`"; `:322` "A pattern must
  match the whole identifier"; `:329-331` one matcher for evaluator, peer
  cache and callback filters; `:437` `excluded_patterns: ["memory_personal"]`
  as the way to exclude a list. Spec `:2296-2298`: glob matching, "explicit
  deny > explicit allow > trust type defaults", "Default to deny if no
  matching rule is found" (SHOULD). Nothing on hierarchy.
- **Tests that constrain a fix.** `tests/test_peer_paths_binding.py:967` (a
  grant of exactly `settings` reads the whole object), `:945`, `:1011`
  (exclusion `settings/private`: parent readable, key dropped), `:994`,
  `:1039`, `:1059`; `tests/test_transparent_hook_permissions.py:253-353`. No
  test asserts that bare `private` is readable or that `<list>/<x>` returns
  the list.
- **Fix shapes.** (1) An exclusion of a path covers its descendants. (2) An
  exclusion `X/*` also names `X`. (3) A read of a parent, the listing and
  whole-target diffs are filtered to what the grant allows, at any depth, and
  a write or delete of a parent with an excluded descendant is refused. (4)
  The list branch checks the bare list name and serves a numeric tail as the
  item. 1 + 2 + 4 are small; only 3 makes an exact child exclusion hold on a
  parent read. The subscriber-side mirror is `peer_permissions.has_property_access`
  (`:109-140`).

## A6: `/resources/<name>` never evaluates the grant

Open, on `master`; no test exercises the route.

- All four verbs: `authorize(<verb>, "resources", name)` and nothing else
  (`handlers/resources.py:9-16`, `:36-43`, `:66-73`, `:112-119`). The access
  table admits creator, friend, partner, admin (`config.py:303-307`).
- The hook gets no caller: `execute_callback_hooks(name, actor, data)`
  (`interface/hooks.py:661-663`).
- `evaluate_resource_access` exists (`permission_evaluator.py:436-457`), no
  REST caller. MCP enforces the same grant key more strictly
  (`handlers/mcp.py:1907-1919`: anything but ALLOWED denies).
- Built-in `resources` rules: viewer/associate `public/*` read; friend `*`
  read/write minus `private/*`, `security/*`; partner `*` read/write minus
  `security/*`; admin everything; `mcp_client` MCP URIs, read.
- Evaluating as methods/actions do (ALLOWED bypasses the table) **widens**
  for associate and viewer and **narrows** for friend and partner (DELETE,
  the exclusions) and for any per-trust override written for MCP URIs.
- Spec `:2209-2211` and `access-control.rst:74-75` call `resources` the MCP
  grant; spec `:1370` wants MCP enforced "identically to REST access
  control".

## A7: `POST /properties` mutates before any grant check

Open, on `master`.

- `:1068-1074` authenticates and calls `authorize("POST", "properties", name)`;
  no `_check_property_permission`. A non-empty name sets 400 and does not
  return (`:1075-1077`).
- Mutation before the hook check: form list metadata (`:1101`/`:1103`, check
  `:1110`); JSON list creation and metadata (`:1207-1213`, check `:1220`);
  bulk items v2 (`:1435`, `:1446`, `:1470`) and v1 (`:1623-1647`), check in
  `_finish_bulk_list_update` (`:243-285`, no rollback). Scalars check first.
- A denied key is skipped and the rest answer 201; spec `:936-949` wants "no
  values changed" on an error and 403 for an insufficient relationship.
- `evaluate_bulk_property_access` (`permission_evaluator.py:265`) evaluates
  many names on one grant read.
- Pins: `tests/integration/test_property_path_control_chars.py:71-96`,
  `tests/test_transparent_hook_permissions.py:198-256`,
  `tests/test_db_fault_permissions.py:88-104`.

## A8: revocation deletes too little

Open, on `master`. Subscriber side.

- **Compared:** `properties.patterns` only, as a set difference of strings
  (`peer_permissions.py:808-813`). Not `excluded_patterns`, not `operations`.
  Side effects: `memory_*` → `memory_travel` deletes `memory_travel` too;
  `a*` → `*` reads as a revocation. A first copy deletes nothing (`:799-803`).
- **Deleted:** lists only (`handlers/callbacks.py:1469-1501`), behind
  `auto_delete_on_revocation` (default False, checked `:453-455`).
- **Replica layout:** bucket `remote:{peer_id}` in `attributes`; a scalar is
  `<key>`, a list is `list:<name>:meta` plus `list:<name>:<i>`. Enumeration
  exists (`remote_storage.py:190`, `:196-211`; the scalar one is not strict).
- **Writers of the stored copy that never delete:**
  `interface/subscription_manager.py:2528`, `:2613`, `:2925`;
  `remote_storage.py:677`; `maintenance/peer_state.py:380`. Only the callback
  (`callbacks.py:445-473`) and its reconcile (`:1213-1219`) do.
- **Computing from the new grant** is sound (the copy is the effective grant:
  `trust_permissions.py:513-533`, spec `:3106-3108`) with three cautions:
  `has_property_access` answers `None`, not False, on a missing `read`, and
  ignores the `allowed`/`denied` rule shape; the copy can be narrower than
  the real grant (`trust_permissions.py:503-505`, an older peer, `properties:
  None`); replica names are property names only for whole-target `properties`
  subscriptions (`callbacks.py:942-952`).
- Spec `:3128-3134`: cleanup is OPTIONAL; nothing on a copy got by query.
- Emm reads `granted_patterns` and `revoked_patterns` from
  `permission_changes`
  (`../actingweb_mcp/hooks/actingweb/callback_hooks.py:218-235`).
- Adjacent: `TrustPermissionStore.delete_permissions`
  (`trust_permissions.py:609-640`) sends no callback when an override is
  dropped.

## A10: a client chooses its trust type

Open, on `master`.

1. `POST /oauth/register` is anonymous (`handlers/oauth2_endpoints.py:102`,
   `:163-212`) and stores `trust_type` as given
   (`oauth2_server/client_registry.py:114`), on the OAuth2 system actor, with
   an approved, verified trust row of that relationship (`:681-693`,
   `interface/trust_manager.py:655-672`).
2. `client_credentials` (`oauth2_server/oauth2_server.py:640-679`) mints a
   one-hour token on the system actor for that client. The stored
   `grant_types` (`client_registry.py:110`: `authorization_code`,
   `refresh_token`) are never checked. The token reaches `/mcp` only; reach is
   whatever the application's tools do with the system actor.
3. **Authorization-code path.** `oauth2_endpoints.py:268` reads `trust_type`
   from the form; `oauth2_server.py:215` passes it into the state unchecked;
   the callback (`:403-420`) creates the trust on the user's actor with it.
   Nothing ties the POST to a rendered form. A client posts the form itself
   with `trust_type=admin`, sends the user to the provider URL it gets back,
   and holds an `admin` row on that user's actor: every tool and resource,
   properties `*` with write and delete.
4. `configure_oauth2_trust_types` (`permission_integration.py:460`) is read
   only by the form renderer (`oauth2_endpoints.py:580`). The form's
   `allowed_trust_types` (`:662`) and scope filters are dead.
5. Consumers: Emm allows `mcp_client_readonly` and `mcp_client_readwrite`
   (`../actingweb_mcp/application.py:873-878`) and clamps on its own password
   route only; its tests create clients through the authenticated
   `OAuth2ClientManager.create_client` path and then use `client_credentials`.
   The demo configures no allow-list.
6. Tests: `tests/integration/utils/oauth2_helper.py:59-66` registers
   anonymously with `trust_type` and uses `client_credentials`;
   `tests/integration/test_oauth2_client_manager.py:150-176` creates
   `viewer` and `friend` clients as the owner.

## A11: `FanOutManager` sends one unfiltered payload

Open, on `master`. `fanout.py:546`. Not called by the library, the demo or
either consumer. `thoughts/plans/2026-11-06-spec-1-5.md:527-548` removes it
(owner, 2026-11-09). `Actor.filter_subscription_blob` could filter per
subscriber (about 20 lines, thrown away by the removal).

## Lows

- **A12, owner base-URI change unchecked.** Open by design: spec `:1797-1801`
  grants it, and it is the documented recovery for a moved peer
  (`actor.py:2609-2610`). A peer's own move is checked
  (`handlers/trust.py:994-1015`).
- **A13, unconditional delete.** Open on both backends
  (`db/dynamodb/trust.py:485-497`, `db/postgresql/trust.py:672-677`). The
  branch added `modify(only_if_secret=)`, `create(only_if_absent=)` and
  `create(only_if_pending=)`, no conditional delete. The cascade runs before
  the row delete, so the secret has to be checked before the cascade too.
  `thoughts/reference/trust-row-deletion-invariants.md` changes with it.
- **A14, hooks differ by route.** Open. REST and web UI approval fire
  `trust_fully_approved_local` (`handlers/trust.py:1047-1053`, also on a
  repeat PUT); `TrustManager.approve_relationship` fires `trust_approved`
  (`trust_manager.py:313-318`); `modify_and_notify` fires nothing.
  `trust_deleted` carries `trust_data=<row>, initiated_by_peer` from REST and
  `sync_peer`, `trust_data={}` from `delete_relationship`. The reference
  documents four parameters (`docs/reference/hooks-reference.rst:410`), so a
  hook written to it raises `TypeError`, swallowed, on every REST delete.
  `trust_approved` has no reference section.
- **A15, PUT ordering.** The approval and its notification precede the
  permission write (`handlers/trust.py:1025`, `:1062-1105`); the override is
  stored even when the modify failed. The missing-row half is closed
  (`:963-971`).
- **A16, async create.** Open: `actor.py:2466-2475` catches two httpx
  exceptions where the sync twin catches all (`:2273`); the leftover row then
  sends a bearer the peer answers 403.
- **A17, `shared_properties`.** Open (`handlers/trust.py:1529-1653`):
  operation `subscribe` is in no built-in type, so every name lands in
  `excluded_properties`; no approval check, so a pending row enumerates all
  names. The route is in neither spec nor docs.
- **A18, fail-open.** `methods.py:71-78`, `actions.py:71-78` fall back to the
  table when the evaluator cannot be built; the listings return everything
  (`:156-157`); the hook check allows (`hooks.py:444-446`). Properties
  (`properties.py:209-221`) and MCP deny. The 3.13 fail-open was MCP-only and
  was reversed in 3.14.4 and Unreleased (`CHANGELOG.rst:3281-3285`,
  `:1293-1300`); for methods, actions and hooks it was deferred, never
  decided.
- **A19, NOT_FOUND.** Push and pull accept ALLOWED only (`actor.py:3955`,
  `:4019`); direct reads fall back to the access table. No built-in type
  produces NOT_FOUND for a named property; a relationship name outside the
  registry, or a type with no `properties` rule, does. The original design
  promised the fallback (`CHANGELOG.rst:6311`, `access-control.rst:565-581`);
  `access-control.rst:385-389` and spec `:2298` say default deny.
  `authenticated_views.py:686` evaluates `properties/<subtarget>`.
- **A20, unapproved listing.** Open, narrowed to the caller's own id
  (`handlers/subscription.py:219-227`, `approved=False`). Spec `:1610-1614`:
  an unapproved requester SHOULD get nothing beyond its relationship's URL.
- **Audit notes.** The existence oracle on DELETE exists so a peer's cleanup
  converges (`actor.py:3054-3056`): accept. `modify_trust_and_notify` takes
  the notification URL from the row read before its write (`actor.py:2017`).
  A bearer on an unknown id answers 403 (`handlers/trust.py:475-486`, pinned
  by `tests/test_trust_re_pair.py:522`); intended, not in the changelog.

## Calibration against the protocol's intent

Owner's instruction (2026-11-10): judge each item against what the
specification and the model intend, not against the code's own habits. Read
for this: `docs/protocol/actingweb-spec.rst` (abstract, the actor, every
endpoint, `/trust`, the permission sections, `/subscriptions`, security
considerations) and the "more in depth" page on stuff.greger.io.

**What the model says.**

- An actor holds a small piece of one person's data; it is shared "in a very
  granular and controlled way", "on your choosing", and access is revocable
  per service without touching anything else (spec `:98-108`).
- Access follows the relationship. The mini-application "specifies which
  access rights are given to which data, resources, and services for each
  trust level" (`:201-205`); the types are filled "with own meaning"
  (`:1918-1924`), and rights per relationship instance are a MAY for
  "granular access control" (`:2037-2043`). So the rules are the
  application's; what the protocol requires is that whatever rule the actor
  holds is the answer on every way in.
- A relationship is requested by one side and approved by the other,
  "interactively by a user or programatically" (`:151-156`); the requester
  names the type, the owner approves it. Until approval: nothing beyond the
  relationship's own URL (`:1610-1614`).
- `/properties` is a tree: "the URI specifies the property or the part of
  the property tree to operate on" (`:634`); nested paths are a MAY
  (`:834-837`).
- `/resources`, `/actions`, `/methods` are the actor's own endpoints and
  subscription targets (`:2412-2427`); MCP is a bridge onto them (actions →
  tools, resources → resources, methods → prompts, `:1358-1362`) that MUST
  enforce "the actor's trust and permission model ... identically to REST
  access control" (`:1370`).

**What that changes in the reading of each item.**

- **A5.** A rule on a node of a tree that does not hold for the node's
  parent or children is not "granular and controlled". An exclusion is the
  owner's explicit deny (`:2297`, "explicit deny > explicit allow"), so it
  has to hold on every path that reaches the data: the parent's read, the
  listing, a diff. The list tail is a plain conformance gap: `GET
  /properties/notes/0` "MUST return that item only" with "Authorization
  requirements ... the same as for regular properties" (`:1004-1013`), and
  `PUT`/`DELETE` by index path likewise (`:1040-1070`). HEAD serves items by
  `?index=` and returns the whole list for a tail. `:802`: "All attributes
  under /properties MUST be writable by the admin role", so no hierarchy
  rule may refuse `admin`.
- **A6.** The `resources` grant is not MCP's alone: MCP resources *are* the
  bridge onto `/resources`, and `:1370` requires the two to agree. The
  "(for MCP clients)" wording at `:2209` describes the URI patterns, not a
  second model. So the grant governs REST `/resources`, and where a rule
  exists it is the answer in both directions (associate "will normally give
  read access", `:1939`).
- **A7.** Not a design choice: "An error on one or more values MUST result
  in no values changed" and "If the request's current trust relationship is
  not sufficient, a 403 Forbidden MUST be returned" (`:936-949`).
- **No rule (A19, A18).** The access table *is* the application's
  per-trust-level rule (`:201-205`), i.e. the "trust type defaults" of
  `:2297`; falling back to it is the model working, and it denies by default
  itself. What the model does not allow is two routes giving two answers.
  One decision for every route; "cannot evaluate" is not "allowed".
- **New: subscription creation.** "The requesting actor MUST have a
  relationship allowing minimum read permissions on the requested path, and
  the actor receiving the request MUST validate the access rights upon
  receiving the request" (`:2438-2442`). `handlers/subscription.py:322-325`
  validates nothing ("Property-level filtering happens at callback time");
  on `master` too. A peer can subscribe to a path it may not read; it
  receives nothing, but the MUST is unmet and `shared_properties` (A17)
  exists to paper over it.
- **A8.** The promise is the granting actor's: revoke, and access ends
  there. That already holds. Cleanup at the receiver is OPTIONAL
  (`:3128-3134`) and cannot be relied on by the grantor. So A8 is "the
  opt-in cleanup should do what its name says", not a hole in the model.
  The spec-relevant half is the adjacent one: a permission callback SHOULD
  be sent when "an actor explicitly revokes specific permissions"
  (`:3120-3124`), and deleting an override sends none.
- **A10.** The requester may *ask* for a type; the owner *approves* it. On
  the OAuth2 path the access-level form is that approval, and nothing binds
  it to the user: the client fills it in. An allow-list bounds the damage;
  it does not make the choice the user's. The intent is met only when the
  user, after signing in, sees which client gets which level. The
  anonymous registration's `client_credentials` session on the system actor
  is a relationship nobody approved, on an actor that represents no one.
  And `admin` "has full access ... similar to the creator" and "can also
  delete an actor" (`:2011-2017`): never a type a requester gets by asking.
- **A12.** "The actor owning the trust relationship can update the
  relationship ... baseuri, desc, and approved" (`:1797-1801`): the owner's
  right. Not a finding.
- **A13.** "A relationship can be revoked unilaterally at any time by either"
  side (`:1455-1457`): a delete has to keep working for both; it only must
  not remove a row other than the one the caller held.
- **A20.** `:1610-1614`: an unapproved requester lists nothing.
- **A11, A14 to A16, A18.** Library matters; the protocol is silent.

## Overlap with queued work

- `plans/2026-11-06-attribute-list-v2-port.md` Phase 4 moves the same filter
  (`_filter_subscription_data_by_permissions`) ahead of the diff store and
  rewrites the replica code; it must rebase on whatever this plan does to
  `filter_subscription_blob` and `RemotePeerStore`.
- `plans/2026-11-06-spec-1-5.md` Phase 4 removes `FanOutManager` (A11).
- `todo/dcr-registrations-and-client-trust-rows-never-expire.md` and
  `todo/mcp-cache-lifecycle-and-revocation.md` are about retention and cache
  staleness, not about which trust type a client gets.

## Release shape

A minor. 3.16.0 is unreleased and already a minor with a migration guide;
several fixes here change what a peer is answered (a parent of an excluded
path, a mixed bulk POST, a client's trust type), and A14 changes hook
arguments. The entries go under `Unreleased` (`SECURITY`, `CHANGED`), with
`docs/migration/v3.16.rst` sentences for each behaviour change.

## Decisions the owner has to make

1. Branch and PR: this branch, or one stacked on it.
2. A5: which of shapes 1 to 4.
3. NOT_FOUND on every route (A19, A18, A6, A7): one fallback to the access
   table everywhere, or deny everywhere as the spec and guide say.
4. A10: what the allow-list is when the application configured none; whether
   anonymous registration may name a type; whether an anonymously registered
   client keeps `client_credentials`.
5. A6: whether the `resources` grant governs REST names, and whether it may
   widen.
6. A7: all-or-nothing 403 on a mixed batch.
7. A8: diff widened, or computed from the stored grant; the flag's default.
8. A11: leave to `spec-1-5`, filter now, or remove now.
9. Lows: which are fixed, which accepted and documented; A14's canonical
   hook name.
10. Subscription creation (new): 403 for a path the peer may not read.

After the calibration, 3, 5 and 6 are answered by the specification (one
answer per route with the access table as the trust-level default; the
`resources` grant governs REST; all-or-nothing 403), and 2 leans to the full
hierarchy on the deny side. What stays the owner's: 1, 4 (how the user's
consent is bound), 7 to 9.
