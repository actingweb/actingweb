# Research: callers that reach what they should not, on `/callbacks`, `/permissions` and `/subscriptions`

**Date:** 2026-11-06
**Branch:** docs/3-16-rollup-records
**Commit:** fea9e42

Three exposures found by the reviews of the four 3.16 plans of this date, and
one more found while checking them. They exist in the released library and
depend on none of the planned work, so the owner chose to take them first.

## Research Questions

1. **Can an unauthenticated caller post a subscription or permission
   callback?** Yes. Confirmed by running the handler against DynamoDB Local.
   See "Callbacks".
2. **What can such a caller do?** Store permissions for any peer id, trigger
   deletion of replicated data, run the application's `permissions` hook; and
   with a subscription id, inject diffs and have the trust's secret sent to a
   URL of its choosing. See "Callbacks".
3. **Can a peer read another peer's permissions?** Yes, for four relationship
   types; and some peers cannot read their own. See "Permission query".
4. **Can a peer reach another peer's subscriptions?** A peer with a `friend`
   relationship can, over REST; any authenticated caller can delete an
   outbound subscription through `/callbacks/subscriptions/…`; and a peer or
   client view in the SDK lists every peer's. See "Subscriptions".
5. **Do the library's own senders authenticate?** Yes, with the trust secret
   as a bearer token, so requiring authentication breaks no library peer. See
   "Senders".

## Summary

