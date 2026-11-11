# Research: trust replacement, the access table with application rows, and what stale peer state survives

**Date:** 2026-11-07
**Branch:** docs/3-16-rollup-records
**Commit:** 766e3fa
**Plan:** thoughts/plans/2026-11-06-peer-authorisation-fixes.md (its "Second
review", the three `[research]` items)

The research pass `thoughts/todo/INDEX.md` puts between the wire spike and
the redraft of the security plan. Everything here was read in the code (three
independent readings plus a documentation sweep); nothing was run against a
live app in this pass. The wire spike
(`research/2026-11-07-subscription-wire-spike.md`) is the run-side companion.
Line numbers are against `master` at `5a7e07f`.

## Research Questions

1. **What may a trust-creation request do to an existing row, and what may a
   pending or replaced row set on itself?** — It overwrites the row on both
   backends, `approved` included; a pending peer may set only
   `peer_approved` on its own row, and may delete its own row. See "Trust
   replacement".
2. **The full access table with application rows: which rows admit a caller
   to a path naming another peer?** — Default rows 22-25 and 35, and four of
   the consumer's seven `subscriber` rows; only the three `owner` rows bind
   the caller to the path, and only where the handler passes `peerid=`. See
   "The access table".
3. **Which stored peer state can outlive the relationship it belongs to, and
   what reaps it on each backend?** — No TTL on any of it; removal is
   library-driven and identical on both backends. A `_peer_permissions` row
   for a peer id with no trust row has no remover except actor deletion. See
   "Stale peer state".
4. **Which documentation states these behaviours?** — The specification
   states most of the intended rules; the guides state almost none, and none
   documents the default table. See "Documentation Impact".

## Summary

The trust row, which Phases 1 and 2 of the plan use as the caller's
identity, is replaced in place by a trust-creation request for an existing
peer id: every field except `created_at` (PostgreSQL) is overwritten, the
owner's `approved` is reset to the configured default, and the owner's custom
grants are kept. The publisher's send paths read no approval or verification
flag before using the row's `baseuri` and `secret`. So the binding the plan
adds is only as strong as the row it binds to, and the guard on replacement
is the decision the plan's second review left open.

The access table is first-match with plain string-prefix paths, and `<id>`
is a literal, not a placeholder that is compared with the caller. The only
rows that bind the caller to the path's peer are the three `owner` rows, and
only on call sites that pass `peerid=`; a non-owner row later in the table
admits the same caller on every such path except trust read and delete. The
consumer's `subscriber` type inserts seven rows at index 0, four of them on
`<id>` paths, and the subscription handler authorises PUT and DELETE as GET,
so a GET-only application row admits writes. A per-path rule in
`check_authorisation` or per-handler rules both have to account for
application rows, which the plan's Phase 2 as written does not.

None of the peer state on the callback paths carries a TTL; removal is by
trust deletion, subscription deletion and actor deletion, identically on
DynamoDB and PostgreSQL (PostgreSQL has no foreign-key cascade on these
tables). A resync replaces only the keys its baseline contains. After the fix
lands, what was written before it stays until one of those triggers runs,
and one kind (permissions stored for a peer id with no trust row) has no
trigger short of deleting the actor.

## Detailed Findings

### Trust replacement

**The creation route** (`actingweb/handlers/trust.py:370-495`). The handler
loads the actor and does not consult the authentication result or the access
table (`:373-383`); the default row `("", "trust/<type>", "POST")`
(`config.py:325`) would admit any caller anyway. This is the protocol's
design: the specification says the trust request carries no authentication
(`docs/protocol/actingweb-spec.rst:1568-1570`). Body fields read: `baseuri`,
`id`, `secret`, `desc`, `verify`, `type` (`:391-410`, `:445`). `approved` is
derived from configuration, never the body (`:427-433`; default `False`,
`config.py:222-223`), and `peer_approved` is hard-coded `True` (`:453`).

**An existing row for the same peer id.** `Trust.create`
(`actingweb/trust.py:391-482`) refuses only when the *same* secret already
exists for the actor (`:420-427` → 403); any other secret proceeds to the
backend `create`:

| Field | PostgreSQL (`db/postgresql/trust.py:286-320`, `ON CONFLICT DO UPDATE`) | DynamoDB (`db/dynamodb/trust.py:320-427`, unconditional `save()`) |
| --- | --- | --- |
| `secret`, `baseuri`, `type`, `relationship`, `desc` | overwritten | overwritten |
| `approved` | overwritten with the config default | overwritten with the config default |
| `peer_approved` | `True` | `True` |
| `verified`, `verification_token` | overwritten (fresh token) | overwritten |
| `peer_identifier`, `client_*`, `oauth_client_id`, `aw_*`, `capabilities_fetched_at` | set NULL | dropped |
| `created_at` | kept | reset to now |
| the owner's custom grants (separate store) | kept (`trust.py:446-464`) | kept |

Because `relationship` comes from the URL and a bearer resolves to the
role on its row (`auth.py:282`), the replacing request also sets the role
the row's bearer will carry.

**Verification** (`actor.py:1913-2005`). The receiver calls the body's
`baseuri` (`:1939`) with the body's secret; every outcome, including a
connection failure, continues to `create` with `verified` set accordingly
(`:1988-2002`). The response status depends on `approved` only
(`handlers/trust.py:492-495`), and its body is the stored row, `secret` and
the new `verification_token` included (`:489`).

**What a pending peer may set on itself.**
- `PUT /trust/<type>/<id>` (`handlers/trust.py:711-885`) goes through
  `authorize()` with the default `approved=True`, so a pending peer is
  refused by the approval gate (`auth.py:751-760`). An approved peer reaches
  it only with a role row for `trust` (`creator`, `trustee`, `admin`,
  `config.py:329-332`). Fields: `baseuri`, `desc`, `approved` (only ever set
  true, `:736-738`), `permissions`.
- `POST /trust/<type>/<id>` with `{"approved": true}` uses
  `check_authorisation(..., peerid=<path>, approved=False)` (`:637-643`):
  the gate is skipped and the `owner` row (`config.py:327`) admits the peer
  the path names. It sets exactly `peer_approved=True` (`:659-661`).
- `DELETE /trust/<type>/<id>` likewise skips the gate (`:964-973`, and the
  carve-out at `auth.py:755`): a pending peer may delete its own row. With
  `is_peer` true no reciprocal delete is sent (`:982-994`, `:1030-1037`),
  and the local cascade removes the peer's subscriptions, replica, callback
  state, profile, capabilities and permissions cache, then the row and its
  custom grants (`actor.py:2084-2223`, `trust.py:137-241`).

**The send paths** read no flag. `callback_subscription` checks only that a
row exists (`actor.py:2631-2633`) and posts to the row's `baseuri` with its
`secret` (`:2674-2685`); both permission-notify paths
(`trust_permissions.py:264-324`, `:326-407`, through `aw_proxy.py:242-246`)
need only `baseuri` and `secret`. The creator-initiated reciprocal delete
does the same (`actor.py:2046-2056`).

**The consumer re-initiating.** Emm's `POST /api/trust/create`
(`../actingweb_mcp/api/trust.py:146-348`) does no lookup for an existing
relationship; the library's `create_reciprocal_trust` upserts its own row
with a new secret (`actor.py:1703-1713`) and posts the request; on any
answer other than 201/202 it deletes its own row (`:1751-1754`,
`:1772-1775`). A guard that refuses an existing peer id therefore turns a
re-initiation into a deleted local row on the initiator; a guard that
verifies the new secret against the stored base URI lets it through when
the peer is reachable at the same address.

### The access table

**Matching** (`auth.py:740-813`): rows in order, first match returns; role
`""` matches every caller including an unauthenticated one; `owner` matches
only when the handler passed `peerid=` and it equals the caller's peer id
(`:800-804`); path is a string prefix of `path + "/" + subpath` with no
segment boundary (`:806`); method is substring containment, empty meaning
all (`:807`). `<id>`, `<type>`, `<subid>` are literals the handlers pass in
`subpath` (e.g. `subscription.py:314`, `trust.py:536`). `authorize()`
(`base_handler.py:373-395`) never passes `peerid=`, so `owner` rows cannot
match through it. The subscription handler authorises PUT and DELETE as GET
(`subscription.py:381`, `:440`). There are no reject rows.

**Default rows that name a peer path** (`config.py:275-345`, 41 rows): 2
`owner callbacks/subscriptions POST`; 3 `"" callbacks` (all methods); 22-25
`associate|friend|partner|admin permissions/<id> GET`; 29 `"" trust/<type>
POST`; 30 `owner trust/<type>/<id>`; 34 `owner subscriptions`; 35 `friend
subscriptions/<id>` (all methods). Built-in trust types carry no
`acl_rules` (`trust_type_registry.py:58`, `:321-516`).

**Application rows.** `add_trust_type(..., acl_rules=...)` inserts each
rule at index 0 in declaration order, so the block ends up reversed and
ahead of every default row (`permission_integration.py:392-416`). The
consumer's `subscriber` type adds (`../actingweb_mcp/application.py:833-869`):
`permissions/<id> GET`, `methods POST`, `trust/<type>/<id> GET`, `callbacks`
(all), `properties GET`, `subscriptions/<id>/<subid> GET`,
`subscriptions/<id> POST`. Its two MCP types add none.

**Whom a path naming another peer admits** (B in the path, C the caller):

| Path | A `friend` peer C | A `subscriber` peer C | What binds C to B today |
| --- | --- | --- | --- |
| `GET trust/<type>/B` | refused (only row 30 fits) | admitted by its own row | row 30, for `friend` only |
| `POST trust/<type>/B` | admitted by row 29 | admitted by row 29 | nothing on the `authorize()` branch |
| `GET permissions/B` | admitted by row 23 | admitted by its own row | nothing (`permissions.py:59-85` checks a trust A-B exists, not that C is B) |
| `GET/PUT/DELETE subscriptions/B/<subid>` | admitted by row 35 | admitted by its GET row (PUT and DELETE ask for GET) | nothing |
| `POST callbacks/subscriptions/B/<subid>` | admitted by row 3 | admitted by its own row or row 3 | nothing (row 2 binds, row 3 then admits) |
| `POST callbacks/permissions/B` | admitted by row 3 | admitted by row 3 | nothing |

The handler-level bindings that do exist: `subscription.py:235-244` (a
peer cannot create a subscription under another id) and
`trust.py:1275-1282` (shared properties). There is no `_is_path_peer` in
the code; the name exists only in the plan.

### Stale peer state

All in the attributes table except the sequence; no writer on these paths
passes `ttl_seconds`; PostgreSQL has no foreign keys on trusts,
subscriptions or attributes (`migrations/versions/3307e3616c5e_*`), so
removal is library-driven and the same on both backends.

| State | Where (bucket / key) | Removed by | Gap |
| --- | --- | --- | --- |
| Received permissions | `_peer_permissions` / `<actor>:<peer>` (`peer_permissions.py:97-99`, `:279-282`) | trust deletion, per trust row (`actor.py:2186-2204`); actor deletion | a row for a peer id with no trust row: only actor deletion |
| Callback state and pending queue | `_callback_state` / `state:<peer>:<subid>`, `pending:<peer>:<subid>` (`callback_processor.py:103-111`) | `Subscription.delete()` (`subscription.py:102-116`); trust deletion (`callback_processor.py:770-790`); actor deletion; a resync empties pending | bulk `Subscriptions.delete()` (`subscription.py:280-296`) does not clear it |
| Callback sequence | subscriptions row `seqnr` | row deletion | — |
| Replica | `remote:<peer>` (`remote_storage.py:52`) | trust deletion; last subscription to the peer (`actor.py:2555-2619`); actor deletion; revoked lists with `auto_delete_on_revocation` | a resync replaces only keys its baseline holds (`remote_storage.py:550-556`) |
| Profile, capabilities | `_peer_profiles`, `_peer_capabilities` | trust deletion; actor deletion | not written from the callback paths |

Three processing details bear on the plan's Phase 1 and Phase 3:

- A held callback is applied, in order, when the in-order one before it
  arrives (`callback_processor.py:913-939`); `max_pending` rejection leaves
  the stored queue unchanged (`:397-398`, `:886-892`).
- A body `type` of `permission` on the subscription path is dispatched
  before sequencing (`callback_processor.py:821-823`, `:1070-1100`) and its
  `data` is applied to the replica as an unsequenced diff
  (`handlers/callbacks.py:674-677`); nothing is written to
  `_peer_permissions` on that path. Only `diff`, `resync` and `permission`
  are recognised; any other string is sequenced as a diff.
- The "older update" check compares the body's `timestamp` as a string
  with the stored `fetched_at` (`callbacks.py:234-263`,
  `peer_permissions.py:259-268`); a store refusal still answers 204
  (`callbacks.py:274`, `:338`).

## Documentation Impact

### Trust creation and replacement

- `docs/protocol/actingweb-spec.rst:1568-1574` - the request is
  unauthenticated; status codes 201/202/403, no 409. Stays (protocol), or
  gains the guard's status if one lands.
- `docs/protocol/actingweb-spec.rst:1881-1882` - "MAY NOT hold more than one
  relationship with a given other actor": true (one row), but silent on
  replacement; the only statement on the topic anywhere.
- `docs/protocol/actingweb-spec.rst:1747-1751` - "the actor owning the
  trust relationship can update ... baseuri, desc, and approved"; ambiguous
  about owner versus peer.
- `docs/guides/trust-relationships.rst:108-113` and
  `docs/guides/p2p-quickstart.rst:44-49` disagree about a subscription on a
  pending trust (allowed versus 403). Already inconsistent.
- `docs/reference/security.rst:47-50`, `:110` - base URI checks and who
  reads the secret; would need the replacement rule.

### The access table

- `docs/guides/access-control.rst:117-143`, `:184-214` and
  `docs/guides/access-control-simple.rst:171-221` - document `acl_rules`
  and show `("callbacks", "", "a")`; none says rows are prefix-matched,
  first-match, inserted ahead of the defaults, or that `<id>` is not
  compared with the caller. No page documents the default table or
  `check_authorisation`. New section needed whichever rule shape is chosen.
- `docs/guides/p2p-quickstart.rst:179-184` - `acl_rules` must cover
  `subscriptions` and `callbacks/subscriptions`; stays true.

### Callbacks

- `docs/protocol/actingweb-spec.rst:1153-1159` - requires authentication
  with the shared secret, allows an anonymous POST from a non-ActingWeb
  application, and requires 401 for any unauthenticated request: internally
  contradictory today, and the code follows neither branch for the two peer
  paths.
- `docs/reference/routing-overview.rst:36`, `README.rst:255-256`,
  `docs/reference/hooks-reference.rst:46-53`,
  `docs/guides/trust-relationships.rst:439-444`,
  `docs/quickstart/configuration.rst:1078-1084` - name the paths with no
  authentication rule; each needs one sentence.

### Permissions query and subscriptions

- `docs/protocol/actingweb-spec.rst:2036-2042` - "Only the peer can query
  their own granted permissions": already wrong against the code.
- `docs/quickstart/configuration.rst:1128-1133` - "Peers must have a valid
  trust relationship": true but incomplete.
- `docs/protocol/actingweb-spec.rst:2383-2387`, `:2440-2442`,
  `:2889-2896` - peer rights on its own subscription; no page states who
  may DELETE a subscription.

### Cleanup

- `docs/guides/trust-relationships.rst:119-133`, `:395`;
  `docs/quickstart/configuration.rst:978-998` - cleanup on trust deletion;
  true. None mentions state for a peer with no trust row, nor that a resync
  keeps keys absent from its baseline.
- Released migration guides and changelogs (`v3.7`, `v3.10`, `v3.15`) stay.

## Decisions Needed

### Decision 1: a guard on trust replacement, and its shape

1. **Refuse a creation for an existing peer id** (409, as the
   specification plan's T6 proposed). Simple; breaks a peer that
   re-initiates (the library initiator then deletes its own row on the
   non-2xx, `actor.py:1751-1775`), so re-pairing needs a delete first.
2. **Replace only when the new request verifies against the stored base
   URI.** Keeps re-initiation working for a peer at the same address;
   refuses a peer that has genuinely moved, which then needs the owner to
   delete the row.
3. **Keep the owner's `approved` and the stored `relationship` on a
   replacement**, replacing only credentials after verification. Narrower
   change to `Trust.create` and both backends' upsert.
4. **No guard in this plan**; the `SECURITY` entry then says the binding is
   to the row and the row is replaceable.

### Decision 2: where the caller-to-path binding lives

1. **One rule in `check_authorisation`**: a matched row whose path holds
   `<id>` requires the caller's peer id to equal the path's (admin and
   creator exempt). Covers application rows and every handler at once;
   needs every call site to pass the real peer id, which `authorize()` does
   not today.
2. **Per-handler rules** on callbacks, subscriptions, permissions and trust,
   as the plan drafts for the first two. Explicit; misses the next handler
   and must still be written so an application row placed at index 0 cannot
   bypass it (the rule runs after the table).

### Decision 3: PUT and DELETE authorised as GET on subscriptions

Pass the real method (an application's GET-only row then stops admitting
writes; a consumer that relies on it for clearing its queue breaks) or keep
GET and bind the peer in the handler.

### Decision 4: what the fix does about state written before it

1. **Nothing**; document that a trust deletion and re-creation clears it.
2. **An operator command** that, per actor, removes `_peer_permissions`
   rows for peer ids with no trust row, pending queues and state for
   subscriptions that no longer exist, and optionally rebuilds replicas from
   a fresh baseline (a resync alone keeps stale keys).
3. **Reap on read**: drop a `_peer_permissions` row when no trust row
   exists for its peer. Cheap, but adds a trust read to a hot path.

### Decision 5: the `permission` type on the subscription path

Refuse unknown and out-of-place types on the subscription path (only `diff`
and `resync` sequenced), or keep dispatching them; the first is the plan's
Phase 1 proposal and changes no legitimate flow found in the code.

## Release shape

Part of 3.16 (a minor, tag held), as the plan already states. Decisions 1
and 2 change who may call routes and therefore need **Behavior change:**
entries and migration-guide text for applications with custom `acl_rules`.

## Code References

- `actingweb/handlers/trust.py:370-495` - trust creation route
- `actingweb/trust.py:391-482` - `Trust.create`, same-secret refusal, grants kept
- `actingweb/db/postgresql/trust.py:286-320`, `actingweb/db/dynamodb/trust.py:320-427` - the upserts
- `actingweb/actor.py:1913-2005` - verification; `:1703-1775` - initiator side
- `actingweb/handlers/trust.py:614-709`, `:711-885`, `:886-1049` - POST/PUT/DELETE on a row
- `actingweb/auth.py:740-813` - `check_authorisation`; `:751-760` approval gate
- `actingweb/config.py:275-345` - default access table
- `actingweb/permission_integration.py:392-416` - `acl_rules` inserted at index 0
- `actingweb/handlers/subscription.py:235-244`, `:314`, `:381`, `:440` - binding and GET-for-write
- `actingweb/handlers/permissions.py:59-112` - permission query
- `actingweb/handlers/callbacks.py:178-205`, `:351-366`, `:674-677` - callback authorisation and dispatch
- `actingweb/callback_processor.py:397-405`, `:816-823`, `:913-939` - pending, type dispatch, drain
- `actingweb/remote_storage.py:550-556` - resync keeps absent keys
- `actingweb/actor.py:2084-2223` - trust deletion cascade
- `../actingweb_mcp/application.py:833-869` - the consumer's `subscriber` rows
- `../actingweb_mcp/api/trust.py:146-348` - the consumer's trust initiation
