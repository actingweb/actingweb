# Audit: the peer-authorisation branch, by trust boundary

**Date:** 2026-11-09
**Plan:** thoughts/plans/2026-11-06-peer-authorisation-fixes.md
**Research:** thoughts/research/2026-11-06-peer-authorisation-fixes.md
**Branch:** fix/3.16.0-peer-authorisation (local only; not pushed)
**Commit:** 18a9bb5
**Follows:** thoughts/verifications/2026-11-09-peer-authorisation-fixes-reverify-6.md

The owner asked for an audit before the next iteration (2026-11-09; owner
choice: a trust-boundary audit). Delta reviews kept finding new holes next
to closed ones, so this run reads the whole library at HEAD against ten
invariants, not a diff. Each finding says whether it is pre-existing on
`master` (checked with `git show master:<file>`) or introduced by the branch.

This is not a `/verify_implementation` run: no Full tier was run (the code
is that of reverify-6, where it is green). The plan's `verified:` link stays
on reverify-6.

## How it was run

- **Invariants** (shared by all reviewers; kept with the session's scratch
  files): I1 identity (no row whose secret an unproven requester chose
  becomes usable), I2 path binding, I3 the owner's part, I4 read grant on
  every route and level, I5 unauthenticated writes, I6 races, I7 secret
  egress, I8 revocation, I9 no silent regression, I10 consistency across
  twins, routes and backends.