The access table has a row with an empty role for everything under
`callbacks` (`actingweb/config.py:289`, under the comment "Allow anybody
callbacks witout auth"). The callback handler defers authentication on two
branches and relies on `check_authorisation` with the peer id from the path;
for a caller with no credentials the `owner` row cannot match and the
empty-role row grants. The two branches are the two that write: subscription
callbacks and permission callbacks. The generic branch, the one an anonymous
third-party webhook would use, is the one that is closed, by accident: it
answers 200 with an empty body and runs no hook.

The same access table lets a peer of type associate, friend, partner or admin
read any peer's permissions, and lets a `friend` peer address any peer's
subscriptions, because role rows match on the relationship type and only
`owner` rows compare the peer id, and the subscription handlers do not pass
the peer id to the check.

## Detailed Findings

### Callbacks

Confirmed 2026-11-06 with a scratch test (not kept) against DynamoDB Local: a
real `CallbacksHandler`, a real `Config` with `peer_permissions_caching` on,
an actor with **no trust relationship at all**, and a request with no
`Authorization` header.

```
POST /<actor>/callbacks/permissions/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
→ 204 No Content
actingweb.auth: Basic auth failed, response code: 401
actingweb.auth: Testing access for ( ) on (callbacks/permissions aaaa…) using method POST
actingweb.auth: Granted a access with ACL:('', 'callbacks', '', 'a')
actingweb.handlers.callbacks: Stored permission callback from aaaa… : success=True
```

and `PeerPermissionStore.get_permissions(actor, peer)` then returned the
posted permissions. The same test on a generic path
(`POST /<actor>/callbacks/sms_webhook`) answered 200 with an empty body.

The path through the code:

- `handlers/callbacks.py:178-184` authenticates with `add_response=False`,
  under the comment "Allow unauthenticated requests to /callbacks/subscriptions
  and /callbacks/permissions, so do the auth check further below".
- The check that follows is `check.check_authorisation(path="callbacks",
  subpath="permissions", method="POST", peerid=granting_actor_id)`
  (`:197-202`) and the same with `subpath="subscriptions"` (`:358-363`).
- `auth.py:786-809`: a row whose role is the empty string matches any caller.
  The `owner` row (`config.py:287`) needs `self.acl["peerid"] == peerid`,
  which an anonymous caller fails; the loop continues to `config.py:289`.
- Nothing after the check looks at the caller again.

What follows on the permission branch (`:187-338`): the body's permissions are
stored for the peer id in the path (`:274`); if the stored permissions shrank
and `auto_delete_on_revocation` is on, `_delete_revoked_peer_data` deletes the
replicated lists the "revoked" patterns cover (`:264-271`); auto-sync and the
application's `permissions` hook run (`:288-336`). The peer id needs no trust
relationship. The consumer turns the deletion on
(`../actingweb_mcp/application.py:558-560`).
**Correction, 2026-11-06:** it does not. It calls
`with_peer_permissions(enable=True)` and nothing else there, and
`auto_delete_on_revocation` defaults to off
(`actingweb/interface/app.py:851`); the comment on that line of the consumer
says otherwise. The deletion is reachable only in a deployment that sets it.
Also found on this date and added to the plan's Phase 1: a wrong bearer is
accepted like no credentials (the authentication result is never looked
at), and a callback is accepted against a subscription the actor holds as
publisher (`db/dynamodb/subscription.py:69-73` does not filter on the
`callback` flag).

On the subscription branch (`:340-431`) the caller also needs a subscription
id the subscriber holds for that peer (random, but sent in every callback and
stored by both sides). With it:

- a high-granularity body is applied to the replica as a diff;
- a low-granularity body carries `url`, and the receiver fetches it with the
  trust's shared secret: `callback_url = params.get("url")` (`:515`), then
  `client.get(callback_url, headers={"Authorization": f"Bearer {secret}"})`
  (`:617-623`). The URL is not checked against the peer's base URI.

`DELETE /<actor>/callbacks/subscriptions/<peer>/<subid>` (`:78-152`) does
authenticate (`add_response` defaults to True), but its check
(`:91-96`, method `DELETE`) is also granted by the empty-role row for any
authenticated caller: `config.py:287` is POST only. It deletes the actor's
outbound subscription to that peer.

`GET` on a callback path (`:33-56`) and the generic POST branch (`:433-471`)
go through `AuthResult.authorize`, which returns `False` without setting a
status when authentication failed (`handlers/base_handler.py:385-386`): 200,
empty body, no hook.

### Permission query

`GET /<actor>/permissions/<peer>` (`handlers/permissions.py`):

- `:60-74` answers 404 "Trust relationship not found" before authorisation, so
  any authenticated caller learns which peer ids have a relationship.
- `:79-91` calls `check_authorisation(path="permissions", subpath="<id>",
  method="GET", peerid=peer_id)`. The rows that match are role rows
  (`config.py:316-319`: associate, friend, partner, admin), which do not
  compare the peer id. A peer of any of those types reads any peer's
  permissions.
- A peer whose relationship has no row (`viewer`, `mcp_client`, a custom type
  without one) is refused its own, and so is the creator.

### Subscriptions

- `handlers/subscription.py:143-148` (the per-peer GET) passes the URL's peer
  id, but `config.py:336` `("friend", "subscriptions/<id>", "", "a")` matches
  on the relationship type alone.
- `:204`, `:314`, `:381`, `:440`, `:548` call `auth_result.authorize(…)`, which
  passes no peer id (`handlers/base_handler.py:388-390`), so the `owner` row
  (`config.py:334`) can never match there and the `friend` row is what admits
  a peer: to create a subscription under any peer id, read any peer's
  subscription and its diffs, clear them, and delete it.
  **Correction, 2026-11-06:** not "create". The POST handler compares the
  path's peer id with the caller's after the access check and answers 403
  (`handlers/subscription.py:235-244`), so a peer cannot create a
  subscription under another peer's id. Read, not run; the plan's Phase 0
  pins it (row WA12).
- The root listing (`:17-60`) is limited to creator and trustee
  (`config.py:338-340`).
- `interface/authenticated_views.py:691-705` returns every subscription of the
  actor to a peer or client view ("Delegate read-only operations without
  permission checks"). Nothing in the library, the demo or the consumer builds
  such a view for subscriptions today (`as_peer`, `as_client`,
  `_get_authenticated_view` have no caller), so this is an SDK surface, not a
  wire exposure. A client view's accessor id is the client id
  (`:47-49`, `interface/actor_interface.py:732-735`), while subscription rows
  carry the trust's peer id.

### Senders

Subscription callbacks are sent with `Authorization: Bearer <trust secret>`
(`actor.py:2683`, resync `:3283`, `:3325`); permission callbacks the same
(`trust_permissions.py:386-388`, and through `AwProxy` on the synchronous
path, `:286-308`); the subscription delete notification the same
(`actor.py:2531`). A peer bearer sets `acl["peerid"]` on the receiver
(`auth.py:270-290`).

### Who would notice a fix

- The demo documents three anonymous third-party webhooks on
  `/callbacks/<name>` (`examples/demo/shared_hooks/app/callback_hooks.py:47`,
  `:106-107`, `:161`). They cannot run anonymously today (200, no hook).
- The consumer's own webhooks use its own routes
  (`../actingweb_mcp/api/stripe_webhook.py:679`,
  `api/revenuecat_webhook.py:638`).
- No test posts to `/callbacks/permissions/…`, and
  `tests/test_subscription_callbacks.py` asserts nothing about authentication.
- Which relationship types may subscribe is carried by the role rows today
  (only `friend` among the built-in types); applications add rows for their
  own types.

## Documentation Impact

### Callbacks

- `docs/protocol/actingweb-spec.rst:1150-1160` — "an anonymous POST from a
  non-ActingWeb application" beside "All /callbacks requests without
  authentication data MUST return 401". Contradicts itself; settled by the
  specification plan, which this fix is consistent with.
- `docs/guides/subscriptions.rst`, `docs/reference/security.rst` — no
  statement that callbacks are authenticated: none. Needs one.
- The demo's hook docstrings and README section on webhooks — describe
  anonymous use that does not work.

### Permission query and subscriptions

- `docs/protocol/actingweb-spec.rst:2036-2042` — "Only the peer can query their
  own granted permissions". True after the fix.
- `docs/sdk/authenticated-views.rst` — describes peer and client views; says
  nothing about subscription listing.

## Decisions Needed

### Decision 1: how the peer is bound on the subscription paths

1. **A handler rule**: a caller authenticated as a peer must be the peer in
   the path, whatever its relationship type. The role rows keep deciding which
   types may use subscriptions at all.
2. **Through the access table**: pass the peer id into the check so the
   `owner` row applies, and delete the `friend` row. Cleaner, but it lets
   every approved relationship type create and manage subscriptions, where
   today only `friend` (and types an application grants) can.

### Decision 2: unauthenticated generic callbacks

1. **401 for every unauthenticated callback request.** Honest about what
   happens today (nothing runs) and matches the specification's MUST.
2. **Leave the generic branch** (200, empty body) and fix only the two that
   write.

An opt-in for anonymous third-party webhooks is a feature and is in the
specification plan.

## Release shape

3.16, first of the plans. A wire-visible tightening: `SECURITY` entries, with
a `**Behavior change:**` for unauthenticated callback requests and for peers
that relied on the `friend` row to reach another peer's subscriptions. No
route, kwarg or response field changes for a correctly behaving peer.

## Code References

- `actingweb/config.py:283-290`, `:316-319`, `:334-340` — the access rows
- `actingweb/auth.py:740-812` — `check_authorisation`
- `actingweb/handlers/callbacks.py:33-56`, `:78-152`, `:176-338`, `:340-471`, `:508-650` — the callback handler
- `actingweb/handlers/base_handler.py:372-392` — `AuthResult.authorize`
- `actingweb/handlers/permissions.py:55-141` — the permission query
- `actingweb/handlers/subscription.py:134-200`, `:204`, `:314`, `:381`, `:440`, `:548` — the per-peer handlers
- `actingweb/interface/authenticated_views.py:33-60`, `:619-705` — the view
- `actingweb/trust_permissions.py:286-308`, `:372-395` — the permission callback sender

## External References

None.