- **Reviewers** (parallel, read-only, each with an exhaustive route table):
  - trust-row lifecycle (every route that creates, approves, re-pairs,
    replaces, modifies or deletes a row);
  - data served to peers and peer data stored (every route that returns
    actor data or stores a peer's), with two executed reproductions;
  - the outside voice: codex `exec -s read-only` (outside the sandbox) and a
    fresh-context Claude reviewer, per invariant and per attacker (no
    credentials; an associate's secret; an unverified pending row; an admin
    peer; an OAuth2/MCP token).
- **Checking:** I checked A1 to A3 against the code myself, as well as the
  routes behind A6 and A9. The rest are as the reviewers verified them, with
  quoted lines.

## Findings

Reverify-6's Issues 1 to 11 stand; A3 widens Issue 1. The owner-accepted
items are not repeated.

### High

**A1. An unapproved trust row passes the permission evaluator.**
Pre-existing (I1, I4, I10).
- **The gap.** An unauthenticated `POST /<actor>/trust/<rel>` stores an
  unapproved row with any relationship, including `admin`, whether or not it
  verifies (`handlers/trust.py:470-499`, `actor.py:2377-2391`). Its secret
  authenticates as that peer whatever `approved` is (`auth.py:283-294`).
- **The only approval gate is skipped.** It is in `_match_access_row`
  (`auth.py:809-818`). Properties, metadata, list items, methods and actions
  decide through the evaluator alone (`handlers/properties.py:298-310`,
  `:186-198`; `handlers/methods.py:51-62`; `handlers/actions.py:51-62`), and
  `permission_evaluator.py` never reads `approved`.
- **Effect.** A stranger reads and writes properties and calls methods and
  actions with no owner action. As `admin` it clears all properties
  (`DELETE /properties`). The `shared_properties` route
  (`handlers/trust.py:1459-1559`) and `authenticated_views` are the same.
- **Proof.** Reproduced with the real evaluator: the access-table check
  answers False, the evaluator True.
- **Closes the wider hole.** Reverify-6 Issue 1 (an owner's click) is a
  narrower case of this: a fix for Issue 1 alone does not close A1.

**A2. A re-pair in flight lands its secret on the row that replaced the one
it authenticated against.** Introduced by the branch (I1, I6).
- **Unapproved rows count as proven.** `handlers/trust.py:447-455` treats an
  authenticated bearer as `proven` whatever the row's `approved` or
  `verified` (`auth.py:283-286` sets `authenticated` for an unapproved row).
- **The swap is not conditioned on the secret.** `replace_trust_secret`
  (`actor.py:2438-2455`) swaps the secret with a `modify` conditioned only
  on the row existing (`db/dynamodb/trust.py:329`; PostgreSQL `WHERE id,
  peerid`).
- **Effect.** The holder of an unverified pending row under Q's id loops
  re-pairs. A replacement (the owner's create, or Q's verifying request with
  auto-accept) that lands between authentication and the write receives the
  attacker's secret: approved and verified, as Q. `_drop_failed_attempt`
  then keeps it, since the secret differs.

**A3. Every approval route approves an unverified row.** This widens
reverify-6 Issue 1; pre-existing (I1, I10).
- **The approval routes.** Besides the web UI's Approve, `PUT
  /trust/<rel>/<peer>`, `TrustManager.approve_relationship`: the `admin`
  peer's and the trustee's PUT (`handlers/trust.py:98`);
  `approve_relationship_async`; `modify_trust_and_notify(_async)`;
  `TrustManager.modify_and_notify`; `get_peer_trustee` (`actor.py:1457-1477`).
- **No gate at all.** `TrustManager.modify_trust(**kwargs)`
  (`interface/trust_manager.py:859-905`) writes `approved`, `verified`,
  `secret` and `baseuri` with no gate and no hook.
- **A race too.** `_approve_on_create` reads `verified`, then approves
  through a `modify` conditioned only on the row existing, so a replacement
  in between is approved.
- **Fix shape.** One conditional write: approve only where
  `verified = true`.

### Medium

**A4. Push sends a subtarget's non-object value unfiltered.** Pre-existing
(I4).
- **The gap.** `actor.py:3365-3367` returns a non-dict blob as it is.
- **Effect.** A friend excluded from `secret` subscribes with
  `subtarget=secret` and is pushed every JSON scalar or array written there
  (developer-API writes are always JSON, `property_store.py:94`). The pull
  answers `{}`, so the changelog's "as the callback does" is inaccurate.
- **Related.** With reverify-6 Issues 4 to 6, this is one problem: the two
  paths need one filter.

**A5. Permission patterns have no hierarchy, so parents and lists slip
through.** Pre-existing (I4).
- **Matching.** Patterns are anchored whole strings
  (`permission_evaluator.py:114-134`).
- **Lists.** An exact-name exclusion such as `memory_personal` (the example
  in `docs/guides/access-control.rst:437`) refuses `GET
  /properties/memory_personal`. But `/memory_personal/x` returns the whole
  list (`handlers/properties.py:330-457` ignores `path[1:]`), and its list
  diffs (`<list>/action`, `/index`, `/value`) are pushed and pulled.
- **Parents.** Friend's default exclusion `private/*`
  (`trust_type_registry.py:351-354`) does not match `private`, so any
  friend reads and overwrites `GET`/`PUT /properties/private` whole.
- **Related.** Reverify-6 Issue 4's premise ("a direct read refuses it")
  does not hold for a parent.

**A6. `/resources/<name>` never evaluates the resource grant.**
Pre-existing (I4). `handlers/resources.py:15-27`: only the access table; the
hook gets no caller. A friend's `resources.excluded_patterns` (`private/*`,
`security/*`) have no effect.

**A7. `POST /properties` applies list changes before its permission
check.** Pre-existing (I4).
- **The order.** Bulk list updates and deletes and list creation and
  metadata (`handlers/properties.py:1196-1690`) run before
  `_finish_bulk_list_update`'s hook check.
- **Effect.** A denied peer's mutation persists under a 403.
- **Fail-open check.** The hook check fails open on an evaluator error and
  on NOT_FOUND (`hooks.py:438-446`).

**A8. Revocation deletes too little.** Pre-existing (I8).
- **Only `patterns` are compared.** `detect_permission_changes`
  (`peer_permissions.py:808-813`) compares `patterns` only. A revocation by
  a new `excluded_patterns` entry (the documented way under
  `merge_base=True`, `access-control.rst:474`) or by dropping `read` deletes
  nothing.
- **Only lists are deleted.** `_delete_revoked_peer_data` deletes lists
  only (`callbacks.py:1472`), never scalars (`RemotePeerStore.set_value`).
- **Query copies skip the deletion.** Copies stored by query
  (`interface/subscription_manager.py:2506`, `:2591`, `:2913`;
  `remote_storage.py:677`) skip it, so a narrowed copy stored before a
  delayed revoking callback leaves the data forever.

**A9. The revocation probe can never succeed, and the branch strands the
pair.** Trigger pre-existing; outcome introduced (I9, I10).
- **The probe.** `sync_peer` probes `GET <peer>/trust/<our id>`
  (`interface/subscription_manager.py:1543`, async `:2646`). One path
  segment routes to `TrustRelationshipHandler`, whose GET always answers 404
  (`handlers/trust.py:245`; `base_integration.py:196-209`).
- **What follows.** When all of a peer's subscriptions answer 404, the
  subscriber deletes its trust locally (`:1664`, `:2777`). The peer keeps
  its approved row.
- **Why it now strands.** Pairing again is then a bearer-less request on
  that row: 403 on the branch, where `master` upserted. Only the async twin
  has `_skip_revocation_detection`.

**A10. Open client registration chooses its trust type.** Pre-existing
(I5).
- **The route.** `POST /oauth/register` with `"trust_type": "admin"`
  (`oauth2_server/client_registry.py:114`; `trust_type_registry.py:399`).
- **Effect.** It creates an approved, verified `admin` row on the OAuth2
  system actor by upsert (`interface/trust_manager.py:613-669`). Its
  `client_credentials` token carries `trust_type=admin`
  (`oauth2_server.py:671-681`).
- **Reach.** What that token reaches through `/mcp` was not traced; the
  client never holds the row's secret.

**A11. `FanOutManager` sends one unfiltered payload to every subscriber.**
Pre-existing (I4, I10). `fanout.py:535`; no permission read in the module,
where `Actor.callback_subscription` filters. It is a public API
(`interface/__init__.py:84`, `docs/guides/subscriptions.rst:499`); the
library does not call it.

### Low

- **A12, owner base-URI changes.** These are not `/meta`-checked
  (`handlers/trust.py:906-916`; `modify_trust_and_notify(baseuri=)`).
  Pre-existing.
- **A13, unconditional deletes.** Trust deletes are unconditional
  (`actor.py:2664-2668`; both backends): a stranger's DELETE can remove the
  replacement of its pending row. A denial of service; pre-existing.
- **A14, inconsistent hooks.** The approval and delete routes fire different
  hooks (`trust_approved` vs `trust_fully_approved_local`; `trust_deleted`
  with or without `trust_data`). Pre-existing.
- **A15, PUT ordering.** A PUT approves and notifies before writing the
  grant it carries, and writes grants for a missing row
  (`handlers/trust.py:937-1004`). Pre-existing.
- **A16, async drop.** The async create drops its row only on a timeout or
  a `RequestError` (`actor.py:1995-2004`); the sync twin drops it on any
  error. Pre-existing.
- **A17, `shared_properties` disclosure.** It asks for operation
  `subscribe`, which no built-in type lists, so every property name is
  disclosed as excluded (`handlers/trust.py:1459-1559`). Low to medium;
  pre-existing.
- **A18, fail-open evaluator errors.** Methods, actions and the hook check
  fall back or allow on an evaluator error (`methods.py:75-78`, `:156`;
  `actions.py:75-78`; `hooks.py:444-446`); properties and MCP fail closed.
  Pre-existing.
- **A19, NOT_FOUND on pull.** The pull accepts only ALLOWED, where a direct
  read falls back to the access table on NOT_FOUND
  (`handlers/subscription.py:55`; `actor.py:3386`): a type with no
  `properties` rules now pulls `{}` (introduced). The developer API's
  subscribe check uses the wrong path (`authenticated_views.py:646`).
- **A20, unapproved listing.** An unapproved row can list its peer id's
  subscriptions (`handlers/subscription.py:240`, `approved=False`).
  Pre-existing.

### Notes

- **Existence oracle.** `TrustPeerHandler.delete` answers 404 vs 403
  before authorising.
- **Stale notification.** `modify_trust_and_notify` notifies from the row
  as read before its write.
- **DynamoDB index lag.** The DynamoDB bearer lookup reads an eventually
  consistent index: a replaced secret may authenticate briefly.
- **Bearer on an unknown id.** A request for an unknown id carrying any
  bearer answers 403 where `master` stored a pending row
  (`handlers/trust.py:458-467`; possible I9, not traced).

## What holds

- **I2 (path binding)** holds on every route in the three tables.
- **I7 (secret egress)** holds: every outbound request uses the stored base
  URI (`actor.py:2832`, `:2977-2981`, `:3135-3139`, `:3860-3866`;
  `fanout.py:504-513`; `trust_permissions.py:399-410`;
  `callbacks.py:877-882`; `aw_proxy.py:181`).
- **Callback branches** require an approved row (`callbacks.py:195-200`,
  `:305-310`, `:552-557`).
- **OAuth2 and MCP** tokens cannot re-pair (`trust.py:21-36`).
- **Admin peers** have only their documented powers.

## Assessment

The branch's own goal, holding each peer to its own paths, holds. But it
never had the property that rests on: that an authenticated peer is one the
owner accepted. A1 means any stranger who files a trust request is a peer
for every route behind the permission evaluator, and A2 and A3 are two more
ways an unproven requester's secret becomes usable. Approval is checked in
one function that half the routes never reach.

The rest splits in two:
- **Grant enforcement (A4 to A8, A11).** It differs per route and per level
  of a property.
- **Lifecycle consistency (A9, A12 to A20).**

All of A1 to A11 except A2 and A9 are on `master` too. The public
repository's `master` therefore already carries A1, which is the most
severe item found in this branch's life. The owner's rule that security
records stay local until the fix applies to all of them.

Owner decisions needed before `/iterate_plan`: which of these this PR
closes, and which go to a separate (equally local) security plan.
