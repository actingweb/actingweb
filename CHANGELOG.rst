=========
CHANGELOG
=========

Unreleased
----------

SECURITY
~~~~~~~~

- **An actor's owner could write a grant into another actor.** ``PUT
  /<actor>/trust/<rel>/<peer>/permissions`` (and ``permissions`` in a trust
  ``PUT``) on an existing override copied any field the request named,
  ``actor_id``, ``peer_id`` and ``trust_type`` included, and the store keys
  on those, so on a shared host one actor's owner could give itself any
  level at another actor. **Behavior change:**
  ``TrustPermissionStore.update_permissions`` takes only the permission
  categories and ``notes``; identity and bookkeeping fields are refused
  and logged; the grant API sets ``created_by`` itself, and answers 400
  for a rule whose pattern or operation keys are not lists of strings,
  ``null`` included. Such a value already stored (or written through the
  store API) is read on merge as: a malformed ``excluded_patterns`` keeps
  the trust type's exclusions (a string or ``null`` replaced them; a single
  string is taken as one pattern, and a string ``denied`` as a one-item
  list, which replaces the type's ``denied`` as any override does); a malformed
  ``operations`` or ``allowed``, or a category that is not an object,
  allows nothing; a malformed ``patterns`` acts as an empty one and a
  ``properties`` list of names is normalised, both merged with the trust
  type's patterns as any override is (before 3.16 these two denied).
  **Check:** the fix stops new writes, not grants already written. On a
  host that serves actors of more than one owner, review each actor's
  overrides (``TrustPermissionStore.list_actor_permissions``) for peers it
  did not grant, and look in request logs for permission PUTs whose body
  named ``actor_id``, ``peer_id`` or ``trust_type``.
- **A peer read, overwrote and was pushed property parts its grant
  excluded.** An exclusion was checked only at the exact path a request
  named: a peer granted ``*`` without ``settings/private`` read ``settings``
  with its private child inside, overwrote it, received it in every
  subscription diff, and reached an excluded list through
  ``/properties/<list>/<x>``. A bulk ``POST /properties`` skipped a refused
  name silently and applied a refused bulk list update before answering
  403. **Behavior change:** an exclusion covers its node and every descendant
  (``private/*`` also names ``private``); a peer reads a value without its
  excluded parts at any depth (direct reads, the listing, pushed and pulled
  diffs, the developer views); a non-admin peer's write or delete that would
  touch an excluded part is 403; a path under a list is decided by the
  list's grant; a bulk ``POST`` is validated and authorised whole and
  refused whole by the grant (an application hook that refuses part way
  does not undo what was already written: those keys' diffs reach the
  subscribers, then 403, where a hook's refusal of a bulk list update was
  a 500). An object stored or written as JSON text (a form post, an
  SDK write of a JSON string, and every value the developer views read
  back from storage) is filtered as the object, and handed back as text;
  text counts as JSON when a JSON client would read it as JSON (behind a
  byte-order mark, or UTF-16 in its bytes). **Behavior change:** for the
  owner too: such text written as a whole property is stored as plain JSON
  text, it is read back re-serialised, its parts can be read, written and
  deleted, and the read and write hooks receive it as an object.
  **Behavior change:** when the grant excludes anything, a kept part
  nested more than 100 levels deep (objects or arrays) is withheld from
  the peer (a direct read is 403, the name is left out of the listing and
  of a diff, a developer view reads ``None``) and the peer's write of an
  object that deep is 403: the filter cannot walk it safely, and it is never sent
  unfiltered. An excluded part is dropped whatever its depth. Text nested
  beyond the JSON parser (only an application can store it) is never sent
  to a peer, whatever its grant (403 on a read, left out of the listing and
  of diffs); the owner reads it as stored. A sub-path ``PUT`` into such a
  value answers 409 (it cannot be merged into; replacing the whole would
  lose what the write did not name), and a request body nested beyond the
  parser is treated as invalid JSON (both answered 500; a list item
  ``PUT ?index=`` stored such a body as text): 400 on the property,
  method, action, resource and callback routes and the trust ``PUT``s;
  ``POST /trust`` and ``POST /subscriptions`` fall back to form fields, as
  for any invalid JSON. A sub-path ``PUT`` onto plain
  text, or onto a JSON list or scalar, answers 409 too (it replaced the
  whole value, or answered 500). **Behavior change:** a direct
  ``GET /properties/<name>`` of a plain-text value runs the property's read
  hook, as the listing does (a hook answering ``None`` is 404), and a
  sub-path of plain text is 404 (it answered the whole text). A
  peer gets 403 for a list it may not write whether it exists or not
  (``PUT ?index=`` and a bulk ``items`` write answered 404/400 for a
  missing one first). ``docs/migration/v3.16.rst`` ("Grants hold at every
  level") has the details.
- **A grant's rule that did not match a name let the access table serve
  it.** A properties or resources rule in the ``allowed``/``denied`` shape,
  or an empty one, answered "no rule" for a name it did not list, and the
  handlers then asked the access table, which admits a whole category per
  trust level: the type's rule was bypassed. **Behavior change:** a rule the
  grant states decides every name; only a grant that does not mention the
  category leaves a name to the access table, and never for an OAuth2/MCP
  client. Property hooks and the developer views use the same decision; an
  error in a hook's check denies (it allowed).
- **A peer reached ``/resources``, methods and actions past its grant, and
  subscribed to what it could not read.** ``/resources`` ignored the
  ``resources`` grant (the access table alone decided, so a ``friend`` read
  and deleted ``private/x``); a methods or actions rule that did not cover a
  name, or an empty one (``"methods": []``), fell through to the access
  table, which admits the whole category per trust level; an evaluator
  error fell back to the table and a listing showed everything; the async
  listings were not filtered; ``DELETE /methods/<name>`` and a JSON-RPC body
  on the bare ``/methods`` were not decided by the grant; a subscription to
  an excluded path was created; ``shared_properties`` named every property
  the peer could not read and answered an unapproved peer; an unapproved
  peer listed its subscriptions; a subscription the grant stopped admitting
  kept delivering; a ``methods``, ``actions`` or ``resources`` request that
  named nothing (``POST /methods`` without JSON-RPC, an empty JSON-RPC
  ``method``, a bare ``/resources``) went to the access table whatever the
  grant stated, so every ``*`` hook ran with an empty name.
  **Behavior change:** all of these follow the one access decision; a
  subscription is checked again at each delivery, push and pull: one to
  ``properties``, ``resources``, ``methods`` or ``actions`` against its
  creation check, one to an application's own target for an approved
  trust; a request that names nothing is refused when the grant mentions
  the category, except the ``GET`` listing of methods or actions, admitted
  when the rule names anything and filtered per name, and JSON-RPC on the
  bare ``/methods``, decided by the method its body names (an empty
  ``method`` names nothing and is refused; a body with no ``method`` is
  the JSON-RPC error ``-32600``, HTTP 200, where it was a 403).
  **Behavior change:** a refused JSON-RPC method answers HTTP 403 with the
  JSON-RPC error ``-32000`` (it answered 200).
  ``docs/migration/v3.16.rst`` ("Every other way in") lists each.
- **An MCP client could give itself any access level, ``admin``
  included.** An anonymous ``POST /oauth/register`` stored the
  ``trust_type`` it asked for and a ``client_credentials`` grant on the
  OAuth2 system actor; the authorize form took any registered type from a
  form field the client could post itself, with no form shown to the user,
  and preselected the first type in the registry (``admin`` with no list
  configured); a user signing in for such a request gave the client an
  ``admin`` trust on their actor; a re-authorisation never changed an
  existing row's type; a code was issued even when the trust could not be
  written; the SPA authorize call created a trust of any type it named.
  **Behavior change:** the client list (``configure_oauth2_trust_types``;
  with none, every registered type except ``admin``) is enforced at
  registration, the authorize POST, the callback, the confirmation and the
  SPA authorize call; the form is bound to the browser by a nonce cookie,
  and a sign-in it cannot bind waits for the user's Approve on a
  confirmation page in the browser that signed in; a re-authorisation sets
  the row to the level the user approved, up or down (an override it held
  for another type stops applying; see "A client's level follows the
  user's latest approval" under CHANGED); no code is issued without the trust, also when the row is deleted
  during the authorisation. **Behavior change:** a redirect URI with a user
  name or password is refused at registration (``invalid_client_metadata``),
  and the confirmation page names the host the code goes to without one (it
  showed ``claude.ai@evil.test``). The confirmation re-checks the client's
  own ``allowed_trust_types`` at Approve, and any decision hook's answer
  against the client list; a 503 keeps the page usable for a retry; the
  form and confirmation pages send ``Referrer-Policy: same-origin`` (under
  ``no-referrer`` a browser without Fetch Metadata had its own Approve
  refused as cross-site). ``docs/migration/v3.16.rst`` ("An MCP client's
  access level").
- **A write three levels down reached subscribers past their grant.**
  ``PUT /properties/a/b/c`` registered its diff as resource ``b`` holding the
  bare value, so the filter checked ``a/b`` and an exclusion of ``a/b/c``
  never applied (and the subscriber's copy of ``a.b`` was overwritten).
  **Behavior change:** such a write or delete is diffed as resource ``b``
  with its whole stored value, filtered at the true paths.

- **Anyone who requested a trust was granted its relationship's
  permissions before the owner approved it.** ``POST
  /<actor>/trust/<relationship>`` is unauthenticated and stores a pending
  row with the relationship the request names (``admin`` included), and the
  row's secret authenticates as that peer. The access table refused an
  unapproved row, but the permission evaluator, which decides properties,
  list items, metadata, methods, actions and MCP tools, resources and
  prompts, never read ``approved``: a stranger could read and write
  properties, call methods and actions, and as ``admin`` clear every
  property. **Behavior change:** the evaluator grants nothing to a row this
  actor has not approved, nor to a peer id with no trust row at all (a
  permission override left behind grants nothing;
  ``PermissionResult.DENIED``); a pending peer reaches only its own trust
  row (its status and its deletion). An ``actor.as_client(client_id)`` view
  is evaluated as the client's trust row (the one MCP authentication
  resolves, never a peer id the caller passes), so a client with no trust
  row gets nothing; a subscription such a view creates is kept under that
  trust's peer id, and nothing is pushed to it (a client's trust row has no
  endpoint: the client reads its diffs). On ``resume_subscriptions`` its
  next diff is a resync marker, served by ``GET /subscriptions/...`` with
  ``"type": "resync"``, the ``url`` to re-read (the subscription's target,
  or the one subtarget resumed) and empty ``data``: the client re-reads it
  under its own grant. **Check:**
  an application that served data to unapproved peers on purpose (the
  specification allows an unapproved ``associate``) approves them instead.
- **Callbacks were accepted without authentication, and a low-granularity
  callback made the receiver send the trust's secret to a URL of the
  sender's choosing.** ``/callbacks`` let any request through and checked
  the caller only after the subscription or permission it named was found;
  with a subscription id, anyone could inject diffs, store a peer's
  permission copy for any peer id, delete a subscription, or post a
  low-granularity callback whose ``url`` the receiver fetched with the
  trust's bearer. **Behavior change:** every ``/callbacks`` request is
  authenticated (401 with a challenge without credentials, 403 for
  credentials that match nobody); ``/callbacks/subscriptions/<peer>/<subid>``
  and ``/callbacks/permissions/<peer>`` admit only the peer they name (403
  for anyone else, the actor's creator and an ``admin`` peer included),
  before anything is looked up; a callback is accepted only for a
  subscription the actor made; a low-granularity diff is fetched from the
  trust's stored base URI, never from the callback's ``url``; only ``diff``
  and ``resync`` are accepted on the subscription branch (400); and the
  library's own hook names (``permissions``, ``subscription``,
  ``subscriptions``, ``www``, ``resource_*``) answer 403 on the generic
  branch. **Check:** a third party pointed at ``/callbacks/<name>`` without
  credentials now receives 401; ``FanOutManager`` no longer downgrades a
  payload over ``max_payload_for_high_granularity`` to a resource URL (a
  3.16 subscriber does not fetch it): it sends it in full and logs a
  WARNING; ``FanOutManager`` delivers only with
  the trust's secret, to ``<baseuri>/callbacks/subscriptions/<own id>/<subid>``
  under the trust's stored base URI (not a stored ``callback_url``); a peer
  trustee's Basic retry after a refused bearer cannot succeed on the two
  peer branches.
- **A peer could reach another peer's subscriptions, permissions and trust
  row through any access row that admitted it, application ``acl_rules``
  included.** Rows are matched by relationship and path prefix, and ``<id>``
  in a row is a literal, so a ``friend`` row on ``subscriptions/<id>`` (or a
  consumer's GET row on ``trust/<type>/<id>``) admitted a peer to every
  peer's rows: listing, reading, consuming, clearing and deleting another
  peer's subscription, reading another peer's permissions, and reading
  another peer's trust row with its secret. **Behavior change:** one rule
  binds a peer caller to the peer its path names on ``/subscriptions``,
  ``/permissions`` and ``/trust/<type>/<id>``, whichever row admitted it (an
  ``admin`` peer is exempt there); ``GET /permissions/<peer>`` authorises
  before the lookup, so an unknown id and another peer's answer the same
  403, and the creator and an ``admin`` peer may query any; ``GET
  /subscriptions?peerid=`` lists a peer's own rows; a peer on its own trust
  row cannot approve it or write its own permissions; the per-peer trust
  ``GET`` returns ``secret`` and ``verification_token`` only to the creator,
  the trustee and the peer the row belongs to (an ``admin`` peer no longer
  receives another peer's secret), and no peer changes another peer's base
  URI. An ``admin`` peer may still delete any peer's trust row, after which
  it can request a new one under that peer's id: grant ``admin`` only to a
  peer trusted as much as the owner (``docs/reference/security.rst``).
- **A trust request for an existing peer replaced its trust row.** ``POST
  /<actor>/trust/<relationship>`` upserted the row from the request,
  unauthenticated: a re-sent request reset the owner's approval and could
  change the relationship, and a request for a peer's id naming another base
  URI took over the row (base URI and secret) even when its verification
  failed. **Behavior change:** a request for a peer that already has a
  verified or approved row is accepted only with the trust's current secret
  as its bearer, and then swaps only the secret, in one write conditioned on
  the row still holding the secret the request authenticated with
  (relationship, approval, base URI and grants stay; the answer follows the
  stored approval; no ``trust_request_received``); anything else answers
  403 and changes nothing. **Behavior change:** a request carrying a bearer
  for a peer this actor holds no row for answers 403 ("No trust to
  re-pair") and creates nothing; the initiator pairs afresh, without the
  bearer, after removing its own row. A pending row is never re-paired: its holder's
  request is a creation request, which replaces it only if it verifies. A
  creation request is verified when the requester answers with its token
  from a relationship it approved (the one it created before sending the
  request) and its base URI's ``/meta`` names the peer id it claims; this
  proves control of the base URI, not of the id, since the requester answers
  both. **Behavior change:** a verification answered by a relationship the
  requester has not approved fails, and neither a pending row's own peer
  reading its status nor a 202 answer to a trust request or a re-pair
  carries its verification token: a third party could otherwise
  file a request at each of two actors under the other's id, with one
  secret, and each verification read the row filed at the other. **Behavior change:** with ``auto_accept_default_relationship``, only
  a request that verified is approved automatically; any other waits for the
  owner (202). **Behavior change:** an owner approves only a verified
  request, on every route (``PUT /trust/<rel>/<peer>`` and the web UI's
  Approve, ``TrustManager.approve_relationship``,
  ``modify_trust_and_notify``, ``TrustManager.modify_trust``):
  ``approved=True`` is written only to a row stored verified (or approved
  already, so approving it again changes nothing). Approving an unverified
  request first repeats the verification (a GET to our own trust row at
  the requester's base URI with the request's secret, answered by a row
  the host approved, and its ``/meta``; each verification, its GET and its
  ``/meta`` together, follows no redirect, reads at most 64 KB per answer
  and gives up after 15 seconds in all, its connection, over TLS or through
  the environment's HTTP(S) proxy, shut down then; a SOCKS proxy is not
  used, and with all eight verification workers busy a verification is
  refused at once); one that fails is refused (403 on the PUT, with a
  JSON ``error``, or a page with a way back for the web UI's form, whose
  trust page marks such a request "unverified" and offers no Approve). A
  PUT for a missing row answers 404, and one that approves a pending row
  and changes its base URI answers 400. An approval lands only on the row
  it was decided for, and the peer is told only when it landed. **Behavior change:** ``Trust.modify``,
  ``TrustManager.modify_trust`` and ``Actor.modify_trust_and_notify`` take ``approved``, ``verified`` and
  ``peer_approved`` as a bool or ``"true"``/``"false"``; any other value
  (``1``, ``"yes"``) raises ``ValueError`` instead of being stored as
  True. A stranger's request under a real
  peer's id and base URI could otherwise be approved by one click. A peer
  that does not support verification is paired by the owner creating the
  trust toward its URL. A pending row (stored unverified and not yet approved) is
  replaced only by a request that verifies; a re-pair never marks a row
  verified. A trust modification writes the attributes it is given, and
  only those, on a row that still exists (DynamoDB saved the whole loaded
  row, so a request authenticated just before a re-pair could write the old
  secret back). An
  initiator whose re-pair answer is lost asks the peer with the new secret
  before giving up; the per-peer trust ``GET`` answers the row's own peer
  while the owner has not approved it (202 with the row, as the spec's
  "pending"), where it answered 403.
  A new row is written conditionally on both sides, so a request racing
  another never replaces its row, and an initiator whose request failed
  removes only the row it wrote. The library's initiator re-pairs a peer it
  already trusts with its current secret, only toward the stored base URI,
  and stores the new secret only after the peer accepts. **Behavior
  change:** toward a peer whose verified request waits for approval,
  creating the trust (``POST /trust``, the web form or
  ``TrustManager.create_relationship``) approves it, tells the peer and runs
  ``trust_fully_approved_local``, not ``trust_initiated``, where before
  3.16 it overwrote the row with the owner's secret and sent a new request;
  a pending request that never verified (anyone can file one under a
  peer's id) is verified again first (a genuine request whose first check
  timed out is then approved), and otherwise replaced by the owner's own
  request, with the owner's secret, never approved as it is. The trustee
  path (``create_peer_trustee``) and a replaced request run no hook. A replaced pending row takes the
  replacement's creation time on both backends. **Check:** an actor id
  is self-asserted, so a host running its own server can still be verified
  (and, with auto-accept, approved) under another actor's id, which then
  blocks the real peer; its owner removes the row with ``DELETE
  /trust/<rel>/<peer>?notify=false``, and an application that cannot
  afford that leaves auto-accept off. A peer that moved is re-pointed by
  its owner (``PUT /trust/<rel>/<peer>`` with
  ``baseuri``), or moves its own row the same way, accepted only when the
  new base URI's ``/meta`` names it (400 otherwise); when one side removed its row locally, the other side's
  owner removes its own before they pair again (migration guide).
- **A subscriber could post callbacks to its publisher under its own
  subscription id.** The receiver looked the subscription up by peer and
  id without checking which side made it. **Behavior change:** 403.
- **A permission callback with a far-future timestamp blocked every later
  permission update.** Later updates looked older and were ignored.
  **Behavior change:** a timestamp more than five minutes ahead of the
  receiver's clock, or one that does not parse, answers 400. A callback
  older, by the sender's own clock, than the sender's last callback changes
  nothing (no deletion of revoked data, no sync, no hook); a stored copy
  carries the receiver's clock in ``fetched_at`` and the sender's timestamp
  in ``extra_attributes["sender_timestamp"]``, so a copy fetched by query
  never makes a slow sender's callback look older. Every write of a stored
  copy, a callback's or a query's, is a conditional write over the row it
  read, so two writers handled at once never both win: a losing callback
  decides again against the winner's row, and a query result older (by
  ``fetched_at``, stamped before its fetch began) than the stored copy is
  not stored; a copy stored from a query keeps the last callback's sender
  timestamp, so an older callback stays older. Peer data a losing callback
  deleted and the stored copy grants is fetched again from the granting
  peer (best effort; a failure is logged). A callback that would revoke but
  is older than the last one (two sender instances whose clocks differ) is
  checked against the peer's current permissions, which are then stored
  and their revocations applied (logged at WARNING). A callback without a
  timestamp keeps the last one's.
  **Behavior change:** after five lost races in a row, or on a storage
  fault, a callback answers 503 with ``Retry-After``, and the library's
  sender resends a 503 up to twice with the same body (``Retry-After``
  honoured up to 2 seconds; the synchronous sender waits 1 second, and
  logs a final failure at WARNING); a failed permission query no longer
  replaces the stored copy. Any other failure while handling a permission
  callback (a deletion of revoked data that fails) answers 503 too, so the
  sender resends it, at most twice, also when the failure would repeat. A
  copy stored without ``fetched_at`` (written before 3.16) is not read as
  newer: data a refused callback deleted stays deleted until the next
  permission change or query. ``PeerPermissionStore.store_permissions``
  compares against the database, not the process's cache, and raises
  ``DbError`` on a fault.
- **Peer and client views listed every peer's subscriptions.**
  **Behavior change:** ``view.subscriptions.all_subscriptions``,
  ``outbound_subscriptions`` and ``inbound_subscriptions`` list the
  accessor's own; owner mode is unchanged.
- **State written before 3.16 survives the upgrade, and trust rows replaced
  before it cannot be detected.** **Check:** after every instance runs 3.16,
  run ``actingweb-peer-state report`` and ``prune --apply``, then restart
  (``ADDED``); a deployment that suspects a replaced trust deletes it and
  pairs again, which rotates the secret.

- **PyJWT 2.15 is the minimum, and the lock moves past every open advisory.**
  The SPA ``jwt_bearer`` grant decodes the unverified assertion
  (``verify_signature=False``) to check its issuer before validating it.
  Below 2.15, PyJWT can be driven into a ``RecursionError`` while parsing
  that payload, and it accepts OKP keys whose public and private halves
  disagree. **Behavior change:** ``pyjwt`` must be ``>=2.15,<3``; an
  application that pins an older version fails to resolve. The lock (CI,
  docs and the demo) moves to these versions:

  - ``certifi`` 2026.10.23, which drops the emSign roots with compromised
    intermediate CAs;
  - ``urllib3`` 2.8.0;
  - ``oauthlib`` 4.0.1 (its breaking changes and fixed advisories are on
    the provider side, which the library does not use);
  - ``werkzeug`` 3.1.9, ``mako`` 1.4.3 and ``setuptools`` 84.2.1;
  - ``filelock``, ``virtualenv`` and ``python-discovery`` (1.6.0 to
    1.9.4, a ``virtualenv`` dependency), used only in development.

  **Check:** a deployment that resolves its own dependencies upgrades
  ``certifi`` and ``urllib3`` as well, since the library's constraints
  already allow the fixed versions. A deployment still on v3.15.1 runs the
  same unverified decode with a ``^2.14`` floor, which already allows the
  fixed release: ``pip install -U "pyjwt>=2.15"`` closes the advisory there
  today, with no library upgrade.

- **A logout that raced a refresh of the same session could leave the
  session live.** ``/oauth/logout``, ``/oauth/revoke`` and the theft response
  sweep a refresh-token chain once. A refresh whose consume of the old token
  landed before that sweep minted its new pair after it, so the client got a
  working access and refresh token for a chain the user had just ended. The
  MCP ladder had the same window, and actor deletion swept SPA tokens with no
  fence at all. Now every chain revocation writes a chain-revoked marker
  (``spa_revoked_chains`` under the system actor, ``mcp_revoked_chains``
  under the user's actor, 300 s TTL) before its first read, and every
  rotation reads it after minting: when it is there the rotation deletes the
  pair it minted and answers ``invalid_grant`` (401 on the SPA endpoint, 400
  on ``/oauth/token``). Actor deletion bumps the session generation before
  its token sweep, so the rotation's generation guard does the same.
  **Behavior change:** a marker that cannot be written revokes nothing
  (the retry completes it), and a marker that cannot be read during a
  refresh deletes what was minted. Logout, ``/oauth/revoke`` and the SPA
  endpoint answer either with 503 and ``Retry-After``; ``/oauth/token``
  answers 500 ``server_error``, its existing answer to a token-store fault
  (the theft response there writes a marker too). A refresh now
  reads one more row (DynamoDB 3 to 4 reads, PostgreSQL 2 to 3), and a
  refused rotation deletes its two rows instead of sweeping the chain
  again. On PostgreSQL ``delete_expired`` raises ``DbError`` on a fault
  instead of answering 0; the library's callers fold it, the token purges
  with a WARNING and ``actingweb-deletions`` with a printed line.
  **Check:** on DynamoDB, native TTL on the attributes table reaps the
  marker rows as it reaps tokens; without it both marker buckets grow by one
  row per revocation.

- **Disconnecting an OAuth2 client disabled it for every user.** Deleting a
  trust row of an MCP client (the trust page, ``TrustManager.delete_relationship``,
  an actor's deletion or adoption) deleted the client itself, with the
  actor passed as its owner. ``delete_client`` kept that actor without
  comparing it with the client's registration and deleted the client's
  global index row, so the client stopped authenticating for every user
  connected to it. A user who knew a client id could do this on purpose:
  authorize the client as themselves, then delete their own row. Now a row
  deletes the client only when the client is registered under that row's
  actor. Otherwise it revokes that actor's tokens for the client before the
  row goes, then deletes that actor's other rows of it, and the registration
  and every other connection stay. ``delete_client(client_id, actor_id=...)``
  refuses an ``actor_id`` the client is not registered under, and the new
  ``delete_client_connection(actor_id, client_id)`` ends one connection.
  The same change closes these gaps on the deletion path:

  - a fault in that cleanup is raised (503 through the integrations)
    instead of logged under a 204 while the client stayed live. The
    revocation, the owner's client deletion, the provider-token delete and
    the deletion of that actor's other rows of the client run before the
    row goes, so their faults leave the row in place, and deleting the same
    row again finishes them: ``TrustManager.delete_relationship``, and
    ``DELETE /<actor>/trust/<rel>/<peer>``, which calls the same deletion
    while the row exists (a retry answered 404 with the other rows left). A row an earlier row's cleanup already
    removed no longer fails an actor's bulk trust deletion, and any error
    deleting the client's other rows, or a refusal with the row still
    there, is raised as well;
  - the owner's client deletion from a trust row stops with ``DbError``,
    the row kept, when the token store cannot list every token, instead of
    deleting the client with access tokens left to expire. A client counts
    as deleted only when its index row and its row are both confirmed gone,
    in that order (one of them was enough, and a client row left behind
    stayed listed but could not be deleted); its owner's
    ``OAuth2ClientManager.delete_client`` finishes a client whose index row
    already went. A client row in an actor's bucket whose index row names
    another actor (copied or restored) is ended as a connection: every
    deletion of that actor's row refused it, so the row could never go;
  - a row from before ``established_via`` (3.4) belongs to a client when
    it has no baseuri or this actor's own, compared by its ``/<actor_id>``
    suffix, so a row written before the fqdn or protocol changed is still
    the client's; client deletion and the MCP client-credentials lookup no
    longer take such a row with a peer's baseuri for the client's;
  - a legacy ``oauth2:<email>:<client_id>`` row, which authorises, ends its
    connection too (it cascaded nothing), and a tagged row is routed by its
    ``oauth_client_id``;
  - every token chain the revocation reaches is marked revoked before its
    tokens go, so a refresh that raced the deletion deletes what it minted;
  - a trust row's custom permissions are deleted after the row, not before
    (a fault in between left a live row on its trust type's defaults, which
    can be wider), always (a "none" the permission cache held from before
    another process wrote them skipped the delete), and the next row
    created for the same peer id starts without them (an OAuth2 login, or a
    peer's trust requested and approved again; a request over a live row
    keeps them);
  - the provider tokens an OAuth2 login stored for the row
    (``oauth_tokens:<peer_id>``, Google's refresh token among them) are
    deleted with it.

  **Behavior change:** disconnecting a dynamically registered client (from
  ``/oauth/register``, registered under the system actor) no longer deletes
  its registration; the client must authorize again to reach that user.
  ``delete_client`` with the user's actor id for such a client answers
  ``False``. **Check:** code that called the registry's ``delete_client``
  with a user's actor id to remove a client it did not register uses
  ``delete_client_connection`` instead. **Behavior change:** the registry's
  ``delete_client`` answers ``False`` when only one of the client's two
  rows is confirmed deleted; a retry with the owner's ``actor_id`` finishes
  it. **Behavior change:** an MCP client-credentials token for a pre-3.4
  trust row with a peer's baseuri no longer authorises; such a row was
  never written by the library's OAuth2 flows.

- **An unauthenticated ``POST /`` could squat an address, and the address
  owner's first OAuth login adopted the squatter's actor with the squatter's
  credentials still live.** The actor factory creates an actor for any
  address nobody has claimed, with a passphrase of the caller's choosing.
  When the owner later signed in with OAuth, ``lookup_or_create_actor_by_identifier``
  returned that actor as theirs: the passphrase still opened it, and so did
  any trust relationship made with it (including an ``admin`` trust to the
  squatter's own actor with a secret the squatter chose), any subscription,
  and any property the squatter had prefilled. Every creation path now
  records how the actor came to exist (``auth_method`` in the ``_internal``
  store, written before ``actor_created`` fires), and a sign-in that proves an
  address over an actor nobody vouched for no longer inherits it. An actor
  counts as *vouched* when ``auth_method`` is a non-empty value other than
  ``factory``, ``email_unverified`` or ``creator_changed`` **and**
  ``email_verified`` is not ``"false"``. For an unvouched actor the sign-in either **replaces** it (an
  actor created through ``POST /``, marker ``factory``, is deleted through the
  tested wipe and a fresh actor is created: the owner gets a new actor id and
  ``actor_created`` fires again) or **cleans it in place** (every other
  unvouched actor, which may belong to its legitimate creator, keeps its id
  and its properties; its passphrase is rotated and every trust
  relationship, subscription, SPA session, MCP token, registered OAuth2
  client, peer-trustee row, stored provider token and ``trustee_root`` is
  removed, and its stored ``email`` is set to the proven address (the
  provider's email for a provider-id creator such as ``apple:…``), then it is
  marked vouched). A replacement also deletes every other ``factory`` actor
  with the same creator, a sign-in to a vouched actor deletes the ``factory``
  actors beside it, and a lookup by creator prefers a vouched actor, then any
  other unvouched one, and takes a ``factory`` actor last, so a squatter's
  extra factory actors can neither split the owner's sign-ins over new actors
  nor leave the owner's own unvouched actor (and its data) behind a new one.
  The emailed verification link is an address proof too
  and runs the in-place rule before marking the address verified. Neither
  mode contacts a peer: the peer URLs on an unvouched actor were chosen by
  whoever created it, so the wipe skips the remote ``DELETE`` calls and keeps
  every local cleanup. The in-place rule rotates first, wipes second, re-reads
  the trust and subscription lists third and marks last; if the wipe cannot be
  confirmed the sign-in fails closed with an ERROR log and the actor stays
  unvouched, so the next sign-in retries. Every read the rule acts on must be
  answered by the backend: a marker, list or session bucket that could not be
  read fails the sign-in closed instead of passing for "nothing there" (with
  the fault contract below, a fault raises ``DbError`` and the sign-in
  answers 503), so a database blip neither wipes a vouched actor nor marks a
  half-wiped one vouched. The writes and deletes it relies on are confirmed
  the same way: the marker is read back after it is written (an actor whose
  marker did not land is removed again at creation, and a clean whose marker
  did not land fails the sign-in), and the session revoke confirms each
  delete. With ``unique_creator`` off, the actors with the creator are
  listed with a strict read before anything is removed (with it on, the one
  holder is read through the creator record or unique row instead): a listing that
  faults or misses the actor being replaced, or a listed actor that cannot be
  read, fails the sign-in with every actor still in place, and a new actor is
  created only when the read says none is left. A replacement that stopped part-way
  (its tombstone written, its row still there) is finished by the next
  sign-in. **Behavior change:** an actor created before 3.16 other than by the
  provider sign-in buttons (the factory, the email form, ``Actor.create``, the
  MCP OAuth server) has no marker; the sign-in buttons already wrote
  ``<provider>_oauth2``. The MCP OAuth server's actors are real accounts whose
  address the provider proved, so an application with MCP sign-ups must mark
  them before upgrading. An unmarked actor's first address proof after the
  upgrade cleans it in place
  (new passphrase, no trusts, subscriptions, sessions or registered OAuth2
  clients, so MCP connectors must reconnect; data kept), and an actor created
  through ``POST /`` after the upgrade is replaced at its first address proof
  (new id, data gone). The emailed verification link ends the sessions of the
  actor it verifies, so the user signs in again after the click; a user whose
  provider supplies no verified address cannot do that yet, since the
  free-text form answers ``409`` for an address that already has an actor (as
  before 3.16), and must sign in through a provider that supplies the address.
  The same ``409`` locks such a user out while the factory is open, since
  anyone can ``POST /`` their address first (also older than 3.16); closing
  the factory removes that path.
  Install 3.16
  and run ``actingweb-mark-actors-vouched`` before the application serves its
  first sign-in to mark actors you know are legitimate;
  ``docs/migration/v3.16.rst`` has the details. **Known
  limitations:** a provider access token or ``oauth_token`` cookie matched by
  email in ``auth.py`` does not adopt; unvouched siblings other than
  ``factory`` ones (``unique_creator`` off) are cleaned only when a sign-in
  resolves to them; a vouched actor carrying a deletion tombstone written
  before 3.16 (one that records no reason: a ``DELETE /<id>`` that stalled,
  or a create whose tombstone clear faulted) is returned as it is, since a
  stale tombstone must not wipe a live actor (one written by 3.16 is
  finished, see "A stalled deletion" under CHANGED); one
  sign-in deletes the actor it replaces, if any, and (``unique_creator``
  off) at most 10 ``factory`` actors beside it (each is a full wipe inside the request), so a squatter
  who created more is cleared over several sign-ins; with ``unique_creator``
  off, two concurrent first sign-ins may
  both run the rule and fire ``actor_adopted`` twice (a replacement reuses a
  successor the other already created, which narrows the race to two adjacent
  statements; with it on the database refuses the second, see CHANGED); and ``devtest`` must be
  off in production, since it lets a caller rewrite ``_internal``. Close the
  factory with ``with_open_factory(False)`` for an OAuth-only deployment.
  An actor about to be cleaned in place (no marker, or an unvouched one)
  whose deletion status cannot be read answers 503 too and is left as it
  is, so a half-wiped actor is never cleaned and kept tombstoned. The clean
  revokes the actor's tokens again after its client registrations are
  removed, so a token issued before the client was removed does not outlive
  the clean, and a grant that straddles the two revokes mints nothing (the
  session generation, below). A vouched sign-in writes the proven address into ``store.email`` when
  it is missing (the creator when it is an address, else the provider's
  email), with one atomic create that never overwrites a stored value:
  a fault in the create's seeding left it out, and an actor vouched without
  the OAuth create (``mark_actors_vouched``, an application) may never have
  had one. ``actor_created`` is not fired again. **Behavior change:** with
  ``force_email_prop_as_creator`` on, such an actor's creator is pinned to
  that email from then on, so ``PUT /<id>/trust/trustee`` to any other
  address than it or ``trustee`` answers 400, as it already did for actors
  with a stored email.

- **Renaming one's own actor to someone else's address handed it to them,
  vouched, at their first login.** ``PUT /<id>/trust/trustee`` lets the
  actor's creator set any new ``creator``, and nothing checks that the caller
  owns the new address. Before this release that made no difference next to
  the open factory; with the adoption rule above it was the remaining way to
  squat: sign in with your own account (a vouched actor), rename it to the
  victim's address, and their first sign-in returned it with your passphrase,
  sessions and trusts live. A creator changed through that endpoint now marks
  the actor ``creator_changed``, which is unvouched, so the first sign-in that
  proves the new address cleans it in place. The marker is written, and
  confirmed, before the creator changes; if it cannot be, the request answers
  500 and the creator stays; a creator change that fails after it also
  answers 500, with the previous marker restored once a fresh read shows the
  creator unchanged. A vouch is bound to the address it proved: every
  vouched marker is written with that address (``vouched_creator`` in the
  actor's ``_internal`` bucket), and an actor whose creator changed since
  reads as unvouched, whatever order concurrent writes land in. Without it
  two concurrent renames by the actor's own creator, or a rename during the
  first sign-in's clean-in-place, could leave the actor vouched under an
  address nobody proved (with ``force_email_prop_as_creator`` off, or no
  stored email). An actor vouched before 3.16 has no recorded address and
  is judged by its marker alone until a sign-in or ``mark_actors_vouched``
  writes one. ``ActorInterface.modify_creator`` without ``unvouch`` moves
  the recorded address with the rename (the application vouches for it): it
  writes the new address as ``vouched_creator_pending`` first and promotes
  it after the rename, so a sign-in during a rename finds the actor vouched
  under the old creator and the new one, for an email or a provider-id
  creator alike. A fault writing the pending address refuses the rename
  (False). The rename reads ``_internal`` afresh, and when the current
  creator is vouched only through its stored email (a provider-id creator
  that ``force_email_prop_as_creator`` moved to the email) it first records
  the current creator as the vouched address, refusing (False) on a fault,
  so the moves below never leave it unvouched. It answers True once the creator is renamed, also when moving
  the recorded address afterwards faults (logged; the pending value keeps
  the new creator vouched). **Behavior change:** with
  ``force_email_prop_as_creator`` on, a vouched rename to an address moves
  the stored email to the new address first, and writes one when there was
  none (a sign-in seeding a missing email from the old creator would
  otherwise move the creator back at the next load). Since every
  load moves the creator to the stored email, that write commits the
  rename: a ``DbError`` after it leaves the rename to complete at the next
  load (or when the call is repeated), and a rename that loses because a
  load already moved the creator counts as renamed. The email is put back
  only when the rename definitely did not land (``CreatorTaken``, or a
  fresh load still showing another creator), and only while it still holds
  the new address; logged when it cannot be. Before, the next load rewrote
  the creator back to the old stored email, undoing the rename.
  Such a rename to a creator that is not an address is refused (False),
  since the load would undo it too. ``modify_creator`` (without
  ``unvouch``) refuses a rename when the actor's ``_internal`` bucket could
  not be read, in every configuration: unread, a vouched actor looks
  unvouched and its vouch would not move with it. Two concurrent renames of one actor share the one pending value,
  so a sign-in between them can still find it unvouched; serialise renames
  of one actor.
  The emailed verification link proves only the address it was sent to: an
  actor whose creator changed since answers 409, and the link stays
  unused. A restore after a failed change replaces only that change's
  ``creator_changed``, never a marker a sign-in wrote meanwhile. A
  ``factory`` actor keeps
  ``factory``, so it is still replaced, not cleaned. The endpoint reads the
  actor's ``_internal`` bucket first and answers 500 when it cannot, and a
  refused or failed change applies nothing else from the request
  (``trustee_root`` included). Two values keep the marker, because they hand
  the actor to nobody new: ``trustee`` (the protocol's handoff; no sign-in
  resolves to it) and the actor's own stored ``email``, which a provider or
  the emailed link wrote. **Behavior change:** an actor whose creator was
  changed over HTTP to another address is cleaned (new passphrase, no
  trusts, subscriptions or sessions; data kept) at the next sign-in by that
  address. With ``force_email_prop_as_creator`` on and a stored email, the
  endpoint refuses a ``creator`` other than that email or ``trustee`` with
  400: the creator is restored from the email on the next load anyway, and a sign-in
  for the new address in between resolved to this actor.
  ``ActorInterface.modify_creator`` and ``force_email_prop_as_creator`` do
  not unvouch: the application, or a provider-written email, vouches for
  those. A route of your own that passes user input to ``modify_creator``
  vouches for that address unless it passes ``unvouch=True`` (new), which
  applies the endpoint's rules.

- **Another site could sign a browser in through the email form.**
  ``POST /oauth/email`` checked no request's origin: a page on another site
  (a sibling subdomain included) could auto-post the submitter's own OAuth
  session id and an address from a visitor's browser, and the completed
  sign-up set the ``oauth_token`` cookie there, signing the visitor in to an
  actor of the submitter's choosing (login CSRF). A browser form ``POST``
  that the browser reports as started by another site (``Sec-Fetch-Site``
  other than ``same-origin`` or ``none``, else a foreign or ``null``
  ``Origin``, else a foreign ``Referer``) now answers 403 before anything is
  claimed, created, redeemed or mailed, and no request another site started
  gets a session cookie from this endpoint; a JSON client still gets its
  token in the body. **Behavior change:** a form on another origin that
  posts to ``/oauth/email`` is refused. **Check:** an application page that
  posts the email form from a different origin sends it as JSON instead.

- **A link on another site could delete the actor, approve a trust, or
  change a property for a signed-in owner.** Every REST handler honours a
  ``_method`` override on ``GET`` (``GET /<id>?_method=DELETE`` deletes the
  actor; ``/<id>/trust/<rel>/<peer>?_method=PUT&approved=true`` approves a
  pending trust; ``/<id>/properties/<name>``, ``/subscriptions``,
  ``/actions``, ``/methods`` and ``/callbacks`` likewise), and so does the
  web UI's property page. A browser sends the ``SameSite=Lax`` session
  cookie, which the Flask and FastAPI integrations turn into a Bearer
  header, and cached basic-auth credentials, on a top-level navigation
  started by any site. The web UI's ``POST`` forms had no origin check
  either (only the list item actions did, and only on ``Origin``).

  A ``GET`` with a ``_method`` override that carries an ambient credential
  (the session cookie, or basic auth, which browsers cache) now answers 403
  "Cross-site request refused" unless it shows it came from the
  application's own pages: ``Sec-Fetch-Site: same-origin`` when the
  browser sends the header (so ``none``, a link opened from a mail or chat
  client, is refused too), else a same-origin ``Origin`` or ``Referer``;
  without any of the three it passes, except when it carries the session
  cookie. A request with an explicit Bearer token and no cookie is not
  checked: another site cannot attach one. Every ``POST`` under
  ``/<id>/www`` answers 403 when the browser says it is cross-site
  (``Sec-Fetch-Site`` other than ``same-origin`` or ``none``, or a foreign
  or ``null`` ``Origin``, or a foreign ``Referer``). The Flask and FastAPI
  integrations no longer turn the ``oauth_token`` cookie into a Bearer
  header for a ``POST``, ``PUT``, ``PATCH`` or ``DELETE`` that the browser
  says another site, a sibling subdomain included, started, and drop a
  ``Basic`` Authorization header from such a request on every route except
  ``/oauth/token``, where it is an OAuth2 client's own
  ``client_secret_basic`` (the token endpoint now also reads a lowercase
  ``basic`` scheme). A browser sends the ``Lax``
  cookie on any same-site request and on a top-level ``GET`` from any site,
  and cached basic-auth credentials on any request; the drop is logged at
  INFO. This relies on the
  browser's ``Sec-Fetch-Site``, ``Origin`` and ``Referer`` reaching the
  application; a proxy that strips all three turns it off. "Same origin" is the scheme, host and port of
  ``config.root``; a base path does not matter. Peers and SPAs (Bearer
  tokens) are unaffected. The property creation form's ``redirect_to``
  now only redirects within the actor's own web UI (no other actor, no dot
  segments, no percent-encoding, no whitespace). **Limitation:** a
  cross-site request with cached basic-auth credentials and no browser
  headers at all (a browser without Fetch Metadata following a
  no-referrer link) cannot be told from ``curl -u`` and passes; prefer
  OAuth2 sessions for browser use. **Behavior change:** a page on another
  origin that posts to the web UI or links to a ``?_method=`` URL, and a
  browser link opened from outside the browser, now get 403; a form on a
  sibling subdomain no longer acts with the owner's session; a script that
  uses ``?_method=`` with the session cookie and no browser headers must
  send the real method instead.

- **A peer could plant script and links in the owner's web UI.** A trust
  request (``POST /<id>/trust/<rel>``, unauthenticated by design) chose
  the peer's ``id`` and ``baseuri`` freely, and the trust page put the id
  inside an inline ``confirm('...')`` handler, where HTML escaping does not
  protect a quote (the browser decodes ``&#39;`` before running it), built
  links from it unquoted (an id of ``../../<actor>`` turned Delete into
  ``GET /<actor>?_method=DELETE``), and the demo linked to the base URI
  (``javascript:`` or a ``?_method=`` URL on the same origin). The property
  pages did the same with property names. A peer's id must now be
  letters, digits and ``_ . : @ + = -`` (at most 255, starting with a
  letter or digit) and its base URI a plain ``http(s)`` URL with no user
  info, query or fragment, both when a peer asks for trust (400 "Invalid id
  or baseuri"), when a peer changes its base URI with ``PUT
  /<id>/trust/<rel>/<peer>`` (400 "Invalid baseuri"), and when this actor
  asks a peer (``create_reciprocal_trust`` returns ``False`` for such a URL
  or a peer id outside the shape); ``Actor.create_verified_trust`` refuses
  them too. The shipped templates put no value inside an inline handler
  (the confirm text is a ``data-confirm`` attribute), encode property names
  in their URLs (a name with ``?`` made a same-origin ``?_method=DELETE``
  link), quote the peer id in the trust page's links (a row whose id is
  only dots gets none), and the demo links to a peer only through
  ``peer_link``, set only for a valid base URI. The email-verification
  fallback page escapes the message and address. **Behavior change:** a peer whose id or base URI
  falls outside those shapes can no longer establish trust; ids the library
  makes for OAuth2 and MCP trusts are not affected. A custom template that
  interpolates a value inside ``onsubmit``/``onclick`` should move it to a
  ``data-`` attribute.

- **A provider address the provider had not verified could be the sign-in
  identity.** The sign-in took the provider's ``email`` whenever it was
  present, so an account at the provider whose address was never verified
  (Google can return such an address with ``verified_email: false``) signed
  in to the actor of that address, and a provider-id actor (``google:…``)
  had the address written into ``store.email``, which vouches for it and,
  under ``force_email_prop_as_creator``, renamed the creator to it at load.
  An address now counts only when the provider vouches for it: Google's
  ``verified_email`` (web userinfo) or ``email_verified`` (id_token) is
  true, Apple's signed id_token says ``email_verified`` true, or the GitHub
  address is in the token's verified ``/user/emails`` list. An absent claim
  counts as unverified, and the address Apple posts in its form_post
  ``user`` payload is never verified. The rule is applied where the user
  info is built, so bearer-token authentication, the stored ``email`` and
  the email seeding follow it too. **Behavior change:** a user whose
  provider address was never verified signs in to a new provider-id actor
  (or is asked for an address, with ``force_email_prop_as_creator``)
  instead of the address's actor, and a bearer token for such an account no
  longer authenticates as that address; a WARNING naming the provider and a
  redacted address is logged each time. An unverified address reaches
  ``oauth_success`` as ``user_info["unverified_email"]``, not ``email``. A
  GitHub sign-in whose ``/user`` carries an address now makes one
  ``/user/emails`` request (memoised per token for 30 seconds). **Check:**
  ``docs/migration/v3.16.rst`` says how to re-link an affected user.

- **A token minted after the clean in place could outlive it.** The clean
  revokes the actor's tokens before and after it wipes the relationships, so
  a grant that loaded its credential before the clean and wrote its token
  after the second revoke kept a live token for whoever held the actor
  before. The clean now writes a new session generation first, and every
  MCP authorization code, MCP refresh token, SPA refresh token and MCP client
  registration records the generation it was issued under; the clean
  writes another one before its second revoke (and removes the client
  registrations made during it), so a code or client issued while it ran
  mints nothing either. The code
  exchange, the refresh grants and the client-credentials grant compare the
  stamp after writing the new token and revoke it on a mismatch
  (``invalid_grant``); a read fault answers 503 (an authorization code is
  spent by then, so the client restarts the authorization). The SDK's
  ``ActorInterface.oauth_clients.generate_access_token`` passes its
  client's stamp the same way. A credential issued before
  3.16 has no stamp and works only on an actor never cleaned since. The
  window is closed within the issuing process: another worker can keep
  serving an access token it cached for up to its cache lifetime (five
  minutes).

- **An emailed verification link could be confirmed by whatever fetched
  it.** ``GET /oauth/email?verify=<token>`` verified the address on the
  spot, so a mail scanner or link preview that fetched the link confirmed
  an address nobody read. **Behavior change:** the link opens a page with a
  Confirm button (JSON clients get ``status: "confirm_required"`` and the
  ``POST`` to make); ``POST /oauth/email`` with ``verify=<token>`` verifies.
  The confirm issues no session, and the token is consumed only once the
  verification has landed, so a fault leaves the link usable. **Check:** an application template overriding ``aw-verify-email.html``
  must render the ``confirm`` state (a form that posts ``verify``).

- **A bearer token cached on another worker could bring a deleted actor
  back.** The MCP bridge created an actor for a token whose actor was gone,
  and with a caller-supplied id that cleared the deletion tombstone. It now
  refuses an id whose tombstone says deleted (401, as an unknown actor), and
  an unreadable tombstone answers 503.

- **A subscriber read changes its permissions exclude.** Diffs are stored
  whole. The pull paths (``GET /subscriptions/<peer>/<subid>`` and its
  ``/<seq>``) returned them unfiltered, so a ``friend`` peer with a narrowed
  grant read past it; the pushed callback filtered a whole-target diff per
  key but sent a subscription's single value (a subtarget's) unfiltered,
  and neither checked a subscription's resource. **Behavior change:** one
  filter for both paths: a subscription to one property (a subtarget, and
  a resource under it) carries its value only when the peer may read
  ``<subtarget>`` (``<subtarget>/<resource>``), the path a direct read
  checks, and without a resource it drops each key of an object that an
  exclusion names as ``<subtarget>/<key>`` (a resource-level write reaches
  such a subscription as ``{resource: value}``); a whole-target diff is
  filtered per key. A diff the peer may read
  none of is not pushed and is pulled as ``{}`` (a no-op change, its
  sequence kept). The filter follows the peer the path names, whoever
  reads (the creator or a trustee reading a peer's subscription sees what
  that peer may read). Other targets are served as stored, as their
  callbacks are.

- **A trust delete could remove the row a re-pair had just written, and a
  deleted grant left the peer believing it still held it.** ``DELETE
  /trust/<rel>/<peer>`` deleted whatever row the peer id named when the
  delete ran: a re-pair landing between the request's read and its delete
  lost its new row, with its subscriptions, grant and OAuth2 client. ``DELETE
  /trust/<rel>/<peer>/permissions`` sent the peer nothing, so the peer kept
  acting on the grant it was last sent, and answered 204 also when there
  was nothing to delete. **Behavior change:** the delete removes only the row
  it was authorised against (its secret is compared on a consistent read
  before the remote delete, again before the local cleanup, and by a
  conditional row delete); a row replaced meanwhile is kept and the request
  answers 404, and ``trust_deleted`` does not fire for it (it now fires
  after the last comparison, before anything local goes, on the REST route
  and when ``sync_peer`` finds a revocation, and not for a row another
  delete already removed; ``sync_peer_async`` does the same, awaiting a
  coroutine hook on its running loop, given up after 120 seconds, and
  running a sync hook off it). A re-pair landing after the second
  comparison keeps its row,
  but the cleanup that ran (the subscriptions, the peer's stored data) is
  gone; the peer's next sync re-creates the subscriptions. ``Trust.delete``,
  ``Actor.delete_reciprocal_trust`` (and its async twin) and
  ``TrustManager.delete_peer_trust`` take a keyword-only ``only_if_secret`` /
  ``expected_secret``; the store's ``DbTrust.delete`` takes
  ``only_if_secret`` and answers False for a row with another secret.
  **Behavior change:** deleting a grant override sends the permission
  callback with the peer's default grant for its trust type (through the
  same sender, with the same resends, as a ``PUT`` of the grant, and only
  when ``notify_peer_on_change`` is on); deleting a grant that does not
  exist answers 404 and sends nothing. ``TrustPermissionStore.delete_permissions``
  itself still sends nothing (its other callers delete the trust row with it
  or store a new grant next). **Check:** a peer receiving permission
  callbacks with ``auto_delete_on_revocation`` now sees a deleted override
  as a change to the default (see the revocation entry under FIXED for what
  that comparison acts on).

REMOVED
~~~~~~~

- **``Subscription.decrease_seq()`` is removed.** It rolled a subscription's
  sequence number back after a diff could not be stored, which could hand
  the number to a second change. A number whose diff is not stored now stays
  a gap (see the sequence-number entry under FIXED). Nothing in the library
  called it after that change; code that did should drop the call.

- **The legacy reverse-lookup mechanisms are removed.** Reverse lookup (find an
  actor by an indexed property value) now always uses the lookup table. The
  value-keyed ``property-index`` GSI path (``PropertyLegacy``,
  ``PropertyIndex``) on DynamoDB, the v1 ``<prefix>_property_lookup`` table
  and its read fallback (``PropertyLookup``, ``get_v1``), the unindexed
  ``properties`` value scan on PostgreSQL, ``Config.use_lookup_table``, the
  ``USE_PROPERTY_LOOKUP_TABLE`` variable, the ``use_lookup_table`` arguments
  of ``DbProperty``/``DbPropertyList`` and ``--legacy``/``--lookup-table`` on
  ``python -m actingweb.db.verify_tables`` are gone. **Behavior change:**
  ``ActingWebApp.with_legacy_property_index()`` now raises ``RuntimeError``
  (a tombstone, removed at the next major), and ``Config`` raises it for
  ``USE_PROPERTY_LOOKUP_TABLE=false`` and ``Config(use_lookup_table=False)``;
  the message names ``docs/migration/v3.16.rst`` and
  ``actingweb-property-lookup``. A true value is ignored with a
  ``DeprecationWarning``. **Check:** drop the setting, run
  ``actingweb-property-lookup report`` and ``backfill --apply`` before the
  deploy if the lookup table was never populated (see the entry under
  CHANGED), and, once verified, drop the old table and GSI; nothing reads
  them.

CHANGED
~~~~~~~

- **An MCP hook is handed an actor built for that request.** The MCP
  handler kept one ``ActorInterface`` per actor for five minutes and handed
  it to every request, so a hook read the row, ``_internal``, properties and
  the subscription list as an earlier request left them, and a subscription
  created in another process could go without diffs. **Behavior change:**
  every authenticated MCP request loads the actor row and gets a fresh
  ``ActorInterface``; values read through it are current. The first read or
  first write of each property, the first touch of ``_internal`` and each
  ``actor.services`` client cost a storage read per request; a warm MCP
  request reads the actor row, so a backend throttle answers 503 where it
  used to succeed from memory, and under FastAPI that read runs on the event
  loop for every authenticated MCP request. ``actor.creator`` is not
  re-synced to the stored email on an MCP request. The validated-token and
  trust caches stay (per process, 5 minutes; a resolved trust entry now
  expires after 300 seconds too), and the periodic debug line no longer
  reports actor hits. **Check:** hooks that read-modify-write a property on
  every call, hooks that keep the actor in a global (that recreates the old
  lifetime), and MCP clients that do not retry a 503
  (``docs/migration/v3.16.rst``, "MCP actors are built per request").

- **An ``Actor`` reads its subscription list once, an empty one too.** An
  empty list was read again on every subscription read, so the same instance
  saw a subscription created elsewhere as soon as it existed. **Behavior
  change:** an instance memoises whatever its first read answered; code that
  keeps one instance across many writes sees subscriptions created elsewhere
  only on a new instance. The instance reads again after its own creates and
  deletes, after a resume (``resume_subscriptions``), and after every call of
  the trust methods that can send a request to the peer
  (``modify_trust_and_notify``, ``create_reciprocal_trust`` and its async
  form), where the peer may subscribe back. A fault folded by
  ``strict=False`` is not kept. Every instance the library builds lives for
  one request, except the system actor, which has no subscribers.
  **Check:** code that
  holds an ``Actor`` or ``ActorInterface`` across requests and expects new
  subscribers to get its diffs.

- **Deleting an actor, purging its relationships and creating one under an
  explicit id touch the subscription stores.** **Behavior change:**
  ``Actor.delete()`` also removes every subscription diff of the actor (one
  delete by actor id, unread; the per-subscription diff reads are gone), a
  subscription a peer created during the wipe, and the actor's subscription
  suspensions (one delete), and raises ``DbError`` when the suspensions
  cannot be confirmed removed (the row stays and a repeated call finishes,
  as with any fault in the resumable delete); a missing suspensions table
  counts as holding none, on both backends. ``actingweb-deletions resume``
  removes the same for a deletion whose row is already gone. ``purge_relationships()`` removes the same diffs and suspensions
  and answers ``confirmed: False`` when it cannot. ``Actor.create(actor_id=
  ...)`` clears that id's suspensions once the row is written and raises
  ``DbError`` (the new row removed) when it cannot. **Check:** code that
  calls ``delete()`` or ``create(actor_id=...)`` without handling
  ``DbError``.

- **Breaking: a custom trust store and an ``Actor`` subclass take new
  keywords.** ``DbTrust.delete`` takes the keyword-only ``only_if_secret``
  (delete only the row with that secret; False for a row with another one;
  True when absent) and ``DbTrust.modify`` takes ``relationship``; the
  library passes them on every trust ``DELETE`` and an MCP client's
  re-authorisation at a new level. ``Actor.delete_reciprocal_trust`` (and
  its async twin) takes the keyword-only ``expected_secret`` and
  ``before_local_delete``, which the trust ``DELETE`` and ``sync_peer``
  pass, and the sync method the keyword-only ``_subscriptions``, which
  ``Actor.delete()`` and ``purge_relationships()`` pass on every call. A backend or subclass without them raises ``TypeError``.
  **Check:** custom backends and overrides accept the keywords (or
  ``**kwargs``); ``docs/migration/v3.16.rst`` ("Custom database backends").

- **Trust hooks fire once, with the same arguments, on every route.** An
  approval through ``PUT /trust/<rel>/<peer>`` or the web UI fired
  ``trust_fully_approved_local``, ``TrustManager.approve_relationship``
  fired ``trust_approved`` instead, and a repeated ``PUT`` with
  ``approved=true`` fired again; ``trust_deleted`` got the row as
  ``trust_data`` on some routes and an empty dict or no ``initiated_by_peer``
  on others. **Behavior change:** every approving route (``PUT`` and the web
  UI, ``approve_relationship`` and ``approve_relationship_async``,
  approve-on-create) fires ``trust_fully_approved_local`` once, on the
  transition to approved by both sides, with ``trust_data`` = the row; a
  repeat approval fires nothing. ``trust_approved`` is deprecated: it runs
  in its place, with the same arguments, only when no
  ``trust_fully_approved_local`` hook is registered, and registering it
  logs a warning once per process; an application that registered both now
  sees only the canonical one. ``trust_deleted`` fires before the delete on every route
  with the row as ``trust_data`` and ``initiated_by_peer``. A lifecycle hook
  without ``**kwargs`` raises ``TypeError`` on the arguments it does not
  name; that is now logged at ERROR naming the hook, once per process.
  **Check:** rename ``trust_approved`` hooks to
  ``trust_fully_approved_local`` and give every lifecycle hook ``**kwargs``
  (migration guide, "Trust hooks fire once, with the same arguments").

- **A ``PUT`` of a trust with new permissions writes the grant first.** The
  trust was approved and the peer told before the grant was stored, so a
  failed grant write left the peer approved on the grant it had.
  **Behavior change:** the grant is written first; a failure answers 500
  with the trust unchanged (unapproved, when the ``PUT`` approved it) and
  the peer not told. The peer is sent the new grant only once the trust
  write landed; when that write fails (404/400, or a store fault), the
  grant as it was is restored (or the new one deleted) and the peer is told
  nothing; when that restore fails too, the answer is 500 "Trust not
  modified; the permissions change could not be undone". **Behavior
  change:** a trust ``PUT`` body that is not a JSON object answers 400 (a
  scalar was a 500, a list an empty edit), and ``"permissions": null``
  changes nothing.

- **Breaking: an anonymous registration may not ask for
  ``client_credentials`` or a level the client list does not offer.**
  ``POST /oauth/register`` answers 400 ``invalid_client_metadata`` for
  either, names ``OAuth2ClientManager.create_client`` (which an actor's owner
  uses for such a client), and stores the default client type on the
  system actor. **Breaking:** ``client_credentials`` for a client registered
  that way is ``unauthorized_client``, also for one stored before 3.16.
- **The MCP authorize form is bound to the browser; otherwise the user
  confirms.** **Behavior change:** the form sets a nonce cookie
  (``__Host-aw_authz_nonce`` over https) and carries the nonce in a hidden
  ``form_nonce`` input (a custom template must add it, or every sign-in asks
  for confirmation) and in each provider link. A sign-in the library cannot
  bind shows ``aw-oauth-confirm.html`` (new, overridable) and completes on
  ``POST /oauth/authorize/confirm`` (new). The form, the confirmation and
  their JSON answers send ``X-Frame-Options: DENY``, ``frame-ancestors
  'none'``, ``Cache-Control: no-store`` and ``Referrer-Policy:
  same-origin``. A refused or failed confirmation is the same page with an
  ``error`` sentence for a browser (JSON for an API caller), with its
  status (400, 403, 500 or 503). **Behavior change:** an OAuth2 page (the
  form or the confirmation) whose template fails to render answers its JSON
  fallback with the handler's error status, else 500 (it answered 200).
  The form answers JSON for ``Accept: application/json``
  under FastAPI too (the header was matched case-sensitively). The Apple
  button on the form completes (its state was wrapped in JSON and never
  matched).
- **A client's level follows the user's latest approval.** **Behavior
  change:** a re-authorisation re-types the client's existing row (up or
  down); a client's permission override that names a type other than its
  row's is not applied and is deleted at authorisation (a removal that
  fails is logged and retried; it refuses only an approval of the
  override's own type, which would bring it back, or when the override
  cannot be read); the owner's edit of such an override replaces it with
  one holding only that edit (``PUT .../permissions`` then answers 201);
  the permissions views show only an override that applies; MCP caches of
  the process are evicted (other processes until their cache TTL). The
  default selected level is the client default (``mcp_client``), not the
  first registered type. **Behavior change**, for every trust: ``GET
  /trust/<type>/<peer>/permissions`` answers 404 when there is no row or
  ``<type>`` is not the row's type (it answered the override or the type's
  defaults). Rows a client obtained before 3.16 keep their type until it
  authorises again.
- **New:** ``AccessControlConfig.client_trust_type_acceptable()`` and
  ``default_client_trust_type()`` (and module functions of the same names in
  ``actingweb.permission_integration``); the ``oauth2_trust_requested``
  lifecycle hook (fails closed; may decline or lower the level);
  ``ActingWebOAuth2Server.complete_client_authorization()`` for a route that
  signs the user in itself; ``DbTrust.modify(relationship=...)``
  (keyword-only, both backends).

- **Breaking: ``shared_properties`` no longer returns
  ``excluded_properties``.** ``GET /trust/<rel>/<peer>/shared_properties``
  lists the names the peer may read (decided as a read; it asked for an
  operation no rule grants and listed nothing) and answers 403
  ``{"error": "not_approved"}`` for a trust not yet approved.
- **``/resources`` follows the ``resources`` grant.** **Behavior change:**
  GET is ``read``, PUT and POST ``write``, DELETE ``delete``; ``friend`` and
  ``partner`` lose DELETE and their excluded names, ``associate`` and
  ``viewer`` gain GET on ``public/*``. A ``resources`` override written for
  MCP URIs only now denies every ``/resources`` name for that peer.
- **A subscription needs read access to what it carries.** **Behavior
  change:** ``POST /subscriptions/<peer>`` answers 403 for a path the peer
  may not read; a whole-target subscription needs a rule that reads at least
  one name (or, with no rule for the category, the access table's GET).
- **Method and action routes use the request's method for the access
  table.** **Behavior change:** a grant that does not mention methods or
  actions is decided with the request's method (it was always GET); a
  stated rule (even empty) is the answer.

- **A permission refusal answers ``{"error": "forbidden"}``.** **Behavior
  change:** the 403 a peer gets from the property routes carries this body
  (``{"error": "not_approved"}`` for a trust not yet approved); a refused
  bulk ``POST /properties`` adds ``"refused"`` with the names it refused.
  It never says that an exclusion caused the refusal.
- **``POST /properties/<name>`` is 400.** **Behavior change:** it answered
  400 and then wrote the body as if posted to ``/properties``; post to the
  collection.
- **``execute_property_hooks`` answers a permission denial with
  ``PERMISSION_DENIED``.** **Behavior change:** a denied ``get`` used to
  return the value unchanged; it now returns
  ``actingweb.access_decision.PERMISSION_DENIED`` (falsy, distinct from
  ``None``) for every operation, and the handlers answer 403. A caller that
  runs property hooks itself with a peer in the context must check for it.
- **The access table is a pure function.**
  ``actingweb.access_table.access_table_admits`` and
  ``matching_access_row`` (also importable from ``actingweb.auth``) answer
  for a relationship without an ``Auth`` object;
  ``actingweb.access_decision.decide`` is the one decision the routes ask.
  ``PermissionEvaluator.evaluate_property_with_exclusions`` is removed
  (``drop_excluded``, ``holds_excluded`` and ``path_excluded`` replace it).

- **An access row authorises the method a request performs; a PUT or
  DELETE is no longer admitted by a GET row.** The subscription handler
  authorised ``PUT`` and ``DELETE`` on ``subscriptions/<id>/<subid>`` (and
  ``GET ?_method=PUT|DELETE``) as GET, so a row granting GET there let a
  peer clear queues and delete subscriptions. A peer's own subscription and
  trust row are admitted by the built-in ``owner`` rows, which now compare
  with the peer the path names (they never matched on these handlers
  before), so a subscriber type with only a GET row needs no new rows: it
  clears its own queue and is unsubscribed as before, and no other peer
  reaches it. The ``owner`` rows on subscriptions are now
  ``("owner", "subscriptions/<id>", "GET", "a")`` and
  ``("owner", "subscriptions/<id>/<subid>", "GET,PUT,DELETE", "a")``: a
  peer lists, polls, clears and ends its own subscriptions, as before, and
  never creates one through them (``POST /subscriptions/<peer>`` stays with
  the relationship's own rows). **Behavior change:** through the ``owner`` rows a peer of any
  relationship type also reads its own trust's permissions
  (``GET /trust/<rel>/<peer>/permissions``) and may ``PUT`` its own trust
  row (its description, and a base URI whose ``/meta`` names it; approving
  it and writing its permissions stay the owner's, 403). A ``PUT`` to
  ``/callbacks/<name>`` is authorised as PUT and reaches the hook as
  ``PUT``.
- **A peer of any relationship type reads its own granted permissions**
  (``GET /permissions/<peer>``), through the ``owner`` row; the creator and
  an ``admin`` peer read any. Before, only ``associate``, ``friend``,
  ``partner`` and ``admin`` could, and the creator could not.
- **A subscription callback for an unknown subscription id, from the peer
  the path names, answers 403** (was 404), as the specification says for a
  callback URI that does not exist with authentication data.

- **A create with the default creator loaded every actor left with it.**
  With ``force_email_prop_as_creator`` and ``with_unique_creator()`` on, each
  create whose creator was empty or ``creator`` listed every actor with that
  creator and loaded each one, so the load moved it to its stored email.
  **Behavior change:** a create no longer does this. ``actingweb-unique-creators
  report`` lists those actors under "default creator", and ``resolve
  --default-creator-to-email --apply`` moves each one to its stored email,
  keeping the email; once uniqueness is enabled, an address another actor
  holds is reported and left (before ``enable`` the check is a read
  followed by the rename, so a concurrent sign-in can still take the
  address; ``report`` then lists the pair). **Behavior change:** loading an
  actor moves its creator to its stored email only when the actor is
  vouched (a provider or the emailed link proved the address); an unvouched
  one, such as a factory create left with the default creator, keeps its
  creator until ``resolve`` or a sign-in's adoption moves it. **Check:** if
  you relied on the sweep or on the load, run the command once after the
  upgrade.

- **``GET /?format=json`` allowed credentialed cross-origin reads of a public
  document.** The factory's JSON configuration reflected the request's
  ``Origin`` together with ``Access-Control-Allow-Credentials: true``, on both
  integrations. Nothing in it depends on a cookie. **Behavior change:** it
  answers ``Access-Control-Allow-Origin: *`` and no
  ``Access-Control-Allow-Credentials``. **Check:** a cross-origin client that
  sends credentials on this fetch (``credentials: 'include'``, axios
  ``withCredentials``) is refused by the browser now; drop them for this one
  request. The SPA and email endpoints keep their configured CORS.

- **Breaking: a custom ``DbAttribute`` backend must implement
  ``create_attr_if_absent``** (the fourth custom-backend requirement of 3.16;
  the migration guide's list has it). ``delete_attr_conditional`` and
  ``conditional_update_attr`` keep answering ``False`` on a fault, and a test
  now pins that on both backends because single-use consumption depends on it.

- **Breaking: every SPA token-endpoint error answers a stable code.** The
  response carries ``X-ActingWeb-Error: <code>`` and the JSON body gains
  ``code`` beside ``error: true`` (``invalid_request``,
  ``unsupported_grant_type``, ``invalid_grant``, ``refresh_token_reused``,
  ``access_denied``, ``not_found``, ``server_error``,
  ``temporarily_unavailable``). The database fault handler's answers on the SPA
  and ``/oauth/*`` paths carry the header too, and their body (``error``,
  ``message``) gains the same ``code`` key on every route; a JSON body that is
  not an object (``[]``, ``null``) on ``/oauth/spa/token`` and
  ``/oauth/spa/authorize`` (and ``/oauth/revoke``), and a field those
  endpoints read as a string (``provider``, ``refresh_token``, ``code``,
  ``redirect_uri``, ``actor_id`` and the rest) holding a list or object, now
  answer 400 ``invalid_request`` instead of a 500 with no code (or, for
  ``refresh_token``, a 503 that blamed the store); and
  ``Access-Control-Expose-Headers`` on them now lists both ``Retry-After`` and
  ``X-ActingWeb-Error``. **Behavior change:** rule 7 of the SPA guide is now "a
  401 on refresh that carries the header is the library's and final; one
  without it is not". A gateway must pass the header through; the body ``code``
  arrives either way. The email endpoints keep their own ``code`` values.

- **Breaking: ``check_and_verify_auth()``, its async variant and ``Auth()``
  require ``config`` as a keyword-only argument.** Without it they raised
  nothing and built a default ``Config()`` (``devtest=True``, the demo host);
  now a call without it raises ``TypeError`` naming the argument, and one that
  passes it positionally raises ``TypeError`` too.

- **Breaking: ``/meta/actingweb/supported`` advertises what the application
  serves.** ``sessions`` and ``onewaytrust`` are dropped (no route; trust is
  always reciprocal), ``listproperties`` is added, ``www`` appears only when the
  web UI is on and ``oauth`` only when a provider is configured.
  ``Config.aw_supported`` is a read-only property computed on every read, so
  ``with_mcp()`` and the other builder calls cannot leave it stale; assigning
  to it raises ``AttributeError``. ``with_mcp()`` now applies its flag to the
  config immediately.

- **Breaking: a backslash in a permission pattern is an escape** (``\*``,
  ``\?``, ``\\``), so a pattern that contains one changes meaning. The
  peer-permission cache and the callbacks' property filters now use the
  evaluator's matcher instead of ``fnmatch``: no ``[seq]`` character classes
  and case-sensitive. See ``docs/guides/access-control.rst`` ("Pattern
  syntax").

- **Breaking: ``POST /mcp`` with a body that is empty or not JSON answers 400
  with JSON-RPC ``-32700`` before authentication.** It used to be treated as an
  empty request. A well-formed request without credentials still gets the 401
  challenge.

- **Breaking: ``DbProperty`` and ``DbPropertyList`` require
  ``indexed_properties``.** The constructors take a required, keyword-only
  ``indexed_properties: list[str]`` on both backends and read no environment
  variable, so a direct construction can no longer disagree with the
  configured set. ``actingweb.db.get_property`` and ``get_property_list``
  pass it. **Check:** custom code that built the accessors directly (and any
  custom database backend) gets a ``TypeError`` naming the argument.

- **Breaking: a custom ``DbPropertyLookup`` backend gains four readiness
  functions.** ``read_readiness(names)``, ``mark_backfilled(names)``,
  ``unmark(names)`` and ``record_configured(names)`` are module-level
  functions of the backend's ``property_lookup`` module (the startup check
  and ``actingweb-property-lookup`` call them). A missing table or any fault
  raises ``DbError``.

- **Behavior change: an indexed property write whose lookup row cannot be
  written fails with ``DbError`` (503) instead of succeeding.** Before, a
  DynamoDB write logged ``LOOKUP_TABLE_SYNC_FAILED`` and committed the
  property anyway, leaving a value that reverse lookup could never find (the
  legacy GSI had masked this for older deployments). Now the property, its
  lookup row and the old value's lookup row are one ``TransactWriteItems``
  and a fault raises with nothing written; PostgreSQL already rolled the pair
  back together. A value another actor already holds is still a logged
  ``LOOKUP_COLLISION``, not a failure. On DynamoDB an indexed write that
  changes the value is one consistent read of the property plus a
  transaction of two or three items (the property, the new lookup row, the
  old one), each billed at twice a plain write; non-indexed writes are
  unchanged. The IAM role needs ``PutItem`` and ``DeleteItem`` on both
  tables. A
  write that leaves an indexed value unchanged claims a missing lookup row
  (the value was stored during a collision and the other actor has since let
  it go), so the value becomes findable. On DynamoDB it writes nothing: one
  consistent property read plus one consistent lookup read; the claim, when
  needed, is a transaction
  conditioned on the property still holding the value and the actor row
  still existing, and a fault in it is
  logged as ``LOOKUP_HEAL_FAILED`` and never fails the write (the role needs
  ``ConditionCheckItem`` on the properties and actor tables, uniqueness on or
  off). On PostgreSQL the claim is
  an insert in the property's own transaction, so it fails closed like any
  indexed write: a fault rolls the write back with ``DbError``, and a write
  for an actor that no longer exists now fails on the lookup row's foreign
  key when no other actor holds that value's lookup row.
  ``DbPropertyLookup.create`` (DynamoDB) now raises ``DbError`` on a write
  fault instead of returning False, which only means a collision. The
  property write is conditioned on the value it read (DynamoDB: a condition
  on a consistent read; PostgreSQL: the row read ``FOR UPDATE`` inside the
  transaction), so two concurrent writers of one indexed property cannot
  leave the lookup row of the value that lost; deleting an indexed property
  releases the lookup row of the value stored at the delete, not the one a
  handle last read. A write that keeps losing to concurrent writers raises
  ``DbError`` after three attempts (``PROPERTY_WRITE_RACE_EXHAUSTED``).

- **Behavior change: ``check_ready()`` and ``integrate_*`` raise
  ``PropertyLookupNotReady`` for an indexed name that was never backfilled.**
  The startup check reads a per-name backfill-complete marker (reserved
  ``#meta#`` rows in the DynamoDB ``property_lookup_v2`` table, or the new
  PostgreSQL table ``property_lookup_backfill``) and the indexed-name set the
  last passing start saw. It refuses a name that has property data and no
  marker, or that was dropped from the indexed set for a deploy and restored,
  and it refuses a lookup table it cannot read ("could not be checked"). A
  store with no properties marks itself ready. ``check_ready()`` now
  pre-warms the DynamoDB tables first and runs this and the
  creator-uniqueness check together; when both refuse it raises
  ``StoreNotReady`` listing both. **Check:** an application that catches only
  ``UniqueCreatorNotReady`` should catch ``StoreNotReady`` (their common base
  class), or the combined refusal escapes it. A PostgreSQL deployment must
  run ``alembic upgrade head`` (revision ``f6a7b8c9d0e1``) before the deploy.
  A DynamoDB role that lists its actions needs ``dynamodb:BatchGetItem`` on
  ``<prefix>_property_lookup_v2``: the check reads the markers with one
  ``BatchGetItem`` at every start, and a role without it refuses to start
  with "could not be checked" (it was not needed before 3.16).
  An application that never uses reverse lookup calls
  ``with_indexed_properties([])``.

- **Behavior change: ``unique_creator`` defaults to on.** ``Config`` and
  ``ActingWebApp`` now default to creator uniqueness, with
  ``with_unique_creator(False)`` as the opt-out (the duplicate-tolerant
  adoption code stays for it). A deployment with duplicate creators refuses to
  start with ``UniqueCreatorNotReady`` until ``actingweb-unique-creators``
  ``report``, ``resolve --apply`` and ``enable --apply`` have run, or it opts
  out. A fresh deployment under ``integrate_*`` starts once (which creates
  the tables and stops), runs ``enable --apply``, and starts again; with no actors yet the refusal
  says exactly that. The consumer-visible shifts the flag brought, now the
  default: a held creator at ``POST /`` answers 403, ``PUT /trust/trustee``
  409, a store whose enforcement cannot be read 503, and DynamoDB actor
  creates, deletes and creator changes cost about 4-6 write units (the
  application's role needs ``ConditionCheckItem`` on the actor table).
  **Breaking:** ``BaseHandler`` requires ``config`` (a handler built without
  one raises ``ValueError``; the import-time ``Config()`` default would have
  built an enforced handler that never ran ``check_ready()``), and
  ``python -m actingweb.db.verify_tables`` lists the ``creators`` table unless
  given ``--no-unique-creator``. Its ``required_models()``,
  ``required_table_names()`` and ``verify_tables()`` take ``unique_creator``
  as a keyword only: a 3.15 positional ``use_lookup_table`` argument raises
  ``TypeError`` instead of being read as ``unique_creator``. The readiness check now reads one consistent
  item instead of calling ``DescribeTable``, so ``DescribeTable`` can still be
  dropped from the runtime role. Code that builds ``Config()`` and creates
  actors without ``integrate_*`` must call ``check_ready()``: without it,
  with uniqueness on and ``enable --apply`` not yet run, every actor create,
  including the OAuth2 system actor bootstrap, raises ``DbError``
  (``database error during actor create``, 503 through the integrations, and
  retrying does not clear it) on both backends, with an ERROR naming the
  missing or unbackfilled table, or the missing index, and the command. On
  DynamoDB a fault while reading the creators table's backfill item refuses
  the write too, with an ERROR naming the table, the fault and the
  ``dynamodb:GetItem`` permission it needs.

- **Breaking: ``with_unique_creator()`` is enforced by the database.** Before
  3.16 the flag made ``Actor.create`` list the creator's actors and refuse
  when there was one, a check-then-insert that two concurrent sign-ins or
  factory posts could both pass, and that nothing checked on a creator
  change. Now DynamoDB writes a ``<prefix>_creators`` record in the same
  transaction as the actor create and creator change (the old record is
  then released by a conditional delete, only if it still names the actor;
  a fault there leaves a record ``report`` lists), and PostgreSQL
  enforces the partial unique index ``ux_actors_creator`` (built by
  ``actingweb-unique-creators enable``, not by a migration). ``trustee``,
  ``creator`` and the empty creator stay shared. **Behavior change:**

  - The application refuses to start (``UniqueCreatorNotReady`` from
    ``integrate_flask``, ``integrate_fastapi`` or the new
    ``ActingWebApp.check_ready()``) until the database enforces the flag:
    run ``actingweb-unique-creators report``, ``resolve --apply`` and
    ``enable --apply`` first. A fault while checking refuses to start too:
    starting unchecked on DynamoDB, against an empty auto-created
    ``creators`` table, would let existing users' sign-ins create second
    actors. A process that builds ``Config()`` directly no longer creates
    that table, nor claims against one that is not backfilled (the table a
    refused first start leaves is empty), nor without the index on
    PostgreSQL: its enforced creates and creator changes raise ``DbError``
    until ``enable --apply`` has run. If your IAM policy
    lists tables by name, add ``<prefix>_creators`` first.
  - The factory no longer returns the existing actor to a caller who
    supplies its passphrase: a second ``POST /`` for a held creator answers
    403 "Creator already exists" whatever the passphrase (this also removes
    a passphrase-guessing oracle). Keep the id and URL from the first 201 and
    use basic auth on ``/<id>``, or sign in through OAuth.
  - ``ActorInterface.create`` and ``ActorInterface.modify_creator`` raise
    ``CreatorTaken`` for a creator another actor holds;
    ``PUT /<id>/trust/trustee`` answers 409 and applies nothing else from the
    request, and a route of your own answers 409 through the app-level
    handler. The factory keeps its 403.
  - On PostgreSQL the index answers ``CreatorTaken`` even with the flag off,
    so a rolled-back flag never fails silently; ``disable --apply`` drops it.
  - A sign-in that replaces a ``factory`` actor creates the successor first,
    moving the creator to it in one backend step, then removes the squatter:
    ``actor_created`` for the successor fires before ``actor_deleted`` for
    the squatter. There is no ranking and no sibling sweep with the flag on.
    A squatter mid-deletion is finished by the replacement; when its
    deletion status cannot be read the sign-in answers 503.
  - With ``force_email_prop_as_creator`` on, loading an actor whose stored
    email another actor holds leaves the creator as it is after one read of
    the record, instead of a refused rename and a WARNING on every load.
  - Two concurrent sign-ins for one identifier (a first sign-in, or two
    replacing the same squatter) both end on the actor the winner created,
    unless that actor carries no ``auth_method`` marker (a row an older
    process wrote): then the second answers 409.
    A new actor's ``auth_method`` marker is written before the actor row, so
    a sign-in never finds an actor still being created and takes it for a
    pre-3.16 one.
    A creator record whose actor is gone or holds another creator now is
    removed by the next sign-in for it, which then creates the owner's
    actor; it never signs anyone in to that actor.
  - ``report``, ``resolve`` and ``enable`` confirm what they list as damage
    with a consistent read, and a record they write commits only while the
    actor is as read, so they are safe against live traffic; ``resolve``
    points the record at the kept actor before it renames the others, and
    ``enable`` refuses while orphaned records or ``@`` addresses stored
    with capitals remain. ``disable --apply`` on DynamoDB deletes every
    record as well as the backfill-complete item; run it only once every
    process with the flag on has stopped.
  - **Behavior change:** a ``modify`` through a stale handle (another
    process renamed the actor since it was loaded) returns False on both
    backends, with or without the flag. On PostgreSQL this covers a creator
    change. On DynamoDB it covers a password change too, and a handle whose
    actor was deleted, or whose password was rotated since: the save used to
    write the handle's copy back, undoing the rename, the rotation, or
    re-creating the actor. ``PUT /<id>/trust/trustee``
    answers such a lost race with 409 instead of 500, and an actor deleted
    meanwhile with 404.
  - On DynamoDB with the flag on, the application's role needs
    ``ConditionCheckItem`` on the actor table (the sign-in's repair of a
    stale record checks the actor in the same transaction), and the role
    running the command does too.
  - Two applications sharing one actor table can no longer both bootstrap
    their system actors (``system``, ``oauth2-system``) with the flag on.
  - On DynamoDB an actor create, delete or creator change costs about 4-6
    write units instead of 1 (uniqueness is on by default; the opt-out keeps 1).

  **Check:** the migration guide's "Creator uniqueness" section has the
  rollout order (Step 0: ``report``, ``resolve --apply``, ``enable --apply``
  before the deploy) and the IAM grants (``ConditionCheckItem`` on the actor
  table); the demo application and ``actingweb_mcp`` run the flag on and
  need both before they serve 3.16, or they refuse to start. See the entry
  "Behavior change: ``unique_creator`` defaults to on" below.

- **Breaking: the factory form no longer redirects to an existing actor.**
  A form ``POST /`` for a creator that has an actor redirected to
  ``/<id>/www``, which told any caller which id an address has. It now
  redirects to ``/login``, with or without ``with_unique_creator()``.
  **Behavior change:** a form user with an actor signs in to reach it.

- **Breaking: creators beginning with ``#`` or containing ``#dup-`` are
  reserved, and so are ``system`` and ``oauth2-system``.** The factory and
  ``PUT /<id>/trust/trustee`` answer 400 for them, with or without
  ``with_unique_creator()``; ``Actor.create`` (so
  ``ActorInterface.create``) refuses the first two, and
  ``ActorInterface.modify_creator`` answers False for them (with
  ``unvouch=True``, for all four). The check is on the
  value as stored, so ``#DUP-`` in an address counts. The DynamoDB
  ``creators`` table keeps its metadata under ``#meta#…``,
  ``actingweb-unique-creators resolve`` renames a duplicate to
  ``<creator>#dup-<hash>``, and the system actors' creators must stay
  free for their bootstrap. **Check:** no real address or provider id has
  any of these forms.


- **Breaking: a custom database backend's ``DbActor`` takes
  ``unique_creator``.** ``actingweb.db.get_actor`` constructs it as
  ``DbActor(unique_creator=config.unique_creator)``, and ``create`` takes a
  keyword-only ``replace_holder``. With the flag set the backend must raise
  ``CreatorTaken`` for a second holder and implement
  ``replace_creator_holder``, ``get_creator_holder`` and
  ``release_stale_creator``
  (``actingweb.db.protocols.DbActorProtocol``). A backend that does not
  accept the argument fails at construction. See the migration guide's
  "Custom database backends".

- **Breaking: a custom database backend must implement
  ``DbSubscription.increment_seq()``.** The library allocates each diff's
  sequence number through it, as one atomic update that returns the new
  number (``None`` when the row is gone), instead of writing ``previous + 1``
  through ``modify(seqnr=...)``. The two built-in backends implement it. A
  backend without it fails with ``AttributeError`` at its first diff. See
  the migration guide's "Custom database backends".

- **Breaking: a database fault raises ``DbError`` instead of reading as
  "not found".** Before 3.16 PostgreSQL caught every query error and answered
  ``None``, ``[]`` or ``False``, and DynamoDB did the same on most single-row
  reads, so a throttle or a timeout looked exactly like absence, and a caller
  that acted on "absent" created, overwrote or deleted on a guess (the FIXED
  entries below list eleven). The fault contract is now the same on both
  backends and is stated in ``actingweb.db.protocols``: every ``get``,
  ``fetch``, ``get_by_creator``, ``get_bucket`` and reverse lookup raises
  ``actingweb.db.exceptions.DbError`` on a fault unless called with
  ``strict=False``; writes raise too; a delete through a loaded handle
  answers ``True`` when the row is gone, an already-absent row included;
  conditional deletes still answer ``True`` only when that call removed the
  row. ``Attributes.get_bucket()``/``get_attr()`` are strict by default
  (``strict=False`` folds), ``actor.store`` still never raises on a read and
  keeps ``loaded`` as its signal, and the property list container raises
  instead of reading a fault as an empty list. Both integrations register an
  app-level handler: a ``DbError`` that reaches Flask or FastAPI, from a
  library route or your own, answers **503** with ``Retry-After: 5`` and a
  fixed JSON body (``"error": "temporarily_unavailable"``); the exception text
  is logged, never sent. A cross-origin client can read the answer: it
  carries the SPA allowlist's CORS headers on the SPA routes, the wildcard
  set on the other OAuth2 endpoints, and a wildcard set without credentials
  on ``/``. It never carries a redirect or cookie the handler set before the
  fault. A backend error a retry cannot fix (a validation, size or
  constraint error) answers **500** without ``Retry-After``. An exception
  counts as the fault only when it is the ``DbError`` or was raised from one
  (``raise ... from e``); an error raised while a ``DbError`` was being
  handled, without ``from``, is a bug and answers **500**. **Check:** in your
  own routes and hooks let the ``DbError`` itself propagate: the app-level
  handlers and the hook runners match the type, so a wrapping exception
  answers 500 there (or, in a hook, is logged and dropped) whether or not it
  uses ``from``.
  ``CreatorTaken``, a new ``DbError`` subclass for a creator another actor
  holds, answers **409** (``with_unique_creator()`` raises it, see above).
  ``get_by_creator`` gains
  ``consistent`` (DynamoDB's per-row consistent re-read, no longer implied by
  ``strict``) and ``ids_only``. **Behavior change:** on DynamoDB, a
  ``get_by_creator`` call without ``consistent=True`` returns the rows as the
  creator index has them, which can lag a passphrase change or a deletion;
  it used to re-read each row consistently. Pass ``consistent=True`` where
  the answer decides something. **Behavior change:** a throttled DynamoDB or a
  PostgreSQL pool timeout that used to answer 401, 404 or an empty list
  answers 503; a sign-in that hits one answers 503 instead of a failed login,
  a token-store fault no longer signs a SPA user out, and a permission check
  whose override cannot be read answers 503 instead of denying (or, in the
  property, method and action handlers, falling back to the trust type's
  default access). **Behavior change:** the hook runners no longer swallow a
  ``DbError``: a hook (``oauth_success``, a property, method or action hook,
  a callback hook) whose own store read faults now fails the request with
  503 instead of being logged and treated as "no answer", which for
  ``oauth_success`` meant "accepted". Notifications fired after the work
  committed (``actor_created``, ``actor_adopted``, ``actor_deleted_complete``,
  ``trust_approved``) still log a fault and let the request succeed. A subscription callback whose
  storage write faults answers 503; the publisher does not retry, so the diff
  stays there for the subscriber's next poll or gap resync, which runs the
  handler again. Once the callback's handlers have run, a fault recording its
  sequence is logged
  and the callback answers as processed, so the handlers do not run twice.
  The two list maintenance tools (``migrate_property_lists``,
  ``verify_property_lists``) exit **2** when the actor list cannot be read,
  where they exited 0 with "No actors found". Check any
  ``except Exception`` around ``ActorInterface`` calls that treats a failed
  read as "absent", and any custom backend: it must accept ``strict`` and
  raise ``DbError`` (see the migration guide's "Fault contract").

- **``auth_method`` is now set before ``actor_created`` fires.** It used to be
  written after the actor was created, so an ``actor_created`` hook could not
  read it. Only ``auth_method`` moves; the other post-create properties are
  still written after the hook, as before. **Behavior change:** actors the
  library creates through ``POST /`` carry ``factory``, those created by an
  OAuth sign-in carry ``<provider>_oauth2``, by the self-asserted email form
  ``email_unverified``, by the MCP bearer path ``oauth2_bearer``, the system
  actors ``system``, and ``Actor.create`` / ``ActorInterface.create`` default
  to ``app``.

- **Breaking: ``actor_deleted`` and ``actor_deleted_complete`` also fire when
  a sign-in replaces a factory-created actor, with keyword arguments.** They
  used to fire only for the HTTP ``DELETE /<actor_id>``. A replacement passes
  ``reason="replaced_at_adoption"`` and ``replaced_by_identifier=<creator>``
  so a hook that mails "your account was deleted" or cancels billing can tell
  it apart. A hook written as ``def on_deleted(actor):``, the signature 3.15
  documented, raises ``TypeError`` on those arguments, which is logged and
  skipped, so its cleanup never runs for a replaced actor. **Check:** give
  every ``actor_deleted`` and ``actor_deleted_complete`` hook ``**kwargs``
  (``actor_deleted_complete`` gets ``actor_id`` and the same two).
  **Behavior change:** a replacement that fails mid-wipe is resumed by the
  next sign-in, a ``DELETE`` or ``actingweb-deletions``: ``actor_deleted``
  runs again only when it raised ``DbError`` the first time (then every
  registered hook runs again), and ``actor_deleted_complete`` is announced
  by the one finisher that holds the deletion's lease.

- **Breaking: the trust, subscription and peer-trustee list backends and
  ``DbActor.get_by_creator`` take ``strict``.** ``fetch(actor_id, *,
  strict=False)`` and ``get_by_creator(creator, *, strict=False)`` are part of
  the database protocols (``actingweb.db.protocols``); with ``strict=True`` a
  read fault raises instead of answering ``[]`` or ``None``, and
  ``get_by_creator`` leaves out an actor its index lists whose row is gone
  (DynamoDB's creator index is eventually consistent). Both bundled backends
  implement it. **Check:** a custom backend must accept the keyword.

- **Breaking: ``conditional_update_attr`` takes ``clear_ttl``.** The
  attribute backend protocol (``actingweb.db.protocols``) gains a
  keyword-only ``clear_ttl=False``: with it, the same conditional write
  removes the row's TTL, so the row never expires (ignored when
  ``ttl_seconds`` is given). A deletion tombstone written before 3.16 that a
  ``DELETE`` or ``actingweb-deletions resume`` now records as resumable uses
  it, so the record does not expire before its wipe is confirmed; it is
  passed only there, so a backend without it fails only that resume. Both
  bundled backends implement it. **Check:** a custom backend must accept
  the keyword.

- **The SPA ``refresh_token`` cookie lives on ``path=/`` only.** The OAuth
  callback's hybrid delivery set it on ``/oauth/spa/token`` and the refresh
  grant's rotation on ``/``, so ``/oauth/logout`` did not receive the
  callback's cookie (the refresh token stayed valid after a logout before
  the first refresh), and after a rotation a browser held two and sent the
  stale one to the refresh grant first. On FastAPI the split was hidden
  until now: its cookie copy dropped ``path`` and ``samesite``, so every
  handler cookie got ``/`` and ``Lax``. **Behavior change:** every setter
  writes ``refresh_token`` on ``/`` (the callback keeps ``SameSite=Strict``,
  the rotation ``Lax``) and expires the cookie on ``/oauth/spa/token`` in
  the same response; FastAPI now keeps every attribute a handler sets on a
  cookie (``path``, ``samesite``), as Flask always did. **Check:** an SPA
  that reads cookies by path, or a proxy that rewrites ``Set-Cookie``,
  sees the new attributes.

- **The email form's error pages answer their real status.** The Flask and
  FastAPI integrations rendered ``aw-oauth-email.html`` with status 200
  whatever the handler set. **Behavior change:** the "address has an actor"
  page answers 409, an invalid address 400 and a refused sign-in code 401;
  the verification result page's errors carry a Continue link to the app's
  root, so an invalid or expired link is not a dead end. A browser whose
  sign-in session is missing or expired (the form waits ten minutes) gets
  that error page with its Continue link (400) instead of the address form
  drawn again with the dead session; a JSON client still gets the error
  body. The sign-in errors on that page are titled for what happened
  ("Sign-in expired", "Sign in", from a new ``title`` template value), not
  "Email verification". **Check:** a front end that tests ``response.ok`` on
  these pages; a template overriding ``aw-verify-email.html`` renders
  ``title`` when it is set.

- **``Actor.delete`` returns a bool.** It returned ``None``; it now returns
  ``True`` when the backend reported no fault removing the actor row
  (PostgreSQL answers ``False`` on a caught fault; DynamoDB raises).
  **Behavior change:** none for callers that ignored the result.

- **``Actor.create`` returns ``False`` when it created nothing.** It returned
  ``True`` whenever it got past the unique-creator check, including when the
  backend refused the insert because the id was taken or the insert failed,
  and then fired ``actor_created`` and wrote ``trustee_root`` into the bucket
  of whatever actor held that id. It now returns ``False`` without a hook or
  a write, and ``ActorInterface.create`` raises; the ``Actor`` object is left
  unbound (``id``, ``handle`` and ``store`` are ``None``), so a caller that
  ignores the ``False`` cannot modify or delete the actor holding the id. The
  MCP bearer bridge loads the actor another request created first, when it
  carries its marker and no tombstone. If the ``auth_method`` marker
  does not land, only the new row is removed (a fixed id such as a system
  actor can own buckets older than its row), and the object is left unbound
  the same way. **Behavior change:** a create
  with a caller-supplied ``actor_id`` that is already taken returns ``False``
  (``ActorInterface.create`` raises). **Check:** code that re-creates a known
  id to "ensure" it exists must load it instead when ``create`` returns
  ``False``; the two bundled system actors do.

- **The factory's ``GET /`` no longer honours ``_method=POST``.** A GET with
  that parameter ran the create. A link prefetcher or an ``<img>`` on another
  site could create actors on an open factory. **Behavior change:** such a GET
  now answers like any other ``GET /``; post the form instead.

- **``Actor.modify`` takes a passphrase and returns the backend result.** It
  accepted only ``creator`` and returned ``True`` whatever the backend did.
  ``Actor.modify(creator=None, passphrase=None)`` now returns ``False`` when
  neither is given or the backend reports failure; DynamoDB raises on a failed
  save and PostgreSQL returns ``False``, so callers that must know treat both
  as failure. The in-memory values change only after the backend succeeded.
  **Behavior change:** PostgreSQL's ``DbActor.modify`` reports a zero-row
  update as failure. **Check:** code that ignored the return value is
  unaffected; code that relied on ``True`` for a vanished row is not.

- **The MCP OAuth2 server writes the same actor fields as the other sign-in
  paths.** ``_get_or_create_actor_for_email`` hand-rolled actor creation and
  wrote only the creator. It now delegates to the provider's authenticator, so
  the adoption rule applies to MCP sign-ins and a new actor gets
  ``created_at``, ``oauth_provider``, ``email`` and the marker; an existing
  actor has ``oauth_provider`` refreshed on every sign-in. **Behavior
  change:** actors created through the MCP OAuth2 server carry the same
  fields as those created by a web sign-in.

- **The two factory 403s carry a body.** The duplicate-creator 403 on
  ``POST /`` was empty; it now answers ``{"error": true, "status_code": 403,
  "message": ...}`` for JSON clients and renders ``aw-root-failed.html`` with
  ``error`` for form clients, as does the new closed-factory 403. The Flask
  and FastAPI form fallbacks render the error page on 403 as well as 400.
  **Behavior change:** a client that expected an empty 403 body gets one.

- **The devtest all-buckets listing no longer answers 500 for an entry without
  a timestamp.** Every created actor now has an ``_internal`` bucket and its
  entries carry none; ``GET /<id>/devtest/attribute`` called ``strftime`` on
  ``None``. The listing skips the formatting for such an entry.

- **GitHub and other license scanners could not identify the project's
  license.** The only license file was ``LICENSE.rst``, a documentation page
  with an RST label, a badge and a summary of terms, so no scanner matched it
  to BSD-3-Clause, and the package metadata said only ``License: BSD``. The
  repository root now carries a plain-text ``LICENSE`` with the exact
  BSD-3-Clause text and the existing copyright notices, the documentation
  page moved to ``docs/license.rst`` (it now reproduces that text), and
  ``pyproject.toml`` declares the SPDX identifier ``BSD-3-Clause``. The
  license itself is unchanged. **Behavior change:** wheels and sdists built
  from this release report ``License: BSD-3-Clause`` and ship
  ``dist-info/licenses/LICENSE`` instead of ``LICENSE.rst``; the license page
  in the built documentation moves from ``LICENSE.html`` to
  ``docs/license.html``.

- **MCP ``tools/list``, ``resources/list`` and ``prompts/list`` listed
  everything when the permission evaluator failed.** An evaluator that
  could not be constructed left the filter off, and an item whose
  evaluation raised was listed anyway, so an evaluator fault showed a
  connected client every tool, resource and prompt. The three lists now
  fail closed: an evaluator that cannot be constructed answers an empty
  list, and an item whose evaluation raises is left out, each logged at
  ERROR with the traceback. A database fault still answers 503.
  **Behavior change:** a client connected while the permission system is
  broken sees an empty server instead of every item; check the ERROR log
  when a client reports an empty tool list.

- **Breaking: a list-item diff whose blob would exceed the span threshold
  is sent as a reference.** A ``SubscriptionDiff`` row has the same row cap
  as a list item, and an ``update`` diff carries two values, so a diff over
  ``list_item_span_threshold`` (390,000 bytes on DynamoDB; off on
  PostgreSQL) used to be lost or fail the full-state fallback. Such a diff
  now has its value fields (``item``, ``old_item``, ``value``, ``items``)
  removed and top-level ``"spanned": true`` and ``"bytes"`` added; this
  covers a spanned item, a large ``update``, an ``extend`` of many items,
  the REST handlers' single-item diffs and the full-state fallback for a
  peer without resync. The library's receiver does not apply a reference: it
  logs a WARNING and answers ``{"success": false, "spanned": true}``; the
  subscriber re-reads the list. **Behavior change:** a pre-3.16 subscriber
  answers ``unknown operation`` to a reference and stores nothing; a
  subscriber that applies diffs itself must re-read the list on
  ``"spanned": true``.

- ``downgrade_to_v1`` refuses a list holding spanned items
  (``reason="envelopes"``), and ``migrate_to_v2()`` refuses a v1 list
  holding a dict item whose first key is ``__aw_env``
  (``reason="envelope-shaped item"``; the migrate script reports it as a
  refusal). Writers refuse an item that is a dict carrying ``__aw_env`` (or
  whose string form starts like a storage envelope) with ``ValueError``
  before any write.

- **``$`` is refused in new list names.** It separates a list's spanned
  body rows from its items. **Behavior change:** creating a list whose name
  contains ``$`` raises ``ValueError``; existing lists with ``$`` in their
  name keep working.

- **``Actor.create`` refuses a caller-supplied ``actor_id`` containing
  ``$`` or longer than 251 characters**, with ``ValueError`` before any
  write: ``$`` separates an actor's property-list side partition
  (``{actor_id}$aux``), and the side partition key must fit PostgreSQL's
  255-character ``properties.id``. **Behavior change:** generated ids (32
  hex characters) are unaffected; an application that supplies its own ids
  must keep them free of ``$``.

- An actor delete also sweeps the actor's property-list side partition
  (spanned items' body rows), until a prefix read finds it empty, at most
  three passes. ``actingweb-verify-orphans`` reports a leaked side
  partition under its raw ``{actor_id}$aux`` key once the actor is gone.

- ``GET /properties?metadata=true`` reports each list's ``total_bytes``
  from the item rows alone (a spanned item's head carries its size), and
  ``format=full`` and ``metadata=true`` report a list with a broken span or
  a malformed head with an ``error`` marker instead of failing the whole
  response. The handle-only reads in the REST and www item handlers no
  longer read spanned items' bodies. The bulk ``items`` update size-checks
  every entry before writing any, so its 413 means nothing was written, and
  ``PUT ?index=`` answers a broken span with the 409.

- **Behavior change: the REST property handlers deny when their permission
  check raises.** For a peer request, ``PropertiesHandler``,
  ``PropertyMetadataHandler`` and ``PropertyListItemsHandler`` caught an
  exception from ``get_permission_evaluator()``, or from the legacy check
  behind a ``NOT_FOUND`` result, and answered with the coarse legacy
  ``access`` table, which for the default table allowed ``friend``,
  ``partner`` and ``admin`` every property method. They now deny (403) and
  log at ERROR; a ``DbError`` still answers 503. An error inside the
  evaluator's own rule evaluation already answered ``DENIED`` and is
  unchanged, as is the no-rule (``NOT_FOUND``) fallback. Only a deployment
  whose evaluator cannot be built, or whose legacy check raises, sees 403s
  where it saw 200s; check the ERROR log for "Error in permission evaluation".

- **The web UI's list pages read item heads only and act by identity.**
  ``/<id>/www/properties/<list>`` no longer reads spanned items' bodies: it
  passes ``list_entries`` (index, rank, a digest of the stored value, size,
  and the item's JSON with key order and non-ASCII kept, ``None`` for a
  spanned item) beside ``list_items`` (where a spanned item is
  ``UNRESOLVED``), and ``?edit=<rank>`` loads one item whole as
  ``edit_entry``; a corrupted list sets ``list_error``. The item actions
  accept ``item_rank`` and ``item_digest`` and answer 409 when the item
  changed or went since the page was loaded, refuse writes on a list a put
  hook makes read-only (403), refuse a cross-site request (403, see
  SECURITY), refuse invalid JSON when ``item_format=json``, store every
  textarea's line breaks as ``\n`` (a textarea posts CRLF; an item written
  over REST with CRLF is rewritten with LF when it is saved in the web
  UI), and treat a whitespace-only value as empty. A v1 list's items are
  edited by position (``?edit_index=<i>``), and its actions accept
  ``item_digest`` too, answering 409 when that position now holds a
  different item or none; this is best effort (the check and the write are
  two steps) and only runs when the form posts ``item_digest``. The web
  UI's redirects, the trust and email-verification redirects and the error
  pages' back links keep the deployment's base path (``config.root``). **Behavior change:** in ``list_items`` a spanned item is the
  ``UNRESOLVED`` sentinel, so a custom template that prints ``list_items``
  shows the text ``UNRESOLVED`` for it, and one that passes ``list_items``
  through ``tojson`` raises ``TypeError``. Render ``list_entries`` instead,
  as the shipped templates do (see ``docs/guides/web-ui.rst``).

- **The web UI's list item actions answer with a reason.** The
  ``/<id>/www/properties/<list>/items`` actions answered errors with an empty
  body, mapped an oversized item to 500 and a broken span to 400, and an
  ``update`` with an empty ``item_value`` replaced the item with ``""``.
  They now answer with a small HTML page carrying the reason and a link back
  to the list, answer 413 and 409, and
  refuse an empty ``update`` value with 400 as ``add`` already did.
  **Behavior change:** a form that posts an empty value to blank an item
  gets 400.

- **``with_list_item_limits()`` refuses a ceiling more than 9,999 body rows
  of the threshold** (``list_item_max_bytes > 9999 *
  list_item_span_threshold``), where an item at the ceiling could not be
  stored. **Behavior change:** such a pair raises ``ValueError`` wherever
  it is set.

- An actor delete skips the side-partition sweep, with an ERROR, when an
  actor exists whose id is the deleted actor's id plus ``$aux`` (possible
  only with pre-3.16 caller-supplied ids), and logs a WARNING when rows
  remain after its last pass.

- **Breaking: ``SubscriptionManager.is_suspended()`` raises ``DbError`` on a
  fault.** It answered ``False`` when the suspension could not be read, so a
  throttle looked like "not suspended" and fired the callbacks a suspension
  meant to hold back. Both bundled backends now raise ``DbError`` from
  ``DbSubscriptionSuspension.is_suspended`` too (DynamoDB let the raw error
  escape, PostgreSQL answered ``False``). **Check:** in a background job,
  catch ``DbError`` and retry; a custom backend must raise it.

- **A stalled deletion is finished by the next ``DELETE``, sign-in or
  operator run.** An actor's wipe that stopped part-way (a fault, a crash)
  left a live row under its tombstone. Every wipe now goes through one
  finisher behind a tombstone that records why it was written, whether peers
  are notified, the ``actor_deleted`` kwargs and the actor's OAuth2 client
  ids, and that has no retention TTL until the row is gone. A finisher holds
  the tombstone's two-minute lease, renewed between the wipe's peer
  notifications, so a slow wipe keeps it and a lease another finisher took
  over stops the first one. **Behavior change:** a repeated
  ``DELETE /<id>`` resumes the wipe without firing ``actor_deleted`` again
  (unless it raised ``DbError`` the first time) and fires
  ``actor_deleted_complete``; a ``DELETE`` of a live actor carrying a
  tombstone written before 3.16 fires ``actor_deleted`` (whether it ran then
  is not knowable; handlers are idempotent); one that arrives while another request holds
  the lease answers 503 with ``Retry-After`` set to the lease's remainder
  (``DeletionInProgress``, logged at INFO). ``DELETE /<id>`` now revokes the
  actor's MCP and SPA tokens and removes its client index rows, and answers
  503 when the backend does not confirm the row removed (it answered 204). A
  provider sign-in completion (the callback, the SPA grants, the MCP OAuth
  callback) on a vouched actor carrying such a tombstone finishes the wipe
  and creates a new actor for the creator, so a user who deleted their
  account and signs up again gets a new one under ``unique_creator`` too;
  under a live lease it answers 503. The email form and the emailed link
  have no provider to create the new actor with and fail closed there. A tombstone written before 3.16 leaves a
  vouched actor as it was (a WARNING names it), and a bearer-token request or
  a page load never wipes. A vouched sign-in now reads the tombstone, so an
  unreadable tombstone store answers 503 there. A replacement victim's peers
  are never notified, also when the wipe is resumed or ``Actor.delete()`` is
  called again. A fixed-id ``Actor.create`` whose tombstone clear cannot be
  confirmed fails (503) and leaves no row. A programmatic
  ``Actor.delete()`` or ``ActorInterface.delete()`` marks its own tombstone
  finished once the row is gone, so it gets the retention TTL and
  ``report`` does not list it. **Check:** run
  ``actingweb-deletions report`` after upgrading.

- **A permission callback that revoked access stored the new permissions
  before deleting the revoked data.** With ``auto_delete_on_revocation`` on,
  a fault in the deletion (its listing folded to "nothing to delete") left
  the cached peer data while the stored permissions no longer showed a
  revocation, so the retry deleted nothing. **Behavior change:** the revoked
  data is deleted first, with strict reads, and a failure answers 503 (a
  store fault) or 500 (anything else) with the old permissions still
  stored, so the peer's retry finishes it.
  Removing a trust also fails with 503 when that peer's callback state
  cannot be listed. The comparison acts only on patterns that disappear from
  the grant, not on an added exclusion, a dropped ``read``, scalar
  properties or copies an application fetched by query
  (``docs/quickstart/configuration.rst``).

- **Behavior change: a write whose subscription diff cannot be registered
  answers 503.** The property write stays, but a fault reading the
  subscribers (or a subscriber that gets neither its diff nor a sequence
  gap) raises ``DbError`` instead of being logged, so the subscriber's gap
  is not silent. ``PUT``, ``POST`` and ``DELETE`` on
  ``/<id>/properties`` and the property-list operations of
  ``ActorInterface`` all answer it. **Check:** a client that retries after
  the 503 writes again; for a list ``append``, ``extend``, ``insert`` or a
  ``POST /<id>/properties`` that adds, that is a second item.

- **Behavior change: a resume whose resyncs did not all land re-sends to the
  ones that missed.** ``resume_subscriptions()`` records the subscribers
  whose resync failed (over HTTP, or a permanent store error); the next call
  sends to those only, and drops the record once they all answered; a
  suspension set after that partial resume is still lifted by the same
  call, and its subscribers get their resync.

- **Behavior change: DynamoDB ``DbSubscription.modify`` updates only the
  given fields.** It saved the whole item from the handle it loaded, so a
  concurrent sequence increment was written back to its old value. It is now
  one conditioned ``UpdateItem`` and answers ``False`` for a subscription
  deleted since it was loaded (it recreated it). PostgreSQL's ``modify``
  always updated only the given columns; it now answers ``False`` for a
  deleted subscription too (it answered ``True``). The library ignores the
  answer in its sequence updates.

ADDED
~~~~~

- **``SubscriptionManager.get_subscriptions_by_peer()``** returns every
  subscription of the actor grouped by peer id, as ``PeerSubscriptions``
  (``peer_id``, ``outbound``, ``inbound``), from one subscription read; a
  peer with none has no key. Through a peer view it holds that peer's key
  only, through a client view its trust's peer id and its client id.
  ``PeerSubscriptions`` and ``SubscriptionInfo`` are exported from
  ``actingweb.interface``.

- **``actingweb-peer-state``** (``report | prune [--apply] [ACTOR_ID]
  --rps``) finds and removes peer state written before 3.16: permission
  copies for peers with no trust or stamped in the future, callback state
  for subscriptions the actor never made, and peer data for peers with no
  trust or subscription; ``--all-permissions`` also every live peer's copy
  (a forged one for a trusted peer looks real). A trusted peer's removed
  copy (a live one, or one stamped in the future) is rebuilt right after
  its removal by a permission query to its peer. Strict reads; exit 0
  nothing found, 1 found or removed, 2 a store could not be read, a delete
  failed or a removed copy was not rebuilt. See the
  maintenance guide.
- **``DELETE /<actor>/trust/<relationship>/<peer>?notify=false``**, creator
  only: removes the row and its cascade without contacting the peer (a dead
  or unreachable peer).

- **Python 3.14 is tested and listed as supported.** CI runs the test suite on
  both backends with Python 3.11, the oldest version ``python = "^3.11"``
  allows, and with 3.14, the newest. The package lists the 3.14 classifier.
  The minimum stays 3.11.

- **``create_attr_if_absent``** (the attribute protocol, both backends and
  ``Attributes``) creates an attribute only if no live row holds its name, in
  one conditional write. An expired row (its stored ``ttl_timestamp`` in the
  past, the rule ``get_attr_strict`` applies) counts as absent and is replaced
  in the same write; a row in another bucket is never touched; a lost condition
  whose stored row is JSON-equal to the data written is ``True`` (a create that
  landed and was retried by the SDK); a fault raises ``DbError``. **Behavior
  change to know:** two callers writing identical data both get ``True``, so a
  caller that needs exactly one winner puts a per-call nonce in ``data``.
  After a ``False``, ``Attributes.get_attr(name)`` on the same instance reads
  the winner's row through. The stored ``ttl_timestamp`` carries the
  one-hour ``TTL_CLOCK_SKEW_BUFFER`` like every attribute TTL, so a row
  written with ``ttl_seconds=600`` holds its name for 70 minutes; an
  application with a shorter expiry keeps its deadline in ``data`` and takes
  a stale row over with ``conditional_update_attr``. See
  ``docs/sdk/attributes-buckets.rst``.

- **``actingweb-property-lookup``** (``report``, ``backfill``,
  ``mark-complete``, ``unmark``; dry-run unless ``--apply``) makes the
  reverse-lookup table ready on both backends, and ships in the wheel
  (``scripts/`` does not). ``backfill`` rebuilds the lookup rows from the
  properties table (DynamoDB: rate-limited segment scan, resumable; a write
  fault is retried and never reported as a collision; PostgreSQL: primary-key
  batches that commit alone, orphaned property rows skipped and counted),
  marks each name that finished with no fault and no collision, and records
  the name set. A collision is kept in the checkpoint, so a run resumed after
  a fault still leaves that name unmarked; the dry run predicts the
  collisions ``--apply`` would find (a value another actor's lookup row
  holds, or two actors sharing a value with no row yet) and exits 1 for
  them. ``mark-complete`` marks without a scan and refuses a name with
  property rows and no lookup rows unless ``--force``. ``report`` exits 1
  when the startup check would refuse.
  ``scripts/backfill_property_lookup.py`` stays as a shim that delegates.
  New exports: ``StoreNotReady`` and ``PropertyLookupNotReady`` from
  ``actingweb.interface``.

- **``Config.actor_path(actor_id, suffix="")``** returns an actor's path
  with the deployment's base path (the path part of ``config.root``). The
  library's redirects after sign-in, after the email flow, from ``/<id>``
  in a browser, from the email-verification page and from the trust and
  web UI pages use it, so a deployment mounted under a base path no longer
  lands on ``/<id>/www`` without it. **Behavior change:** the
  ``redirect_url`` the OAuth2 callback passes to the ``oauth_completed``
  hook, and returns to an SPA, now carries the base path; a hook that
  prefixed ``config.root`` to it should prefix the origin only.

- **``actingweb-unique-creators``** (``report``, ``resolve``, ``enable``,
  ``disable``; dry run unless ``--apply``). ``report`` lists actors sharing
  a creator, including addresses that differ only by case, and on DynamoDB
  ``creators`` records whose actor is gone or holds another creator and
  actors without a record. ``resolve`` keeps one actor per group (vouched,
  then unvouched, then ``factory``; then the oldest; then the lowest id;
  ``--keep`` overrides) and renames the others to ``<creator>#dup-<hash>``,
  clearing their stored email; no data is deleted. ``enable`` refuses while
  duplicates remain, then backfills the DynamoDB table or builds the
  PostgreSQL index ``CONCURRENTLY``; it is safe to re-run. Exit codes: 0
  clean, 1 found or refused, 2 store unreadable. Also as
  ``scripts/unique_creators.py``.

- **``ActingWebApp.check_ready()``** runs the ``with_unique_creator()``
  startup check for an application that uses neither integration, and
  ``python -m actingweb.db.verify_tables --unique-creator`` includes the
  ``creators`` table.

- **``ActorInterface.modify_creator(new_creator, *, unvouch=False)``** and
  **``Actor.modify_creator_unvouched(creator)``**. With ``unvouch=True`` an
  application route that passes a user-supplied address applies
  ``PUT /<id>/trust/trustee``'s rules: ``creator_changed`` written and
  confirmed first (``factory`` kept; ``trustee``, the stored email and the
  current creator exempt), and the old marker restored when the change fails
  and a fresh read shows the creator unchanged. With
  ``force_email_prop_as_creator`` on, it refuses an address other than the
  stored email or ``trustee`` (``Actor.creator_change_pinned``), as the
  endpoint does. Returns ``False`` when the creator did not change.

- **``with_open_factory(enable=False)`` closes the actor factory.** The
  factory (``POST /``) creates an actor for any address from unauthenticated
  input, which is the only way to squat one. An OAuth-only deployment can now
  answer it with a 403 (the house JSON body, or the error page for a form)
  instead; the existing-creator form redirect is closed with it (and no
  longer names the actor on an open factory either, see CHANGED). ``Config`` gains
  ``open_factory`` (default ``True``); a value assigned on the ``Config``
  survives until ``with_open_factory`` is called, after which the builder's
  value wins. This deviates from the protocol's mandatory factory, so the
  factory stays open unless you call it. A closed factory still renders the
  ``GET /`` page and its form, whose submit gets the 403; replace the
  template if that page should not offer one. **Behavior change:** none
  unless you call it.

- **``actor_adopted`` lifecycle hook.** Fires once on the surviving actor
  after an unvouched actor was replaced or cleaned, with
  ``previous_auth_method``, ``previous_actor_id`` (the replaced id, else
  ``None``), ``provider`` (base name, ``None`` for the emailed link),
  ``mode`` (``"replaced"`` or ``"cleaned"``), ``removed_trusts`` (``peerid``,
  ``relationship``, ``approved``, ``established_via``; never ``secret``),
  ``removed_subscription_peers``, ``tokens_revoked``, ``removed_client_ids``,
  ``removed_sibling_ids`` (the other ``factory`` actors the sign-in deleted,
  including the one it first resolved to when it then cleaned the owner's own
  actor instead)
  and ``property_names``
  (the in-place case, so the application can inspect what a squatter may have
  prefilled). It may fire more than once for one actor.

- **``auth_method`` on create.** ``ActorInterface.create(..., auth_method="app")``
  and ``Actor.create(..., auth_method="app")``. It is a trust assertion:
  ``app`` means the application vouches for the creator; pass ``factory`` for
  anything created from unauthenticated input. Adoption also records
  ``auth_method_adopted_from``, ``auth_method_adopted_at`` and, for a
  replacement, ``auth_method_replaced_actor_id`` in the ``_internal`` store.

- **``prompt`` on ``POST /oauth/spa/authorize``.** A SPA can ask the provider
  for account selection with ``"prompt": "select_account"``. It is additive:
  ``consent`` is always sent, and Google receives ``select_account consent``;
  GitHub and Apple drop the addition. Any other value answers 400 listing the
  accepted ones. ``GET /oauth/spa/config`` and ``GET /?format=json`` list
  ``prompt_values``; on ``/oauth/spa/config`` (and ``/oauth/config``) each
  provider entry also carries ``prompt_supported``.
  ``OAuth2Provider.authorize_prompt_params`` and
  ``OAuth2Authenticator.create_authorization_url(prompt=)`` carry it.

- **Core primitives for the adoption rule.** ``Actor.purge_relationships``
  removes every trust, subscription and peer-trustee row with all side-stores
  and reports whether the lists are empty afterwards;
  ``Actor.delete``, ``delete_peer_trustee`` and ``delete_reciprocal_trust``
  take ``notify_peers`` (default ``True``) to skip the remote ``DELETE``
  calls; ``ActingWebTokenManager.revoke_actor_tokens`` revokes an actor's MCP
  tokens whatever the client; ``adopt_actor`` and ``is_vouched_actor`` in
  ``actingweb.oauth2``. Fault-aware reads for callers that act on absence:
  ``InternalStore.loaded`` (whether the ``_internal`` read was answered),
  ``fetch(actor_id, strict=True)`` on the trust and subscription list
  backends (raise instead of PostgreSQL's ``[]`` on a fault), and
  ``OAuth2SessionManager.revoke_all_tokens(actor_id, strict=True)`` (raise
  ``TokenStoreUnavailable`` when a token could not be revoked).
  ``InternalStore.set_confirmed(name, value)`` writes a value and confirms
  it with a strict read-back, for a write that must not fail silently.

- **``actingweb-mark-actors-vouched``** (``actingweb.maintenance.mark_actors_vouched``;
  ``scripts/mark_actors_vouched.py`` wraps it). For operators upgrading a
  deployment that must not have its existing actors cleaned at first sign-in:
  writes ``auth_method`` (default ``operator``; an unvouched value is
  refused) on actors with no marker, with ``--creator``, ``--start-after`` to
  resume, ``--dry-run`` and ``--include-factory`` to also re-mark ``factory``
  actors. It needs the 3.16 library and scans the whole actor table, streamed
  (only each matching actor's id and creator is kept, about 220 MB per
  million actors) and strongly consistent on DynamoDB, since it writes back
  the creator it read (twice the read units of an eventual scan;
  ``--rate-limit`` caps it in read capacity units per second, ignored on
  PostgreSQL). It prints ``scanned``, ``marked``, ``skipped``, ``pending`` (marked, but still waiting
  for email verification, so still unvouched) and ``errors``. Exit 0 when
  every actor was handled, 1 when one could not be marked (re-run it without
  ``--start-after``; the summary says so), 2 when the actor list could not be
  read and nothing was scanned, or when an argument such as ``--marker`` was
  refused. Run it as maintenance, with the application's environment.

- **``ListItemTooLargeError``** (``from actingweb import
  ListItemTooLargeError``), raised before any write when a property-list
  item's encoded size is over a limit; it carries ``list_name``, ``bytes``,
  ``limit`` and ``reason``, and its message never includes item content.
  The REST handlers map it to 413 with ``{"error": "list_item_too_large",
  "list", "bytes", "limit", "detail", "remedy"}``. It subclasses
  ``ValueError``: catch it ahead of a generic ``except ValueError``.

- **``ActingWebApp.with_list_item_limits(span_threshold=..., max_bytes=...)``**
  and the ``Config`` settings ``list_item_span_threshold`` and
  ``list_item_max_bytes``. Defaults follow the backend: DynamoDB 390,000
  bytes and 4 MiB; PostgreSQL neither (unchanged behaviour there). An
  omitted argument keeps the default and an explicit ``None`` turns the
  limit off; out-of-range values raise ``ValueError`` wherever they are
  set. A backend declares its row cap with ``DbProperty.MAX_ROW_BYTES``.
  ``list_item_max_bytes`` is a storage bound: size the request-size limit
  at the deployment's edge to match it. A deployment that develops on
  PostgreSQL and runs DynamoDB in production sets both explicitly.

- **Spanned list items.** On a v2 list an item over
  ``list_item_span_threshold`` (390,000 encoded bytes on DynamoDB; off on
  PostgreSQL unless configured) is stored across several rows and reads back
  whole through every reader. The list row holds a small envelope; the
  bodies live in the actor's side partition (``{actor_id}$aux``), so no
  dump or range read of the actor's own properties carries a body byte.
  Every rewrite writes a fresh body generation and then deletes the old
  one; a reader that finds a generation short re-reads the head and bodies
  strongly (at most twice) before raising ``ListItemSpanError`` (a
  ``ListCorruptionError``; 409 over REST with a ``remedy`` naming the
  repair), never a partial item. Costs: one extra paged read per spanned
  item on every resolving read, and the body rows on every write.

- ``items_with_handles(resolve=False)`` and
  ``to_list_from_rows(rows, resolve=False)`` skip spanned items' bodies (the
  slot holds the new ``UNRESOLVED`` sentinel, exported from ``actingweb``),
  ``ListItemHandle`` gains ``spanned`` and ``bytes``, ``item_at(handle)``
  reads one item now, and ``sizes_from_rows(rows)`` gives each item's size
  without a body read.

- ``verify()`` reports ``spanned_items``, ``span_bytes`` and
  ``malformed_heads``; ``verify(spans=True)`` also enumerates body rows and
  reports ``span_body_rows``, ``orphan_span_gens`` and ``broken_spans``.
  ``sweep_span_orphans()`` removes orphan body generations older than an
  hour, heads whose bodies are missing and malformed heads that carry the
  library's envelope marker (``orphan_span_gens_removed``,
  ``broken_spans_removed``, ``malformed_heads_removed``) without
  rebalancing; a head that is not valid JSON is kept with the bodies it
  names (``malformed_heads_kept``) for recovery, and the script reports a
  list whose sweep left one in place as unhealthy;
  ``compact(sweep_span_orphans=True)`` sweeps and then rebalances.
  ``actingweb-verify-property-lists`` gains ``--spans`` and, with
  ``--repair``, ``--sweep-spans`` (which runs the sweep, not a rebalance).
  A span records its body's SHA-256, so same-length wrong content reads as a
  broken span rather than as the item. ``ListProperty.check_item_size(item)``
  checks an item against the limits without writing.

- **``ListProperty.append_once(item, *, key)``: a create a client can
  repeat.** A client whose create timed out at a gateway while the server
  finished the write could not tell "not stored" from "stored, answer
  lost", and a find-then-append guard races. ``append_once`` stores
  ``item`` unless an item with the same client-minted ``key`` is already in
  the list, and returns ``AppendOnceResult(created, item, handle)`` (exported
  from ``actingweb``): on a repeat ``created=False`` and the item the first
  call stored, whatever payload the repeat sent. The key is stored only as
  ``HMAC-SHA256(actor_id, key)`` in a key row in the actor's side partition,
  and that row's conditional create decides between overlapping calls; the
  loser deletes its own copy, so two items are visible for the length of
  that delete. A key is bound to its item: deleting the item (by handle,
  ``pop``, ``remove``, ``del``, ``clear``, ``delete``) deletes its key row,
  and a later repeat creates again; a rewrite keeps the key. A repeat costs
  two point reads, a first call one more strongly consistent read of the
  list's heads. A ``DbError`` can follow a stored item (a repeat
  converges). v2 only; ``extend()``, ``insert()`` and the REST handlers
  take no keys. Also on ``NotifyingListProperty`` (at most one diff per
  item: an ``append`` from the call that created it, or an ``insert`` at
  ``announce_index`` from the repeat that finished a call which stopped
  before its key row, ``announced=True`` there) and the permission-checked
  list view (needs ``write``). ``ListItemHandle`` gains ``key_hash``.
  ``verify()`` now always reads the list's key rows and reports
  ``key_rows``, ``dangling_key_rows``, ``duplicate_keyed_items`` (part of
  ``healthy``) and ``unkeyed_keyed_items``, by rank, never by hash, leaving
  out anything written in the last hour by the writer's clock (a call
  still running). ``clear()`` deletes the key rows of the items it deleted
  and dangling ones older than an hour. New ``ListProperty.repair_keys()`` (also on the notifying list,
  with a ``metadata`` diff, and the permission-checked view) removes duplicate keyed items, keeping the
  one the key row names, writes missing key rows and deletes dangling ones
  (``duplicate_keyed_items_removed``, ``key_rows_created``,
  ``dangling_key_rows_removed``), under the same age rule and without
  rebalancing; ``compact()`` runs it before it rebalances, and
  ``actingweb-verify-property-lists --repair`` runs it for a list whose
  only repairable finding is duplicate keyed items. **Behavior
  change:** the first ``append_once`` on a list makes it unreadable to
  pre-3.16 readers (they see the storage envelope as the item) and makes
  ``downgrade_to_v1`` refuse it; deploy 3.16 everywhere first.
  ``verify()`` on a v2 list makes one more small read (the key rows) and
  its report has the four new keys.

- **``actingweb-deletions``** (``report``, ``resume``, ``clear``;
  ``actingweb.maintenance.deletions``). ``report [ACTOR_ID]`` lists
  deletions that stopped part-way (``stalled``, ``in progress`` while a
  finisher holds the lease, ``legacy, review`` for a tombstone written
  before 3.16, ``unfinished`` when the row is gone but client index rows may
  remain); ``resume [ACTOR_ID] --apply`` finishes them without application
  hooks and prints the finished ids, and purges expired tombstone and
  verification-index rows on PostgreSQL; ``clear ACTOR_ID --apply`` removes
  a stray tombstone from a live actor. Exit 0, 1 (work left, or a dry run
  with work), 2 (the tombstone store cannot be read). Pass
  ``--no-unique-creator`` when the application runs without uniqueness.

- **Signing in again with an emailed code: the
  ``email_sign_in_code_required`` lifecycle hook.** A user whose provider
  has no verified address proves their address once through the email form
  and its link; the next sign-in reached the form again, which answered 409
  because the address had an actor. With this hook registered
  (``func(actor, email, code, expires_in)``, the application sends the mail,
  as it does for ``email_verification_required``), the form answers a
  verified actor's address with a six-digit code instead: the browser page
  shows a code field, a JSON client gets ``status: "code_required"`` and a
  ``code_challenge``. ``POST /oauth/email`` with ``code_challenge`` and
  ``code`` signs that page in (the ``oauth_token`` cookie and a redirect to
  the actor, or a JSON ``access_token`` and ``refresh_token``). A code lasts
  10 minutes and 5 tries, is single use and stored only as a digest; only
  the page that asked holds the challenge, and only the mailbox the code. A
  challenge a browser page asked for is bound to that browser by an
  HttpOnly, ``Secure``, ``SameSite=Strict`` cookie
  (``__Host-aw_sign_in_binding``, path ``/``), and only a bound challenge
  with its cookie can be redeemed into a session cookie: a cross-site post
  of a challenge and code from another browser, or of one a JSON client
  asked for, answers 401 and signs nobody in. A JSON client's challenge is
  redeemed by a JSON request, which gets its tokens in the body. At most
  five challenges are created per actor per hour (then 429 for everyone
  until the hour ends, the limit's cost: five requests for an address lock
  its owner out of codes for that hour), counted with a conditional write
  so concurrent requests cannot exceed it; a new challenge does not cancel
  an earlier one, and a browser that already holds a binding keeps it for
  its next challenge, so a second tab does not void the first page's code.
  A browser form that another site started, a sibling subdomain included,
  answers 403 before a challenge is created or a code mailed (see "Another
  site could sign a browser in through the email form" under SECURITY), so
  no other site can bind a challenge to a browser; a JSON challenge is
  never redeemed into a browser session. A wrong code answers
  401 with the code page again (JSON: the error body); a challenge id that
  is not one the app issued answers 401 with the error page. The code
  signs in only to the actor that still holds the address it was sent to,
  and is never offered for, or redeemed into, an actor whose deletion is
  under way; such a refusal leaves the code unconsumed, and the attempt
  counts as one of its five tries. When every registered hook raises, the
  code was not sent: the challenge is withdrawn (its hourly slot stays
  used, since a hook can fail after the mail left) and the page answers
  503 "The sign-in code could not be sent"; once one hook sent it, a later
  hook's failure is logged and the code stays good. A store
  fault while counting a try or consuming the code answers 503, never
  "invalid code"; a token-store fault after a correct code answers 503 and
  that code is spent (ask for another). Over HTTP the binding cookie needs
  HTTPS (``Secure``), except on ``localhost`` in browsers that treat it as
  a secure origin.
  **Behavior change:** none without the hook, which keeps the 409.
  **Check:** an application template overriding ``aw-oauth-email.html``
  renders the code field when ``code_challenge`` is set, and ``error``
  beside it; the bundled template is headed "Enter your sign-in code" then.

- **``DeletionInProgress``** (``actingweb.db.exceptions``, a ``DbError``):
  another request is finishing the actor's deletion; answered 503 with
  ``Retry-After`` from its ``retry_after``.

FIXED
~~~~~

- **One actor instance read its subscription list again on every write
  when the actor had no subscribers.** Each property written, each list
  mutation and each per-peer subscription accessor issued its own strongly
  consistent list read. The second and later reads on an instance are now
  served from the first: writing three properties on one instance of an
  actor with no subscribers reads the list once (three before), and five
  peers' ``get_subscriptions_to_peer`` and ``get_subscriptions_from_peer``
  once (ten before). A request that writes once still reads it once.

- **A subscription created in another process could go without diffs from
  a long-lived MCP actor.** The actor an MCP request used was kept for five
  minutes with its subscription list; it is now built per request.

- **For up to 300 seconds after an actor's row was removed, a worker
  holding its MCP token kept serving the deleted actor's cached state.**
  (Distinct from the ``SECURITY`` entry on a cached token bringing a
  deleted actor back.) A cached token whose actor row is gone is now
  dropped and the token validated against storage: only a token that
  validates there can lead to the OAuth2 bridge creating the actor (as on
  any first request), never the cached entry.

- **A trust lookup on a cached MCP token could re-cache a trust revoked
  while it was being read, and an eviction could land between a cache
  fill's check and its write.** Every fill is now checked against the
  revocation counter, and fills and evictions run under one lock.

- **In a process hosting more than one application, a token or a trust one
  application had validated could be accepted by another that had the same
  actor id.** Each MCP cache entry records the application that filled it.

- **A trust deletion left deleted subscriptions in the instance's list**,
  also when the trust row was kept (a re-pair, a fault); later writes on
  that instance registered diffs for them. Each relationship's
  subscriptions are read for it, and the list is read again afterwards.

- **Deleting an actor, or purging its relationships, left its subscription
  suspensions and could leave subscription diffs;** an actor created again
  under the same id started suspended and sent no diffs. Suspensions left
  by a deletion on an earlier version are cleared when the id is created
  again.

- **A bulk ``POST /properties`` with a JSON body that is not an object
  answered 500.** It answers 400. A bulk ``POST`` that stops part way (a
  400, 413 or a hook's refusal) or faults in its form arguments now
  registers the diffs of the keys it had already written, as a fault in a
  JSON body did.

- **The trust's shared properties refused a row without an approval
  field.** ``GET /trust/<rel>/<peer>/shared_properties`` answered
  ``not_approved`` for a row with no ``approved`` field, which every other
  route treats as approved. A conditional trust delete of a row already
  gone skipped the permission and cache cleanup an unconditional one runs.

- **In a process serving two ActingWeb applications, a changed grant was
  not seen.** The permission store is rebuilt when another application's
  config asks for it, and the permission evaluator kept the store it was
  built with: writes went to the new store while decisions read the old
  one's cache, so a narrowed grant kept serving what it had excluded. The
  evaluator now looks the store up on each use. A process with one
  application was not affected.

- **An approval that also moved the peer's base URI was announced at the
  old one.** ``modify_trust_and_notify(approved=True, baseuri=...)`` sent
  the approval to the URL the row had before the write. It goes to the base
  URI the same call wrote, else to the row's as it stands after the write
  when that row still holds this call's secret (a row a re-pair replaced
  keeps the URL read before; a fault re-reading it no longer stops the
  notice). **Behavior change:** the notice authenticates with the secret
  the call wrote, when it wrote one (it sent the old one).

- **An async trust creation that failed with an error other than an HTTP
  one left its half-made row.** ``create_reciprocal_trust_async`` dropped
  the attempt only on an ``httpx`` error (an invalid URL raised something
  else), and the next attempt was taken for a re-pair. Any failure of the
  request now drops the attempt, as the sync method does.

- **A subscriber deleted a live trust when its peer deleted its
  subscriptions.** When every subscription to a peer answered 404,
  ``sync_peer`` asked the peer for ``trust/<our id>``, a path that always
  answers 404, and deleted its trust locally; since 3.16 the peer's approved
  row then refuses a fresh request, so the pair could not form again.
  **Behavior change:** it asks for its own trust row at the peer
  (``trust/<relationship>/<our id>``) and decides by the status: 2xx keeps
  the trust, 401, 403 or 404 deletes it locally, no answer or a server error
  keeps it until the next sync. A 401, 403 or 404 that a gateway in front of
  the peer answers (during a deploy, say) reads as a revocation too; the
  probe runs only when every subscription to the peer already answered 404.
- **A refusal with no body was read as success.** ``AwProxy.change_resource``
  and its async twin answered ``{}`` for a non-2xx response without a JSON
  object body, and callers test for ``error``, so a 403 on a subscriber's
  queue clear or acknowledgement was logged as success. Any non-2xx answer
  now carries an ``error`` with its status, and the subscriber's warnings
  name it (ERROR for a 403).
- **Every successful permission callback was logged as a failure.** The
  synchronous permission sender read a 204 (an empty answer) as a failure
  and logged ``Failed to notify peer … {}`` at WARNING.

- **A subscription ``callback`` that was not a bool was stored as ``True``
  on DynamoDB and failed as a store fault on PostgreSQL.** The column is a
  boolean on both backends, but nothing checked the argument: PynamoDB
  coerced any truthy value (a URL, on the path that found it) to ``True``,
  and PostgreSQL answered the failed cast as a ``DbError``, which read as an
  outage. ``DbSubscription.create`` and ``modify`` now refuse a non-bool
  before any I/O on both backends. **Behavior change:** a non-bool
  ``callback`` raises ``TypeError`` naming the type (never the value);
  ``modify`` still accepts ``None`` to leave it. No request can reach it
  (the handlers pass literals), so only code that calls the backend
  directly needs checking.

- **FastAPI answered ``resources/read`` differently from Flask.** The async
  handler sent a ``dict`` result as ``str()`` (or, when it had a
  ``content`` key, that value alone), read ``mimeType`` from a key the
  decorator never writes (so every answer was ``text/plain``), passed the
  hook only the template's variables, and ignored a resource declared only
  by ``uri_pattern``; the Flask handler passed only the request params, not
  the variables. Both handlers now share one resolver and one formatter,
  and pass the hook the request params, then the template's variables over
  them, then ``uri``, which is always the requested URI. **Behavior change
  for FastAPI deployments:** a ``dict`` body is indented JSON with the
  declared ``mime_type`` (``application/json`` when undeclared), including a
  ``dict`` with a ``content`` key, which was unwrapped before; a hook
  receives ``uri`` and the other request params; a ``uri_pattern`` resource
  resolves; and a ``dict`` holding a value JSON cannot serialise (a
  ``datetime``) answers the generic error instead of a Python repr.
  **Behavior change for Flask deployments:** a hook also receives the
  template's variables, which win over a request param of the same name.
  **Check:** a FastAPI client that parsed the old ``text/plain`` body or a
  hook that returned ``{"content": ...}``; a hook that splats its arguments
  into a fixed signature (it now receives ``uri``); a template with a
  variable named ``uri`` (the hook sees the requested URI under that name).

- **Deleting an OAuth2 client could delete another client's trust row.**
  Client deletion matched trust rows by substring
  (``pattern in peer_id or peer_id.endswith(client_id)``) and deleted the
  first hit, so an unrelated row on the same actor whose peer id contained
  the client id could go instead. It now deletes every row of the client,
  each found exactly: the rows the MCP authentication resolver accepts
  (``oauth_client_id``, then the exact legacy peer id), plus the real-email
  legacy rows ``<source>:<email>:<client_id>``. A second row of the same
  client (an upgraded actor can hold a legacy ``oauth2:`` row beside the
  tagged ``oauth2_client:`` one) was already removed for generated
  ``mcp_`` client ids, by the cascade that deleting the tagged row runs; it is
  now deleted directly, whatever the client id, and a fault on one row no
  longer stops the deletion of the others (the first fault is raised to
  the client-deletion caller after them, also when the deletion started
  from a trust-row delete). A retry through
  ``OAuth2ClientManager.delete_client`` after such a fault deletes the
  actor's leftover rows of that client id even though the client itself is
  already gone. **Behavior change:**
  an unrelated row whose peer id merely contains the client id is kept; a
  two-segment ``oauth2_client:<client_id>`` row, which the resolver
  already ignored, is no longer deleted with the client.

- **An MCP-token logout cleared the browser's SPA session cookies.**
  ``/oauth/logout`` with an MCP access token (``aw_…``) revoked the MCP
  chain and then cleared every session cookie, while any SPA refresh token
  sent beside it stayed live: half a logout of a session it did not own. An
  MCP login is an AI agent's on behalf of the user, not the user's browser
  session, so now that logout ends only the MCP chain; SPA refresh tokens
  presented with it are ignored and logged at DEBUG. **Behavior change:**
  the response keeps its shape (``"Successfully logged out"``,
  ``redirect_url``), but ``cleared_cookies`` is ``[]`` and no ``Set-Cookie``
  is sent. A browser ends its own session by logging out of the SPA.

- **A reverse-lookup row stayed with an actor that no longer held the
  value.** Releasing an indexed value's lookup row is best effort, so a
  throttled delete (or an actor removed without its rows) left the row
  behind, and the next actor to hold the value was written as a logged
  collision forever: reverse lookup never found it, and
  ``actingweb-property-lookup backfill`` reported the same collision and
  never marked the name. **Behavior change:** a write of an indexed value
  whose lookup row names an actor that no longer holds it (its property is
  gone or holds another value) takes the row over, in one step conditioned
  on that actor still not holding it, and logs ``LOOKUP_TAKEOVER`` with the
  value's digest. ``backfill`` does the same and counts it (``taken-over``,
  ``would-take-over`` in a dry run); on PostgreSQL a stale row with two or
  more current holders stays a collision, on DynamoDB the first current
  holder the scan meets takes it. An owner that still holds the value keeps
  its row, as before. **Check:** reverse lookup is not an identity proof
  (sign-in resolves by creator); an application that treats
  ``get_by_property`` as one should read the note on indexed properties in
  ``docs/quickstart/configuration.rst``.

- **Two concurrent deliveries of one subscription callback could both run
  the handler.** The callback processor's version check read the state row,
  compared the version and then wrote unconditionally, so two in-order
  deliveries of the same diff (a retried callback, a poll beside a callback)
  could both pass; and a delivery that lost the check retried after the
  winner's state write but before its sequence write, so it ran the handler
  again. The state write is now a compare-and-swap that also claims the
  batch's sequences for 60 seconds. **Behavior change:** a concurrent
  delivery of a claimed sequence is not handled
  (``ProcessResult.IN_PROGRESS``, new): a callback answers **503** with
  ``Retry-After: 5`` and ``X-ActingWeb-Error: callback_in_progress``
  instead of 204, and the gap timeout waits while the claim is live. A
  poll (``sync_subscription``) stops before such a sequence, neither
  clearing nor recording past it (``SubscriptionSyncResult.in_flight``,
  new), and after applying diffs it writes its sequence only when that is
  above the one it read (a read, then a write; the baseline fallback still
  writes the publisher's sequence as it is). A
  high-granularity diff stays on this library's publisher until a poll or an
  acknowledgement clears it (the publisher does not redeliver), so if the
  claiming delivery fails, the next poll or gap resync applies it. A handler
  ``DbError`` releases the claim; a delivery that crashes while holding one,
  or whose sequence write faults, is taken over by the next delivery of its
  sequences once 60 seconds have passed. A low-granularity diff is deleted
  on the publisher by the subscriber's own fetch, so a low-granularity
  callback is answered before the fetch when its sequence is already
  handled (204) or claimed (503); a delivery that claims it between that
  check and the fetch can still find it gone, and a failed delivery of one
  is recovered only by a resync. One whose diff cannot be fetched now
  answers 503 and processes nothing (it used to apply an empty diff and
  advance the sequence). With subscription processing on and
  ``auto_sequence`` at its default (on), a callback the subscriber fetches by URL (not a resync)
  without an integer ``sequence`` answers 400. ``FanOutManager`` no longer counts
  the in-progress answer toward opening a subscriber's circuit breaker, and
  a half-open breaker that gets it closes; every other 503, a subscriber's
  store-fault answer included, and a 429 still count. **Check:** the claim
  holds once every instance runs 3.16 (an older instance ignores it),
  between processes with synchronised clocks, and for handlers that finish
  within the 60 seconds (the lease is not renewed).

- **A GitHub sign-in with no public email asked GitHub's ``/user/emails``
  twice.** With an email required, the callback asked for the primary
  address, and when that failed asked the same endpoint again for the
  verified list, each with a ``(5, 10)`` second timeout. The GitHub provider
  now makes one request per token and derives both answers from it, a
  failure included, so a failing GitHub costs one timeout before the existing
  502 (or the SPA ``identifier_failed`` redirect), not two. The token and
  userinfo requests keep their own timeouts. The primary address is the
  verified entry GitHub flags primary, else the first verified entry; an
  entry with no address is skipped. **Behavior change:** a response whose
  entries are not objects counts as a failed request (the 502), and calling
  the provider's ``get_primary_email`` and ``get_verified_emails`` for one
  token within 30 seconds reuses the first answer.

- **DynamoDB's trust, subscription and subscription-diff list ``fetch``
  answered ``None`` for an empty actor id.** The protocol and PostgreSQL
  answer ``[]``; DynamoDB does too now. **Behavior change:** a custom caller
  that tested the result with ``is None`` sees an empty list instead.

- **The PostgreSQL ``actingweb-property-lookup backfill`` faulted at the same
  batch on every run when one indexed value was too long to index.**
  ``property_lookup``'s primary key is a btree on ``(property_name, value)``.
  PostgreSQL refuses a key row over about 2,704 bytes after compression
  (SQLSTATE 54000), and that error aborted the whole pass. A refused batch is
  now retried row by row. Each refused row is logged as ``UNINDEXABLE``
  (actor, name, size, never the value) and counted as ``unindexable=N``.
  Every other row in a batch that commits is written; each row is re-read
  as it is inserted, so a concurrent ``set()`` cannot leave a lookup row for
  a value the actor no longer holds. **Behavior change:** the command commits the
  other rows, leaves that name unmarked and exits 1, where it used to fault
  and write nothing past the bad batch. The dry run notes values that may be
  too long; that note does not change its exit status. **Check:** that actor cannot
  write the property at all until the value is shortened. The property and
  its lookup row succeed or fail together, so every write raises
  ``DbError``. Shorten or remove the value and re-run; marking the name
  complete would hide that failure.

- **``Actor.modify_trust_and_notify_async`` never notified the peer.** It
  built ``AwProxy(peer_target=...)`` without the ``id`` key the proxy reads,
  and the ``KeyError`` was folded into a debug line ("Not able to notify peer
  async"). It also sent ``PUT`` where the peer's trust route treats only
  ``POST`` as an approval notification. It now runs the sync
  ``modify_trust_and_notify`` in a worker thread (``asyncio.to_thread``), so
  the two send the same ``POST`` and handle errors around the trust write the
  same way. **Behavior change:** for applications that call the async method
  directly (nothing in the library does), the peer is now told of the
  approval and, once both sides have approved, its
  ``trust_fully_approved_remote`` hook runs, as for the sync method.
  Cancelling the await does not stop the worker thread: the trust write and
  the notification still complete.

- **A provider-verified sign-in left the abandoned verification address
  behind.** ``clear_pending_email_verification`` removed the token and the
  pending flag but kept ``email_verification_address``. Nothing could use it
  without the token; it is now cleared with the token, as the verify
  handler's own success path does.

- **The marker restore after a failed creator change logged "auth_method
  changed since this creator change wrote it" for a store fault.** The
  conditional update answers False for both cases. A strict re-read now tells
  them apart, and an outage logs "could not restore auth_method (store
  fault)". The actor stays unvouched either way.

- **Four per-process permission caches grew with every actor and peer pair
  the process saw.** ``TrustPermissionStore``, ``PeerProfileStore``,
  ``PeerPermissionStore`` and ``CachedCapabilitiesStore`` cached in a plain
  dict on a process-wide singleton, with no bound. They now keep at most
  4,096 entries each (least recently used goes first), read under one lock.
  A pair evicted from the cache is read from the store again, which is
  correct, only slower.

- **Payload summaries in log lines were built at every log level.**
  ``summarize_payload`` sat inside eager log arguments on 17 lines, including
  the subscription callback sender, which runs once per subscriber. Each line
  now checks its own level first.

- **A glob with many ``*`` no longer backtracks exponentially (security).**
  The evaluator's translation turned every ``*`` into ``.*`` and measured 12
  stars against 40 characters at over 20 seconds, and the callbacks and
  peer-permission patterns are peer-supplied. One matcher now serves all three
  places, with the atomic segments ``fnmatch.translate`` uses and an LRU cache
  (a peer sending distinct patterns can no longer flush the whole cache). The
  call sites that used ``fnmatch`` were linear already, so the fix is to the
  evaluator's own engine.

- **``Config(fqdn=...)`` without ``oauth=`` composed ``redirect_uri`` from the
  default host.** It is now derived from the host the caller gave, and a
  caller's own ``redirect_uri`` still wins.

- **Registering an OAuth2 client listed the actor's trust relationships** to
  build a log string; the read is gone.

- **A ``GET /<id>/callbacks/<name>?_method=POST`` ran the POST and then
  the GET.** ``CallbacksHandler.get`` did not return after dispatching an
  override, so both hooks ran and the GET's answer replaced the POST's. It
  now returns after the override, as every other handler does.

- **``GET /?format=json`` on Flask returned the HTML page.** The Flask root
  route rendered the factory template for every GET without running the
  handler, so the JSON configuration document (providers, endpoints,
  ``prompt_values``) that FastAPI serves never reached a Flask client. A GET
  asking for JSON (``?format=json`` or ``Accept: application/json``) now gets
  it on both integrations; a browser still gets the page. The Flask JSON
  branch returns the configuration only: ``_method=POST`` on that GET does not
  create an actor. **Behavior change:** a Flask ``GET /`` (and ``/login``,
  which shares the handler) with either signal answers JSON instead of HTML.

- **``Accept: application/json`` was not recognised on FastAPI's ``GET /``.**
  The factory handler looked the header up case-sensitively, and FastAPI
  passes header names lowercased. The lookup is case-insensitive now, which
  also lets a closed factory answer a form post that asks for JSON with the
  JSON error body instead of an empty 403.

- **On DynamoDB, ``Actor.create`` with a caller-supplied ``actor_id`` could
  overwrite a live actor.** The existence check reads the row first, and that
  read answers ``None`` on a throttle or timeout as well as on absence; the
  put that followed was unconditional. The MCP bridge supplies the id exactly
  when it could not load the actor. The insert is conditional now
  (``attribute_not_exists(id)``), as PostgreSQL's primary key already made it,
  so the live row and its ``_internal`` bucket stay untouched.

- **``Actor.create`` with ``unique_creator`` could fail right after a
  replacement on DynamoDB.** The creator index is eventually consistent and
  can still list the just-deleted actor, which reads back as ``None``; the
  uniqueness check dereferenced it. The check is gone: the database enforces
  uniqueness now (see CHANGED).

- **A trust read that faulted issued a new secret over a live OAuth trust.**
  ``TrustManager.create_or_update_oauth_trust`` read the existing trust, and
  a fault read as "none", so it generated a new secret, reset
  ``peer_approved`` and upserted over the stored row. The read raises now and
  nothing is written. (B1)

- **A permission-override update could overwrite the stored override with a
  partial one.** ``PUT /<id>/trust/<rel>/<peer>`` and
  ``PUT .../permissions`` read the existing override, and a fault read as
  "none", so the request's partial update was stored as the whole override
  and the peer notified. The read propagates now (503) and nothing is stored
  or sent. (B2)

- **One faulted read cached "no permission override" for the whole
  process.** ``TrustPermissionStore.get_permissions`` cached the fault's
  ``None``, and the evaluator then applied the trust type's base permissions
  to that peer until restart. Nothing is cached on a fault now; the store
  and the evaluator re-raise ``DbError``, so the request answers 503 instead
  of being evaluated against the wrong permissions. (B3)

- **With ``unique_creator`` a listing fault let ``Actor.create`` insert a
  duplicate.** The uniqueness check listed the creator's actors, and a
  PostgreSQL fault answered "none". The check-then-insert is gone: the
  database refuses the duplicate, and a fault refuses the create. (B4)

- **A sign-in, the email form or the factory form could create a second
  actor for an address that has one.** ``Actor.get_from_creator`` read a
  listing fault as "no actor", and its callers created one. It raises now; a
  sign-in answers 503 and creates nothing. (B5)

- **A faulted peer-trustee read created a new peer actor.**
  ``Actor.get_peer_trustee`` read a fault as "no peer" and POSTed to the
  peer's factory, creating a peer actor and a reciprocal trust. It raises
  now, before any request. (B6)

- **A faulted read reset a subscription's callback queue.** The callback
  processor read its state, pending queue and sequence with folding reads, so
  a fault overwrote the queue and treated every callback as a gap. The reads
  raise before any write now, and ``POST /<id>/callbacks/subscriptions``
  answers 503 so the peer retries with the queue and state untouched. (B7)

- **``Actor.delete`` could delete an actor without notifying its peers.**
  The trust and subscription lists were read after the wipe had started, and
  a PostgreSQL fault answered "none", so the actor was deleted, its peers
  never told and their per-peer data orphaned. Both lists are read first now,
  strictly: a fault raises before ``Actor.delete`` writes its tombstone or
  removes anything. The ``DELETE /<id>`` route reads them before it writes its
  own tombstone and fires ``actor_deleted``, so a fault there answers 503 with
  nothing written either. (B8)

- **Two concurrent changes to one subscription could share a sequence
  number, and a failed diff could hand its number out again.** The publisher
  read the sequence, added 1 and wrote it back, so two writers both produced
  diff N + 1: PostgreSQL rejected the second (its change was lost without a
  gap) and DynamoDB overwrote the first. A diff that could not be stored also
  rolled the number back. Each diff's number is now allocated with one atomic
  update (``DbSubscription.increment_seq``), and a number whose diff was not
  stored stays a gap, as the protocol requires ("the sender MUST continue
  incrementing sequence numbers for each change"). A subscriber that
  ``register_diffs`` skips on a store fault also gets a gap, so it detects the
  missed change at the next diff and polls or resyncs. **Behavior change:**
  after a failed diff store the next diff carries the following number, not
  the same one again. When the sequence row itself cannot be reached no gap
  can be made: the write stands and the request answers 503 (it used to
  succeed with the change lost). Both backends
  now refuse a diff whose number already has one (DynamoDB overwrote it).
  Upgrade every worker before the 3.16 ones publish diffs: a 3.15 worker
  still writes the sequence as ``previous + 1`` and can move it back. A
  custom backend must implement ``increment_seq`` (see the migration guide).
  (D4, G4, D5)

- **Resuming suspended subscriptions could lose every change made while
  they were suspended.** ``resume_subscriptions()`` removed the suspension
  first and then read the subscribers with a folding read, so a fault there
  answered 0 resyncs, the same as "was not suspended", and a fault resyncing
  one subscriber stopped the rest. A retry found nothing suspended. Changes
  made during a suspension store no diff, so the resync is their only
  recovery. The subscribers are now read strictly before the suspension is
  removed, every subscriber gets its resync attempt, and if any faulted the
  suspension is put back and the fault raised. **Behavior change:** such a
  fault answers 503 and the call can be retried. A fault no retry can fix
  (an item over the backend's size limit) is logged as that subscriber's
  miss instead, and a resync that fails over HTTP is not counted: a return
  value below the number of subscribers means some did not get the resync.
  (A5, A6, C6)

- **On DynamoDB, ``GET /<id>/subscriptions/<peer>/<subid>`` listed diffs in
  key order.** Past sequence 9 the diffs came back as 1, 10, 11, 2, because
  the list was sorted into a result that was then thrown away. They are now
  in sequence order, as on PostgreSQL. (H5)

- **Deleting an outbound subscription could delete the peer's whole stored
  dataset.** ``Actor.delete_subscription`` counted the actor's other
  subscriptions to that peer, and a fault read as "none", so it deleted the
  ``RemotePeerStore`` bucket. The fault propagates now; neither the
  subscription nor the bucket is deleted. (B9)

- **A faulted read during a permission callback skipped revocation
  cleanup.** ``POST /<id>/callbacks/permissions/<peer>`` read the previous
  permissions, and a fault read as "first grant": revoked data was kept and
  everything was synced. The callback answers 503 now, before anything is
  stored or synced. (B10)

- **A faulted read reset an open circuit breaker.** The fan-out manager read
  a peer's persisted breaker, and a fault read as "no breaker": a fresh,
  closed one was created and persisted over the open one. That delivery is
  skipped now (``error="breaker_state_unreadable"``) and the stored state is
  left as it was. (B11)

- **An actor whose sign-in marker could not be read was ranked like an
  unvouched one.** With several actors sharing an address, a fault on the
  owner's vouched actor let a lower-id unvouched sibling (an attacker's
  actor renamed to the address, say) win the sign-in, be cleaned and then
  outrank the owner's for good. ``get_from_creator`` raises on an unreadable
  marker now, and the replacement creates a successor only when every actor
  left is a ``factory`` one: an unreadable one fails the sign-in. (BR)

- **Every sign-in read every factory actor for the address.** With an open
  factory anyone can add actors to an address faster than the per-sign-in
  cap removes them, and each sign-in read and loaded all of them (about
  three reads each) to remove ten; a fault on any of them failed it.
  ``get_by_creator(ids_only=True)`` now lists ids from the index alone, the
  lookup reads actors in id order only up to the first vouched one plus the
  cap, the listing is passed down instead of repeated, and a fault on an
  actor the sign-in will not touch no longer blocks it. (BS)

- **A fault reading the OAuth2 state encryption key replaced the key.** The
  state manager read the stored key inside a catch-all, so a throttle or
  timeout on the system actor's property read looked like "no key yet": a
  new key was generated and stored over the old one, and every MCP OAuth2
  authorization in flight on every instance then failed with an invalid
  state. A fault now fails the request (503) and leaves the stored key alone;
  the next request reads it. A faulted key write or system-actor load no
  longer falls back to an in-memory key either.

- **The default trust types could go missing after a store fault at
  startup.** The trust-type registry was published before its default types
  were registered, so a fault during that registration left a registry
  without them for the life of the process, and a permission check on a
  default type answered "not found". The registry is now published only once
  the defaults are in place; a fault fails the request and the next one
  registers them again.

- **A generated OAuth2 state key was written to the log.** When the state
  manager could not store a key it generated one in memory and logged it in
  full. It now logs that a non-persistent key is in use, not the key.

- **A list item over DynamoDB's 400 KB row cap failed with an untyped
  ``DbError("property write")``.** Nothing checked an item's size before
  the write, so the backend refused the row and the caller (and a REST
  client, as a 500) could not tell an oversized item from an outage; a v2
  list's first mutation had already created its meta row by then. Every
  item write (``append``, ``extend``, ``insert``, ``__setitem__``,
  ``update_by_handle``, on v1 and v2 lists) now measures the encoded item
  first and raises ``ListItemTooLargeError`` before anything is written,
  including the meta row of a never-created list; ``extend()`` checks the
  whole batch before its first write. On a v2 list an item over the span
  threshold now spans several rows (see ADDED); an item over
  ``list_item_max_bytes`` (4 MiB on DynamoDB), or a v1 list item over the
  span threshold, is refused. The REST handlers answer 413 with a
  structured body. **Behavior change:** a caller that caught ``DbError``
  for an oversized item gets ``ListItemTooLargeError`` (a ``ValueError``)
  instead, before any write, or the item is stored.

- The property-list module docstring said items were stored "bypassing the
  400KB limit"; each item is one row, so the limit applies per item, and
  the docstring now says so. ``get_metadata()``'s ``chunk_size`` is
  documented as a legacy field that is always ``1``. The configuration
  guide's "property lists for chunked storage" advice is reworded the same
  way. No behaviour change.

- The ``://`` prefix form of a permission pattern (``notes://``) is now
  matched through the glob path as ``notes://*`` instead of a separate
  ``startswith`` branch. No behaviour change: the two match the same
  targets, ``..`` segments included, and a pattern that already holds a
  wildcard (``*://``) is left as written. The access-control guide and the
  security reference now say that resource URIs are not normalised and a
  resource reader validates its own path.

- **Adoption follow-ups.** A listing by creator dropped no row that the
  DynamoDB index still listed after a rename (it now reads each row's
  creator); a second sign-in meeting a ``factory`` sibling that another one
  was wiping wiped it again (it is now left to that one); a nested
  replacement reported only its own level in ``actor_adopted``; a
  replacement scanned the shared SPA token buckets once per actor (now one
  pass); a successor whose create raised was never announced (the next
  verified sign-in for the creator fires ``actor_adopted`` with the old id,
  its counts ``None``: one that creates the actor, one that cleans the
  actor the email form created meanwhile, whose own unverified create
  announces nothing, or one that replaces a ``factory`` actor created
  meanwhile, or any later sign-in to the creator's vouched actor; the
  record keeps every unannounced replacement, so a sign-in that fails after
  recording its own loses none, and a fault writing it fails the sign-in
  before anything is removed; like ``actor_deleted`` it is not exactly
  once: a concurrent sign-in for the creator can announce a replacement
  twice, a crash between the claim and the hook loses it, and an
  unannounced record expires after seven days); a summary read that faulted
  reported nothing removed (the counts are now ``None``, unknown); the
  provider bookkeeping writes on three sign-in paths failed the sign-in on a
  fault (they are logged). **Behavior change:** ``actor_adopted``'s
  ``removed_trusts``, ``removed_subscription_peers`` and ``property_names``
  can be ``None``, and a sign-in that completes an earlier failed
  replacement while adopting another actor fires ``actor_adopted`` more
  than once: one per earlier replacement (``mode="replaced"``), then its
  own.

- **``force_email_prop_as_creator`` renamed an unvouched actor's creator
  at load.** ``Actor.get`` copied ``store.email`` into the creator of every
  actor whose two differed, so an address a previous creator wrote was
  restored before adoption could clean it. It now does so only for a vouched
  actor.

- **A rejected sign-in kept the provider's tokens.** The OAuth callback,
  both SPA completions and the email form wrote the provider's access and
  refresh tokens onto the actor before ``oauth_success`` ran, so an
  application that rejected the sign-in still had them stored. They are now
  written only once the hook accepts. A replacement reads the victim's
  trusts and subscriptions before revoking its tokens, so a read fault
  leaves the victim's sessions in place.

- **The MCP bridge counted a concurrent create as the winner when the
  tombstone could not be read.** It now answers 503.

- **Two fan-out comments said the subscription circuit breaker was shared
  through persistence.** It is per process; persisted state only seeds a new
  process. ``docs/quickstart/deployment.rst`` says so.

v3.15.1: September 29, 2026
---------------------------

SECURITY
~~~~~~~~

- **Logging out of an SPA session, or revoking a token, left the refresh
  chain alive.** ``POST /oauth/logout`` with a session token deleted only
  the access-token row, and ``POST /oauth/revoke`` deleted only the row it
  was given, so the refresh token kept working for up to its 14-day TTL.
  Revoking a *used* refresh token was worse than nothing: it removed the row
  that would have caught a thief who had already rotated, and left the live
  successor. Both endpoints now end the whole refresh-token chain (access
  token, refresh token and every rotated successor) through the new
  ``OAuth2SessionManager.revoke_session``. Another device of the same user
  has its own chain and keeps working. **Behavior change:** the v3.15
  migration guide's line "``/oauth/logout`` with an SPA session token is
  unchanged" no longer holds. This covers the www UI's cookie logout too, and
  a token with no chain (the www cookie login, and any token issued before
  3.15.1) still revokes only itself. **Behavior change:** login access tokens
  now carry their chain id (the passphrase, authorization-code, JWT bearer
  and mobile ticket grants, and both provider callbacks),
  so an access token is a handle for ending its chain and the theft response
  revokes it as well. An access token issued before 3.15.1 has no chain, so a
  session that began before the upgrade is ended only by its refresh token
  until its next rotation. **Known limitation:** a refresh already in flight
  when the logout runs can mint its successor tokens after the chain was
  deleted, so a 200 logout can leave one live pair for that chain (a
  millisecond window; a client should not refresh while logging out, and a
  second logout or revoke ends it). Reported by the Emm AI client, twice.

- **The SPA theft response could answer "session revoked" over a chain it
  had not revoked.** On refresh-token reuse,
  ``OAuth2SessionManager.revoke_token_chain`` called ``delete_by_chain`` with
  no fault handling. PostgreSQL's ``delete_by_chain`` answers 0 on a fault,
  so the handler still answered 401 "session revoked for security" while the
  thief's branch survived; DynamoDB's raises part-way and answered a
  framework 500 with the MCP cache eviction skipped. **Behavior change:** a
  fault now answers **503** with ``Retry-After: 5``, keeps the presented
  (used) token in place as the retry handle, and evicts the caches
  regardless, as the MCP token store's theft response has done since 3.15. A
  revocation that a concurrent request already finished still answers 401
  "revoked". A chain-less legacy token goes through the same confirmed delete
  instead of reporting success for an unconfirmed one.

CHANGED
~~~~~~~

- **Revoke and logout follow the 3.15 fault contract.** A token-store fault
  used to read as "unknown token": ``/oauth/revoke`` swallowed every
  exception and answered 200 with the cookies cleared, and ``/oauth/logout``
  looked the session up with a read that returned ``None`` on a fault and
  reported success. **Behavior change:** both answer **503** with
  ``Retry-After: 5``, revoke nothing, clear no cookie, and leave the
  presented token valid for the retry; a client must clear its local tokens
  only after a 2xx (RFC 7009 §2.2.1). The bodies keep their endpoint's
  shape: logout answers ``{"success": false, "error":
  "temporarily_unavailable"}``, revoke and ``/oauth/spa/token`` answer
  ``{"error": true, "status_code": 503}``. An unknown token still answers
  200 (RFC 7009 §2.2). The stored provider token is cleared for the actor
  only after a confirmed revoke, and for every device of that actor (by
  ``/oauth/revoke`` and a POST logout; a GET logout leaves it alone). Only
  the provider access token is cleared; the provider refresh token in
  ``actor.store.oauth_refresh_token`` stays, and nothing in the library reads
  it. **Behavior change:** ``/oauth/revoke`` no longer catches a bug in its own
  code; that now surfaces as the framework's 500 instead of a false 200.
  **Behavior change:** ``/oauth/logout`` no longer answers 200 "Logged out
  (token revocation failed)" with the cookies cleared when its own code hits
  an unexpected error; it answers 500 and clears no cookie, so the client
  keeps its retry handle and never reads a logout that did not happen as done.

- **Logout also accepts the refresh token, and clears the right cookies.**
  An access token expires after an hour and its expired row cannot be read,
  so logout after an idle hour had no chain to end. **Behavior change:** POST
  a JSON body ``{"refresh_token": "..."}`` (a form field of the same name is
  accepted), or send the ``refresh_token`` cookie on any method. With no
  access token the refresh token alone drives the revocation; with both,
  each is revoked, so two different chains both end. A missing, empty or
  malformed body is ignored, never a 400. **Behavior change:** the cookies
  cleared are now ``access_token``, ``oauth_token``, ``refresh_token`` and
  ``session_id`` at ``/`` plus ``refresh_token`` at ``/oauth/spa/token``. The
  list named ``oauth_refresh_token`` before, which nothing ever set, so a
  cookie-mode browser kept its refresh cookie after logout. The response's
  ``cleared_cookies`` lists those four names. ``GET /oauth/logout`` ends the
  chain too; a cross-site navigation carrying the ``SameSite=Lax`` cookies
  can therefore force one device's logout, which exposes nothing; a GET
  leaves the actor's stored provider token alone, and only a POST logout (or
  ``/oauth/revoke``) clears it.
  ``/oauth/revoke`` likewise reads the ``refresh_token`` cookie when the
  body and the ``Authorization`` header carry no token, and a token the hint
  does not locate is searched for in the other token type (RFC 7009 §2.1); an
  unrecognised hint is ignored.

- **FastAPI's logout route now returns the handler's response on every
  path.** The route rewrote it: with an ``oauth_token`` cookie it answered
  200 and deleted the cookie whatever the handler said (a 503 included), and
  a request carrying only a refresh token never reached the handler.
  **Behavior change:** the route always delegates and passes the handler's
  status, ``Retry-After`` and ``Set-Cookie`` headers through. A browser form
  post or link carrying the ``oauth_token`` cookie still gets the 302 to
  ``/``, only after a successful logout, and the redirect carries the
  handler's cookie clears. A fault answers JSON 503 and keeps the cookie, so
  a www UI cookie logout that hits a fault is a 503 now, where it used to
  redirect. A request with no token at all answers the handler's
  ``{"success": true, "message": "Successfully logged out"}`` with the
  cookies cleared, where the route answered ``{"message": "No active session
  to logout"}``. Flask already delegated and needed no change.

- **CORS on the SPA endpoints and logout honours the origin allowlist and
  exposes Retry-After.** Both integrations echoed any ``Origin`` with
  ``Access-Control-Allow-Credentials: true`` on logout and the SPA
  endpoints, discarding the ``spa_cors_origins`` allowlist the handler
  computes, and a cross-origin browser could not read the ``Retry-After`` of
  a 503. **Behavior change:** a shared ``spa_cors_headers`` builder applies
  the allowlist everywhere, and every response lists
  ``Access-Control-Expose-Headers: Retry-After``, including the refresh
  grant's 3.15.0 503. The default is ``["*"]``, so only a deployment that
  called ``with_spa_cors_origins()`` changes, and it changes to what it
  configured: an origin outside the list gets the first allowed origin, and
  a browser blocks the response. Check that the list contains your SPA's
  real origin. The FastAPI ``OPTIONS /oauth/spa/logout`` preflight, which
  answered ``*`` with credentials and so failed in a browser, now answers
  like ``/oauth/logout``.

- **A failed access-token write now raises.** ``store_access_token`` handed
  out a token that validated nowhere when the write failed. **Behavior
  change:** it raises ``TokenStoreUnavailable``, as ``create_refresh_token``
  does, and the SPA handler's ``_generate_actingweb_token`` no longer
  swallows it. The login access token is the logout handle now, so a token
  that was never stored must not be issued. **Behavior change:** the SPA
  login grants (authorization code, JWT bearer and mobile ticket, passphrase)
  answer **503** with ``Retry-After: 5`` on a store fault, as the refresh
  grant does; before, a fault there was a framework 500. The provider
  callbacks and the www cookie login (no refresh token) gain a 500 on a store
  fault where the cookie login used to set an unusable cookie.

- **The chain revocation method takes an anchor and logs INFO.**
  **Behavior change:** ``OAuth2SessionManager.revoke_token_chain`` has a new
  keyword-only ``anchor=(bucket, name)`` naming the presented row, which is
  deleted last; with it a fault raises ``TokenStoreUnavailable`` and a chain
  a concurrent request already revoked returns 0. PostgreSQL's
  ``delete_by_chain`` now raises on an error, as DynamoDB's does, instead of
  answering 0 (this revocation path is its only caller). Without it the method
  still returns 0 and never raises for a zero delete. It logs at INFO; the
  WARNING moved to the theft handler, the one caller that wants it.
  ``revoke_access_token`` and ``revoke_refresh_token`` are single-row and
  fault-blind; they are kept for compatibility, and library paths use
  ``revoke_session``.

- **The SDK logout answers retry on a store fault.**
  ``OAuth2Server.handle_logout_request`` answered ``action: "success"`` with
  the cookies to clear while the token was still valid. **Behavior change:**
  a fault while validating or revoking returns ``{"action": "retry",
  "message": ..., "retry_after": 5}`` with no ``clear_cookies``, and its
  ``clear_cookies`` names are the four above. An SDK caller that branches on
  ``action`` should handle ``retry``.

- **Operations: chain revocation on DynamoDB scans the two SPA token
  buckets once per logout or revoke.** ``delete_by_chain`` has no index on
  the JSON-embedded ``chain_id`` there; PostgreSQL uses one. That was
  acceptable for a rare theft event and is now routine. It stays cheap while
  the two buckets together are under about 1 MB (about 3,000 rows, one page
  each, at most about 250 read units per call; a production deployment
  measured 42 rows and a few read units). A WARNING is logged once per call
  when one bucket holds more than 1,000 rows; that is the signal to promote
  ``chain_id`` to a top-level attribute with a global secondary index, the
  named growth path. The scan also reads ``bucket:`` as its prefix now, so a
  sibling bucket that shares the name is no longer read, and a bucket whose
  query cannot be built raises instead of being skipped.

- **The expired-token cleanup returns a skipped count.** **Behavior
  change:** the dictionary ``cleanup_expired_tokens()`` returns has a new
  ``skipped`` key (see FIXED).

ADDED
~~~~~

- ``OAuth2SessionManager.revoke_session(token, *, token_type_hint=...)``, the
  one entry point logout and ``/oauth/revoke`` use: a strict read in the
  hinted bucket then the other, the whole chain ended when the row has one,
  and the revoked row's data returned so the caller can clear the provider
  token after a confirmed revoke (a row whose payload is not a mapping is
  removed and answered as an empty dict). It raises ``TokenStoreUnavailable``
  on a fault. ``OAuth2SessionManager.new_chain_id()`` starts a chain for a login
  pair, and ``actingweb.handlers.oauth2_spa.spa_cors_headers`` builds the SPA
  CORS headers. ``actingweb.single_use.revoke_chain_confirmed`` is the
  internal core both token stores share.

FIXED
~~~~~

- **A store fault during an MCP code exchange answered invalid_grant.** The
  auth-code and provider-token lookups ended in ``except Exception: return
  None``, so a transient fault read as "no such code" and the client redid
  the consent redirect. **Behavior change:** they read strictly and the token
  endpoint answers ``server_error`` (500, retryable), and the code stays
  exchangeable: the provider-token read now happens before the code is
  consumed. This also corrects the 3.15.0 entry below, which says the SPA
  refresh grant answers 503 "as ``/oauth/token`` does": ``/oauth/token``
  answers ``server_error``; ``Retry-After`` on a 503 is the SPA grant's own
  convention. Upgrading ``/oauth/token`` to 503 is not part of this release.

- **The scheduled cleanup orphaned TTL-past rows and aborted on one fault.**
  ``cleanup_expired_tokens()`` removed the index row of a token it could not
  find and left its actor row behind, and read a transient fault as "the
  token is gone", which deleted a live authorization code's index row.
  **Behavior change:** every row is classified with a strict read. A row that
  reads as absent has its index row and its actor row removed by name (an
  actor row's TTL is never longer than its index row's, so nothing live is
  hidden); a row or index it cannot read is left alone and counted under
  ``skipped``, and the sweep goes on. A consumed refresh token past the reuse
  window and an access token past its ``expires_at`` are removed as before.
  Only confirmed deletes are counted as removed: the actor row goes first and
  its index row only after that delete is confirmed, so a delete the store did
  not perform is counted under ``skipped`` and retried by the next run, and a
  row whose payload is not a mapping is left alone and counted as skipped.

- **Deleting a client skipped cache eviction when a token delete raised, and
  bumped the cache generation once per token.** **Behavior change:**
  ``revoke_client_tokens`` evicts each token's cache entry whatever its
  delete did, and the actor's caches once per client.

- **Removing an expired MCP access token deleted the actor row before the
  index row, and re-read an owner it already had.** **Behavior change:** the
  index row goes first in both branches, so the token stops validating on
  every worker whatever happens to the rows below, and the actor row's delete
  is confirmed. A removal the store could not confirm now answers ``False``
  where the fallback branch reported success.

v3.15.0: September 28, 2026
---------------------------

.. note::

   **This is a security release for the MCP OAuth2 server and the trust
   API.** The trust list stops returning peer secrets, MCP refresh tokens
   become single-use with reuse detection, public MCP clients (such as
   Codex) work, and PKCE is enforced on the built-in sign-in pages. The
   refresh-token grace period becomes a setting, and the SPA guide gains how
   native clients avoid being signed out when a refresh response is lost to
   sleep. Most applications need to check three things; see
   ``docs/migration/v3.15.rst``, which starts with the list.

SECURITY
~~~~~~~~

- **Peer-proxy DEBUG logs no longer contain the request body.**
  ``AwProxy.create_resource``, ``change_resource`` and their async twins
  logged the full JSON body of every remote-method call, property write and
  action sent to a peer at DEBUG, so user- and agent-supplied values reached
  the logs verbatim. Those four lines, the ``/oauth/authorize`` parameter
  and server-response lines, and the FastAPI trust-parameter lines now log a
  summary: the sorted key names (at most 20) and the serialised byte length.
  Key names of a ``/properties`` write are the property names; keep the
  ``actingweb.aw_proxy`` logger above DEBUG if those are sensitive. A
  consumer that quieted ``actingweb.aw_proxy`` to hide bodies can drop that
  override. ``OAuth2ClientManager.regenerate_client_secret`` also stopped
  logging the new and stored secret when its read-back check fails.

- **The async reciprocal-trust request logged the new trust secret at
  INFO.** ``Actor.create_reciprocal_trust_async`` logged its whole request
  body, which carries the relationship's ``secret`` and
  ``verification_token``, at INFO, so both reached production logs at the
  default level. It now logs the same key-name summary as the proxy. The
  subscription-create and subscription-callback bodies and the peer-info
  responses in ``actor.py`` (DEBUG) are summarised too. The MCP token
  manager masked authorization codes only in the exchange: the code lookup
  and removal helpers, the provider-token rows (whose names embed the code)
  and client-token revocation logged live codes and tokens in full at
  DEBUG, WARNING and ERROR; they now log the first eight characters. The
  FastAPI integration's DEBUG lines for the decrypted MCP OAuth state and the
  authorize template values log a summary. Key names in every summary are
  sanitised and capped at 64 characters, because a peer chooses them. Check
  retained logs from
  deployments running INFO or lower for ``Requesting trust relationship
  async``.

- **``GET /{actor_id}/trust`` no longer returns peer credentials.** Every
  row of the trust list carried the relationship's ``secret`` (the peer's
  bearer credential) and ``verification_token``, so a browser session or SPA
  cache that fetched the list held every peer's secret. **Behavior change:**
  the list omits both fields; the per-relationship
  ``GET /{actor_id}/trust/{relationship}/{peerid}`` still returns them to
  creator and admin, as the protocol spec requires. Code that read
  ``secret`` from the list must read the relationship URI instead.

- **PKCE is now bound on the library's own MCP authorize paths.**
  ``GET`` and ``POST /oauth/authorize`` never read ``code_challenge``, so an
  authorization code issued through the provider sign-in buttons or the
  email form was not bound to the client's verifier, and a public client's
  code could be exchanged without one. Both paths now read the challenge,
  echo it through the form and the provider state, and store it with the
  ``redirect_uri`` on the code; exchange verifies the verifier and refuses a
  different ``redirect_uri``. **Behavior change:** these paths accept
  ``code_challenge_method=S256`` only; ``plain``, or a challenge without a
  method, is ``invalid_request``, and the challenge must be 43–128
  unreserved characters. Exchange still accepts a ``plain`` challenge that
  was stored explicitly through ``create_authorization_code``. A custom
  ``aw-oauth-authorization-form.html`` must keep the two hidden inputs
  ``code_challenge`` and ``code_challenge_method``.

- **MCP refresh tokens rotate and are single-use; authorization codes are
  single-use atomically.** A refresh returned the same refresh token
  forever, and the step meant to revoke the previous access token was a
  no-op that logged a WARNING on every refresh. **Behavior change:** each
  refresh returns a new ``refresh_token`` and consumes the presented one;
  the previous access token is revoked. A consumed token presented again
  within 60 seconds rotates again (a retry or a lost response); within two
  days it is treated as theft, every token in its chain is revoked and the
  grant answers ``invalid_grant``; after that it answers ``invalid_grant``
  without revoking. The 60 seconds is the default grace period, shared with
  the SPA refresh grant and configurable downwards with
  ``with_refresh_token_grace()`` (see ADDED). A refresh token issued before
  3.15 joins a chain on its first rotation and is covered from then on. If
  the store cannot complete a theft revocation, the grant answers
  ``server_error`` and leaves the replayed token in place for the next
  presentation to retry from, rather than report the chain revoked.
  A store fault while an MCP refresh token or
  an authorization code is being consumed answers ``server_error`` and
  leaves it usable; it is never read as "already used" (the SPA refresh
  endpoint now answers 503 on such a fault; see FIXED). Revocation removes a
  token's index row first, unconditionally, so a token being revoked is
  unusable on every worker at once even when the store then faults; what a
  fault leaves behind is cleanup (the actor row, reaped by TTL or the
  purge). ``/oauth/logout`` answers such a fault with **503** and
  ``Retry-After: 5``, clearing no cookies, so the client logs out again and
  confirms. The one case a token survives a fault is when its **chain**
  could not be revoked: the presented token is then kept as the handle to
  the chain and stays valid until the client logs out again with it, which
  revokes the chain. Revoking an MCP token
  (``/oauth/logout`` with an MCP bearer token, or ``revoke_token``) revokes
  every token in its chain, consumed ones included, so a consumed refresh
  token cannot rotate after its successor was revoked. **Behavior change:**
  ``/oauth/logout`` with an MCP bearer token now revokes it in the MCP
  token store; before, the route knew only the SPA session store and the
  MCP token and its chain stayed live. SPA session tokens keep their
  existing logout path. MCP clients must store the refresh token from every
  response. Revocation clears this process's MCP token cache only: another
  worker or container may honour a revoked access token from its own cache
  for up to 300 seconds. Two concurrent exchanges of one authorization code
  now mint exactly one token pair, and a wrong PKCE verifier burns the code.

- **An unauthenticated MCP ``initialize`` could name another user's
  connection.** ``initialize`` cached ``clientInfo`` under the client's
  ``Mcp-Session-Id`` or, without one, under a key shared by every client
  with the same User-Agent prefix; the OAuth callback then copied the most
  recent cached entry, whatever its key, into the trust row of whoever had
  just signed in, and the web OAuth callback read the shared key too. So
  anyone could put text into another user's trust row (``client_name``,
  ``client_version``, the default ``desc``) and into the live ``clientInfo``
  handed to their tools. The callbacks no longer write client info; the
  trust row is named by the client's authenticated ``initialize``. The cache
  is keyed only by ``Mcp-Session-Id`` or, after authentication, by the
  bearer token, is bounded and thread-safe, and a request that carries a
  bearer token reads its token entry first, since the session id is chosen
  by the client. A session entry belongs to the actor whose authenticated
  ``initialize`` wrote it (or whose request first used it): an
  unauthenticated ``initialize`` cannot replace it while it is in use, and
  another actor's request ignores it. Every string in the cached ``clientInfo`` is sanitised, not
  only the name and version: ``title`` is capped like the name, and other
  strings, nested ones included, at 200 characters. **Behavior change:** a request without
  ``Mcp-Session-Id`` gets no cached ``clientInfo`` until the client sends an
  authenticated ``initialize``.

- **Client-supplied names are sanitised.** ``clientInfo`` name and version,
  the dynamic-registration ``client_name`` and the User-Agent used as
  ``client_platform`` reached trust rows, logs and applications raw; a name
  carrying newlines added lines to text an LLM reads. They are now stripped
  of control and format characters (U+200C and U+200D kept), whitespace is
  collapsed, and names are capped at 80 characters (platform at 200) before
  they are stored, logged or returned. **Behavior change:** both trust GET
  routes apply the same rule on the way out, to rows stored before 3.15,
  and strip (never cap) ``desc`` — for every trust row, peers' included.
  The rule is ``actingweb.client_text``.

CHANGED
~~~~~~~

- **Breaking: ``secret`` and ``verification_token`` are no longer in the
  ``GET /{actor_id}/trust`` response.** See SECURITY. The protocol spec's
  list example is updated; read credentials from the relationship URI.

- **Breaking: MCP refresh tokens are single-use.** A client that keeps
  presenting its first refresh token works once, then reads as theft and
  loses its chain. See SECURITY and the migration guide.

- **Public MCP clients are supported.** Dynamic registration honours
  ``token_endpoint_auth_method: none``: the client gets no
  ``client_secret``, must use PKCE, may refresh without a secret, and is
  refused the ``client_credentials`` grant with ``unauthorized_client``.
  Confidential registrations now include ``client_secret_expires_at: 0``.
  An unknown auth method is refused with ``invalid_client_metadata``
  (RFC 7591), as is a ``client_name`` that is empty after sanitising.
  ``OAuth2ClientManager.create_client(token_endpoint_auth_method="none")``
  creates one; ``regenerate_client_secret`` raises ``ValueError`` for it.

- **A token-store fault answers 503 on ``/mcp``, not 401.** The MCP token
  lookups read the store strictly and raise the new
  ``actingweb.oauth2_server.TokenStoreUnavailable`` when it cannot be read;
  before, a throttle or connection error read as "no such token".
  **Behavior change:** ``GET /mcp`` and the JSON-RPC ``POST /mcp`` answer
  503 with ``Retry-After: 5`` during a store outage (cached tokens keep
  working), with both the Flask and the FastAPI integration; ``/oauth/token``
  answers 500 ``server_error`` rather than ``invalid_grant`` or 401
  ``invalid_client`` (the client registration is read strictly too), so
  clients keep their refresh token and their registration.
  ``validate_access_token`` and ``validate_mcp_token`` raise it; callers
  that guard ``/mcp`` should fail closed on it.

- **``Attributes.loaded``** tells an empty bucket from a failed read after
  ``get_bucket()``, which returns ``{}`` for both. Use it instead of the
  private ``_bucket_loaded``.

- **``/oauth/token`` runs a throttled purge of expired MCP token rows**
  (at most once an hour per process, before the grant so a slow purge never
  delays a rotated token's response; PostgreSQL only, DynamoDB relies on
  native TTL). ``cleanup_expired_tokens()`` also sweeps provider-token
  rows, and its result gains a ``provider_tokens`` count; the actor rows of
  expired and consumed tokens are removed by that purge (PostgreSQL) or by
  native TTL (DynamoDB).

- **Additive keyword arguments:** ``create_authorization_code(redirect_uri=)``,
  ``exchange_authorization_code(redirect_uri=)``,
  ``MCPHandler.clear_token_from_cache(actor_wide=)`` and
  ``evict_caches_for_token(actor_wide=)``. The attribute backend protocol
  gains ``conditional_update_attr(ttl_seconds=)`` (the same conditional
  write sets the row's TTL, never re-creating a deleted row) and
  ``delete_by_chain(defer_name=)`` (a row-by-row backend deletes that row
  last); both built-in backends implement them, and a custom backend must
  accept them. New constants
  ``MCP_REFRESH_TOKEN_GRACE_PERIOD`` (60), ``MCP_REFRESH_TOKEN_REUSE_WINDOW``
  (two days) and ``MCP_TOKEN_PURGE_INTERVAL`` (one hour).

- **The agent workflow instructions in ``CLAUDE.md`` now follow the shared
  contract the slash commands read**: one ``## Workflow`` section listing the
  check tiers (Fast and Full, both database backends), how to start the
  reference app for browser QA, the CI re-trigger policy, tool pins, and
  the changelog and release recipes, with per-command addenda under
  ``.claude/workflow/``. The former "Quick Reference", "Release Process",
  "Quality Standards", "Testing" and "Project Documentation System"
  sections are folded into it without loss. ``thoughts/`` gains a
  ``features/`` directory for ``/plan_feature`` documents, matching the
  ``actingweb_mcp`` repository. No library code changes.

ADDED
~~~~~

- **The refresh-token grace period is a deployment setting.**
  ``ActingWebApp.with_refresh_token_grace(seconds)`` sets
  ``Config.refresh_token_grace_period``, the time after a refresh token is
  consumed during which presenting it again rotates again instead of
  counting as theft. It applies to both the SPA (``/oauth/spa/token``) and
  the MCP (``/oauth/token``) refresh grants, which both hard-coded 60
  seconds. The default stays 60 seconds, which is also the ceiling (Okta's
  maximum for the same setting); a value outside 0 to 60, or one that is not
  an integer, raises ``ValueError`` wherever it is set: the builder,
  ``Config(...)``, or an assignment to the attribute. A lower value narrows
  the window in which a copied token yields a new branch of its chain, which
  reuse detection flags only if that branch later replays one of its own
  consumed tokens. ``0`` means no grace: every reuse of a consumed token
  inside the two-day reuse window is answered as theft and its chain
  revoked, which also signs out a client's own concurrent duplicate refresh
  and a client retrying a refresh that consumed its token but failed to
  store the new one. Of two
  requests presenting the same token at once, the one that consumed it may
  keep its new tokens, depending on whether it creates them before or after
  the other revokes the chain, so ``0`` stops a later replay, not reliably
  a simultaneous one; use it only with clients that single-flight their
  refreshes. No value covers a client that loses a
  refresh response across a device sleep: the SPA guide gains "Refreshing
  reliably on native and mobile clients", which describes how a client
  avoids that lockout, and the troubleshooting guide gains the symptom.
  Deployments that do not call the method behave as before.

FIXED
~~~~~

- **Codex and other public MCP clients failed every refresh with
  ``invalid_client``.** Registration ignored ``token_endpoint_auth_method:
  none`` and issued a secret, and the token endpoint turned an absent secret
  into ``""``, which the refresh grant compared and rejected. Fixed by the
  public-client support above. **Connectors registered before 3.15 stay
  confidential clients**: one that refreshes without its issued secret
  keeps failing until it is removed and added again, which registers it
  afresh (signing in again reuses the old registration). Clients that send
  the secret, such as ChatGPT, claude.ai and Claude Code, are not
  affected.

- **``/oauth/token`` reported every 400 as ``invalid_request``.** The error
  body was rebuilt from the status, so ``invalid_grant`` (a dead refresh
  token), ``unsupported_grant_type`` and ``unauthorized_client`` reached
  clients as ``invalid_request``. The body now carries the server's error
  code (RFC 6749 §5.2).

- **The scheduled MCP token cleanup deleted live index rows on a store
  fault.** ``cleanup_expired_tokens()`` read each indexed token through a
  lookup that answered "absent" when the store could not be read, and then
  removed the index row, orphaning a valid token until it expired. The
  lookup now raises ``TokenStoreUnavailable`` on a fault, so the scheduled
  job fails loudly and removes nothing it could not read; rerun it.

- **HTTP Basic client credentials were ignored when the body also carried
  ``client_id``.** The ``Authorization: Basic`` header is now read whenever
  present and form-urldecoded (RFC 6749 §2.3.1). A body ``client_id`` or
  ``client_secret`` that differs from the header's is ``invalid_request``;
  identical values in both places are accepted.

- **Deleting an MCP client could silently leave its tokens.**
  ``revoke_client_tokens`` read the client's token buckets with a read that
  answers "empty" on a store fault, so a delete during a throttle revoked
  nothing and logged "Revoked 0 tokens". It now raises
  ``TokenStoreUnavailable`` after revoking what it could read, and counts
  only deletes it could confirm (DynamoDB reports a failed delete as a
  success). Each revoked access token is also dropped from this process's
  MCP token cache (other workers keep theirs up to 300 seconds).
  ``delete_client`` still deletes the client, which is what
  disables its refresh tokens, and logs at ERROR that unrevoked access
  tokens expire within an hour. **Behavior change:** it confirms the client
  row and its index row are gone, and answers ``False`` when neither is,
  instead of reporting success for a client that can still authenticate.

- **A token-store fault on the SPA refresh grant signed the client out.**
  ``/oauth/spa/token`` answered a store it could not read, a consume it
  could not confirm, and a rotated token it could not store with 401
  "Invalid or expired refresh_token", the answer for a dead token, and a
  client that treats 401 on refresh as final signed the user out on a
  transient throttle with the token untouched. A refresh token whose write
  answered ``False`` was also handed out unstored, so the next refresh got
  that 401. **Behavior change:** the grant answers **503** with
  ``Retry-After: 5`` and "Token store temporarily unavailable; retry", as
  ``/oauth/token`` does, and both the FastAPI and Flask integrations now
  pass ``Retry-After`` through. A client should keep its token and retry
  after that many seconds: a read or consume fault leaves the token
  untouched, and after a fault storing the successor a retry inside the
  grace period rotates again. **Behavior change:**
  ``OAuth2SessionManager.try_mark_refresh_token_used`` and
  ``create_refresh_token`` raise ``TokenStoreUnavailable`` on a store fault
  instead of answering "unknown token" or returning an unstored token;
  code calling them directly should catch it. Reported by the Emm AI
  client while reviewing the 3.15 refresh guidance.

- **An expired SPA refresh token could revoke its whole chain.** The SPA
  token store checked whether a presented refresh token was already used
  before checking whether it had expired. A consumed token presented after
  its own ``expires_at``, but inside the two-day reuse window, therefore
  reached the reuse ladder, was read as theft, and revoked its chain,
  logging out the device holding the current token. The store now checks
  expiry first, as the MCP token store already did: such a token answers
  401 "Invalid or expired refresh_token" and its row is removed.
  **Behavior change:** a consumed SPA refresh token replayed after its own
  expiry is no longer treated as theft; it is refused without revoking the
  chain.

v3.14.7: September 14, 2026
----------------------------

SECURITY
~~~~~~~~

- **``cryptography`` floor raised to ``>= 50.0.0``** (was ``>= 48.0.1``).
  Versions 44.0.0 through 49.x expose a Bleichenbacher oracle in PKCS#7
  ``EnvelopedData`` decryption (CVE-2026-69247, GHSA-g6cj-pr64-35w5).
  ActingWeb itself never calls the affected ``pkcs7_decrypt_*`` APIs -- it
  uses ``Fernet`` and PEM private-key loading only -- so no ActingWeb code
  path was exploitable, but the library pulled the vulnerable range into
  every consumer's environment and Dependabot flagged both ``poetry.lock``
  and ``docs/requirements.txt``. Both now resolve to ``cryptography``
  50.0.1. Consumers pinned below 50.0.0 will see a resolver conflict on
  upgrade and should lift their pin. ``cryptography`` 50 also *deprecates*
  finite-field Diffie-Hellman (``asymmetric.dh``); ActingWeb does not use
  it, but an application importing it will now get a deprecation warning
  from the shared dependency.

- **``pyjwt`` floor raised to ``^2.14`` (was ``^2.13``).** 2.14.0 is a
  security release: it hardens HMAC key validation against public-key
  material supplied as a key (the algorithm-confusion class,
  GHSA-r6x4-923q-g947 and related), stops ``PyJWKClient`` following
  redirects to untrusted JWKS hosts, bounds JWKS refreshes on unknown key
  IDs, and rejects malformed or deeply nested JWS/JWK input without
  uncaught recursion. ActingWeb decodes and verifies provider ID tokens
  through ``pyjwt`` (``oauth2_id_token.py``; the JWKS fetch itself is
  ActingWeb's own ``oauth2_jwks`` module, so the ``PyJWKClient`` fixes do
  not apply to it) and signs Apple client secrets with it, so consumers
  get the JWS/JWK parsing and HMAC-key hardening by upgrading. Consumers
  pinned to ``pyjwt`` 2.13.x will see a resolver conflict on upgrade and
  should lift their pin.

- **Lock file refreshed.** All other dependencies updated to the newest
  releases within their existing constraints, notably ``fastapi`` 0.139.0
  → 0.141.1, ``starlette`` 1.3.1 → 1.6.0, ``uvicorn`` 0.50.0 → 0.53.0,
  ``boto3``/``botocore`` 1.43.40 → 1.43.93, ``psycopg`` 3.3.4 → 3.3.5,
  ``sqlalchemy`` 2.0.51 → 2.0.52, ``alembic`` 1.18.5 → 1.20.0. No
  constraint other than ``cryptography`` and ``pyjwt`` changed, so
  consumers on the previous lock are unaffected until they re-resolve.

FIXED
~~~~~

- **A v2 list mutation could raise after its item write had committed.**
  Every v2 ``ListProperty`` mutator writes its item row and then makes an
  advisory metadata touch (``updated_at``/``count_hint``); the touch's
  ``advisory=True`` swallowed compare-and-swap contention only, so a
  genuine backend fault (a throttle, timeout, or connection error) during
  the touch still raised — out of a mutation whose item write had already
  committed. A caller that retried on that exception duplicated its own
  save, got ``not_found`` against its own delete, or lost one side of a
  move. Backend faults during the touch are now logged at WARNING and
  swallowed on every v2 item mutator, including ``pop()`` (which still
  returns the popped item), ``remove_where()``/``update_where()`` (which
  still return their partial results), and ``NotifyingListProperty``
  (which still registers its subscription diff). **Behavior change:** a v2
  mutation whose metadata touch hits a backend fault now returns success
  and logs one WARNING instead of raising; the advisory ``count_hint`` may
  be off by one until the next rank-counting mutation or ``compact()``.

- **A list's first mutation could leave item rows with no meta row.** Under
  v2 there is no separate creation step — a list's first ``append()``/
  ``extend()``/``insert()`` created its meta row as a side effect of the
  advisory touch, *after* the item write. A fault on that touch left item
  rows with no meta row: invisible to ``exists()``/``list_all()``/the REST
  handlers, called healthy by ``verify()``, and swept as residue by the
  next ``delete()``/``clear()``/``migrate_to_v2()``. A list's first
  mutation now creates its meta row, conditionally, *before* its first
  item write; the one remaining way to get this orphan is a ``delete()``
  racing the first mutation while the touch's recreation write also
  faults, which is now logged and which ``verify()`` reports (see below).
  **Behavior change:** a fault on the item write of a list's first
  ``append()``/``extend()``/``insert()`` now leaves an empty, visible list
  where it previously left nothing; a lost meta-row create (another writer
  created the row first, and it is not v2) raises
  ``ListMetadataContentionError`` before any item write, mapped to 503
  with ``Retry-After``. ``ListMetadataContentionError`` gains a
  keyword-only ``detail`` argument (default ``None``, existing message
  unchanged) so that raise says what happened. The browser UI's list-item
  form (``/{actor_id}/www/properties``) now maps
  ``ListMetadataContentionError`` to 503 with ``Retry-After`` too, where it
  previously rendered a 500 "Error processing list item"; that also covers
  the v1 contention raise the UI never mapped.

- **``verify()`` called an orphaned v2 list healthy.** **Behavior change:**
  the v2 report gains ``meta_row_present`` (whether the meta row physically
  exists -- also ``False`` for a never-created list with no items);
  ``healthy`` is ``False`` when item rows exist without a meta row, and
  stays ``True`` for a never-created list.

  Retrying a *raised* mutation is still not safe in general: a timed-out
  conditional write retried by the SDK can itself report ``False`` for a
  write that landed, independent of the fix above — tracked in
  ``thoughts/todo/conditional-write-ambiguous-after-sdk-retry.md``.

v3.14.6: September 12, 2026
----------------------------

FIXED
~~~~~

- **A JSON-RPC notification was answered with a response body, which made
  the MCP server unreachable from strict clients.** ``POST /mcp`` with
  ``notifications/initialized`` and no ``id`` — the shape every client sends
  right after ``initialize`` — came back ``200`` with
  ``{"jsonrpc": "2.0", "id": null, "result": {}}``. JSON-RPC forbids
  answering a notification, and ``null`` is not a valid response id, so that
  body is not a protocol message at all. Lenient clients (Claude, ChatGPT)
  ignored it; the Codex CLI's ``rmcp`` client rejected it (*data did not
  match any variant of untagged enum JsonRpcMessage*) and tore down the
  transport, so the whole server showed up as unavailable rather than
  merely noisy. Any ``notifications/*`` method arriving without an ``id``
  now gets ``202 Accepted`` with an empty body, as the streamable-HTTP
  transport specifies — including unknown ones, which previously fell
  through to the authenticated dispatch and came back as a method-not-found
  error keyed on a null id. ``notifications/initialized`` sent *with* an
  ``id`` is a client bug, but it has always been answered and still is.
  Both the FastAPI and Flask integrations emit the bodyless 202, with no
  ``Content-Type``. The ``MCP-Protocol-Version`` header is still validated
  first: a notification carrying an unsupported version gets ``400``, as
  before.

- **A JSON-RPC response sent by an MCP client was answered with a 401.** The
  streamable-HTTP transport lets a client ``POST`` a response (an ``id`` with
  a ``result`` or an ``error``, and no ``method``). It fell through to the
  authenticated dispatch and came back ``401`` with a JSON-RPC error — a
  reply to a reply, the same violation as the notification bug above. It now
  gets ``202 Accepted`` with an empty body, unless its
  ``MCP-Protocol-Version`` header is unsupported, which still gets ``400``.
  This server sends no requests to clients, so the response is dropped.

- **A JSON array posted to ``/mcp`` crashed the handler.** ``POST /mcp``
  with a JSON-RPC batch reached ``data.get(...)`` on a list, and so did the
  handler's own error path, so both integrations failed with an unhandled
  ``AttributeError`` — a ``500`` with no JSON-RPC body. Any body that is not
  a single JSON object now gets ``400`` with a ``-32600 Invalid Request``
  error whose ``id`` is ``null``; unlike the notification reply above, a null
  id is what JSON-RPC requires here, because no request id could be read.
  Batches are declined, not processed. MCP 2025-06-18 removed batching, but
  2025-03-26 — which this server still negotiates, and assumes when a
  request carries no ``MCP-Protocol-Version`` header — required servers to
  receive them, so that revision is not fully honoured. Tracked in
  ``thoughts/todo/mcp-batch-receive.md``.

- **The Flask integration ignored the ``MCP-Protocol-Version`` header.**
  werkzeug hands header names over title-cased (``Mcp-Protocol-Version``),
  and the MCP handler looked up only ``MCP-Protocol-Version`` and
  ``mcp-protocol-version``, so on Flask the header was never read. Every
  request was treated as 2025-03-26: an unsupported version was never refused
  with ``400``, and a client that negotiated 2025-06-18 or later never got
  what that version gates, such as ``structuredContent`` in tool results. The
  lookup is now case-insensitive. FastAPI was not affected. A Flask
  deployment whose clients send a newer version will start returning those
  fields, and one whose clients send an unsupported version will start
  answering ``400``.

v3.14.5: September 10, 2026
----------------------------

SECURITY
~~~~~~~~

- **``POST /oauth/email`` selected and rewrote an existing actor for any
  typed address.** When an OAuth provider returned no verified email, the
  free-text branch of the email form looked up the typed address by creator
  and, on a hit, adopted that actor: overwrote its ``oauth_token`` /
  ``oauth_provider`` / token timestamp fields and re-ran ``actor_created``
  against it, while returning 200 with the victim's ``actor_id`` and marking
  it ``email_verified = "false"``. The free-text branch now checks
  ``Actor.get_from_creator()`` before completing the session; an address
  that already has an actor answers ``409`` with
  ``{"code": "actor_exists"}``. The pending session is claimed by an
  *atomic* conditional delete (``delete_attr_conditional``, the same
  single-use consume primitive the refresh-token rotation uses) **before**
  the existence probe runs, not left to expire naturally and not deleted
  afterwards: several concurrent submissions carrying one session id would
  otherwise each get to probe a different address, so one provider login
  would be worth N guesses instead of one. Exactly one concurrent caller
  wins the claim; the rest get the ordinary expired-session error.
  Completion of a free-text address is additionally **create-only**: the
  existence probe necessarily runs before the claim, so an *independent*
  login can create that actor in between, and a plain lookup-or-create would
  then adopt it — the original defect, through a narrow race. Create-only
  re-checks immediately before the create and answers the same 409 instead.
  This narrows the window rather than closing it; nothing enforces creator
  uniqueness in the database yet (tracked in
  ``thoughts/todo/creator-uniqueness-not-enforced.md``). A
  dropdown-selected address — verified by the provider in the same session —
  is unaffected; that is a returning user, not this bug.
- **The ``oauth_token`` cookie set by the email form was not HttpOnly.**
  Every other credential cookie in the library already was. Fixed.

REMOVED
~~~~~~~

- **``/{actor_id}/www/verify_email``, GET and POST — the legacy
  email-verification handler.** The POST had no authentication and rejected
  only ``email_verified == "true"``, a value the library never writes for a
  provider-verified actor: anyone holding an actor id could rotate its
  verification token and fire ``email_verification_required`` (mail to
  ``actor.creator``) an unlimited number of times, without logging in. The
  GET duplicated ``GET /oauth/email?verify=<token>`` against the same store
  fields but did not delete the token-index row on success. Neither
  integration registers the route any more and the handler module is
  deleted: on FastAPI both verbs answer 404, and on Flask the path falls
  through to the generic authenticated ``/{actor_id}/www/<path>`` route and
  answers 401. Nothing rotates a verification token either way, which is
  what the removal was for. The ``aw-verify-email.html`` template stays — it is now
  rendered by the surviving ``GET /oauth/email?verify=<token>`` route (see
  FIXED below). **This retracts the v3.10 changelog's note that the legacy URL
  "remains functional for backward compatibility"**: the library's own
  ``email_verification_required`` hook has passed the
  ``/oauth/email?verify=`` URL format since v3.10, and the legacy resend
  emitted that format too, so only an application that composed the legacy
  URL by hand is affected — its user redoes the sign-in and gets a current
  link. One verification mechanism remains:
  ``GET /oauth/email?verify=<token>``, and an application shipping its own
  ``aw-verify-email.html`` still has it rendered, now by that route.
- **Ten in-process secret compares were not constant-time** (client
  secrets, Basic-auth and Bearer-token passphrases, the devtest passphrase
  grant, the email-verification token, the trustee-passphrase adoption
  check, a peer's trust-verification-token, and both PKCE compare sites).
  All now route through the new ``actingweb.secret_compare`` module
  (``secrets.compare_digest``). The Basic-auth handler's DEBUG log, which
  printed both the submitted and stored passphrase on a mismatch, is
  deleted. **Behavior change**: the trustee-passphrase adoption check
  (``actor.py``) previously adopted on ``None == None`` when a candidate
  record had no stored passphrase; it no longer does (``"" == ""`` still
  adopts, matching a set-but-empty passphrase).

FIXED
~~~~~

- **``actor_created`` fired twice for every OAuth-created actor since
  v3.5.1.** Four handler-level calls (the email form, the web callback, the
  SPA token-exchange path, and the SPA native-grant tail) duplicated the
  single firing site already inside ``Actor.create()``. The four calls are
  removed; ``Actor.create()`` now receives an explicit ``hooks=`` kwarg
  (threaded through ``lookup_or_create_actor_by_identifier()``,
  ``lookup_or_create_actor_by_email()`` and
  ``OAuth2SessionManager.complete_session()``) so a handler built with a
  bare ``Config`` — no ``config._hooks`` to fall back on — still fires the
  hook once instead of zero times. **Behavior change**: the single
  remaining call runs before ``auth_method``, ``created_at``,
  ``oauth_provider``, ``email``, ``oauth_token``, ``oauth_token_expiry``,
  ``oauth_refresh_token``, ``oauth_token_timestamp`` and
  ``email_verified`` are stored on the actor; a hook that read any of those
  fields on the (now-removed) second call sees them absent. ``oauth_success``
  is the hook that carries the OAuth tokens and provider metadata.
- **A GitHub ``/user/emails`` API failure was indistinguishable from "no
  verified emails" and sent a fully-verified user to the free-text form.**
  ``OAuth2Provider.get_verified_emails()`` (default ``[]``, overridden by
  GitHub) now returns ``None`` when the API call itself fails — a non-200
  status (including a 404 from a token whose ``scope`` omits
  ``user:email``) or a network exception — distinct from the legitimate
  ``[]`` ("the provider vouches for nothing"). Both OAuth callback branches
  now answer 502 (web) or an ``identifier_failed`` redirect with a
  retry-worded description (SPA) on ``None``, instead of falling through to
  the free-text form.
- **``oauth_success`` did not fire on the email-form path.** It now fires
  with the same kwarg shape as the OAuth callback (``email``,
  ``access_token``, ``token_data``, ``user_info``), ordered after the
  pending-verification flag is set and before the verification token is
  generated, so a hook that rejects the login (returns a falsy value)
  answers 403 with no token, index row, or verification mail written.
- **The membership check against the provider's verified-email list ran on
  the raw form submission**, so mixed-case input (e.g.
  ``Probe.Existing@Example.com``) against a lowercased list was wrongly
  rejected. The submitted address is now normalised (stripped, lowercased)
  before the check.
- **JSON clients got an HTML template body, or an empty body, on
  ``/oauth/email`` errors.** ``error_response()`` now writes a JSON body
  (``{"error": true, "status_code": N, "message": ...}``) and sets CORS
  headers whenever the client sent ``Accept: application/json``, instead of
  letting the integration render ``template_values`` first.
- **``GET /oauth/spa/session/{id}`` echoed a pending email-entry session's
  raw provider token, and was replayable for the full ten-minute session
  TTL.** It now answers 404 for a pending email-entry session (only a
  success session, one carrying ``actor_id``, is retrievable at all) and
  grants a success session a 30-second retrieval grace window rather than
  full-TTL replay — long enough to cover a duplicate fetch (e.g. a React
  ``StrictMode`` double effect in development) without leaving the session
  readable indefinitely.
- **A form-created orphan actor, later claimed by its real owner through a
  provider login, kept its abandoned ``email_verified = "false"`` state and
  a live verification token.** A provider-verified login of an existing
  actor now clears any pending-verification token, its index row, and the
  ``email_verified`` flag.
- **The email verification link rendered the email-entry form instead of a
  result page, and its errors rendered nothing at all.** Both integrations
  routed every ``template_values`` from ``/oauth/email`` to
  ``aw-oauth-email.html``, which renders an input form unconditionally, so a
  user who clicked a valid link was asked for their address again; and the
  handler's 403 / 404 / 410 results set no ``template_values`` at all
  (``error_response()`` templates only 400 and 500), so a bad or expired link
  answered with the right status and an empty body. The integrations now
  render ``aw-verify-email.html`` — which already shipped and branches on
  ``status`` — whenever the handler sets a ``status`` value, which only the
  verification path does, and the verification path sets one for its error
  results too. Previously masked by the legacy
  ``/{actor_id}/www/verify_email`` route, which rendered that template
  correctly; removing it (see REMOVED) would otherwise have left the broken
  rendering as the only path. JSON clients are unaffected.
- **``actor_created`` fired zero times on the SPA browser-redirect path for a
  handler built with a bare ``Config``.** That path
  (``_process_spa_oauth_and_create_session``) relied on the
  ``config._hooks`` fallback rather than threading ``hooks=`` like the other
  three actor-creation sites. Applications configured through
  ``ActingWebApp`` were never affected, since it sets ``config._hooks``.
- **A rendered error page answered 200.** Both integrations render
  ``aw-root-failed.html`` (OAuth callback) and the email-verification result
  page without passing the handler's status, so a provider-outage 502, a
  rejected-login 403, and an invalid or expired verification token's 403 /
  404 / 410 all reached the browser as ``200 OK``. Anything reading the
  status rather than the page — a monitor, a client, a test — saw a success.
  The status is now carried onto those rendered responses. Pre-existing for
  400 and 403; this release would have widened it to 502 and to the
  verification result page.
- **A state-selected actor kept squatted pending-verification state.** When
  the OAuth callback loads an actor named by ``actor_id`` in the state
  parameter, it never calls ``lookup_or_create_actor_by_identifier()`` and so
  skipped the cleanup added above — leaving ``email_verified = "false"``, the
  stale token and its index row intact on a provider-verified login. That is
  the common shape for an actor-specific or MCP authorization flow. The
  cleanup now runs on that branch too, after the existing check that the
  provider's identifier matches the actor's creator.
- **A peer's trust-verification-token compare could raise an uncaught
  ``KeyError``**, past the surrounding ``except ValueError``, when the
  peer's callback response omitted the ``verification_token`` key. Switched
  to ``data.get(...)``.
- **``Actor.get_from_creator()`` silently picked one of several actors
  sharing a creator** when ``unique_creator`` is disabled, with no signal
  that a duplicate existed. It now logs a ``WARNING`` with the lookup
  creator and every candidate id before falling back to the existing
  deterministic (lowest-id) selection; selection behavior is unchanged.
  Enforcing uniqueness is tracked separately — see
  ``thoughts/todo/creator-uniqueness-not-enforced.md``.
- Documentation corrected in several places where it described behavior the
  code did not implement: ``email_verified`` is **absent** (not ``"true"``)
  for a provider-verified address; the email-form's ``oauth_token`` cookie
  carries the OAuth *provider's* token, not a separate ActingWeb session
  token; the actor-creator lookup lowercases identifiers containing ``@``
  while the indexed-property lookup matches verbatim.

v3.14.4: September 2, 2026
--------------------------

SECURITY
~~~~~~~~

- **A peer could write into a namespace its trust type excludes by putting a
  newline in the property name.** Permission globs were compiled to a regex
  anchored with ``$`` and without ``re.DOTALL``, so ``*`` could not cross a
  newline and ``$`` tolerated a trailing one: for a ``friend`` or ``partner``
  peer, ``excluded_patterns: ["private/*", "security/*", "_internal/*"]`` did
  not match ``private/\nx``. The reachable vector is the JSON body of
  ``POST /{actor}/properties`` (keys are property names); at the previous
  release a ``friend`` peer's ``{"private/\nx": "v"}`` returned 201 and the
  row appeared in the owner's listing. A newline in the URL path never reaches
  a handler on either integration (both routers answer 404), and tab, NUL and
  CR were already matched by ``*``. Impact is integrity — a value planted
  inside a protected namespace — not disclosure. Affected: any deployment
  that grants ``friend`` or ``partner``, or a custom trust type with
  ``excluded_patterns`` or a bare-literal ``denied`` entry, to a peer. What
  changed, all of it about **identifiers only** (property, list, tool, prompt,
  method and resource names, peer ids); values — property content, list
  items, tool input — are untouched:

  - Patterns now match the **whole** identifier (``\Z``), and ``*``/``?``
    match a newline like any other character (``re.DOTALL``).
  - The evaluator **denies any identifier containing a C0 or C1 control
    character** before consulting rules. This is also what keeps a
    bare-literal ``denied: ["secret"]`` from flipping to an allow for
    ``secret\n`` now that the anchor is exact. Denials are logged at
    ``WARNING`` with the identifier's ``repr()``.
  - New property and list names containing a control character are refused
    at the store (``ValueError``) and answered ``400`` by the REST layer, for
    every path segment of a ``PUT`` and every key of a ``POST`` (checked
    before any key is applied). A name that already exists stays readable and
    deletable by its owner.
  - Six other identifier validators moved from ``$`` to ``\Z`` /
    ``fullmatch``: the two remote peer-id patterns (a ``<32 hex>\n`` peer id
    is how a ``remote:<id>\n`` bucket came to exist), the two encrypted-state
    classifiers, the v1 list index and orphan-row patterns, and MCP resource
    URI template matching. Legacy ``uri_pattern`` resource dispatch uses
    ``re.fullmatch`` instead of the prefix match ``re.match``.
  - The six MCP single-item permission checks (``tools/call``,
    ``prompts/get``, ``resources/read`` on both transports) now **fail
    closed**: an evaluator that raises denies with ``-32003`` and an
    ``ERROR`` log line carrying the traceback, instead of serving the request
    at ``DEBUG``. The ``*/list`` filters are unchanged.

  Observable changes for legitimate use: a wildcard rule that used to miss an
  identifier with an embedded newline now matches it; an identifier carrying
  any control character is now denied to peers and cannot be created; and a
  fault inside the permission subsystem (a failing trust lookup, say) now
  blocks MCP ``tools/call``, ``prompts/get`` and ``resources/read`` with
  ``-32003`` until it is fixed, where it used to let them through — an
  availability cost taken deliberately on a security path, and the
  ``ERROR`` log line names it. The equivalent ``methods``/``actions`` deny
  bypass was never reachable — dispatch there is an exact dict lookup.

FIXED
~~~~~

- **PostgreSQL ``get_bucket()`` returned ``None`` for an empty bucket.** It
  now returns ``{}`` and reserves ``None`` for missing arguments or a caught
  backend fault, matching DynamoDB. Consequence: an empty bucket is now
  authoritative on PostgreSQL as it has been on DynamoDB since 3.14.3 —
  ``Attributes.get_attr(name)`` after ``get_bucket() == {}`` answers ``None``
  without a backend read for the life of that instance. DynamoDB still
  reports most faults by raising rather than returning ``None``, because the
  guarded region there is Query construction and PynamoDB fires the request
  lazily. The five library call sites that end in ``get_bucket(...) or {}``
  (``attribute_list_store``, ``callback_processor``, ``remote_storage`` twice,
  ``fanout``) still fold a fault into "empty" and are knowingly deferred.
- **The two backends stored different attribution for a colliding attribute
  row.** ``bucket_name`` is ``bucket + ":" + name`` and both halves may
  contain ``:``, so bucket ``remote:abc``/name ``x`` and bucket
  ``remote``/name ``abc:x`` share a primary key. DynamoDB's PutItem
  reattributed the row to the last writer; PostgreSQL's ``ON CONFLICT DO
  UPDATE`` refreshed only ``data``/``timestamp`` and kept the first writer's
  ``bucket``. The upsert now sets ``bucket`` and ``name`` too, so on both
  backends the row belongs to the last writer — which means a later write
  through the other pair *moves* it between buckets.
- **Attribute point reads and deletes compare the bucket exactly.**
  ``get_attr``, ``get_attr_strict``, ``delete_attr``,
  ``delete_attr_conditional`` and ``conditional_update_attr`` keyed on
  ``bucket_name`` alone and would answer, or delete, the colliding sibling's
  row; they now apply the same exact ``bucket`` compare ``get_bucket()`` and
  ``delete_bucket()`` gained in 3.14.3.

CHANGED
~~~~~~~

- **``GET /mcp/info`` is derived from the application, not the demo.** Both
  integrations carried a byte-identical literal document (``tools_count: 4``,
  ``prompts_count: 3``, ``actor_lookup: "email_based"``, "ActingWeb MCP
  Demo …") for every deployment. It is the ``resource_documentation`` target
  of the OAuth discovery chain and unauthenticated, so it is now built by one
  function from config and the in-memory hook registry only. Removed:
  ``tools_count``, ``prompts_count``, ``actor_lookup``. Added: ``server_name``
  (from ``with_mcp(server_name=)``). Changed: ``mcp_enabled`` follows the
  configured value (it was a literal ``True``), ``description`` is the app's
  own (``ActingWeb app: {aw_type}`` unless the app sets ``desc``), and
  ``supported_features`` lists only what the registry actually exposes.
  Read the tool list from ``tools/list``. No library version is disclosed.
  **This changes a response shape in a patch release**: a client that reads
  ``tools_count``, ``prompts_count`` or ``actor_lookup`` from ``/mcp/info``
  will find them gone. The old values were the demo's literals for every
  deployment, so nothing that read them was reading anything true; still, a
  client that hard-coded them needs updating.
- **``GET /mcp`` reports the configured server name and real
  capabilities.** It answered ``"actingweb-mcp"`` and three literal ``True``
  capabilities regardless of configuration while the ``initialize`` handshake
  answered the configured name; the three surfaces now share one derivation.
  A deployment that never set ``server_name`` sees ``"actingweb"`` here now,
  which a client keyed on the old ``"actingweb-mcp"`` string will notice.
- **``fqdn`` and ``proto`` are stripped, then validated, when ``Config`` is
  built.** Surrounding whitespace (a trailing newline from a ``.env`` file)
  is stripped; a double quote, backslash, interior whitespace or control
  character raises ``ValueError`` naming the character, ``APP_HOST_FQDN`` /
  ``APP_HOST_PROTOCOL``, and the accepted form ``host[:port][/base]`` with no
  scheme. ``ActingWebApp`` strips at its boundary too. A scheme prefix on
  ``fqdn`` is not detected — it produces the doubled scheme it always has.

REMOVED
~~~~~~~

- **``BaseActingWebIntegration.get_oauth_discovery_metadata()``**, and the
  two tests that were its only callers. Both integrations serve
  ``/.well-known/oauth-authorization-server`` from ``OAuth2EndpointsHandler``,
  the method was never rendered in the API docs, and while it lived it
  advertised ``scopes_supported: ["openid", "profile", "email", "mcp"]`` —
  neither the served list nor a subset of it.

v3.14.3: August 29, 2026
-------------------------

FIXED
~~~~~

- **A transient read fault could empty a v1 list.** ``verify()``,
  ``compact()`` and ``migrate_to_v2()`` each read the actor's whole property
  partition through ``fetch_all_including_lists()`` and ended the line in
  ``or {}``. PostgreSQL's ``fetch_all_including_lists`` returns ``None`` on a
  *caught* exception, so a throttle or a dropped connection presented itself
  as an empty partition: ``compact()`` computed ``ordered_values = []``,
  deleted rows ``0..stored_length-1`` and wrote ``length: 0`` — and a
  following ``verify()`` reported the now-empty list ``healthy: true``. All
  three now read only their own list's rows, through
  ``get_range(_v1_bounds())``, which **raises** ``DbError`` on a backend
  fault instead of returning nothing.
- **Those same three reads are now strongly consistent.** Two of them rewrite
  destructively from what they read — ``compact()`` writes survivors to
  ``0..n-1`` then deletes the tail, ``migrate_to_v2()`` deletes v1 rows
  ``0..highest_seen`` — so a row missed by an eventually consistent replica
  read was overwritten by its successor and its slot deleted, silently. The
  v2 counterparts already stated this rule; v1 now agrees.
- **``actor.property_lists.list_all_with_rows()`` raised ``TypeError`` on a
  permission-scoped actor view.** ``AuthenticatedPropertyListStore`` defined no
  bulk readers, so the call fell through ``__getattr__``, which
  permission-checked the *method name* as a list name — which passes, since an
  unmatched target evaluates to ``NOT_FOUND`` and only ``DENIED`` raises — and
  returned a ``_PermissionEnforcingListView`` wrapping a bound method. All
  three bulk readers (``list_all()``, ``list_all_with_rows()``,
  ``list_prefix_with_rows()``) are now defined explicitly and filter denied
  lists out of **both** ``names`` and ``rows``, in one bulk permission
  evaluation. Rows are narrowed with the library's own attribution logic, never
  a bare ``startswith()`` prune, which for a denied list ``foo`` would also
  strip permitted sibling ``foo-old``'s item rows while leaving its ``-meta``
  row — after which the permitted list reads as ``[]`` with nothing raised.
  A permission-system error returns an empty result rather than a partial one,
  and no denied list name appears in any message or log emitted by this path.
  **Behavior change**: ``__getattr__`` on that view now raises
  ``AttributeError`` for a name colliding with a store method (``exists``,
  ``list_all``, ``list_all_with_rows``, ``list_prefix_with_rows``), so a user
  list actually named one of those is unreachable through the authenticated
  view. That is the safe reading: the alternative repair — resolving such a
  name to the underlying store's method — would hand a permission-scoped
  accessor an unfiltered whole-partition read.
- **DynamoDB attribute buckets matched by bare prefix, and one of them
  deleted what it matched.** ``Attribute``'s range key is
  ``bucket + ":" + name``, but ``get_bucket()`` and ``delete_bucket()``
  queried it with ``begins_with(bucket)`` — no delimiter — so a bucket saw,
  and in ``delete_bucket()``'s case destroyed, the rows of every bucket
  having its name as a prefix. ``RemotePeerStore.delete_all()`` tears down
  bucket ``remote:{peer_id}`` when a trust relationship ends, and most call
  sites build that id with ``validate_peer_id=False``, so the ids are
  remote-party-chosen: ending trust with peer ``abc`` deleted peer ``abcd``'s
  entire dataset. Both methods now query with the delimiter **and** compare
  the stored ``bucket`` exactly, the guard ``delete_by_chain()`` and
  ``subscription_suspension``'s cascade check already carried. The delimiter
  alone is not enough — bucket names contain ``:`` and attribute names
  contain ``:``, so bucket ``remote:abc``/name ``x`` and bucket
  ``remote``/name ``abc:x`` produce an identical range key and are in fact
  the same row. PostgreSQL compared ``bucket`` exactly on both paths and was
  never affected; the two backends now agree.

ADDED
~~~~~

- **``property_lists.list_prefix_with_rows(prefix)``** — read one namespace of
  an actor's list properties, and their rows, in a single query, instead of
  dumping the whole partition. Available on ``PropertyListStore`` and on the
  ``ActorInterface`` wrapper. Both halves of the return are scoped: ``names``
  holds only the matching lists, so code migrating from
  ``list_all_with_rows()`` that keeps iterating ``names`` silently stops seeing
  every list outside the prefix — this is a contract, not a caveat.
  ``prefix`` is a prefix, not a namespace: it also matches a list named
  exactly ``prefix`` and siblings like ``{prefix}-old``, so pass the delimiter
  (``"memory_"``, not ``"memory"``) if you mean a namespace. **It is not
  universally cheaper**: on a measured account the whole-partition dump was
  1,361.0 RCU over 11 queries and the five scoped reads covering the same lists
  were 1,363.5 over 15, so replacing one dump with several scoped calls is
  marginally worse. It pays when you want one namespace, or when you issue
  several concurrently — the library stays synchronous and spends one query per
  call, so the latency win is the caller's to take. Reads are eventually
  consistent, matching what the dump already did. An empty prefix raises
  ``ValueError``, and a backend fault raises ``DbError`` rather than swallowing
  to ``([], {})`` as ``list_all_with_rows()`` does — for a scoped read an empty
  result is the ordinary answer, so a swallowed throttle would read as content.
  There is deliberately no names-only ``list_prefix()`` sibling: a keys-only
  projection saves no DynamoDB read capacity.
- **``actingweb.property.rows_for(names, rows)``** — the subset of a ``rows``
  dict attributable to a given set of list names, using the library's own row
  encoding. For narrowing a ``(names, rows)`` pair after pruning ``names``. A
  bare ``startswith(f"list:{name}-")`` is wrong here: for list ``foo`` it also
  claims sibling ``foo-old``'s rows, and used to prune it strips a permitted
  sibling's item rows while keeping its ``-meta`` row, after which
  ``to_list_from_rows()`` returns ``[]`` with nothing raised.
- **``DbPropertyProtocol.get_prefix(actor_id, prefix, keys_only,
  consistent_read)``** — read every property row of an actor whose name begins
  with a prefix, in one query. The sibling ``get_range`` cannot express: a
  prefix has no exact inclusive upper bound, and any synthesised sentinel
  (``prefix + "~"``) is a guess about which byte sorts last that is wrong for
  names continuing past it. DynamoDB uses native ``begins_with``; PostgreSQL
  uses ``starts_with()`` with a bound parameter — **not** ``LIKE``, so ``_``
  and ``%`` are literal, and **not** a ``COLLATE "C"`` bound pair, because
  byte ordering itself disagrees between collations while ``starts_with`` does
  not. Neither backend normalizes Unicode, so an NFD prefix does not match an
  NFC name — the same on both. A falsy prefix returns ``{}`` without touching
  the backend, since PostgreSQL would match every row and DynamoDB would raise.

CHANGED
~~~~~~~

- **Behavior change**: **a fully-loaded attribute bucket is now authoritative.**
  After ``Attributes.get_bucket()`` returns, ``get_attr()`` answers ``None`` for
  a name absent from the loaded dict *without* a point read — where before every
  absent name cost one read per instance. Nothing raises or warns, so this note
  is the discovery mechanism. What changes observably: a long-lived
  ``Attributes`` instance loses the accidental first-miss re-read, so an
  attribute written by *another* process after this instance loaded the bucket
  is not seen by ``get_attr()`` on it. Library call sites are unaffected —
  every ``Attributes`` in the permission and token paths is constructed per
  call — but note that ``handlers/mcp.py`` caches an ``ActorInterface`` on a
  sliding five-minute TTL, so instances there can outlive a single request.
  Call ``delete_bucket()``, or construct a fresh ``Attributes``, to force a
  re-read. Three supporting corrections ride with it: the "loaded" flag is now
  set only when the backend actually returned a dict, so a faulted read can
  never present itself as "the bucket has no such attribute"; ``get_attr()``
  no longer caches its misses into the loaded bucket, which used to make
  ``get_bucket()`` report names that have no stored row; and a
  ``delete_attr()`` (or falsy ``set_attr()``) that the backend reports as
  **failed** clears the flag, so the row the backend still holds is re-read
  rather than reported absent for the life of the instance.
- **Behavior change**: **``Attributes.set_attr()`` now mirrors the backends'
  falsy delete.** Both backends treat a falsy ``data`` as a delete and return
  ``True`` — ``delete_attr()`` is literally ``set_attr(data=None)`` — while the
  in-memory dict cached ``{"data": <falsy>, "timestamp": ...}``. So
  ``set_attr(name, data={})`` (or ``[]``, ``""``, ``0``, ``False``) removed the
  row but left the name present in the cache. The name is now dropped from the
  cache too. "Absent" stays distinguishable from "present with a null value": a
  stored row holding ``null`` still reads back as the truthy dict
  ``{"data": None, "timestamp": ...}``.

- **The v1 list maintenance methods no longer dump the actor's whole property
  partition.** ``verify()``, ``compact()`` and ``migrate_to_v2()`` read one
  list through ``get_range()`` over that list's own bounds — the read shape
  ``_v1_item_names_in_range()`` and every v2 counterpart already used. On an
  actor with many lists this is roughly one dump's worth of read capacity
  saved per call rather than spent per list. The user-facing beneficiary is
  ``_maybe_lazy_migrate()`` (off by default, behind
  ``ACTINGWEB_LAZY_MIGRATION_MAX_LENGTH``), which runs all three inside a
  user's ``append()``/``insert()``: three whole-partition dumps in one
  request become three one-list reads. Reports are unchanged, including
  ``foreign_format_rows`` — v2 residue rows sort below the v1 bounds, so
  they now cost one extra keys-only range read, mirroring what ``_v2_verify()``
  already spends counting v1 residue. On a single-list actor the saving is
  ~3×, not the headline ratio.

v3.14.2: August 28, 2026
-------------------------

FIXED
~~~~~

- **``GET /mcp`` answered an unauthenticated request with a ``200`` discovery
  document** instead of the ``401`` challenge — the other half of the same
  discovery bug as the entry below. The MCP authorization spec has clients
  find the authorization server by making an unauthenticated request to the
  MCP endpoint and reading ``WWW-Authenticate``. A conformant client instead
  parsed this handler's bespoke JSON body as the protected-resource metadata
  and failed on the missing ``resource`` field, never reaching the real
  metadata — which was correct all along. Codex reported exactly that:
  *"Metadata error: Protected resource metadata missing required resource
  field"*. An unauthenticated ``GET`` — including one carrying
  ``Accept: text/event-stream``, the spec's stream opener — is now the same
  ``401`` challenge as every other MCP method.
  **Behavior change**: a caller that read the discovery document from
  ``GET /mcp`` without a token now gets ``401``. The document is unchanged and
  has not moved — an authenticated ``GET /mcp`` still returns it — but there
  is no unauthenticated copy of it. A client that needs server metadata
  without a token should read ``/.well-known/oauth-protected-resource/mcp``,
  which is where the challenge points and which the MCP spec directs it to
  anyway; ``/mcp/info`` is a separate endpoint with a different shape, not a
  substitute. The ``.with_mcp(enable=False)`` ``404`` still takes precedence,
  so a disabled endpoint never advertises an authorization server.
- **The MCP ``401`` challenge did not point at the protected-resource
  metadata.** ``WWW-Authenticate`` carried only a non-standard
  ``authorization_uri``, omitting the ``resource_metadata`` parameter that
  RFC 9728 section 5.1 (and, through it, the MCP authorization spec from
  ``2025-06-18``) requires. A conformant client had no discovery pointer: it
  either guessed the well-known location or reported the resource metadata as
  missing/malformed and never opened the sign-in window — the user sees a
  configured server that never asks them to authenticate. The challenge now
  carries ``resource_metadata="<base>/.well-known/oauth-protected-resource/mcp"``
  alongside the existing ``error="invalid_token"`` and ``authorization_uri``
  hints, at all three sites that emit it — including the async handler the
  FastAPI integration actually serves.

CHANGED
~~~~~~~

- **``offline_access`` is now advertised in ``scopes_supported``** on the
  authorization-server metadata and both protected-resource variants. The
  server already issues a refresh token with every authorization-code token
  response and already advertises the ``refresh_token`` grant; clients that
  gate long-lived sessions on the scope being listed could re-prompt for
  authorization. The authorization endpoint does not validate the requested
  scope, so this is advertising catching up with behaviour — no token
  semantics changed, and the token response still reports the granted scope
  as ``mcp``.

v3.14.1: August 25, 2026
-------------------------

FIXED
~~~~~

- **``@app.subscription_hook`` never fired.** It registered into
  ``HookRegistry._subscription_hooks``, but nothing in the callbacks handler
  ever called ``execute_subscription_hooks()`` — the legacy fallback path
  (used when ``.with_subscription_processing()`` is not enabled) only invoked
  ``@app.callback_hook("subscription")``. A hook registered with
  ``@app.subscription_hook`` was silently never invoked. The legacy fallback
  branch in ``actingweb/handlers/callbacks.py`` now also calls
  ``execute_subscription_hooks()``, so both mechanisms work; either can mark
  the callback as processed. **Behavior change**: on the legacy fallback
  path, a subscription callback that a registered ``@app.subscription_hook``
  handles (returns truthy for) now gets ``204`` instead of ``400`` — this is
  the fix taking effect, since such a hook's return value was previously
  discarded. The legacy path does not track sequence numbers or clear diffs
  (that only happens via ``.with_subscription_processing()`` or an explicit
  PUT acknowledgment), so this does not affect data integrity.
- **``.with_mcp(enable=False)`` didn't actually disable the ``/mcp``
  endpoint.** The Flask and FastAPI integrations register ``/mcp``
  unconditionally, and neither ``MCPHandler.get()``/``.post()`` nor
  ``AsyncMCPHandler.post_async()`` checked ``config.mcp`` before serving a
  full response — an app that disabled MCP still had a live, responding MCP
  server. All three now return ``404`` when ``config.mcp`` is ``False``.
  **Behavior change**: found while consolidating ``examples/demo/`` (which
  disables MCP) — a consumer relying on the endpoint silently responding
  regardless of ``with_mcp()`` will now see ``404`` unless it explicitly
  enables MCP. ``MCPHandler()``'s default (test-only) ``Config`` now
  defaults ``mcp=True``, since every existing caller of the no-arg
  constructor was specifically testing MCP behavior.
- **Documentation taught APIs that do not exist or had the wrong contract**:
  ``@app.trust_hook`` (does not exist; the real mechanism is
  ``@app.lifecycle_hook("trust_fully_approved_local"/"trust_fully_approved_remote"/"trust_deleted")``),
  ``@app.mcp_tool_hook`` (does not exist; use ``@app.action_hook(...)`` +
  ``@mcp_tool(...)``), ``app.config`` (not public; use ``app.get_config()``),
  ``execute_action_hooks``'s argument order (``action_name`` comes first, not
  ``actor``), and the ``@resource_hook`` example in
  ``actingweb/mcp/decorators.py``'s docstring (the real mechanism is
  ``@app.method_hook(...)`` + ``@mcp_resource(...)``). Also fixed: docs
  passing a literal ``peer_id="peer123"`` after binding
  ``create_relationship()``'s real return value, in
  ``docs/guides/trust-relationships.rst`` and
  ``docs/quickstart/getting-started.rst``.
- ``with_sync_callbacks()``'s docstring said its default was ``True``; the
  underlying setting defaults to ``False`` until the method is called.
  Clarified that calling the method at all is the opt-in.
- ``from actingweb.interface import lifecycle_hook`` raised ``ImportError``;
  every other standalone hook decorator was exported except this one.
- **``DbTrust.create()`` defaulted ``approved`` to ``""`` on both database
  backends**, which PostgreSQL rejects outright on its boolean ``approved``
  column (``invalid input syntax for type boolean``) when a caller omits the
  argument. DynamoDB silently tolerated the empty string. Both backends now
  default to ``False``, matching the ``TrustProtocol`` signature. Every
  in-library caller already passed a bool, so behavior only changes for
  direct callers relying on the default — which previously crashed on
  PostgreSQL.
- **The new p2p quickstart's subscribe step 403'd as written**:
  ``create_relationship()`` only approves a relationship on the side that
  initiates it, so the peer's side stayed unapproved and
  ``subscribe_to_peer()`` was rejected — the guide's Python narrative never
  had the peer approve its side (its curl "Verify" walkthrough happened to,
  independently, which is why manual testing during development didn't
  catch this). ``examples/p2p_quickstart.py`` now registers an
  ``on_trust_request_received`` lifecycle hook that auto-approves incoming
  requests (demo-only — flagged as such in both the code and the guide);
  ``docs/guides/p2p-quickstart.rst``'s curl walkthrough now also captures
  each actor's passphrase from its creation response and sends the Basic
  auth every non-creation request actually requires, rather than omitting
  it and discarding the passphrase. Verified end-to-end against a running
  server. Also fixed: ``examples/mcp_quickstart.py`` had the same missing
  ``proto="http://"`` override as the p2p example did before this release —
  the OAuth2 redirect URI generated for Stage 2 pointed at
  ``https://localhost:...``, which nothing on the plain-HTTP uvicorn server
  it starts answers on.

CHANGED
~~~~~~~

- CI now enforces ``ruff format --check`` alongside ``ruff check``, and the
  19 files that had drifted from the pinned formatter (0.15.20) were
  reformatted in a mechanical commit.
- **README documentation pointers are now absolute readthedocs.io URLs**
  instead of bare ``docs/...rst`` paths, which render as broken text on
  PyPI (a ``:doc:`` role only resolves inside the Sphinx build).
  Repository-only files (``CONTRIBUTING.rst``, ``CLAUDE.md``,
  ``CHANGELOG.rst``) are unaffected — those are correctly filesystem paths,
  not published docs.
- **MCP quickstart is now explicitly a two-stage recipe.** Previously the
  pasted example had OAuth2 configuration commented out, so following it
  produced a server where every MCP method beyond ``initialize`` 401s with
  no explanation. The example now configures OAuth2 (reading credentials
  from the environment) and the guide states plainly that Stage 2 (real
  OAuth2 credentials, a bearer token) is required before ``tools/list`` and
  ``tools/call`` work, linking to the token-acquisition steps rather than
  leaving a 401 unexplained. The database prerequisite (previously unstated)
  is now inline, matching the peer-to-peer quickstart.
- **PyPI discovery metadata**: the one-line description now names what the
  library does (per-actor MCP servers, OAuth2, peer-to-peer data sharing)
  instead of "The official ActingWeb library"; ``keywords`` gained
  ``mcp``, ``ai``, ``llm``, ``agent``, ``model-context-protocol``, and
  ``actor``; added the ``Topic :: Scientific/Engineering :: Artificial
  Intelligence`` and ``Programming Language :: Python :: 3.13`` trove
  classifiers; ``homepage``/``documentation`` URLs are now ``https://``;
  and a ``[tool.poetry.urls]`` block adds Changelog/Issues links to the
  PyPI sidebar.
- **``actingweb/__init__.py`` now has a module docstring**: the two headline
  capabilities, the modern entry point
  (``from actingweb.interface import ActingWebApp``), the MCP decorators,
  links to the MCP and peer-to-peer quickstarts, and a note that every hook
  boundary is erased to ``Callable[..., Any]`` despite ``py.typed`` shipping
  — a type checker will not catch a wrong hook signature. ``__all__``
  (the legacy lazy-load surface) is unchanged; a comment now says so
  explicitly.
- **``AGENTS.md`` rewritten**, replacing 105 lines of contributor guidance
  that had drifted from ``CLAUDE.md`` (a nonexistent ``thoughts/shared/``
  path, a structure diagram omitting the PostgreSQL backend, a
  three-file version-bump instruction contradicting the tag-driven release
  process, and zero mentions of MCP, trust, or subscriptions) with a ~40-line
  pointer to ``CLAUDE.md`` plus MCP/peer-to-peer quickstart links for anyone
  building an application with the library. Also removed ``AGENTS.md`` from
  ``.github/workflows/claude-code-review.yml``'s ``paths-ignore`` — that
  exemption is what let it go eight months without automated review while
  ``CLAUDE.md`` stayed current.
- **Superseded-API warnings added to every migration guide**
  (``docs/migration/v3.1.rst`` through ``v3.14.rst``) and inline markers on
  illustrative (non-real) signatures in
  ``docs/contributing/style-guide.rst`` and ``architecture.rst``. Grepping
  ``docs/`` for trust-creation calls previously returned several hits with
  no indication of whether the code shown was current, historical, or never
  real to begin with.

ADDED
~~~~~

- **``examples/demo/``**: the full ActingWeb demo application (OAuth2 login,
  the complete hook system, a customized web UI — a pure ActingWeb protocol
  example, not MCP; see ``examples/mcp_quickstart.py`` for that) moved into
  this repository from the separate ``actingwebdemo`` repository, so the reference
  application is version-locked to the library and exercised by this
  repository's own test suite instead of drifting against a floating
  ``>=`` dependency pin. Deployment (AWS credentials, the OAuth client
  secret, the ``demo.actingweb.io`` custom domain) stays in
  ``actingwebdemo``, which remains the deployment pipeline for this code —
  see ``examples/demo/README.md``. Repo-only: not part of the published
  wheel.
- **Agent Skill for building applications on ActingWeb**
  (``skills/actingweb-app/``): task recipes — add a property hook, expose an
  MCP tool, establish trust and subscribe to a peer, configure a custom
  trust type's ``acl_rules``, look up an actor by property value — for AI
  coding agents working in a repository that merely ``pip install``s this
  library, which is the one surface that reaches them (everything else in
  this release improves what such an agent finds *if it comes looking*).
  ``git clone`` this repo and point your agent at the directory, or
  ``npx skills add actingweb/actingweb``.
- **``llms.txt`` / ``llms-full.txt``** are now generated on every docs build
  via ``sphinx-llms-txt``, and will be served at
  ``https://actingweb.readthedocs.io/en/latest/llms.txt`` once this lands.
  Adopted as a substrate for tools that read it (a human pointing an agent
  at the docs) and for the Google Lighthouse audit that now checks for it —
  not on a claim that AI agents fetch it live at request time; the evidence
  for that is thin.
- **Two docs guides published to Read the Docs for the first time**:
  ``docs/guides/caching.rst`` and ``docs/guides/oauth-login-flow.rst`` were
  previously ``.md`` files — invisible to the Sphinx build
  (``source_suffix`` is ``.rst`` only) despite being real, substantial
  content. A reader with the repo checked out could find them; a reader on
  readthedocs.io, which every other change in this release now points at,
  could not. The other two ``.md`` files under ``docs/`` in the same
  situation (``docs/guides/postgresql-migration.md``,
  ``docs/contributing/TESTING.md``) duplicated a larger, current ``.rst``
  twin and were deleted rather than published.

v3.14.0: August 21, 2026
-------------------------

.. note::

   **This release makes property lists faster and cheaper to use,**
   especially for code that looks up list items by position in a loop
   (``for i in range(len(lst)): lst[i]``) — that pattern can be
   surprisingly slow on larger lists. The fix is a new way to find and
   change items by value instead of position: ``find()``,
   ``items_with_handles()``, ``remove_where()``, ``update_where()`` and
   friends. See ``docs/migration/v3.14.rst`` for the full guide, including
   three small breaking changes.

SECURITY
~~~~~~~~

- **A peer with only read access to a property list could still write to
  it.** ``AuthenticatedPropertyListStore`` — the permission-checked way
  apps expose property lists to peers — only checked read permission
  before handing back a list object, and that object was fully editable.
  So a peer granted read-only access could add, change, or remove items
  anyway. Plain properties (not lists) were never affected; this was
  specific to lists, and has been present since the feature was
  introduced. It's now fixed: list writes require write (or delete)
  permission, matching how plain properties already worked. If any peer's
  trust type is meant to be read-only on a property list, it's worth
  checking that peer's recent activity for writes it shouldn't have been
  able to make.

CHANGED
~~~~~~~

- **Breaking:** ``get_metadata()["length"]``, and the ``count`` field the
  REST API returns for a single list, are now a close estimate rather
  than a guaranteed-exact count. In practice the estimate can only be off
  by a handful, and it self-corrects. ``len(actor.property_lists.<name>)``
  and actually iterating a list remain exact, always, on every list
  format — this only affects that one metadata field and that one REST
  field. See ``docs/guides/property-lists.rst`` for a recipe if you rely
  on an exact count near a hard limit.
- **Breaking:** ``AuthenticatedPropertyListStore.create()`` is removed. It
  never worked in any released version — every call raised an error — so
  there is no working code for this to break. Lists are created
  automatically on first write; there was never a separate creation step.
- **Breaking (narrow):** in a bulk request that both updates and deletes
  the same list item in one call, the delete used to win and silently
  discard the update. Now the delete is recognized as stale and reported
  back as a conflict instead. If you relied on the old "delete wins"
  behavior, send the update and delete as two separate requests.
- Bulk list updates now report a conflict for an individual item instead
  of silently overwriting it, when something else changed that item at
  the same time. See ``docs/guides/property-lists.rst`` "Bulk update
  items".
- Updates made with the new value-based methods now notify subscribed
  peers using the item's value, so a peer can still find the right item
  even if its position changed. Peers on an older ActingWeb version keep
  working exactly as before for every operation that existed before this
  release; the one exception is these new value-based *update* diffs,
  which carry no position for an old peer to fall back on, so a pre-3.14
  peer does not apply them (it skips them without error). If peers you
  do not control replicate a list you mutate with ``update_where()`` or
  ``update_by_handle()``, they need 3.14 to see those updates.
- A previously-documented race window, where a list format upgrade could
  be silently undone by a change happening at the same moment, is now
  closed rather than merely bounded. See ``ListMetadataContentionError``
  below.

ADDED
~~~~~

- **Look up and change list items by value, not position** -- the
  headline feature of this release:

  - ``find(key, value)`` / ``find_all(key, value)`` -- find the item(s)
    whose field matches a value, in one read.
  - ``items_with_handles()`` -- fetch every item in a list along with a
    short-lived reference ("handle") you can use to update or delete that
    exact item afterward. Handles are meant to be used right away, not
    saved for later -- see the migration guide for why.
  - ``delete_by_handle(handle)`` / ``update_by_handle(handle, item)`` --
    change or remove one item by its handle. If something else already
    changed that item, the call safely does nothing and reports that
    instead of overwriting it.
  - ``remove_where(key, value)`` / ``update_where(key, value, item)`` --
    remove or update every item matching a value, in one call.

  All of the above are available directly on
  ``actor.property_lists.<name>`` and go through the same permission
  checks as the library's existing list methods. See
  ``docs/guides/property-lists.rst`` for full examples.

- ``consistent=False``, an opt-in parameter on list-reading methods
  (``to_list()``, ``slice()``, ``find()``, and similar) for reads that can
  tolerate being a moment out of date, in exchange for lower cost and
  better performance. Off by default everywhere, including inside the
  library itself.
- ``ListMetadataContentionError`` (importable from ``actingweb``): a new,
  specific, catchable error for the rare case where a list update can't
  complete because of a conflicting change happening at the same moment.
  The library's own request handlers turn this into an HTTP 503
  "please retry" response automatically.
- ``PropertyListStore.list_all_with_rows()`` -- for apps that read several
  of an actor's lists at once, this fetches everything in a single read
  instead of one read per list.
- ``actingweb-verify-orphans``, a new command-line tool that scans your
  database for leftover data belonging to actors that no longer exist
  (for example, from an interrupted deletion). It only reports what it
  finds and never deletes anything on its own. See
  ``docs/reference/actor-deletion.rst`` "Finding orphaned rows".
- Clearing or deleting a whole list now happens in a small number of
  batched operations instead of one step per item -- much faster on
  large lists, with no code changes needed.

FIXED
~~~~~

- ``actor.property_lists.<name>.get_metadata()`` was silently unreachable
  through the normal way apps access lists, despite being a documented,
  public method. It now works as documented.
- A list item whose value is ``None`` now replicates to subscribed peers
  like any other value. Previously a diff for such an item omitted its
  ``item``/``old_item`` field entirely, and the receiving side dropped
  the whole notification as unrecognized -- silently, the same failure
  mode as the ``remove()`` bug below.
- When a peer receives a value-based update it cannot apply (the value
  matches no row, or more than one), it now logs a WARNING naming the
  list and suggesting a resync. The update was already (correctly) not
  applied in that case; what was missing was any operator-visible signal
  that the replica had just diverged.
- ``remove_where()``/``update_where()`` on the core ``ListProperty``
  layer now capture the values they return during the same scan that
  matches them (v1 format) -- previously a second positional read could
  return a different value than the one actually removed or replaced if
  a concurrent writer landed in between.
- ``actingweb-verify-orphans`` re-run against a checkpoint in which every
  table is already complete now says so (``REPLAYED FROM CHECKPOINT``)
  and exits with a distinct status (3) instead of reprinting the earlier
  scan's findings as if they were current.
- **Removing an item from a list wasn't reaching subscribed peers.** A
  bug meant ``remove()`` never actually notified peers, for as long as
  the feature has existed -- the notification was silently dropped every
  time. This is now fixed. If you have peers subscribed to a list that
  uses ``remove()``, they may be out of sync with removals made before
  this upgrade; a manual resync is the safest way to catch them up if you
  suspect this affected you.
- On PostgreSQL, reading properties for an actor with no data at all
  returned an empty result differently than on DynamoDB. Both backends
  now behave the same way; unlikely to have been noticeable in practice.

v3.13.0: August 15, 2026
------------------------

.. note::

   **This is the consolidated release. It supersedes ``v3.13.0rc1`` through
   ``v3.13.0rc6``, whose separate sections have been merged here.** Changes
   that existed only between release candidates — defects introduced by one
   pre-release and fixed by the next — are deliberately not listed: nothing
   released before ``v3.13.0`` ever exhibited them, so they are noise for
   anyone upgrading from ``v3.12.0``. If you pinned an rc and want the
   intermediate history, it is in the git log for ``CHANGELOG.rst``.

.. warning::

   **Upgrading from ``v3.12.0`` requires reading three things**, in this
   order, because two of them change behaviour rather than only fixing it:

   1. The **SECURITY** section below. An MCP authorization bypass affected
      every release from ``v3.3`` (2025-10-04) onwards. The library cannot
      tell you whether it was exploited in your deployment; the migration
      guide says what to check.
   2. The three entries marked **Breaking** under CHANGED — the
      ``/properties/<name>/items`` response shape, list reads failing fast on
      corruption instead of silently compacting, and out-of-bounds ``PUT``
      now returning 404.
   3. ``docs/migration/v3.13.rst``, in full. In particular: **a green test
      suite is not evidence this release landed correctly.** The read-path
      and capacity fixes are invisible to functional tests, and the guide
      gives an operation-profile recipe for confirming them against your own
      hot paths.

   **Two operator tools ship with this release** —
   ``actingweb-verify-property-lists`` and
   ``actingweb-migrate-property-lists``. Automatic conversion of existing
   lists to the v2 storage format is **off by default**; read the migration
   guide before turning it on, and note that ``compact()`` is documented as
   not crash-safe (see DOCUMENTATION).

SECURITY
~~~~~~~~

- **Fixed an MCP authorization bypass where one client's permissions could
  be served to a different client on the same actor.** The trust-relationship
  cache used by the MCP authentication path was keyed by actor id alone, not
  ``(actor_id, client_id)``. On an actor with more than one registered MCP
  client, once the cache was warm, one client's resolved trust relationship
  — and therefore its entire permission rule set — could be silently served
  to a different client's requests on the same actor. This has been
  demonstrated in practice: a read-only client performed a write immediately
  after a read-write client authenticated against the same actor. The
  trust cache is now keyed by ``(actor_id, client_id)``, closing the bypass.
  **Affected versions:** every release since ``v3.3`` (2025-10-04) through
  ``v3.13.0rc2``, roughly ten months (i.e. fixed in this release). The library cannot detect whether this
  was exploited in your deployment; see the migration guide for what to
  check.

- **``resources/read`` had no authorization check at all on Flask (sync)
  deployments.** The permission gate read an actor attribute
  (``_mcp_trust_context``) that no production code ever wrote, so the check
  silently fell through and every resource read was served regardless of the
  requesting client's trust type or permissions. FastAPI (async) deployments
  were not affected — the async handler already read the correct runtime
  context. The sync path now uses the same mechanism as async and is
  authorized identically. If your Flask deployment serves resource URIs
  beyond the default ``mcp_client`` trust type's narrow pattern set
  (``public/*``, ``shared/*``, ``notes://*``, ``usage://*``,
  ``actingweb://properties/all``), see the audit step in
  ``docs/migration/v3.13.rst`` — those requests have been working only
  because the check was dead.

- **Missing trust is now fail-closed instead of fail-open.** A valid MCP
  access token that cannot be resolved to a trust relationship (a broken or
  orphaned trust row, or an eventual-consistency gap right after
  registration) previously granted full access. It now returns an empty
  ``tools/list``/``resources/list``/``prompts/list`` and a distinct
  ``-32003`` error naming the cause on ``tools/call``/``prompts/get``/
  ``resources/read``, rather than silently permitting the request. A short
  negative-TTL cache bounds transient eventual-consistency misses to
  seconds rather than the full token cache window. Deployments relying on
  the permission subsystem being unavailable (a genuine outage, as opposed
  to no trust being found) are unaffected — that failure mode is still
  fail-open, deliberately, so a permission-subsystem outage does not lock
  out every client.

- **The MCP client-id-to-trust resolver now matches exactly instead of by
  substring.** The previous resolver checked whether the OAuth2 client id
  appeared anywhere inside a trust row's peer id (``client_id in
  peer_id_str``), which a peer id crafted through the ordinary ``/trust``
  peer protocol could satisfy without ever going through MCP client
  registration. The resolver now requires an exact ``oauth_client_id``
  match, or — for legacy rows created before that field existed — an exact,
  fully-reconstructed peer-id match gated on the row's ``established_via``
  being an OAuth2-family value. See ``docs/migration/v3.13.rst`` for how to
  find trust rows that predate ``oauth_client_id`` and may need
  re-authorization after upgrading.

- **Trust-row client metadata written during the affected window is
  unreliable.** ``client_name``, ``client_version``, ``client_platform``,
  ``last_accessed``, and ``last_connected_via`` may have been overwritten by
  a different client than the one that actually holds the credential, for
  any trust row touched while the cache-crossing bug was live. Current
  values self-heal on that client's next request after upgrading (current
  state, not history — the metadata is a live cache with no audit trail).

CHANGED
~~~~~~~

- **Lookup-table mode is now the default reverse-lookup mechanism**
  (``use_lookup_table`` defaults to ``True``; the deprecated legacy
  GSI/index mode can be pinned with ``with_legacy_property_index(True)``
  or ``USE_PROPERTY_LOOKUP_TABLE=false``). Upgrading deployments keep
  resolving reverse lookups through deprecated fallbacks (v1 lookup
  table, then the legacy GSI where present) with per-hit warnings and a
  loud startup ERROR until the new
  ``scripts/backfill_property_lookup.py`` is run — see
  ``docs/migration/v3.13.rst`` for the per-deployment decision tree.
  Note the semantic change: lookup-table matching is per (property name,
  value); the legacy GSI matched on value alone.

- **Freshly created properties tables match the configured reverse-lookup
  mode.** In lookup-table mode, auto-created ``<prefix>_properties``
  tables no longer carry the legacy value-keyed ``property-index`` GSI —
  previously every fresh deployment inherited it even when nothing read
  it, paying double write/storage cost and rejecting any property value
  over DynamoDB's 2048-byte GSI-key limit (values over 2 KB now verified
  to store correctly). Legacy mode still creates the GSI so the legacy
  reverse-lookup path works. Existing tables are never altered.

- **Property reverse-lookup table redesigned (v2, digest keys).** On
  DynamoDB, lookup rows now live in a new ``<prefix>_property_lookup_v2``
  table keyed by a SHA-256 digest of (property name, value); the plaintext
  value is no longer stored. This removes the old design's hot-partition
  key (all emails shared one partition), its undocumented 1024-byte value
  cap, and plaintext PII in key material. Writes are conditional: a value
  already mapped to a **different** actor is now a loudly-logged collision
  instead of a silent last-writer-wins overwrite (PostgreSQL gained the
  same idempotent-create/collision semantics). Existing v1 lookup tables
  are read as a deprecated fallback; rebuild the v2 table from the
  properties table with the backfill script, verify, then drop the v1
  table. Reverse lookups for property names not configured as indexed now
  return ``None`` with a warning instead of silently using the legacy
  path, and the legacy GSI path raises an actionable error when the index
  is missing from the live table instead of an opaque backend exception.
  Lookup write failures are logged at ERROR (previously swallowed —
  a failed lookup write silently broke login-by-email for that user).

- **Hot-path read amplification removed across the property and actor
  paths.** ``GET /<actor>/properties`` now serves the entire response
  (simple properties, list discovery, list metadata and list items) from a
  single partition read — it previously re-read every property
  individually after the bulk read, read the partition a second time for
  lists, and re-read each list's metadata row. Single-property reads no
  longer pay an extra list-existence check on every hit, repeat property
  writes skip the list-collision read, the actor's internal attribute
  bucket is loaded lazily (once, instead of eagerly twice per actor
  construction), attribute buckets in general no longer load fully on
  construction, bulk property deletion reads its partition once instead of
  twice, and permission evaluation caches confirmed-absent trust
  overrides instead of re-reading per request.

- **Auto-created DynamoDB tables now use on-demand billing.** Tables the
  library creates were provisioned with tiny fixed capacities inherited
  from old Meta defaults (the property lookup table — the login path —
  got 2 read units / 1 write unit per second, a hard throughput wall).
  Newly created tables are now ``PAY_PER_REQUEST``. **Existing tables are
  not changed** — convert them once, in place (never recreate; the lookup
  table holds live login data)::

      aws dynamodb update-table --table-name <prefix>_property_lookup \
          --billing-mode PAY_PER_REQUEST

  (AWS allows one billing-mode switch per table per 24 hours. Check
  ``<prefix>_peertrustees`` too.)

- **Per-actor DynamoDB reads no longer scan the whole table.** Nine call
  sites (property fetch/delete, trust list fetch/delete, peer-trustee
  fetch/lookup/delete) issued a full-table ``Scan`` with a partition-key
  filter — read cost grew with total table size, not the actor's data
  (measured ~2,000 RCU per property fetch on a 16 MB table). All are now
  partition ``Query`` calls; the trust reads keep their strong consistency.
  Trust and peer-trustee list results are now range-key sorted
  (deterministic order) instead of arbitrary scan order.

- **DynamoDB table-existence checks are now memoised per process.** Every
  accessor construction used to issue a live ``DescribeTable`` call
  (measured at >1,000/minute in a near-idle deployment); the check now runs
  at most once per table per process, and all tables are pre-warmed
  concurrently at Flask/FastAPI integration time instead of serially on the
  first request.

- **``RuntimeContext`` is now genuinely request-scoped, and
  ``set_custom_context()`` no longer persists across requests.** Runtime
  context (MCP/OAuth2/web) was stored as a mutable attribute on the actor
  object, while the MCP handler deliberately hands the *same* cached
  ``ActorInterface`` to every request for a hot actor — so context could
  leak between requests and, under concurrency, between callers. It is now
  stored in a ``contextvars.ContextVar`` keyed by actor id (task-local
  under asyncio, thread-local under a WSGI worker), and the Flask and
  FastAPI integrations clear it at the end of every request including when
  a handler raises. The public API (``RuntimeContext(actor)`` and all its
  getters/setters) is unchanged, and read-only use inside request-scoped
  hooks needs no changes. **The one behavior change for application code:**
  data written with ``set_custom_context()`` is gone by the next request,
  even against the same actor object. If your hooks used it as a
  cross-request cache rather than as request-scoped data, move that to
  actor properties or the caching guide's patterns
  (``docs/guides/caching.md``). See ``docs/guides/hooks.rst``.

- **``tools/call`` permission checks now pass ``operation="use"`` on
  FastAPI, matching Flask.** The async handler passed ``"invoke"`` while
  the sync handler passed ``"use"``, a transport-dependent divergence. It
  is unread by every trust type shipped with ActingWeb (they express
  ``tools`` as allowed/denied lists, which do not consult ``operation``),
  so this changes nothing unless your application defines a
  patterns/operations-based tools rule — in which case a rule that
  matched ``invoke`` on FastAPI must now match ``use``.

- **MCP ``structuredContent`` is now opt-in.** ``tools/call`` results emit
  ``structuredContent`` only when a tool hook sets that key explicitly, and only
  when its value is a JSON object. Extra top-level keys are **no longer promoted**
  into ``structuredContent``.

  Why this changed: at least one major MCP client discards **every** text content
  block when ``structuredContent`` is present on a result. Under the previous
  behaviour, adding a single scalar key to a hook's return value silently deleted
  that tool's entire prose payload — the model received only the promoted keys,
  and nothing in the protocol reported the loss to either side. Neither reference
  server implementation promotes individual keys: the SDK's low-level server emits
  ``structuredContent`` only when ``content`` is its exact serialization, and
  FastMCP only for a declared return model.

  This is also a hardening improvement. A hook doing
  ``return {"content": [...], **rel.to_dict()}`` was shipping the trust row's
  ``secret`` to the model; ``properties.to_dict()`` can likewise carry
  ``oauth_token`` / ``oauth_refresh_token``. Only an explicitly named
  ``structuredContent`` now leaves the process. Note the win is scoped to the
  ``content`` branch — the legacy text-wrap path still stringifies the whole dict.

  Migration: nest the data you want structured under an explicit
  ``structuredContent`` key, and keep the same object serialized in a text
  ``content`` block (the spec's backwards-compatibility guidance — some clients
  ignore ``structuredContent`` entirely). For tools whose payload is prose, drop
  the extras instead. The explicit passthrough already exists in ``v3.11.0`` and
  ``v3.12.0``, so migrated hooks produce identical output on both, and no
  coordinated deploy is needed.

- **New list properties now use a v2 storage format (fractional rank
  keys) instead of dense integer indices.** Delete and insert are now a
  single conditional write each instead of a shift loop over every
  following item -- the interrupted-shift corruption class Phases 1-3
  hardened against structurally cannot occur in a v2 list, because there
  is no separate stored ``length`` a row could disagree with; position is
  always derived by sorting present rows. ``to_list()``/``slice()``/
  iteration remain a single query regardless of list size. Existing lists
  are untouched and keep working exactly as before (the v1 format,
  including everything Phases 1-3 hardened, is fully supported
  indefinitely) until migrated. New list names may no longer contain
  ``#`` (reserved for internal storage keys) -- ``ListProperty`` raises
  ``ValueError`` immediately on first use of such a name; existing v1
  lists already named this way are unaffected. ``list:``-prefixed
  property names are now also structurally excluded from the
  property-lookup table sync, regardless of configuration.
  ``scripts/verify_property_lists.py`` now understands both formats --
  v2's "unhealthy" signal is rank keys approaching the length cap
  (``compact()`` rebalances them), not holes/orphans, which are
  structurally impossible under v2.

- **Existing v1 lists migrate to v2 automatically and gradually.** Small
  lists (<= 50 items) migrate lazily the next time they're mutated
  (``append``/``insert``/item ``__setitem__``/``__delitem__``); a failed
  lazy migration is logged and the original mutation still succeeds as
  v1 -- migration is a background upgrade, never a reason an ordinary
  write can fail. Larger lists stay fully functional as v1 until swept by
  the new ``scripts/migrate_property_lists.py`` (dry-run by default;
  ``--migrate`` to perform it; reports refused names and duplicate
  residue; ``--downgrade ACTOR_ID/list_name`` is an emergency-only v2->v1
  converter for rollback scenarios). ``ListProperty.migrate_to_v2()`` is
  idempotent and safe to interrupt and re-run at any point, including
  across concurrent v1 mutations between attempts.

- **Breaking: list-property reads now fail fast on corruption instead of
  silently compacting past it.** ``ListProperty.to_list()``, ``.slice()``
  and ``.to_list_from_rows()`` raise ``ListCorruptionError`` (an
  ``IndexError`` subclass) when an item within the list's recorded length
  is missing from storage, matching ``AttributeList``'s existing contract.
  Every HTTP path that serves list content (``GET /properties/<name>``,
  ``?format=full``, ``?metadata=true``, ``GET/POST /properties/<name>/items``,
  the bulk list-item POST, list DELETE) now returns **409 Conflict** with
  ``{"error": "list_corrupted", "list": ..., "detail": ..., "remedy": "compact"}``
  instead of a 500 or a quietly-wrong compacted response. Repair with
  ``ListProperty.compact()`` (see ADDED below) before retrying.

- **Breaking: ``GET /properties/<name>/items`` response shape changed.**
  Was a bare JSON array (identical to ``GET /properties/<name>``); is now
  ``{"items": [{"index": i, "item": ...}, ...], "count": n}``. ``index`` is
  the storage index, matching what ``action=update``/``action=delete``
  already expect in ``item_index`` — GET and POST are now consistent with
  each other. Flask gained this route for the first time (parity with
  FastAPI, which already had it).

- **Breaking: ``PUT /properties/<name>?index=N`` beyond the list length now
  returns 404** instead of silently padding the list with ``None`` up to
  ``N`` (an unbounded-write DoS vector as well as a spec violation — the
  spec requires 404 for ``index > length``; ``index == length`` still MAY
  append). ``docs/protocol/actingweb-spec.rst`` "List Property PUT".
- The bulk list-item POST (``POST /properties`` with a
  ``{"items": [{"index": N, ...}]}``-shaped list value) now applies every
  update before any delete, regardless of the order items appear in the
  request, then applies deletes in descending index order. Previously,
  processing in request order meant a delete appearing before an update in
  the same batch could shift the update onto the wrong item. All indices
  in a batch are now interpreted against the list as it stood before the
  batch, consistently.

- **The bulk list-item POST now rejects an update index beyond the end of
  the list with 400**, the same rule ``PUT ?index=N`` follows. A batch may
  still populate a list with consecutive indices (``0, 1, 2, …``) — the
  bound advances with each append the batch performs — but it can no longer
  name an arbitrary index and have the gap padded with ``None`` one row at a
  time, which turned a single request into as many database writes as the
  index was large. The whole batch is validated before anything is written.

- **``verify()`` accepts an ``identity_key``**, adding a
  ``duplicate_identities`` report that catches duplicates the existing
  byte-adjacency heuristic structurally cannot. That heuristic is blind two
  ways, and both were hit in a real deployment: it stops finding a duplicate
  the moment either copy is edited (so it misses exactly the lists that have
  been used since the damage), and it only looks at neighbouring rows (so it
  missed the same ``id`` at positions 31 and 36 and called the list healthy).
  ``duplicate_identities`` compares the identifying field across the whole
  list and survives later edits, and the report carries
  ``identity_checked_count`` so an empty result is distinguishable from a
  mistyped key that compared nothing. Both sweep tools gained
  ``--identity-key``; the migrate tool's dry-run duplicate warning
  previously used only the unreliable comparison.

- **The operator tools now ship with the library** as the console commands
  ``actingweb-verify-property-lists`` and
  ``actingweb-migrate-property-lists`` (implementation moved to
  ``actingweb.maintenance``; ``scripts/`` keeps thin wrappers). They were
  previously absent from the wheel, which mattered once converting existing
  lists became an explicit operator step rather than something that
  happened on its own.

- **Both sweep scripts now print the backend, region/host and table prefix
  they are about to operate on**, and warn when ``AWS_DB_PREFIX`` is an unset
  default. The library defaults it to ``demo_actingweb``; running a sweep
  without the application's environment could silently target a different
  deployment and report it clean, which looks exactly like good news.
- ``scripts/verify_property_lists.py`` no longer deletes the checkpoint file
  on a clean **read-only** run — it is now gated on ``--repair``, matching
  the migrate script. A dry run could previously remove the resume state of
  an interrupted ``--repair``.

- **Lazy migration now refuses a list that ``verify()`` reports as
  unhealthy**, logging what it found and how to fix it, instead of
  migrating it. Migration closes holes in flight and reports what it
  closed, which is right for an operator running
  ``scripts/migrate_property_lists.py`` and reading the output — but doing
  it silently under an ordinary ``append()`` destroyed the evidence: the
  hole disappeared, the lost item stayed lost, duplicate residue was
  promoted to real data, and ``verify()`` began reporting the list healthy.
  Repair (``compact()`` or ``verify_property_lists.py --repair``) is now
  always an explicit operator action; damaged lists keep serving v1 and
  keep raising ``ListCorruptionError`` until then.

- **Automatic conversion of existing lists to the v2 format is OFF by
  default**, controlled by the new ``ACTINGWEB_LAZY_MIGRATION_MAX_LENGTH``
  environment variable (default ``0``; set a positive number to allow v1
  lists of at most that size to convert on their next write, or use
  ``scripts/migrate_property_lists.py``). **This does not make v2 opt-in** —
  every list created after upgrading is v2 with no operator action; only the
  conversion of pre-existing data waits for a deliberate decision. The
  default is off because it is a **rollback-safety control** before it is a
  latency one. A pre-3.13.0 process does not
  error on a migrated list — it reads it as *empty*, because a v2 list
  stores no ``length`` field and an older reader takes the absence as zero;
  a write from that process then forks the list across both formats with
  nothing reporting an error, and ``--downgrade`` cannot reconcile a forked
  list. Deployment gives a brief mixed-version window; **rollback gives
  none** — every list that migrated before the rollback reads as empty
  afterwards, recoverable only one list at a time. With the limit at 0 the
  release changes no data, so rolling back is a pure code rollback.
  Secondarily: migration is synchronous, so one ``append()`` to a 40-item
  list performs the whole migration — dozens of sequential writes plus two
  full-partition reads — inside that request. The library logs one INFO per
  process the first time it encounters a v1 list while conversion is
  disabled, naming the script, so "off" does not quietly become "never".
- ``ListProperty.storage_format()`` (new, public) returns 1 or 2 from a
  single point read. ``scripts/migrate_property_lists.py`` now uses it
  instead of ``verify()`` for format detection, which was fetching the
  actor's entire property partition once per list.

- **Migration now refuses a damaged list.**
  ``actingweb-migrate-property-lists --migrate`` and
  ``ListProperty.migrate_to_v2()`` refuse a list whose ``verify()`` reports
  missing or orphaned indices, and the dry run reports those lists as
  needing repair rather than counting them as "would migrate" — it exits
  ``1`` when any exist, so ``0`` means the migration has nothing to trip
  over. Migrating damaged data is not merely lossy but *unreportably*
  lossy: migration renumbers the survivors, so afterwards the hole is
  gone, the list verifies healthy, and nothing is left to say an item was
  destroyed. An earlier form of the dry run warned about duplicate residue
  and said nothing whatsoever about holes, so a sweep over a fleet containing one
  could report "0 refused, 0 errors" and an operator would proceed past the
  last moment the damage was visible. Lazy migration already refused
  damaged lists on exactly these grounds; this applies the same rule to the
  deliberate path. Repair first
  (``actingweb-verify-property-lists --repair``), or pass
  ``--migrate-damaged`` / ``migrate_to_v2(allow_damaged=True)`` to migrate
  anyway — which logs what it is giving up.

  Duplicate residue is unaffected and still migrates: it stays visible
  after conversion, since a v2 list's ``verify()`` reports duplicates the
  same way a v1 list's does, so migrating it destroys no evidence. Only
  holes and orphans gate.
- A successful migration that closed holes (only reachable via
  ``--migrate-damaged``) now logs at WARNING rather than INFO.

- **``--repair`` refuses a reverted migration instead of blessing it as
  healthy.** A v1 list that is damaged **and** carries rows of the v2 storage
  format is not an ordinary hole: it is a list whose migration was reverted,
  with its items alive in the v2 rows and the v1 range empty. ``compact()``
  used to rewrite that empty range, set the length to what it found, report
  the list **healthy**, and leave the only surviving copy as unreferenced
  residue for the next ``clear()``/``delete()``/migrate re-run to sweep — the
  same unreportable loss the entry above refuses damaged lists to avoid, in
  the other operator tool.

  ``compact()`` now refuses that combination and says why;
  ``allow_reverted=True`` (``actingweb-verify-property-lists
  --repair-reverted``) is the deliberate override, mirroring
  ``--migrate-damaged``. The verifier's log line for foreign-format rows
  splits accordingly: on a healthy list it still reports inert residue and how
  to clear it; on a damaged v1 list it now **warns** that those rows are
  probably the data and that sweeping or repairing destroys them. The previous
  text said "harmless to reads; clear it by re-running --migrate"
  unconditionally, which in this shape was an instruction to delete the only
  surviving copy.

- **A write from a ``ListProperty`` held across a migration is no longer
  silent.** Such an instance dispatches on its cached storage format, so the
  item lands in a row of the old shape that readers of the new format never
  return — and ``verify()`` reports the list **healthy**, because the row
  surfaces only as ``foreign_format_rows``, which is documented as inert
  residue. It now logs a WARNING naming the list, both formats, and what to
  do. Bounded to one write per retained instance: the metadata write refreshes
  the cache, so the instance self-corrects from there. The write itself is
  still lost — closing that needs dispatch on a fresh metadata read, which is
  deferred.

  This needs an instance retained *across* a migration.
  ``PropertyListStore.__getattr__`` builds a fresh ``ListProperty`` on every
  attribute access, so ordinary ``actor.property_lists.<name>`` use has a
  one-request window rather than a process-lifetime one.

- **Each list mutation now costs one additional point read.** Merging into a
  fresh read of the metadata row is what makes the fix above work, and it is
  not free: where a mutation previously wrote metadata from cache, it now reads
  the row first. One extra round trip per ``append()``/``insert()``/``pop()``/
  ``remove()``/``__setitem__()``/``__delitem__()``, on both backends. The
  alternative is a compare-and-set primitive neither backend's ``DbProperty``
  exposes; correctness was preferred over the round trip, and the trade is
  recorded rather than buried.

- The migration and property-list guides now state what a whole-list rewrite
  does and does not exclude. Nothing locks out a concurrent application
  write, so "run repair when the actor is not taking writes" remains a real
  requirement; what is now guaranteed is that such a write cannot change the
  list's storage format. Two concurrent migrations resolve to
  last-writer-wins at whole-list granularity — accepted and documented
  rather than prevented.

- **The MCP unsupported-protocol-version rejection now names the supported
  versions and logs at WARNING.** A client sending an
  ``MCP-Protocol-Version`` this server does not speak still gets HTTP 400 with
  JSON-RPC ``-32600`` and no ``data`` payload — that response shape is
  deliberately unchanged, because it is the signal dual-era MCP clients use to
  recognise a legacy-era server and fall back to ``initialize``. What changed:
  the error ``message`` now lists the versions that would have worked, which
  for a client that cannot fall back is the only diagnostic it can show a
  user; and the rejection is logged at all, which it previously was not.

  The logging is graded per origin rather than uniform, because the rejection
  is answered on an **unauthenticated** path. A lone rejection is the normal
  legacy-server handshake and is recorded at INFO; only a sustained run from
  the same origin — a client retrying instead of falling back, i.e. a
  modern-only client — escalates to WARNING, once per origin per five-minute
  window. That keeps the actionable signal visible without handing anonymous
  callers a log-volume lever, and it makes the "one-off versus sustained"
  judgement in code instead of leaving it to whoever reads the logs. Origin is
  taken from ``Mcp-Session-Id`` or the ``User-Agent``; the number of tracked
  origins is capped.

  The response code and the absence of ``data.supported`` are now covered by
  regression tests that state why, since "fixing" this to a spec-shaped
  ``-32022`` with ``data.supported`` would silently convert every dual-era
  client's working fallback into a retry loop.

- **Revoking a token, deleting a trust relationship or downgrading a permission
  now evicts the MCP caches.** ``MCPHandler.clear_token_from_cache()`` had
  exactly one caller — the logout handler — so every other path that
  invalidates a client's identity or authorization left the in-process MCP
  caches serving the old answer for up to their five-minute TTL. A revoked
  token kept authenticating, a deleted trust kept authorizing, and a narrowed
  permission kept being honoured at the old level, from any warm process.

  Eviction is now wired into ``TokenManager.revoke_token()``, the SPA session
  paths ``revoke_access_token()`` / ``revoke_refresh_token()`` (which is what
  ``/oauth/revoke`` reaches), ``revoke_token_chain()`` (the refresh-token-reuse
  theft response), ``revoke_all_tokens()``, trust deletion, and both the store
  and delete paths of ``TrustPermissionStore``. It is actor-wide by necessity
  rather than scoped to one client: the cached ``ActorInterface`` carries the
  trust list itself, so evicting a single ``(actor, client)`` entry would leave
  the shared wrapper answering from stale state. One consequence worth knowing:
  any permission change on one client invalidates the cache for every MCP
  client connected to that actor.

  Eviction alone would not have been enough. A request that read a token from
  storage just before the revocation could write what it read back into the
  cache just after, reviving the credential for a full TTL while the eviction
  reported success. A generation counter, bumped by every eviction and
  snapshotted by each request before the reads that feed the caches, makes such
  a request decline to populate them.

  **This closes the window within one process only.** Every MCP cache is a
  module global, so a multi-worker or multi-container deployment still serves
  the stale entry from every *other* process until its TTL expires. Closing
  that needs a shared invalidation channel and is not attempted here.

- **``tools/list`` now warns when a hook's ``output_schema`` will not be
  advertised.** ``outputSchema`` comes solely from ``@mcp_tool``; a schema
  passed to ``@app.action_hook(..., output_schema=...)`` or derived from a
  ``TypedDict`` return annotation is stored separately and never bridged, so an
  author who declares one either of those ways gets silence rather than an
  advertised schema — and the missing-``structuredContent`` warning stays quiet
  for them too, because it is gated on the same metadata. The warning fires once
  per tool per process, at listing time.

  Deliberately a warning and not a merge: merging would newly advertise
  ``outputSchema`` for every ``TypedDict``-annotated tool, and each one that
  does not also return ``structuredContent`` would begin failing on
  spec-conforming clients. That decision belongs with the ``structuredContent``
  work and is not foreclosed here.

ADDED
~~~~~

- **DynamoDB table auto-creation can now be disabled** for deployments that
  manage tables via infrastructure-as-code: set
  ``AWS_DB_AUTO_CREATE_TABLES=false`` or call
  ``with_dynamodb(auto_create_tables=False)``. With auto-creation off, the
  library never calls ``DescribeTable``/``CreateTable``, so both permissions
  can be dropped from the runtime IAM role.

- **Actor deletion tombstones and a tri-state deletion check.**
  ``ActorInterface.get_deletion_status(actor_id, config)`` returns
  ``DeletionStatus.DELETED`` / ``NOT_DELETED`` / ``UNKNOWN`` from a tombstone
  written *before* the ``actor_deleted`` hook runs — so an external call made
  from that hook, and any provider callback racing it, already sees
  ``DELETED`` — and retained for 30 days, past every provider's webhook retry
  window.

  This exists because a guard of the form "skip this work if the actor no
  longer exists" could not be written correctly. ``Actor.delete()`` removes the
  actor row **last**, so ``get_by_id()`` keeps returning a live actor for the
  entire wipe: the check fails **open** in exactly the window it matters,
  which the documented cleanup pattern enters deliberately (``actor_deleted``
  cancels an external subscription; the provider's callback races the wipe).
  Checking harder is not available either, because ``get_by_id()`` returns
  ``None`` for a deleted actor *and* for a failed read — so the same guard
  fails **closed** on a throttle, which for a paid-subscription webhook means
  the customer paid and silently never got access. A consumer hit both:
  4 attribute rows in production belonged to fully deleted accounts.

  A tombstone is *positive* evidence, so it has a safe failure direction:
  ``UNKNOWN`` means proceed, costing at most one orphan row an operator sweep
  can find, rather than dropping work for a paying customer. The read is a
  single strongly-consistent point read — measured at exactly one ``GetItem``,
  not asserted. Tombstones live under a reserved id that is never itself an
  actor, so no deletion can destroy them, and expired ones are filtered at
  read time so TTL means the same thing on both backends. Re-creating an actor
  clears its tombstone (``create(actor_id=...)`` accepts a caller-supplied id).

  The actor row deliberately still goes last. Deleting it first would make
  existence checks fail closed rather than open, but "missing" is
  indistinguishable from "read failed" anyway, and it would cost the two
  properties that ordering buys: deletion stays retriable if a wipe step
  fails, and rows are never briefly classifiable as orphaned. The tombstone
  answers the question without that trade.

- **``actor_deleted_complete`` lifecycle hook**, fired after the
  wipe completes with ``actor=None`` and ``actor_id=<id>``. There was
  previously nowhere to put "do this once the actor is definitely gone", which
  forced applications into the race above by design: ``actor_deleted`` is the
  only place the actor's data is readable, so it was also the only place to
  act on it. Now the work splits — read in ``actor_deleted``, act in
  ``actor_deleted_complete`` — which removes the race at its source
  independently of the tombstone. The absent ``ActorInterface`` is the point,
  not an omission.

- **``get_attr_strict()`` on both attribute backends** —
  a point read that raises on infrastructure errors instead of collapsing them
  into ``None``, and treats an expired row as absent. Used by the tombstone
  read; available to applications with the same need. Building the tombstone
  read on ``get_attr()`` would have reintroduced the very bug it fixes.

  **Custom backend implementers:** this method is now part of
  ``DbAttributeProtocol``, which is ``@runtime_checkable`` — an out-of-tree
  attribute backend must add ``get_attr_strict()`` to keep satisfying
  ``isinstance()`` checks against the protocol. Both bundled backends
  implement it.

- **Operator-facing table verifier:**
  ``python -m actingweb.db.verify_tables`` reports which required DynamoDB
  tables exist and which are missing. With auto-creation disabled, "all
  tables exist" becomes a precondition the library deliberately no longer
  checks (an existence check would cost an ``AccessDenied`` per accessor
  construction on a slimmed role), and the required set previously had to be
  read out of the source. Run it out-of-band with operator credentials —
  it only reads, never creates, and adds nothing to the request path.
  ``--list`` prints the names without calling AWS. Exit codes: ``0`` all
  present, ``1`` one or more missing, ``2`` the check could not run. The
  same list now drives table pre-warm, so what the library creates and what
  operators are told to pre-create cannot drift apart.

- **``auto_create_enabled()`` is public API**
  (``from actingweb.db.dynamodb import auto_create_enabled``). Dropping
  ``DescribeTable``/``CreateTable`` from the runtime role affects the whole
  role, not just the library, so application code that probes its own tables
  (boto3 ``table.load()``/``describe_table``, pynamodb ``exists()``) needs
  the same switch — previously it had to re-implement the environment
  parsing. ``set_auto_create()`` and ``reset_ensure_cache()`` are exported
  alongside it.

- **MCP: a warning when a tool declares ``output_schema`` but returns no
  ``structuredContent``.** Spec-conforming clients reject such a result outright
  (``Tool X has an output schema but did not return structured content``), which
  was already broken before this release for anyone declaring a schema — the
  library advertises ``outputSchema`` in ``tools/list`` but never consulted it at
  call time. The warning fires once per tool per process, at call time, and only
  when the negotiated protocol version supports structured content, so a
  correctly-written hook talking to an older client never trips it.
  ``output_schema`` and ``structuredContent`` remain independent: declaring a
  schema has never caused structured output to be emitted, and the library still
  does not validate ``structuredContent`` against a declared schema.

- **MCP: a warning when ``structuredContent`` is set to a non-object.** MCP
  requires a JSON object there; a list, string or number was previously dropped
  silently. ``None`` is exempt and stays silent — it carries no payload, both
  reference clients read a null ``structuredContent`` as absent, and
  ``{"structuredContent": value or None}`` is a legitimate way to express
  "nothing structured this time". In that case the key is omitted from the
  response rather than emitted as ``null``.

- **Property-list repair primitives.** ``ListProperty.verify()`` reports a
  list's health (holes, orphan rows, a duplicate-value heuristic) without
  modifying anything; ``ListProperty.compact()`` closes holes and removes
  orphans in one pass while preserving ``description``/``explanation``/
  ``created_at`` (unlike the previous ``clear()`` + ``extend()`` workaround,
  which reset them). Duplicate residue is reported but never rewritten — a
  duplicate value always means a destroyed item, and silently collapsing
  one copy would bless the data loss as intentional. Both are also
  available through ``actor.property_lists.<name>.verify()``/``.compact()``.
  New operator script: ``scripts/verify_property_lists.py`` (dry-run by
  default; ``--repair`` invokes ``compact()`` on unhealthy lists).

- **Opt-in diagnostics for the PostgreSQL attribute ``DELETE`` path.** Set
  ``ACTINGWEB_PG_DELETE_DIAGNOSTICS=1`` to log, per attribute delete, the
  statement's ``rowcount``, the deleting connection's resolved schema and
  ``search_path``, and a post-commit re-read on a freshly checked-out
  connection. That combination distinguishes a delete that matched no rows
  (wrong schema or wrong key) from one that matched and did not persist — the
  question the quarantine above left unanswered for two months. Off by
  default. When on it costs a savepoint-wrapped schema read plus a post-commit
  re-read per delete, and cannot affect the delete it observes: the schema read
  runs *before* the ``DELETE`` and inside a savepoint, because a server-side
  failure there would otherwise abort the transaction and turn the later commit
  into a silent rollback — the exact defect the diagnostics exist to find.


.. note::

   ``compact()`` crash atomicity is **not** addressed here and is deferred.
   The warning boxes describing that window stand: the damage it
   leaves is visible in the data and ``verify()`` catches it.

FIXED
~~~~~

- **Changing an indexed property left its old reverse-lookup row behind on
  DynamoDB.** When an indexed value (e.g. ``email``) was updated through the
  normal properties API, the old lookup row was never deleted, so reverse
  lookup by the previous value kept resolving to the actor and blocked any
  other actor from claiming that value. The DynamoDB backend now reads the
  current value before writing, matching the PostgreSQL backend. (Only
  affected lookup-table mode, which is unreleased.)

- **Reverse-lookup migration fallbacks matched on value alone, ignoring the
  property name.** During a not-yet-backfilled migration, the legacy-GSI
  (DynamoDB) and sequential-scan (PostgreSQL) fallbacks could return an actor
  whose *different* property happened to share the requested value; both now
  filter by property name. (Migration-only path, unreleased.)

- **Two DynamoDB accessors never auto-created their tables.** First use of
  subscription suspension (``DbSubscriptionSuspension``) or the peer-trustee
  list on a fresh deployment crashed with a table-not-found error; both now
  go through the same table-existence guard as every other accessor.

- **Property lookup env overrides were silently ignored by the fluent builder.**
  ``ActingWebApp`` stamped its own hardcoded lookup-table defaults onto the
  config on every ``with_*()`` call (a guard intended to detect "explicitly
  set" was always true), so the documented ``USE_PROPERTY_LOOKUP_TABLE`` and
  ``INDEXED_PROPERTIES`` environment variables were clobbered for any app that
  called a builder method after construction — including the documented
  rollback path for lookup-table migration. The builder now tracks whether
  these settings were explicitly configured; precedence is consistently
  explicit builder call > environment variable > library default.

- **Every property write issued a subscription-suspension read,
  even with no subscribers.** ``register_diffs()`` runs on each write and
  checked suspension *before* fetching subscriptions, so an actor with no
  subscriptions on the target paid a DynamoDB ``GetItem`` **and** the
  subscription query, only to do nothing either way. The subscription fetch
  now comes first and returns early when empty; suspension is consulted only
  when there is something to suspend — one fewer read per property write on
  the common path, no caching assumptions required. Behaviour is unchanged
  (suspended and no-subscriptions were already the same outcome). Measured on
  DynamoDB Local, a property write on an actor with no subscribers is now
  ``{GetItem: 1, PutItem: 1, Query: 1}`` — no suspension read, no
  ``DescribeTable``, no ``Scan``.

- **A failed subscription-suspension check was indistinguishable
  from "not suspended".** ``Actor.is_subscription_suspended()`` logged any
  failure at DEBUG and returned ``False``, so a missing suspensions table
  (pynamodb raises ``TableDoesNotExist``, which is *not* ``DoesNotExist``) or
  a denied read made every target read as un-suspended: a bulk import's
  ``suspend()`` silently no-opped and per-item callbacks fired for every
  imported item — exactly what suspension exists to prevent — with no error
  anywhere. Operational failures are now logged at ERROR, naming the actor,
  the target and the consequence. The call still degrades to "not suspended";
  it is no longer silent about it. (The PostgreSQL accessor already logged
  these at ERROR.) The ERROR is rate-limited to once per five minutes per
  process — ``register_diffs()`` calls this on every property write, so an
  unconditional ERROR would flood at write rate, while a once-per-process
  guard would report the fault a single time on a warm serverless container
  and then stay silent through every later failure, including a different
  one. Throttled failures are logged at DEBUG.

- **Suspending a target suppressed nothing.**
  ``suspend_subscriptions("properties")`` — the documented bulk-import usage —
  had no effect on property writes. ``PropertyStore`` registers every diff
  with the property name as the **subtarget**, so the check looked up
  ``"properties:<name>"`` while ``suspend()`` had stored ``"properties"``, and
  the two never met. Only an exactly matching ``(target, subtarget)`` pair
  ever suspended anything. Target-level suspension now **cascades** to every
  subtarget beneath it, on both backends.

  This is the functional half of the same symptom the missing-table fix above
  addresses: a bulk import's ``suspend()`` no-opping and per-item callbacks
  firing for every item. Restoring the table alone would not have fixed it.

  Verified on DynamoDB Local: a property write under a suspended target now
  issues ``{GetItem: 1, PutItem: 1, Query: 2}`` against ``{GetItem: 3,
  PutItem: 3, Query: 3}`` un-suspended — the diff row and sequence bump are
  genuinely skipped. Previously the two were identical, because suspension
  did nothing.

  **Behaviour change.** Code that suspended a target while expecting
  individual subtargets to keep notifying will now see them suppressed. The
  reverse case is unaffected: ``suspend(target, subtarget)`` still suspends
  only that pair, and a subtarget suspension made while its target is already
  suspended is still recorded separately, so resuming the target does not
  silently lift it.

- **Subscriptions created through the interface layer received
  no diffs for the lifetime of the actor instance.**
  ``Actor.create_subscription()`` did not invalidate the actor's cached
  subscription list (``subs_list``); only the *delete* paths did, and only the
  protocol handler invalidated by hand after a create. So a subscription
  created via ``ActorInterface.subscriptions`` or the authenticated-peer view
  was invisible to ``register_diffs()`` afterwards — a silently dropped
  notification with no error anywhere. ``create_subscription()`` now
  invalidates it itself, so the invariant no longer depends on every caller
  remembering. Note this refreshes only the instance it is called on: a
  subscription created in another process, or against a different cached
  ``Actor``, still leaves that instance's list stale until it is rebuilt —
  tracked in ``thoughts/todo/subs-list-cache-asymmetry.md``.

- **Config-bound singletons no longer serve one application's state to
  another.** ``get_actingweb_oauth2_server()``,
  ``get_mcp_client_registry()``, ``get_actingweb_token_manager()``,
  ``get_oauth2_state_manager()``, ``get_permission_evaluator()``,
  ``get_registry()`` (trust types), ``get_trust_permission_store()``,
  ``get_peer_permission_store()``, ``get_peer_profile_store()`` and
  ``get_cached_capabilities_store()`` each take a ``config`` argument but,
  once built, ignored it — they bound to the **first** config the process
  ever passed and returned that instance to every later caller. (One of them
  documented this explicitly: "config parameter kept for interface
  consistency but not used".) Any process hosting more than one ActingWeb
  application therefore had the second application silently using the
  first's configuration, **including its database backend**. The observed
  consequence: MCP dynamic client registration wrote a trust row to one
  backend while trust resolution read another, so the client's trust was
  never found. Under the old fail-open behavior that granted the client
  *full access*; under the fail-closed behavior above it returns ``-32003``.
  Each getter now rebuilds when handed a different ``Config`` instance, and
  still returns the cached instance for the same one. Single-application
  deployments — the overwhelming majority — are unaffected either way.

  Note that ``ActingWebOAuth2Server`` *composes* three of these, so rebinding
  the server alone was not sufficient: ``client_registry``, ``token_manager``
  and ``state_manager`` had to rebind too. ``get_oauth2_state_manager()``
  re-reads its encryption key from the new config's system actor on rebind;
  the key is stored rather than generated, so it is stable.

- **MCP: an explicit ``isError`` is now honoured on the legacy text-wrap path.**
  A hook returning ``{"isError": True, "error": "boom"}`` with no ``content`` key
  previously reached the wire with no ``isError`` field at all, so the failure was
  reported to the client as a **success**. ``isError`` is honoured only when the
  hook sets it — it is never inferred from an ``"error"`` key or any other shape
  heuristic, so applications that return ``{"error": ...}`` on their normal error
  path see no change. The ``str(result)`` text serialization is unchanged, so
  ``isError`` appears both inside that text and as a wire field.

- **``list.index()`` semantics for negative ``start``/``stop``.**
  ``index(value, -1)`` could previously return ``-1`` as an index (the loop
  ran ``range(-1, n)`` and then indexed negatively). Both storage formats
  now normalize bounds exactly as ``list.index`` does, through one shared
  helper so they cannot diverge across a migration.

- **``pop()`` and ``remove()`` now delete conditionally on the value they
  read.** Resolving the item's storage key once was not enough: a
  concurrent assignment to that same key between the read and the delete
  would discard the other writer's value while reporting the one this
  caller saw — an outcome corresponding to no serial ordering of the two
  operations. Both now use the new
  ``DbPropertyProtocol.delete_if_value_equals()`` and re-resolve on a
  failed condition, so ``pop()`` always returns exactly what it removed and
  ``remove()`` always removes exactly what it matched.
  ``__delitem__``/``__setitem__`` remain unconditional by design.
- ``pop()`` on a v2 list no longer raises ``pop from empty list`` against a
  list another writer has appended to (the empty check consulted a cached
  length before the v2 path could refresh it).

- **``ListProperty.insert()`` destroyed data on every call into a non-empty
  list on DynamoDB.** ``insert()`` reused one cached ``DbProperty`` handle
  across its whole shift loop instead of taking a fresh handle per
  get()/set() like every other list method; on DynamoDB this caused each
  shifted row to be overwritten with the last value read instead of its
  own. Fixed both at the call site (fresh handles, matching the rest of the
  class) and in the DynamoDB and PostgreSQL backends' ``DbProperty.get()``/
  ``set()`` (a cached handle for a different ``(actor_id, name)`` is now
  always discarded rather than reused).

- **Backend read/write failures on property (and property-list item) storage
  were silently swallowed as absence or as a no-op.** ``DbProperty.get()``
  now raises ``actingweb.db.exceptions.DbError`` on a genuine backend fault
  instead of returning ``None`` (``None`` means the row does not exist, and
  only that, on both backends). Every ``ListProperty`` mutation
  (``append``, ``__setitem__``, ``__delitem__``, ``insert``, ``clear``,
  ``delete``, metadata writes) now checks ``set()``'s return value and
  raises ``RuntimeError`` instead of continuing past a failed write. This is
  a breaking change for any code that relied on a backend fault degrading
  to ``None``/no-op on a property read/write.
- Backend exception text no longer reaches HTTP error responses from the
  list-property handlers (``PUT``/POST/DELETE on ``/properties/<name>`` and
  ``/properties/<name>/items``) — the client sees a generic message; the
  original exception is still logged server-side.
- Unparsable list metadata no longer self-heals into a fresh empty list
  (which orphaned every existing item row with no way back to them) —
  ``ListProperty`` now raises ``ValueError`` instead, and the row is left
  untouched for repair.

DOCUMENTATION
~~~~~~~~~~~~~

- **The migration guide is organised by where you are upgrading from, not by
  which release candidate added what.** ``docs/migration/v3.13.rst`` had grown
  five sections titled "Behaviour change in rcN", each opening with a note
  telling you to read every section between your version and the target. That
  works while the rcs are current and stops working the moment they are one
  release. It now opens with a **Start here** section giving two paths — from
  ``3.12.x`` (do all four pieces of work, in the stated order, because two have
  pre-upgrade steps) and from a release candidate (a table saying exactly what
  is left to do for each of ``rc1`` through ``rc6``) — followed by what changed
  after ``rc6`` for anyone tracking the pre-releases. The four work sections
  are named for what they cover rather than for the rc that introduced them,
  and the DynamoDB material is now nested under its own heading instead of
  sitting as a flat run of peers titled "Overview".

- **New page: Actor Deletion Semantics** (``docs/reference/actor-deletion.rst``).
  States the contract that previously had to be read out of the source: the
  exact deletion order and why the actor row goes last, that ``get_by_id()``
  keeps resolving throughout the wipe, that its ``None`` means "not found *or*
  read failed", which of the two deletion hooks to use for what, and how to
  write the guard. Also documents that **attribute and property writes do not
  validate that the actor exists** — an unknown ``actor_id`` creates rows
  nothing will clean up. That is by design (``actor_id`` is a key prefix, not a
  foreign key, on both backends), but the API shape invites the opposite
  assumption: one consumer's test fixture wrote 228 rows under 114 ids that
  were never actors, unnoticed for five months. Closes with the four
  non-obvious edge cases in classifying orphaned rows, each of which is a way
  to delete live data.

- The Apple Sign-In revocation example now says why ``actor_deleted`` is the
  right hook *there* (``/auth/revoke`` is one-way) and what to do instead for a
  provider that calls back.

- **The required-table list is published** (``docs/reference/database-backends.rst``,
  ``Required DynamoDB tables``) with hash/range keys and which tables are
  conditional. ``AWS_DB_AUTO_CREATE_TABLES=false`` makes this a precondition,
  and it previously existed only in source. ``<prefix>_subscription_suspensions``
  is called out specifically: its accessor had no auto-create guard before
  3.13, so long-lived deployments frequently never created it.

- **The pre-warm/IaC race is documented.** Declaring the new tables in
  CloudFormation/Terraform in the *same* deploy as the library bump lets a
  cold start create ``<prefix>_property_lookup_v2`` first, failing the stack
  with ``ResourceInUseException``. Sequence the deploys, or let auto-creation
  own the tables — not both.

- **The rollback instruction is qualified.** Legacy mode needs the
  ``property-index`` GSI on the properties table; a table created before that
  index existed has no rollback path for reverse lookup. Check
  ``describe-table`` before upgrading.

- **Migration rehearsal against DynamoDB Local** is documented end-to-end —
  table creation, fallback tiers, backfill, tripwire — so the backfill is not
  performed for the first time in production.

- **A recipe for proving the fixes landed**, since both are invisible to
  functional tests: count DynamoDB operations via
  ``botocore.client.BaseClient._make_api_call``. Includes the trap that a
  ``before-call.dynamodb`` session handler counts *nothing* under pynamodb
  (``get_session()`` returns a fresh session per call), which makes
  ``assert scans == 0`` pass vacuously.

- **Validating this release requires a DynamoDB backend** — a green suite on
  PostgreSQL exercises none of the changed code.

- **Auditing your own ``DescribeTable``/``CreateTable`` use** is called out
  when recommending the flag: the IAM change is account-wide, not
  library-scoped.

- **Reverse lookup is not always the login path** — apps resolving via
  ``get_from_creator()`` are unaffected, which changes how urgent the backfill
  is. The doc now says to check rather than assume.

- **Direct ``DbPropertyLookup().get()`` use bypasses the fallback tiers**
  (v2-only), so operational scripts return ``None`` during the migration
  window while the app is healthy. ``get_actor_id_from_property()`` is named
  as the supported entry point.

- **``describe-table``'s ``ItemCount`` refreshes only every ~6 hours**, so a
  freshly backfilled lookup table still reports ``ItemCount: 0``. Verify with
  ``scan --select COUNT``.

- **Documented that ``compact()`` is not crash-safe in either storage
  format, and that an interrupted repair leaves damage repair will not
  itself fix.** Only the v2 rank-rebalance window was documented in
  this release; the v1 path -- the one every upgrading operator runs via
  ``actingweb-verify-property-lists --repair`` -- has the same shape.
  Survivors are written to their new positions before the tail rows are
  deleted, so an interruption leaves a copy at both, with the stored length
  unchanged: the list reads back with **no error**. ``verify()`` catches it
  through the adjacent-duplicate heuristic, but re-running ``--repair``
  will not remove the copy, because duplicates are preserved by design --
  including the one the interrupted repair created. Now covered in the
  migration guide's repair step (where operators are told to run it), the
  property-lists guide, and ``compact()``'s docstring, with a regression
  test pinning the measured interruption states. No behaviour change.
- Corrected two stale statements about lazy migration, which is **off by
  default** in this release: the downgrade-ordering warning described a
  50-item list as "by definition a lazy-migration candidate" (true only where
  an operator has raised the limit), and the bulk script's own docstring
  opened by describing lazy migration as the normal path.


v3.12.0: July 9, 2026
---------------------

ADDED
~~~~~

- **Built-in default web-UI templates.** The library now ships a minimal set of
  templates (factory/sign-in page, actor dashboard, properties, trust, OAuth2
  consent, email/verification pages), so ``with_web_ui(True)`` renders a working
  web UI out of the box with no app-supplied templates. Application templates of
  the same name still take precedence (Flask: a template-only blueprint; FastAPI:
  the app ``templates_dir`` is searched first). Both integrations also register a
  ``/login`` route that renders the sign-in page.

FIXED
~~~~~

- **Programmatically-enabled property lookup tables leaked stale reverse-lookup
  rows on bulk delete.** ``DbPropertyList.delete()`` and
  ``DbProperty.get_actor_id_from_property()`` constructed a fresh ``Config()``
  internally to decide whether to maintain the property lookup table. A fresh
  ``Config()`` only reflects environment variables and defaults, so a lookup
  table enabled through the builder (``with_indexed_properties()`` /
  ``with_legacy_property_index(enable=False)``, which set attributes on the
  app's ``Config`` — not env vars) read back as *disabled* inside these methods.
  As a result, deleting all of an actor's properties (e.g. on actor deletion)
  skipped lookup-table cleanup and left stale entries that could resolve reverse
  lookups to a deleted actor; reverse lookup could likewise take the wrong code
  path. ``get_property_list()`` now injects ``use_lookup_table`` /
  ``indexed_properties`` into ``DbPropertyList`` (matching ``get_property()``),
  and both methods use the injected settings instead of a throwaway ``Config``.
  Applies to both the DynamoDB and PostgreSQL backends. Env-var-based
  configuration is unchanged (constructors still fall back to the environment).
- **DynamoDB bulk property delete could remove another actor's reverse-lookup
  row.** The DynamoDB property lookup table is keyed on ``(property_name,
  value)``, so when two actors share the same indexed value the row points at
  whichever actor wrote last. ``DbPropertyList.delete()`` deleted the lookup
  row for each of the deleted actor's indexed values unconditionally, which
  could wipe out a *different* actor's still-valid reverse-lookup entry. The
  bulk cleanup now verifies the row belongs to the actor being deleted before
  removing it, matching the single-property delete path. PostgreSQL was
  unaffected (its cleanup already scopes the delete by ``actor_id``).
- **``with_mcp(server_name=..., instructions=..., enable=...)`` were silently
  ignored.** ``ActingWebApp.__init__`` builds the ``Config`` eagerly (permission
  warmup), and the runtime config-sync did not re-apply the MCP fields, so
  builder-set MCP options never reached ``Config``. ``config.mcp`` is now a
  first-class attribute, kept in sync (including the advertised ``/meta``
  capability tag).
- **``@mcp_tool`` metadata no longer appears blank in ``GET /<id>/actions``.**
  Stacking the required ``@app.action_hook("name")`` decorator over ``@mcp_tool``
  attached empty explicit metadata that shadowed the MCP metadata. Hook metadata
  resolution now merges per field: explicit non-empty values win, otherwise the
  ``@mcp_tool`` metadata (then auto-generated schemas) is used.
- **Built-in factory templates now honor a URL path prefix.** The sign-in form
  action and the post-creation "Go to dashboard"/"Back to start" links in the
  bundled factory templates hardcoded root-relative ``/`` URLs, so a deployment
  mounted under a prefix (``config.root`` like ``https://host/base/``) posted to
  and linked at the domain root instead of the mounted app. The factory handler
  now passes a ``base_path`` (derived from ``config.root``) into the template
  context and the templates prepend it.

DOCUMENTATION
~~~~~~~~~~~~~

- Rewrote ``README.rst`` to reflect the current framework (AI/MCP + web/SPA +
  native-mobile clients over one backend).
- Corrected a range of API-reference inaccuracies verified against the code:
  ``TrustManager``/``SubscriptionManager``/``PropertyStore`` method names and
  signatures, ``AwProxy`` usage, ``ActorInterface`` attributes, authenticated
  views, and the ``ActorInterface.create(hooks=app.hooks)`` requirement for
  lifecycle hooks to fire. Stopped recommending ``actor.is_owner()`` (a
  placeholder that always returns ``True``) as an access guard.
- Fixed quickstart friction found by a cold-build usability pass: DynamoDB Local
  prerequisites, the ``migrate_db.py`` download URL (``master`` branch), MCP
  endpoint auth (no dev bypass), scalar-property stringification, ``templates_dir``
  being optional, and Basic-auth vs OAuth for ``/www``.

v3.11.0: July 4, 2026
---------------------

3.11.0 rolls up everything developed since v3.10.1 (previously published as the
``v3.10.2bN`` and ``v3.11.0bN`` pre-release lines). The theme is **authentication
breadth and SPA/mobile session hardening**: Sign in with Apple, GitHub and native
Google sign-in, native-mobile OAuth code/ticket exchange, a substantial hardening
of the SPA refresh-token rotation flow, and a round of MCP protocol improvements.
It also removes the vestigial optional MCP Python SDK dependency.

Almost all of 3.11.0 is additive and backward compatible. The items that need
action when upgrading from 3.10 are collected in
``docs/migration/v3.11.rst`` — in short: PostgreSQL users run one new Alembic
migration; DynamoDB users confirm native TTL is enabled; split-domain SPA
deployments set ``spa_redirect_origins``; SPA/mobile clients review the
refresh-token contract. The notes below describe the **net change from v3.10.1**;
fixes to functionality introduced within this same pre-release window are folded
into the feature that introduced them rather than listed separately.

ADDED
~~~~~

Native mobile and multi-provider sign-in:

- **Sign in with Apple support** across web SPA, native iOS, Android Capacitor,
  and the LLM-triggered (MCP) OAuth web form. New ``app.with_apple_sign_in(...)``
  builder configures Apple as a first-class OAuth provider (Services ID + Team ID
  + Key ID + ``.p8`` private key). Apple's ES256 ``client_secret`` JWT is minted
  on demand and cached per 5-minute bucket; the ``id_token`` is validated against
  Apple's JWKS (no userinfo endpoint). The ``.p8`` key is supplied via
  ``private_key_path`` / ``APPLE_PRIVATE_KEY_PATH`` (file wins) or
  ``private_key_pem`` / ``APPLE_PRIVATE_KEY_PEM`` and is validated eagerly at
  config-build time. See ``docs/guides/apple-sign-in.rst``.
- **New ``app.with_github(...)`` builder** mirroring ``with_apple_sign_in`` /
  ``with_google_native``: fills in GitHub's endpoints and, with
  ``mobile_redirect_uri``, registers a ``github-mobile`` provider that uses the
  server-side ticket flow (GitHub issues no OIDC ``id_token``, so it cannot use
  the JWT-bearer grant).
- **New ``app.with_google_native(...)`` builder** for native Google sign-in via
  the JWT-bearer grant (accepts explicit ``audiences`` or derives them from the
  per-platform client IDs).
- **Native mobile OAuth code exchange**: the ``authorization_code`` grant on
  ``POST /oauth/spa/token`` lets native mobile apps exchange an OAuth code received
  via deep link for ActingWeb SPA tokens (RFC 8252). ``exchange_code_for_token()``
  accepts an optional ``redirect_uri`` override so provider classes honor custom
  URL schemes, and the SPA authorize endpoint validates the requested provider via
  ``_is_known_provider()``. Provider-name variants such as ``google-mobile`` /
  ``github-mobile`` are resolved by prefix matching in
  ``create_oauth2_authenticator``.
- **New JWT-bearer grant on ``POST /oauth/spa/token``**
  (``grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer``, RFC 7523): native
  apps exchange a provider ``id_token`` (``assertion``) plus ``nonce`` for an
  ActingWeb session. The validator is dispatched by the declared ``provider`` and
  the token ``iss`` must match it; single-use replay protection is enforced.
- **New ``mobile_ticket`` grant** (generalized from the original Apple-only
  ``apple_mobile_ticket``, which remains as an alias): any native-mobile provider
  whose authorization response lands on the HTTPS callback is handed an opaque
  single-use deep-link ticket and the code is exchanged server-side — no IdP code
  and no ActingWeb token ever rides the deep link. Used by Apple-on-Android and
  GitHub mobile. Redemption is atomic and race-free single-use (a conditional
  delete reports success to exactly one caller, closing the concurrent-replay
  window), and the 300 s TTL is enforced at redemption.
- **Apple nonce hashing handled by the library.** Apple's native flow puts
  ``SHA256(nonce)`` (hex) in the id_token's ``nonce`` claim while Google echoes
  it verbatim. The Apple id_token validator accepts either the raw nonce or its
  SHA-256, so apps pass the **same raw nonce** to the JWT-bearer grant for every
  provider instead of pre-hashing per provider. Google validation stays a strict
  verbatim match.
- **New POST ``/oauth/callback/apple`` endpoint** for Apple's
  ``response_mode=form_post`` callback, protected by a server-side single-use
  state nonce (CSRF-safe without relying on SameSite cookies).
- **Normalized ``user_info`` shape on the ``oauth_success`` hook**
  (``display_name`` / ``given_name`` / ``family_name`` / ``email`` / ``sub``
  plus passthrough) across all providers. Apple's first-sign-in ``user`` payload
  (name) is merged before the hook fires. GitHub carries the profile name in
  ``name`` (falling back to ``login`` when unset), normalized consistently across
  the web-login, SPA-via-callback and token-exchange paths.
- ``actor.store.oauth_provider`` is now written on **every** sign-in (create and
  existing-actor paths), so account-deletion / revocation logic can rely on it.
- ``/oauth/config`` provider entries gain additive ``response_mode``
  (``form_post`` for Apple, ``query`` otherwise) and ``platform`` fields.

SPA session hardening:

- **``ActingWebApp.with_spa_redirect_origins(*origins)`` builder** — a fluent
  way to allow additional SPA redirect origins for split-domain deployments
  (previously only settable via ``Config.spa_redirect_origins``). Feeds the
  ``/oauth/spa/authorize`` redirect_uri allowlist.
- **``ActingWebApp.with_spa_cors_origins(*origins)`` builder** — restrict the CORS
  ``Access-Control-Allow-Origin`` for the SPA OAuth endpoints (default ``"*"``).
  ``spa_cors_origins`` is now a first-class ``Config`` attribute, and the CORS
  handler treats an empty list as ``"*"``.
- **Bounded retention for used SPA refresh tokens + an efficient expiry purge.**
  Two changes keep the (single, shared) SPA token bucket from growing without
  bound — previously a used refresh token was retained for the full two-week TTL
  and nothing ever deleted it:

  - On rotation, a consumed refresh token's storage TTL is shortened from two
    weeks to a bounded reuse-detection window
    (``SPA_REFRESH_TOKEN_REUSE_WINDOW``, default 2 days). After the window a used
    token is purged and a later replay reads as an expired token (rejected)
    rather than triggering chain revocation — an acceptable, bounded detection
    horizon that shrinks steady-state token volume ~7×.
  - Self-contained purge — **no cron/Lambda required**. The
    ``/oauth/spa/token`` endpoint opportunistically calls the new
    ``OAuth2SessionManager.maybe_purge_expired_tokens()``, which runs at most
    once per ``SPA_TOKEN_PURGE_INTERVAL`` (1 hour) per process via a
    process-local throttle. The underlying ``purge_expired_tokens()`` /
    backend ``DbAttribute.delete_expired(now_epoch=None, buckets=None)`` issues a
    single set-based ``DELETE`` on PostgreSQL backed by the existing
    ``idx_attributes_ttl`` partial index (O(expired rows), not O(all tokens)).
    On **DynamoDB** the purge is a no-op: cleanup relies on the table's native
    TTL on ``ttl_timestamp``, which must be enabled once per environment (see
    ``docs/reference/database-backends.rst`` → "Expired Token Cleanup (TTL)").
- **Indexed refresh-token family revocation (PostgreSQL).**
  ``revoke_token_chain`` delegates to a new backend
  ``DbAttribute.delete_by_chain(actor_id, buckets, chain_id)``. On PostgreSQL
  this is a single ``DELETE`` backed by a new partial expression index
  ``idx_attributes_chain_id`` on ``(data ->> 'chain_id')`` — O(chain) regardless
  of how large the shared token partition grows (**requires the new Alembic
  migration ``d4e5f6a7b8c9``; run** ``alembic upgrade head``). On DynamoDB it
  remains a bounded scan of the two token buckets (no GSI on the JSON-embedded
  ``chain_id``); a GSI on a promoted top-level ``chain_id`` attribute is the
  documented optimization path for very large DynamoDB deployments.

MCP:

- **MCP protocol version negotiation**: the ``/mcp`` handler negotiates the
  protocol version during ``initialize`` instead of hardcoding ``2024-11-05``. It
  echoes the client's requested ``protocolVersion`` when supported, otherwise
  returns the server's latest supported version (maintained in
  ``actingweb/mcp/protocol.py``, currently through ``2025-11-25``). The
  ``MCP-Protocol-Version`` request header is honored on post-initialize requests
  (defaulting to ``2025-03-26`` when absent, ``400`` when present-but-unsupported),
  and GET discovery reports the full supported-version set. Backward compatible:
  ``2024-11-05``-only clients still negotiate ``2024-11-05``. The new
  ``actingweb/mcp/protocol.py`` module exposes the version constants and
  ``negotiate_protocol_version`` / ``is_supported_protocol_version`` /
  ``supports_structured_content`` helpers as a single source of truth (also used
  by the OAuth2 discovery endpoint).
- **Structured tool output (``structuredContent``)**: ``tools/call`` results
  populate the spec ``structuredContent`` field when the negotiated protocol
  version supports it (>= ``2025-06-18``). A hook returning a dict with ``content``
  plus extra top-level keys has those extras promoted into ``structuredContent``;
  an explicit ``structuredContent`` from the hook is passed through, and a
  hook-supplied ``_meta`` is preserved. For older negotiated versions
  ``structuredContent`` is omitted (the payload is still carried by ``content``).

  .. warning::

     **The promotion described above was removed in v3.13.0rc4.**
     ``structuredContent`` is now emitted only when a hook sets that key
     explicitly; extra top-level keys are no longer promoted. See the
     ``v3.13.0rc4`` entry and ``docs/migration/v3.13.rst``.
- **MCP tool per-actor visibility**: ``@mcp_tool`` accepts a
  ``visibility_predicate(actor) -> bool`` to omit tools from ``tools/list`` for
  actors that should not see them (fail-closed on predicate errors). Note:
  visibility filtering applies to ``tools/list`` only — omitted tools can still be
  invoked by name, so call-time enforcement must be implemented separately for any
  tool that gates privileged behavior.
- **MCP tool per-actor descriptions**: ``@mcp_tool`` accepts a
  ``description_predicate(actor) -> str | None`` to override the tool description
  per actor, taking precedence over ``client_descriptions`` and the static
  ``description``.
- **Configurable MCP server name**: ``ActingWebApp.with_mcp(server_name="myapp")``
  sets the name announced in the MCP ``initialize`` handshake and surfaced on
  ``serverInfo.name`` (some clients use it as the default tool prefix,
  ``myapp:search`` vs ``actingweb:search``).
- **Configurable MCP server instructions**:
  ``ActingWebApp.with_mcp(instructions="...")`` sets the server-level orientation
  string emitted on the ``InitializeResult.instructions`` field — useful for
  pointing new LLMs at an entry-point tool (e.g. ``how_to_use()``).
  ``serverInfo.version`` reports the ActingWeb version.
- **Per-MCP-session identity on ``MCPContext``**: new optional
  ``transport_session_id`` and ``client_info`` fields expose per-session identity
  distinct from ``peer_id`` / ``trust_relationship`` (which are per-OAuth2-
  credential and shared across concurrent sessions on the same credential).
  ``transport_session_id`` is taken from the spec's ``Mcp-Session-Id`` header and
  is ``None`` when the transport supplies none; ``client_info`` carries the live
  ``clientInfo`` captured at the session's ``initialize`` call.
  ``get_client_info_from_context()`` prefers this live per-session ``client_info``
  so two MCP sessions sharing one OAuth2 credential no longer see each other's
  identity. Backward compatible: both fields default to ``None``.

CHANGED
~~~~~~~

- ``PyJWT[crypto]`` is now a core dependency (required for Apple's ES256
  ``client_secret`` and RS256 ``id_token`` validation).
- **FastAPI minimum raised to ``>=0.112``** (the ``fastapi`` extra). The FastAPI
  integration uses the Starlette 1.0 request-first ``TemplateResponse`` signature
  (adopted in 3.10.1), which requires Starlette ``>=1.0`` / FastAPI ``>=0.112``;
  the dependency floor now matches, so ``actingweb[fastapi]`` can no longer resolve
  an incompatible older FastAPI/Starlette that raised ``unhashable type: 'dict'``.
- ``OAuth2Authenticator`` was refactored to a strategy pattern: provider-specific
  behavior now lives on ``OAuth2Provider`` subclasses
  (``GoogleOAuth2Provider`` / ``GitHubOAuth2Provider`` / ``AppleOAuth2Provider``).
  Public method signatures and the ``actingweb.oauth2.requests`` patch point are
  preserved — fully backward compatible.
- **Logout no longer revokes the upstream identity-provider grant.** On
  ``/oauth/logout`` (and the ``/oauth/spa/*`` session-token revoke), the handler
  now clears the stored provider token **locally** (nulling ``oauth_token``,
  ``oauth_token_expiry`` and ``oauth_token_timestamp``, leaving only the
  ``oauth_provider`` identity metadata) instead of calling the provider's
  token-revocation endpoint. The old behavior (added in 3.10.0) was acceptable for
  Google but wrong for **Apple**: hitting Apple's revocation endpoint emails the
  user and severs the Sign in with Apple grant entirely, re-prompting for consent
  on the next login. Logout is a session action, not an account disconnect;
  provider-side revocation is now reserved for an explicit account-disconnect /
  delete flow. This supersedes the 3.10.0 "OAuth provider token revoked on logout"
  behavior.
- The MCP OAuth2 server now resolves authenticators on demand
  (``_get_authenticator(provider)``) instead of pre-instantiating Google/GitHub,
  so Apple is offered in the LLM-triggered authorization web form.
- Token-exchange, token-refresh, token-revocation, and userinfo error logs now
  redact ``client_secret`` / ``assertion`` / ``id_token`` / ``client_assertion``
  and truncate the response body.
- **MCP ``tools/call`` results include ``isError``** (defaulting to ``false``)
  per the MCP spec **when the hook returns a dict containing ``content``**,
  where previously such a hook returning ``{"content": [...]}`` without
  ``isError`` was passed through verbatim. Clients doing strict equality on the
  result object may observe the added field. This does not apply to the legacy
  text-wrap path (a hook returning a dict with no ``content`` key, or a bare
  value), which emits no ``isError`` at all; see the ``v3.13.0rc4`` entry,
  which makes that path honour an explicitly set ``isError``.
- **MCP server name no longer includes ``actor_id``**: the announced server name
  defaults to ``"actingweb"`` instead of ``"actingweb-{actor_id}"``. Each MCP
  connection is already per-actor, so disambiguation in the name was unnecessary
  and made client-side tool prefixes noisy.

FIXED
~~~~~

- **SPA/mobile refresh-token reuse detection now revokes only the offending token
  family, not every token for the actor.** Refresh tokens carry a ``chain_id``
  identifying their rotation *family*: rotation propagates the parent's
  ``chain_id`` while each fresh login starts a new chain, and reuse-after-grace
  now calls ``OAuth2SessionManager.revoke_token_chain(actor_id, chain_id)`` to
  revoke only that lineage (RFC 6819 token-family revocation), including the
  chain's access tokens. Previously reuse called ``revoke_all_tokens(actor_id)``,
  so a single stale token from one device logged the user out everywhere (and
  clients that did not degrade the resulting ``401`` to a login screen went blank).
  The actor's other devices/sessions keep working. Legacy refresh tokens minted
  before ``chain_id`` existed fall back to revoking only the presented token.
- **The refresh-token grace window now issues a full rotation instead of an
  access-token-only response, fixing a delayed-lockout trap.** Reuse of an
  already-used refresh token within the extended grace window now issues a full
  rotation (new access + new refresh token in the same ``chain_id``), so a client
  that dropped a prior rotation (e.g. a mobile WebView suspended before persisting
  the rotated token) recovers instead of being locked out one access-token
  lifetime later. Any later reuse across the divergent branches is caught by the
  chain-scoped reuse detection above.
- **``OAuth2SessionManager.revoke_all_tokens()`` no longer crashes** with
  ``RuntimeError: dictionary changed size during iteration`` when an actor has a
  matching token to revoke: both loops now snapshot ``list(<bucket>.items())``
  before deleting.
- **Cancelled SPA consent no longer renders a backend error page.** When a user
  cancels consent during an SPA login, the provider redirects back with
  ``error=access_denied`` and no authorization code. The OAuth callback now detects
  ``spa_mode`` from the OAuth ``state`` and bounces the error back to the SPA's
  callback URL as ``error`` / ``error_description`` query params (validated with
  ``is_safe_spa_redirect``, falling back to the configured root), so the app can
  show a friendly message instead of ``aw-root-failed.html`` / a 500. Apple's
  ``response_mode=form_post`` callback gets the same treatment.
- **Actor/trust deletion no longer recurses infinitely and exhausts the DB
  connection pool.** ``Trust.delete()`` now deletes the local trust record
  **first** and performs OAuth2 client cleanup afterwards, so the delete-client
  cascade (``delete_client -> delete_relationship -> delete_reciprocal_trust ->
  Trust.delete``) finds nothing to re-discover and terminates. Previously the
  cascade recursed until ``maximum recursion depth exceeded``, and on PostgreSQL
  each recursion level leaked a pooled connection, self-deadlocking the pool.
- **OAuth2 client deletion (and trust deletion) no longer aborts** when the
  best-effort global client index lookup misses: when the caller supplies the
  authoritative ``actor_id`` (as trust deletion does), the client is deleted from
  that actor's bucket regardless, preventing orphaned-but-listable clients.
- **MCP ``tools/list`` now surfaces ``title`` and ``outputSchema``**: ``@mcp_tool``
  has long accepted ``title`` and ``output_schema``, but the ``/mcp``
  ``tools/list`` builder dropped both when constructing the tool definition. Hosts
  that key on the MCP 2025-11-25 ``Tool.title`` (e.g. Claude Code's tool-permission
  dialog) therefore saw only the internal ``name``, and clients supporting
  structured output had no schema to validate against. ``tool_def`` now includes
  ``title`` and ``outputSchema`` when set on the decorator.
- **MCP ``tools/call`` formatting parity between Flask and FastAPI**: the sync
  (``MCPHandler``) and async (``AsyncMCPHandler``) handlers now share a single
  ``format_call_tool_result`` implementation, so both frameworks format tool-call
  responses identically.
- A leftover debug log in the actor-by-creator lookup (``db.postgresql.actor`` and
  ``db.dynamodb.actor``) that was emitted at ``WARNING`` on every match — a hot path
  during OAuth sign-in — is now ``DEBUG`` with a clearer message.

REMOVED
~~~~~~~

- **Dropped the optional ``mcp`` (MCP Python SDK) dependency.** ActingWeb's MCP
  support is fully hand-rolled and did not functionally depend on the SDK (the
  SDK-backed ``ActingWebMCPServer`` was never wired to serve requests). Removing it
  also drops ~a dozen transitive packages (the SSE/streaming + jsonschema +
  pydantic-settings stack). The ``mcp`` install extra is removed; MCP support no
  longer requires any extra.
- **Removed ``actingweb.mcp.get_server_manager``, ``MCPServerManager`` and
  ``ActingWebMCPServer``** (the vestigial SDK-backed server). The supported way to
  configure the MCP server name and instructions is
  ``ActingWebApp.with_mcp(server_name=..., instructions=...)``. The internal
  ``_match_uri_template`` helper moved to ``actingweb/mcp/uri.py`` as
  ``match_uri_template``.

SECURITY
~~~~~~~~

- **SPA OAuth open-redirect / session-token leak fixed.** The ``redirect_uri``
  passed to ``POST /oauth/spa/authorize`` (where the browser is later redirected
  with a one-time ``?session=`` id) is now validated against an allowlist: the
  backend's own FQDN, the origins of configured OAuth redirect URIs / Apple mobile
  deep links, and any origins listed in the new ``Config.spa_redirect_origins``
  (for split-domain SPA deployments). An off-origin ``redirect_uri`` is rejected
  with ``400`` at authorize time, and the callback falls back to the backend root
  rather than honoring an unsafe target. Previously an attacker who induced a
  victim to start an authorize flow with an attacker-controlled ``redirect_uri``
  could receive the victim's one-time session id and exchange it for tokens. This
  affected all SPA providers (Google / GitHub / Apple).

- **Raised the minimum versions of security-sensitive dependencies past known
  vulnerable releases.** ``PyJWT >= 2.13`` (was ``^2.9``) clears CVE-2026-48523 —
  an algorithm-allowlist bypass in the ``PyJWKClient`` / JWKS decode path, which
  is exactly the flow the new native ``id_token`` validation (Apple / Google)
  relies on. ``cryptography >= 48.0.1`` (was ``>= 43.0``), ``requests >= 2.32.4``
  (was ``>= 2.20``; clears the proxy-``Authorization`` and ``.netrc`` credential
  leaks and the ``verify=False`` persistence bug), and ``oauthlib >= 3.2.2``
  (was ``>= 3.2``; clears the ``redirect_uri`` DoS CVE-2022-36087). These are
  lower-bound raises only — they do not cap any dependency's upper version.

v3.10.1: Apr 2, 2026
---------------------

FIXED
~~~~~

- **Starlette 1.0 compatibility**: Update all ``TemplateResponse`` calls in
  ``fastapi_integration.py`` to use the new Starlette 1.0 signature
  ``TemplateResponse(request, name, context=...)`` instead of the deprecated
  ``TemplateResponse(name, {"request": request, ...})`` convention. This fixes
  an ``unhashable type: 'dict'`` error when rendering OAuth authorization forms
  with Starlette >= 1.0.0. Requires Starlette >= 1.0.0 (included with
  FastAPI >= 0.112.0).

v3.10.0: Mar 21, 2026
----------------------

BREAKING CHANGES
~~~~~~~~~~~~~~~~

- **Library Bucket Naming Convention**: All library-internal attribute buckets now use ``_``
  prefix to avoid namespace collisions with user-defined buckets. Renamed: ``trust_types`` →
  ``_trust_types``, ``trust_permissions`` → ``_trust_permissions``, ``peer_profiles`` →
  ``_peer_profiles``, ``peer_capabilities`` → ``_peer_capabilities``, and all OAuth index
  buckets. Existing transient data (tokens, sessions) will naturally be recreated; trust types
  and permissions may need explicit migration.

- **``google_token_data`` parameter renamed**: ``TokenManager.create_authorization_code()``
  parameter renamed to ``provider_token_data`` to reflect multi-provider OAuth support.

ADDED
~~~~~

- **Multi-Provider OAuth Support**: Multiple OAuth providers (e.g., Google and GitHub) can now
  be configured simultaneously using
  ``.with_oauth(provider="google", ...).with_oauth(provider="github", ...)``. The login page
  renders buttons for all configured providers, and ``/oauth/config`` returns all providers.
  Fully backward compatible — existing single-provider configurations work without modification.

- **SPA Email Collection Flow**: When an OAuth provider cannot supply a verified email, the SPA
  OAuth callback now redirects back to the SPA with ``?email_required=true&session=<id>`` so
  SPAs can display their own email input UI.

- **Email Verification via ``/oauth/email?verify=<token>``**: New GET handler provides
  actor-ID-free email verification URLs. The ``email_verification_required`` hook now fires
  consistently for both SPA and HTML template flows. The legacy
  ``/{actor_id}/www/verify_email?token=<token>`` URL remains functional for backward
  compatibility.

- **Provider Display Name Helper**: New ``get_provider_display_name()`` public function in the
  ``oauth2`` module for consistent provider name formatting (e.g., "GitHub").

- **Peer Profile Caching**: Cache profile attributes (displayname, email, etc.) from trusted
  peer actors to eliminate repeated API calls. Configure with
  ``ActingWebApp.with_peer_profile(attributes=[...])``. New ``TrustManager`` methods:
  ``get_peer_profile()``, ``refresh_peer_profile()``, ``refresh_peer_profile_async()``.

- **Peer Capabilities Caching**: Cache methods and actions that peer actors expose. Configure
  with ``ActingWebApp.with_peer_capabilities(enable=True)``. New ``TrustManager`` methods:
  ``get_peer_capabilities()``, ``get_peer_methods()``, ``get_peer_actions()``,
  ``refresh_peer_capabilities()``, ``refresh_peer_capabilities_async()``.

- **Peer Permissions Caching**: Cache permissions that peer actors have granted us (distinct
  from ``TrustPermissions``, which stores what we grant to peers). Configure with
  ``ActingWebApp.with_peer_permissions(enable=True)``. Includes access-checking methods:
  ``has_property_access()``, ``has_method_access()``, ``has_tool_access()``.

- **Permission Query Endpoint**: New ``GET /{actor_id}/permissions/{peer_id}`` endpoint allows
  peers to query the permissions they have been granted, including effective trust type defaults.

- **Automatic Peer Notification on Permission Change**: When permissions are updated, the peer
  is automatically notified via a POST to their ``/callbacks/permissions/{actor_id}`` endpoint.
  Configure with ``ActingWebApp.with_peer_permissions(notify_peer_on_change=True)``
  (default: ``True``).

- **Auto-Delete Cached Peer Data on Permission Revocation**: Optionally delete cached peer data
  when permissions are revoked. Enable with
  ``ActingWebApp.with_peer_permissions(auto_delete_on_revocation=True)``.

- **Automatic Subscription Processing**: New ``CallbackProcessor``, ``RemotePeerStore``, and
  ``FanOutManager`` modules handle incoming subscription callbacks with automatic sequence
  validation, gap detection, resync triggering, and back-pressure support.

- **Pull-Based Subscription Sync**: New ``SubscriptionManager.sync_subscription()`` and
  ``sync_peer()`` methods (and async variants) for explicitly fetching and processing pending
  diffs from peers. Complements push-based callbacks for "Sync All" workflows.

- **Subscription Suspension**: Subscriptions can be suspended on repeated delivery failures and
  resumed later, with automatic resync on resume. New ``SubscriptionSuspension`` database table
  in both DynamoDB and PostgreSQL backends.

- **Revoke Peer Subscription**: New
  ``SubscriptionManager.revoke_peer_subscription(peer_id, subscription_id)`` for semantically
  clear deletion of inbound subscriptions (peer's subscription to our data). Notifies the peer
  and removes the local record.

- **Subscription Deleted Lifecycle Hook**: New ``subscription_deleted`` lifecycle event triggered
  when an inbound subscription is deleted, receiving ``actor``, ``peer_id``,
  ``subscription_id``, ``subscription_data``, and ``initiated_by_peer`` flag.

- **Inbound Subscription Query**: New
  ``SubscriptionManager.get_subscriptions_from_peer(peer_id)`` for querying inbound
  subscriptions (peers subscribed to our data). Complements existing
  ``get_subscriptions_to_peer()``.

- **AsyncMCPHandler for FastAPI**: MCP tools and prompts with async hooks now execute natively
  in the FastAPI event loop, without thread pool overhead. FastAPI automatically uses
  ``AsyncMCPHandler``; Flask continues using the sync ``MCPHandler``.

- **Database Accessor Pattern**: New factory functions in ``actingweb.db`` (``get_property()``,
  ``get_actor()``, ``get_trust()``, etc.) create database instances with configuration
  automatically injected. New protocol definitions in ``actingweb.db.protocols`` provide full
  type safety and IDE support.

- **Attribute List Storage**: New ``ListAttribute`` and ``AttributeListStore`` classes for
  storing distributed lists in attribute buckets (not exposed via REST API). Same semantics as
  ``ListProperty``/``PropertyListStore`` but stored in attributes, bypassing the 400 KB
  property size limit.

- **List Metadata Access**: New ``get_metadata()`` method on both ``ListProperty`` and
  ``ListAttribute`` exposes internal metadata (``created_at``, ``updated_at``, ``version``,
  ``item_type``, ``chunk_size``, ``length``).

- **Property/List Name Collision Detection**: Creating a property when a list already exists
  with the same name (or vice versa) now raises ``ValueError``, preventing ambiguity and data
  loss.

- **Configurable AwProxy Timeout**: New ``timeout`` parameter on the ``AwProxy`` constructor.
  Accepts a single value or a ``(connect_timeout, read_timeout)`` tuple. Default changed to
  ``(5, 20)`` seconds.

- **Request Correlation in Logging**: Every log line now includes ``[request_id:actor_id:peer_id]``
  context for distributed tracing. New public API: ``enable_request_context_filter()``,
  ``set_request_context()``, ``get_request_id()``, ``get_actor_id()``, ``get_peer_id()``.
  Request IDs are extracted from the ``X-Request-ID`` header or auto-generated, and included in
  response headers.

- **Inter-Actor Request Correlation**: Correlation headers (``X-Request-ID``,
  ``X-Parent-Request-ID``) are automatically added to all peer-to-peer HTTP calls for complete
  request chain tracing.

- **Lambda Environment Detection**: Automatic detection of AWS Lambda deployments with a warning
  when async subscription callbacks are enabled, recommending ``with_sync_callbacks()`` to
  prevent callback loss on function freeze.

- **Configurable FastAPI Thread Pool**: New ``ActingWebApp.with_thread_pool_workers(workers)``
  method for tuning the thread pool size (1–100 workers, default 10).

- **Passphrase-to-SPA-Token Exchange**: ``POST /oauth/spa/token`` now accepts
  ``grant_type="passphrase"`` to exchange a valid creator passphrase for SPA tokens. Devtest
  mode only (returns 403 in production). Useful for Playwright and automated testing tools.

- **Revoked Trust Detection**: During subscription sync, if a peer has revoked a trust
  relationship (all subscriptions returning 404), the system automatically detects this and
  either cleans up dead subscriptions (if trust still exists) or removes the local trust
  entirely, triggering the ``trust_deleted`` lifecycle hook.

- **Baseline Sync on Subscription Creation**: ``subscribe_to_peer()`` now performs an immediate
  baseline data fetch after creating the subscription, ensuring consistent initial state
  regardless of whether the peer has existing data or pending diffs. New async variant:
  ``subscribe_to_peer_async()``.

- **Peer Metadata Refresh on Subscribe**: Subscription creation automatically refreshes cached
  peer profile, capabilities, and permissions metadata (when those features are configured),
  eliminating the need for a separate sync cycle.

- **RemotePeerStore Enumeration**: New ``list_all_scalars()`` and ``get_all_properties()``
  methods on ``RemotePeerStore`` for enumerating stored peer data. ``get_all_properties()``
  returns a combined view of all lists and scalars with type metadata (``type``, ``value``,
  ``item_count``).

- **List Property Format Parameter**: ``GET`` requests on list properties now accept
  ``?format=short`` to retrieve only metadata (count, description, explanation) without
  fetching all items.

- **Permission Callbacks**: Incoming permission change notifications from peers are handled
  automatically and stored in ``PeerPermissionStore``. Use
  ``@app.callback_hook("permissions")`` to receive them in application code. Callbacks are
  delivered to ``/callbacks/permissions/{granting_actor_id}``.

- **Permission Protocol Option Tags**: When ``with_peer_permissions(enable=True)`` is
  configured, ``/meta/actingweb/supported`` automatically advertises the
  ``permissioncallback`` and ``permissionquery`` capability tags per ActingWeb Protocol
  Specification v1.4.

CHANGED
~~~~~~~

- **Loosen dependency version constraints**: Runtime dependencies now use more permissive version
  ranges (e.g., ``boto3 >=1.26``, ``requests >=2.20``, ``cryptography >=43.0``) to reduce
  version conflicts for downstream consumers. Optional framework dependencies (Flask, FastAPI,
  uvicorn) also loosened.

- **OAuth provider token revoked on logout**: Logout now revokes the stored OAuth provider token
  from ``actor.store`` in addition to the ActingWeb session token. Providers without a
  revocation endpoint (e.g., GitHub) are silently skipped.

- **List properties in ``GET /properties``**: List properties are now included even without
  ``?metadata=true``, returned as ``{"_list": true, "count": N}``. The full format (with
  description and explanation) is returned with ``?metadata=true``.

- **``GET /subscriptions?peerid=X`` returns all subscriptions**: Now returns both inbound and
  outbound subscriptions for the given peer, rather than only outbound.

- **Email verification URL format**: Verification links now use ``/oauth/email?verify=<token>``
  as the preferred format instead of ``/{actor_id}/www/verify_email?token=<token>``. The legacy
  URL remains functional for backward compatibility, but new integrations should use the new
  actor-ID-free form.

- **``get_github_verified_emails()`` made public**: Renamed from ``_get_github_verified_emails()``
  on ``OAuth2Authenticator`` (private prefix removed), as it is called across class boundaries.

- **Permission format normalization**: Both shorthand list format (``["pattern1", "pattern2"]``)
  and spec-compliant dict format (``{"patterns": [...], "operations": [...]}``) are now accepted
  and normalized consistently across all permission APIs (``TrustPermissions`` storage,
  ``PeerPermissions`` callbacks, ``AccessControlConfig.add_trust_type()``). Shorthand format
  defaults to read-only operations.

SECURITY
~~~~~~~~

- **GitHub Email Verification**: ``_get_github_primary_email()`` now requires both ``primary``
  and ``verified`` flags when selecting the email for actor linking. Previously, an unverified
  primary email was accepted, which could allow account-linking attacks via the GitHub
  ``/user/emails`` API.

- **Logging Security Hardening**: Comprehensive audit of all log statements to prevent sensitive
  data leakage: OAuth tokens masked (first 8 characters only), OAuth request bodies and HTTP
  Authorization headers removed from logs, property values and HTTP response bodies no longer
  logged.

- **Remote Peer Data Sanitization**: All data received from remote peers is sanitized to prevent
  JSON encoding failures from malformed Unicode (invalid UTF-16 surrogate pairs, invalid UTF-8
  sequences).

FIXED
~~~~~

- **PostgreSQL Properties Value Index**: Dropped the ``idx_properties_value`` B-tree index on
  the ``properties.value`` column, which blocked storage of values larger than ~2700 bytes
  (e.g., embeddings, JSON blobs). The ``property_lookup`` table handles reverse-index lookups
  for properties that require value-based search. Includes Alembic migration ``c3d4e5f6a7b8``
  to drop the index on existing databases.

- **MCP OAuth Flow Verified Email Requirement**: The MCP OAuth flow now returns a clear
  ``invalid_grant`` error when no verified email is available from the provider.

- **List property subscription diff callbacks**: Fixed internal ``list:`` prefix leakage in
  subscription diff callbacks. Subscribers now receive ``subtarget="myList"`` instead of
  ``subtarget="list:myList"``; applications that were stripping this prefix can remove that
  workaround.

- **Fix FastAPI double logout invocation**: The FastAPI ``/oauth/logout`` handler was calling
  the underlying logout handler twice when a Bearer token was present alongside an
  ``oauth_token`` cookie, causing redundant token revocation attempts against the OAuth
  provider.

IMPROVED
~~~~~~~~

- **Parallel Test Isolation**: Significantly improved pytest-xdist parallel test execution
  reliability (flakiness reduced from ~5% to <1%) via worker-namespaced OAuth2 registration and
  improved database state cleanup. All 42 xdist groups are now documented in
  ``tests/integration/XDIST_GROUPS.md``.

- **Structured Proxy Error Responses**: All ``AwProxy`` resource methods (``get_resource()``,
  ``create_resource()``, ``change_resource()``, ``delete_resource()``, and async variants) now
  return structured error dicts with ``code`` and ``message`` keys for all error conditions,
  including when the peer returns a string-typed ``error`` field. Previously, the HTTP status
  code was lost and replaced with a hardcoded 500.

v3.9.2: Jan 16, 2026
--------------------

ADDED
~~~~~

- **Synchronous Subscription Callbacks**: Added ``with_sync_callbacks()`` builder method and ``sync_subscription_callbacks`` config option for Lambda/serverless environments. When enabled, subscription callbacks use blocking HTTP requests instead of async fire-and-forget, ensuring callbacks complete before the request handler returns. This prevents callbacks from being lost when Lambda functions freeze after returning a response.

  - New builder method: ``ActingWebApp.with_sync_callbacks(enable=True)``
  - New config attribute: ``Config.sync_subscription_callbacks`` (default: ``False``)
  - Refactored ``Actor.callback_subscription()`` to use shared sync helper function
  - Improved logging with sequence numbers and peer IDs for callback debugging

- **Subscription Sequence in GET Response**: Added ``sequence`` field to GET subscription response (``/subscriptions/<peerid>/<subid>``). The subscription's current sequence number is now included at the top level of the response, allowing peers to detect gaps in received diffs without examining individual diff sequence numbers. Updated ActingWeb Specification to version 1.4.

FIXED
~~~~~

- **Network Exception Handling in Trust Creation**: Fixed ``get_peer_info()`` to catch network-related exceptions (``ConnectionError``, ``Timeout``, etc.) that were previously uncaught. This prevents HTTP 500 errors during trust relationship creation when the peer is temporarily unavailable or slow to respond. The function now returns a proper 500 status code instead of crashing.

IMPROVED
~~~~~~~~

- **Retry Logic for Peer Communication**: Added automatic retry with exponential backoff to ``get_peer_info()``. Network requests now retry up to 3 times with delays of 0.5s, 1s, and 2s on transient network failures. This significantly improves reliability when peers are briefly unavailable or slow to respond.

- **Test Fixture Reliability**: Improved test server startup detection with faster polling (0.5s vs 1s) and added warmup requests after servers are detected as ready. This helps prevent race conditions in parallel test execution where the first real request might hit before internal initialization is complete.

v3.9.1: Jan 15, 2026
--------------------

FIXED
~~~~~

- **Async Hooks in Sync Execution Methods**: Fixed ``execute_lifecycle_hooks()``, ``execute_callback_hooks()``, ``execute_property_hooks()``, ``execute_subscription_hooks()``, and ``execute_app_callback_hooks()`` to properly execute async hooks when called from synchronous contexts. Previously, async hooks registered for these hook types would return unawaited coroutines instead of executing. Now all sync execution methods use ``_execute_hook_in_sync_context()`` to correctly handle both sync and async hooks via ``asyncio.run()`` fallback.

v3.9.0: Jan 15, 2026
--------------------

ADDED
~~~~~

- **Property Lookup Tables**: Added dedicated lookup tables for property reverse lookups (``get_actor_id_from_property()``), removing DynamoDB GSI 2048-byte size limit. Supports unlimited property value sizes for indexed properties in both DynamoDB and PostgreSQL backends.

  - Configurable indexed properties via ``with_indexed_properties()`` (default: ``oauthId``, ``email``, ``externalUserId``)
  - Dual-mode operation: new lookup table or legacy GSI/index
  - Backward compatible: defaults to legacy mode (``use_lookup_table=false``)
  - Environment variables: ``USE_PROPERTY_LOOKUP_TABLE``, ``INDEXED_PROPERTIES``
  - Automatic cleanup: lookup entries deleted with properties/actors
  - PostgreSQL foreign key CASCADE for automatic orphan cleanup

- ``actingweb.db.dynamodb.property_lookup`` module with ``PropertyLookup`` model and ``DbPropertyLookup`` class
- ``actingweb.db.postgresql.property_lookup`` module with ``DbPropertyLookup`` class
- ``actingweb.interface.ActingWebApp.with_indexed_properties()`` builder method for configuration
- ``actingweb.interface.ActingWebApp.with_legacy_property_index()`` builder method to control mode
- PostgreSQL migration ``70d60420526_add_property_lookup_table.py`` for lookup table schema
- Comprehensive test suite (``tests/test_property_lookup.py``) with 26 tests for both backends
- Documentation in ``docs/quickstart/configuration.rst`` with migration guide and best practices

- **Native Async/Await Hook Support**: ActingWeb hooks now support both synchronous and asynchronous (async/await) function definitions with automatic detection

  - New async execution methods: ``execute_method_hooks_async()``, ``execute_action_hooks_async()``, ``execute_property_hooks_async()``, ``execute_callback_hooks_async()``, ``execute_app_callback_hooks_async()``, ``execute_subscription_hooks_async()``, and ``execute_lifecycle_hooks_async()``
  - Async handler variants: ``AsyncMethodsHandler`` and ``AsyncActionsHandler`` with ``*_async()`` method variants (``get_async()``, ``post_async()``, ``put_async()``, ``delete_async()``)
  - FastAPI integration automatically detects and uses async handlers for optimal performance without thread pool overhead
  - Backward compatible: Existing synchronous hooks continue to work without changes
  - Mixed support: Applications can use both sync and async hooks in the same application
  - Sync context support: Async hooks are executed via ``asyncio.run()`` when called from synchronous contexts (Flask)
  - Use ``async def`` for hooks that need to call async services (AWS Bedrock, async HTTP clients, async database operations, AwProxy async methods)

CHANGED
~~~~~~~

- ``DbProperty.get_actor_id_from_property()`` now uses lookup table when configured, falling back to legacy GSI/index
- ``DbProperty.set()`` now syncs lookup entries for indexed properties
- ``DbProperty.delete()`` now removes lookup entries for indexed properties
- ``DbPropertyList.delete()`` now cleans up all lookup entries when deleting actor properties
- FastAPI integration now preferentially uses async handler variants (``AsyncMethodsHandler``, ``AsyncActionsHandler``) for methods and actions endpoints
- Synchronous hook execution methods (``execute_*_hooks()``) now support async hooks via ``asyncio.run()`` fallback
- Handler factory (``get_handler_class()``) now supports creating async handler variants based on framework preference

v3.8.3: Jan 12, 2026
--------------------

FIXED
~~~~~

- Fixed Flask integration ``TypeError`` in cookie handling by extracting cookie name as positional argument instead of kwarg
- Fixed missing subscription callbacks when deleting properties via WWW handler with ``?_method=DELETE``
- Fixed trust relationship timestamps to always include timezone info in ISO format strings (both DynamoDB and PostgreSQL)
- Fixed property list metadata to avoid auto-saving default metadata on first access

ADDED
~~~~~

- **Rich Metadata for Methods/Actions**: ``GET /<actor_id>/methods`` and ``GET /<actor_id>/actions`` now return metadata (description, input/output schemas, annotations) with auto-generation from TypedDict type hints

CHANGED
~~~~~~~

- Enhanced OAuth2 refresh token reuse handling with three-tier grace period (0-10s: full rotation, 10-60s: access token only, >60s: revoke all)

v3.8.2: Jan 3, 2026
--------------------

FIXED
~~~~~

- **Trust Deletion Error Handling**: Enhanced DELETE handler to return 404 when the remote actor doesn't exist (not just when relationship doesn't exist), enabling complete cleanup of orphaned trust relationships during ``delete_reciprocal_trust()`` flow when the remote actor has been deleted
- **OAuth Refresh Token Race Condition**: Fixed race condition in refresh token rotation that could cause false token theft detection and forced re-login when concurrent requests use the same refresh token. The check-and-mark-as-used operation is now atomic using database-level compare-and-swap, preventing multiple requests from successfully using the same token

ADDED
~~~~~

- **Atomic Attribute Updates**: Added ``conditional_update_attr()`` method to both DynamoDB and PostgreSQL backends for atomic compare-and-swap operations, enabling race-free token rotation and other concurrent update scenarios
- **Atomic Token Marking**: Added ``try_mark_refresh_token_used()`` method in ``OAuth2SessionManager`` that atomically checks and marks refresh tokens as used in a single database operation

v3.8.1: Jan 2, 2026
--------------------

FIXED
~~~~~

- **Subscription Cache Invalidation**: Fixed subscription handler to invalidate ``subs_list`` cache after creating new subscription, ensuring ``register_diffs()`` immediately sees newly created subscriptions for callback delivery
- **Trust Deletion Error Handling**: Fixed DELETE handler for trust relationships to return 404 (instead of 403) when relationship doesn't exist, enabling proper cleanup of orphaned trust relationships during ``delete_reciprocal_trust()`` flow
- **PostgreSQL Backend**: Fixed SQL queries to quote ``desc`` column as reserved keyword (PostgreSQL compatibility)
- **PostgreSQL Backend**: Fixed ``Attributes`` class to handle None values from PostgreSQL for non-existent attribute buckets
- **Database Backend Abstraction**: Removed hardcoded DynamoDB imports in ``TrustManager`` and ``PermissionEvaluator`` to use configured database backend dynamically
- **Test Fixtures**: Fixed ``test_trust_manager_oauth`` mock to properly structure ``DbTrust`` module for compatibility with backend abstraction

ADDED
~~~~~

- **Migration Helper**: Added ``scripts/migrate_db.py`` helper script for simplified PostgreSQL migrations with automatic .env loading and environment validation

CHANGED
~~~~~~~

- **Documentation**: Enhanced PostgreSQL setup documentation in quickstart guides with migration helper script usage, troubleshooting guide, and step-by-step setup instructions
- **TODO**: Added task for implementing ``TrustManager.create_relationship_async()`` method to avoid blocking event loop in async contexts


v3.8.0: Dec 31, 2025
--------------------

CHANGED
~~~~~~~

- **Database Package Structure**: Refactored ``actingweb.db_dynamodb`` to hierarchical package structure ``actingweb.db.dynamodb`` for better organization
- **Installation Extras**: Added optional dependency groups - ``pip install 'actingweb[postgresql]'`` or ``'actingweb[dynamodb]'`` for backend-specific installations
- **Database Backend Selection**: Environment variable ``DATABASE_BACKEND`` (or ``database`` parameter in ``ActingWebApp()``) now supports ``"dynamodb"`` (default) or ``"postgresql"``
- **Documentation Overhaul**: Comprehensive updates across all user-facing documentation:
  - Updated quickstart guides to include PostgreSQL setup instructions
  - Enhanced configuration reference with backend comparison tables
  - Expanded database maintenance guide to cover both DynamoDB TTL and PostgreSQL pg_cron cleanup
  - Added backend selection guidance throughout documentation
- **Logging Architecture**: Implemented hierarchical logging with named loggers throughout codebase using ``__name__`` pattern
- **Logging Configuration**: Added centralized logging configuration with ``configure_actingweb_logging()`` helper functions
- **Log Levels**: Rebalanced log levels - significant operations (actor creation, trust deletion, etc.) now use INFO instead of DEBUG

ADDED
~~~~~

- **PostgreSQL Database Backend**: Full PostgreSQL support as an alternative to DynamoDB
- ``actingweb.db.postgresql`` package with all 7 database tables (Actor, Property, Trust, PeerTrustee, Subscription, SubscriptionDiff, Attribute)
- PostgreSQL connection pooling via psycopg3 with configurable pool sizes
- Alembic migrations for PostgreSQL schema management (``actingweb/db/postgresql/migrations/``)
- Database backend protocols (``actingweb.db.protocols``) for interface consistency across backends
- Protocol compliance tests to ensure both backends implement the same interface
- ``scripts/migrate_dynamodb_to_postgresql.py`` - Data migration tool with export, import, and validate operations
- Performance benchmarks (``tests/performance/``) for comparing backend performance
- Comprehensive PostgreSQL documentation:
  - ``docs/guides/postgresql-migration.md`` - Complete migration guide from DynamoDB to PostgreSQL
  - ``docs/reference/database-backends.rst`` - Detailed backend comparison, cost analysis, and recommendations
- GitHub Actions matrix testing for both DynamoDB and PostgreSQL backends
- Backend-specific pytest markers (``@pytest.mark.dynamodb``, ``@pytest.mark.postgresql``)
- ``actingweb.logging_config`` module with production/development/testing configuration helpers
- Performance-critical logger identification for production optimization
- Lazy log evaluation in hot paths for improved performance
- **ActorInterface.config property**: Direct access to ActingWeb configuration object from ``ActorInterface`` instances
- **Trust Lifecycle Hooks**: Added ``trust_initiated`` hook - fires when actor initiates trust request to peer (outgoing)
- **Trust Lifecycle Hooks**: Added ``trust_request_received`` hook - fires when actor receives trust request from peer (incoming)
- **Trust Lifecycle Hooks**: Added ``trust_fully_approved_local`` hook - fires when THIS actor approves, completing mutual trust
- **Trust Lifecycle Hooks**: Added ``trust_fully_approved_remote`` hook - fires when PEER actor approves, completing mutual trust

FIXED
~~~~~

- Database module import paths corrected from relative to absolute imports

v3.7.6: Dec 30, 2025
--------------------

FIXED
~~~~~

- **Subscription Filtering**: Fixed ``get_subscriptions()`` callback parameter to properly filter by callback flag - ``callback=None`` now returns all subscriptions, ``callback=False`` returns inbound subscriptions, ``callback=True`` returns outbound subscriptions
- **Trust Deletion Hook**: Enhanced ``trust_deleted`` lifecycle hook to include ``relationship`` and ``trust_data`` parameters for consistency with ``trust_approved`` hook

CHANGED
~~~~~~~

- Added documentation to ``get_subscriptions()`` method explaining parameter filtering behavior

v3.7.5: Dec 27, 2025
--------------------

ADDED
~~~~~

- **Actor Root Content Negotiation**: ``GET /<actor_id>`` now supports content negotiation - API clients receive JSON, browsers are redirected based on authentication status and ``with_web_ui()`` configuration.
- **Browser Redirect to /login**: Unauthenticated browser requests to ``/<actor_id>`` now redirect to ``/login`` for a consistent login experience instead of triggering OAuth directly.
- **SPA Redirect Support**: When ``with_web_ui(False)``, authenticated browsers and OAuth callbacks redirect to ``/<actor_id>/app`` instead of ``/<actor_id>/www``.
- Integration tests for actor root endpoint content negotiation and redirect behavior.

CHANGED
~~~~~~~

- OAuth2 callback handler now respects ``config.ui`` setting - redirects to ``/<actor_id>/app`` when web UI is disabled (SPA mode).
- FastAPI and Flask integrations updated to redirect unauthenticated browser requests to ``/login``.
- Documentation extensively updated: routing-overview, web-ui guide, spa-authentication guide, and configuration reference now document browser redirect behavior.

v3.7.4: Dec 26, 2025
--------------------

ADDED
~~~~~

- DynamoDB TTL support for automatic cleanup of expired tokens, sessions, and auth codes.

v3.7.3: Dec 19, 2025
--------------------

FIXED
~~~~~

- **WWW Callback Hook Template Rendering**: The ``www`` callback hook can now render custom templates by returning ``{"template": "template-name.html", "data": {...}}``. This allows applications to add custom web UI pages without modifying the core library.
- **Callbacks Handler Response Data**: GET, POST, and DELETE callback handlers now return the hook's response data as JSON (200 OK) instead of just boolean success/failure, enabling richer callback interactions.
- **Methods/Actions ACL Rules**: Added default ACL rules for ``/methods`` and ``/actions`` endpoints for creator, friend, partner, and admin trust types.
- Added ``template_name`` attribute to ``AWResponse`` for custom template rendering support.
- Fixed methods and actions handlers to use dual-context authentication (``_authenticate_dual_context``) supporting both web UI (OAuth cookie) and API (basic auth) access.

ADDED
~~~~~

- Added integration tests for custom www template rendering via callback hooks.
- Added integration tests for OAuth2 logout SPA CORS behavior (origin echoing and credentials).

CHANGED
~~~~~~~

- **OAuth2 Logout Consolidation**: ``/oauth/spa/logout`` now delegates to the main ``/oauth/logout`` handler for consistent behavior. The logout endpoint uses SPA CORS (echoed origin + credentials) to ensure cross-origin SPAs can clear session cookies. Both Flask and FastAPI integrations now properly propagate cookies from handler responses.
- Callbacks handler now returns actual hook results as JSON response body instead of just HTTP status codes.
- Documentation updated with template rendering examples for www callback hooks.

v3.7.2: Dec 19, 2025
--------------------

FIXED
~~~~~

- Fixed Flask integration cookie handling: added ``path`` and ``samesite`` parameters for proper session cookie behavior across browser security policies
- Simplified Flask OAuth session validation to use session manager directly instead of OAuth2 authenticator, fixing token validation issues
- Improved Flask template rendering error logging for easier debugging

CHANGED
~~~~~~~

- Added thoughts/shared/plans/2025-12-18-passphrase-login-feature.md as a way to support www login without a 3rd party auth provider

v3.7.1: Dec 18, 2025
--------------------

FIXED
~~~~~

- **SECURITY**: Permission override merging now uses union semantics for both ``patterns`` AND ``excluded_patterns`` arrays by default - base security exclusions (private/*, security/*, oauth_*) can no longer be accidentally cleared by individual trust relationship overrides
- Cleaned up integration/unit tests to have all dynamodb-dependent tests in integration dir

v3.7.0: Dec 16, 2025
--------------------

BREAKING CHANGES
~~~~~~~~~~~~~~~~

- **Developer API Extended**: SubscriptionManager and TrustManager have new methods with cleaner APIs and automatic lifecycle hooks
- See ``docs/migration/v3.7.rst`` for comprehensive migration guide
- **HTTP API remains 100% backward compatible** - no changes required for applications using REST endpoints only

FIXED
~~~~~

- **SECURITY**: Permission evaluator now returns DENIED (not NOT_FOUND) when explicit patterns are defined but target doesn't match - fixes permission bypass via legacy ACL fallback
- **SECURITY**: Properties ``listall`` endpoint now filters properties and list properties based on peer permissions - prevents unauthorized data exposure
- Properties ``listall`` now includes list properties even when all regular properties are filtered by permissions
- Subscription callbacks now fire asynchronously in async contexts to avoid blocking the caller
- Fixed permission filtering for property lists to strip 'list:' prefix before permission checks
- Property list diff notifications now include item data (item, index, items) for subscribers
- Add trigger of oauth_success hook in SPA oauth2 login
- Fixed unused variable and import warnings identified by ruff linting
- Fixed ``hasattr(x, '__call__')`` pattern replaced with ``callable(x)`` for better type safety

ADDED
~~~~~

- **Permission Merge Control**: Added ``merge_base`` parameter to ``merge_permissions()`` function - defaults to ``True`` for fail-safe union merging of patterns/excluded_patterns; set to ``False`` for explicit full override capability
- **Developer API Extensions**: Added methods to SubscriptionManager: ``create_local_subscription()``, ``get_subscription_with_diffs()``, ``get_callback_subscription()``, ``delete_callback_subscription()``
- **Developer API Extensions**: Added methods to TrustManager: ``create_verified_trust()``, ``modify_and_notify()``, ``delete_peer_trust()``, ``trustee_root`` property
- **Wrapper Classes**: Added ``SubscriptionWithDiffs`` wrapper providing clean access to subscription data and diffs
- **Async Authentication**: Added async versions of authentication methods (``check_token_auth_async()``, ``check_and_verify_auth_async()``) to avoid blocking event loop during OAuth2 validation
- **OAuth2 Token Heuristic**: Added ``Auth._looks_like_oauth2_token()`` method to avoid unnecessary network calls for non-OAuth tokens
- **List Property Subscriptions**: List property operations now trigger subscription notifications with structured diff payloads
- **Parallel Test Execution**: Added pytest-xdist support with worker isolation (unique DB prefixes, ports, emails) for 3-4x faster test runs
- Added Makefile targets: ``make test-parallel``, ``make test-parallel-fast``, ``make test-all-parallel``
- Added ``pytest-xdist`` dependency for parallel test execution
- GitHub Actions CI now runs tests in parallel with 4 workers
- oauth_success hook now receives full OAuth user info

CHANGED
~~~~~~~

- **Permission Merge Documentation**: Added "Permission Override Merging" section to ``docs/guides/access-control.rst`` and updated ``docs/reference/security.rst`` cheatsheet
- **Architecture**: Handlers refactored to four-tier architecture (Handler → Developer API → Core Actor → Database) for clean separation of concerns
- **Handler Simplification**: Handlers are now thin HTTP adapters delegating business logic to developer API
- OAuth2 token validation now includes quick heuristic check before network requests for better performance
- Integration tests now support parallel execution with automatic worker isolation
- GitHub Actions workflow uses parallel testing (4 workers for public repos, 2 for private)
- Added timeout-minutes to GitHub Actions jobs (20 min tests, 10 min type-check)
- Documentation consolidated into CONTRIBUTING.rst and CLAUDE.md

v3.6.0: Dec 11, 2025
--------------------

FIXED
~~~~~~~

- Trust ``trust_approved`` lifecycle hook now triggers when receiving POST approval notification from peer (moved from PUT handler to POST handler)
- Fixed race condition in trust approval flow where trust relationship must be saved to database before notifying the peer.
- Fixed missing deletion of permissions for trust relationship when deleting it.
- Fixed missing ``trust_deleted`` lifecycle hook trigger in trust DELETE handler.

ADDED
~~~~~

- **ACL Rules for Custom Trust Types**: ``add_trust_type()`` now accepts an ``acl_rules`` parameter to specify HTTP endpoint access permissions. This enables custom trust types (like ``subscriber``) to access ActingWeb REST endpoints like ``/subscriptions/<id>`` for creating subscriptions. Each rule is a tuple of ``(path, methods, access)``.
- **SECURITY**: Subscription callbacks now respect property permissions - only properties the peer has ``read`` permission on are included in callbacks (fail-closed design)
- **NEW ENDPOINT**: Added ``/trust/{relationship}/{peerid}/shared_properties`` endpoint for discovering properties available for subscription
- **BREAKING**: Subscription permission filtering is fail-closed - if permission evaluation fails, no data is sent to subscribers

**Note on Subscription Access Control**: Subscription creation is controlled by ACL rules (e.g., ``("subscriptions/<id>", "POST", "a")``), NOT by property permission patterns. Any peer with the subscription ACL can create subscriptions to any target. Property permissions only affect what data is included in subscription callbacks.
- **Async HTTP Methods**: Added async versions of ``AwProxy`` methods using ``httpx`` for non-blocking operations in async frameworks like FastAPI:

  - ``AwProxy.get_resource_async()`` - Async peer resource retrieval
  - ``AwProxy.create_resource_async()`` - Async peer resource creation
  - ``AwProxy.change_resource_async()`` - Async peer resource update
  - ``AwProxy.delete_resource_async()`` - Async peer resource deletion

- **Dependencies**: Added ``httpx`` as a new dependency for async HTTP client operations

CHANGED
~~~~~~~

- Subscription handlers now use unified permission evaluator (``evaluate_property_access``) instead of legacy ``check_authorisation``
- Permission changes made after subscription creation now affect subsequent callbacks (dynamic permission enforcement)
- Actor ``callback_subscription`` method now filters property subscription data based on peer permissions before sending

v3.5.6: Dec 4, 2025
-------------------

FIXED
~~~~~

- **SECURITY**: Fixed token revocation searching wrong actor bucket during trust deletion - tokens were stored in user's actor but revocation looked in system actor (``_actingweb_oauth2``), leaving tokens valid after trust deletion

v3.5.5: Dec 3, 2025
-------------------

FIXED
~~~~~

- Fixed Flask and FastAPI integrations not propagating handler headers (e.g., WWW-Authenticate) to OAuth2 endpoint responses

v3.5.4: Dec 3, 2025
-------------------

FIXED
~~~~~

- **SECURITY**: Trust relationship deletion now properly deletes the associated OAuth2 client and revokes all tokens - prevents deleted MCP clients from being reused after trust relationship is removed

v3.5.3: Dec 3, 2025
-------------------

FIXED
~~~~~

- **SECURITY**: MCP client deletion now immediately revokes all access and refresh tokens - prevents deleted clients from continuing to access resources using cached tokens

v3.5.2: Dec 3, 2025
-------------------

FIXED
~~~~~

- **SECURITY**: Fixed missing WWW-Authenticate header for 401 responses in OAuth2 token endpoint - RFC 6749 Section 5.2 requires WWW-Authenticate header for invalid_client errors

v3.5.1: Dec 1, 2025
-------------------

FIXED
~~~~~

- **CRITICAL**: Fixed OAuth2 actor creation not triggering lifecycle hooks - ``config._hooks`` was never set, causing ``actor_created`` and other lifecycle hooks to be silently ignored during OAuth-based actor creation
- Added comprehensive regression tests for OAuth2 lifecycle hook integration

CHANGED
~~~~~~~

- ActingWebApp now automatically attaches HookRegistry to Config object's ``_hooks`` attribute in ``get_config()``

v3.5: Nov 30, 2025
------------------

**ActingWeb Specification version 1.2**

This release implements ActingWeb Specification version 1.2 with SPA-friendly API behavior.

FIXED
~~~~~

- **SECURITY**: Fixed SPA PKCE code challenge not being sent to OAuth providers - PKCE parameters are now properly forwarded to authorization URLs
- **SECURITY**: Fixed trust-based permissions bypass - handlers were using ``getattr()`` on dict instead of ``.get()`` for peer ID lookup, causing permission evaluator to be bypassed
- Fixed FastAPI cookie setting using ``key`` parameter instead of ``name`` (FastAPI/Starlette API difference)
- Fixed SPA refresh token cookie not being stored by browser (changed ``path="/"`` and ``samesite="Lax"``)
- Fixed refresh token reuse false positives on rapid page refresh with 2-second grace period
- Fixed ``oauth_state.decode_state()`` to handle JSON null values for optional trust_type field
- Removed sensitive token values from debug log messages (security improvement)
- Fixed pytest marker registration for integration tests (added ``integration`` marker)

CHANGED
~~~~~~~

- SPA OAuth2 authorize endpoint only includes ``trust_type`` in state when provided (distinguishes user login from MCP client auth)

BREAKING CHANGES
~~~~~~~~~~~~~~~~

**Empty Collection Response Behavior (Spec v1.2)**

The following endpoints now return ``200 OK`` with empty arrays/objects instead of ``404 Not Found``
when collections are empty. This is a **breaking change** for clients that rely on ``404`` to detect
empty collections:

- ``GET /trust`` - Returns ``200 OK`` with ``[]`` when no trust relationships exist (was ``404``)
- ``GET /trust?relationship=<type>`` - Returns ``200 OK`` with ``[]`` when no matches (was ``404``)
- ``GET /properties`` - Returns ``200 OK`` with ``{}`` when no properties exist (was ``404``)
- ``GET /subscriptions`` - Returns ``200 OK`` with ``{"id": ..., "data": []}`` when no subscriptions (was ``404``)

**Migration Guide:**

Before (v1.1):

.. code-block:: python

    response = requests.get(f"{actor_url}/trust", auth=auth)
    if response.status_code == 404:
        trusts = []  # No trusts
    else:
        trusts = response.json()

After (v1.2):

.. code-block:: python

    response = requests.get(f"{actor_url}/trust", auth=auth)
    trusts = response.json()  # Always returns array (may be empty)

**Note:** Individual resource lookups still return ``404 Not Found`` when the specific resource
does not exist (e.g., ``GET /properties/nonexistent``, ``GET /trust/friend/nonexistent-peer``).

DOCS
~~~~

- **Spec v1.2**: Added "Response Conventions" section documenting SPA-friendly empty collection behavior
- **Spec v1.2**: Updated ``/properties``, ``/trust``, and list properties sections with new 200 OK behavior
- Added ``listproperties`` option tag to ActingWeb specification for list property support
- Added comprehensive List Properties section to ``docs/actingweb-spec.rst`` documenting ordered collections
- Documented list property CRUD operations (GET/POST/PUT/DELETE) for items and full lists
- Documented list property metadata endpoint (GET/PUT ``/properties/{name}/metadata``)
- Updated GET ``/properties?metadata=true`` documentation to reference listproperties option tag

ADDED
~~~~~

- SPA mode support in OAuth2 callback handler (``spa_mode=true`` in state parameter returns JSON instead of redirect)
- JSON API responses in email verification handler (based on ``Accept: application/json`` header)
- ``GET /{actor_id}/meta/trusttypes`` endpoint for trust type enumeration
- ``GET/PUT /{actor_id}/properties/{name}/metadata`` endpoint for list property metadata
- Factory JSON API: ``GET /?format=json`` or ``Accept: application/json`` returns OAuth configuration for SPAs
- New test suites for SPA API endpoints (``tests/test_spa_api_endpoints.py``, ``tests/integration/test_spa_api.py``)

CHANGED
~~~~~~~

**Trust Type Configuration Clarification**

Trust types are now correctly scoped to MCP client authorization flows only:

- Trust types are **no longer** exposed in user login endpoints (``GET /?format=json``, ``/oauth/spa/*``)
- Library no longer hardcodes default trust types (e.g., ``mcp_client``)
- Applications must configure trust types for MCP OAuth2 flows via ``AccessControlConfig.configure_oauth2_trust_types()``
- ``/oauth/authorize`` (MCP authorization) shows trust types from registry; ``/oauth/spa/authorize`` (user login) does not

This change clarifies the distinction between:

1. **User Login** (ActingWeb as OAuth client to Google/GitHub): No trust relationship created, no trust_type needed
2. **MCP Authorization** (ActingWeb as OAuth server for MCP clients): Trust relationship created with specified trust_type

**Security Enhancement**

- Added explicit validation in OAuth2 callback to prevent actor spoofing (validates OAuth email matches actor creator)
- MCP OAuth2 flows derive actor_id from authenticated email, not user input

FIXED
~~~~~

- Fixed unit test configuration to use correct DynamoDB port (8001) matching docker-compose.test.yml
- Fixed Trust class attribute initialization to prevent AttributeError on early returns

v3.4.3: Nov 23, 2025
--------------------

FIXED
~~~~~

- Fixed MCP authentication to include error="invalid_token" in WWW-Authenticate header per RFC 6750 to force OAuth2 clients to invalidate cached tokens
- Fixed Flask and FastAPI integrations to properly propagate HTTP 401 status codes and WWW-Authenticate headers from MCP handler
- Reduced excessive debug logging in MCP trust relationship lookup
- Added conditional update check to prevent unnecessary trust relationship updates when client info hasn't changed

v3.4.2: Nov 22, 2025
--------------------

ADDED
~~~~~

- Github action to push new package to pypi on merging PRs to master branch

FIXED
~~~~~

- Fixed wrong URL in OAUTH2 discovery URL that prevented detection of dynamic client registration

CHANGED
~~~~~~~

- Reduced unnecessary error logging for access and authentication
- Ruff linting and formatting and pyright type fixes

v3.4.1: Nov 8, 2025
-------------------

FIXED
~~~~~

**MCP Tool Annotations**

- Fixed tool annotations not being serialized in ``tools/list`` responses in MCP handler
- Tool annotations (``readOnlyHint``, ``destructiveHint``, ``idempotentHint``, ``openWorldHint``) are now properly included when decorators define them
- This fix enables ChatGPT and other MCP clients to properly evaluate tool safety before execution
- Aligns FastAPI/HTTP integration path with SDK server behavior

**OAuth2 Trust Type Selection**

- Fixed OAuth2 authorization form ignoring user-selected trust type during Google/GitHub authentication
- OAuth provider buttons now submit form to ``/oauth/authorize`` POST with selected trust_type before redirecting to provider
- Trust type is properly embedded in encrypted OAuth state and applied during callback
- Fixes regression introduced when OAuth provider integration was added (previously worked with email form submission)

v3.4: Oct 26, 2025
-------------------

ADDED
~~~~~

**OAuth2 Security Enhancements**

- Added email verification system for OAuth2 actors when provider cannot verify email ownership
- Added cross-actor authorization prevention in MCP OAuth2 flows (blocks attackers from authorizing access to other users' actors)
- Added session fixation prevention in web OAuth2 login flows
- Added comprehensive security documentation in ``docs/authentication-system.rst``
- Added security tests in ``tests/integration/test_oauth2_security.py``
- Added lifecycle hooks: ``email_verification_required`` and ``email_verified``
- Added email verification endpoint: ``/<actor_id>/www/verify_email``
- Added verified emails dropdown for GitHub OAuth2 (fetches verified emails via GitHub API)
- Added provider ID support (stable identifiers like ``google:sub`` or ``github:user_id``) as alternative to email addresses
- Added 32-byte cryptographic verification tokens with 24-hour expiry
- Added security logging for all authorization violations

**Trust Relationship Enhancements**

- Added ``last_accessed`` and ``last_connected_via`` fields to trust relationships for tracking connection activity
- Handler now updates trust relationship timestamps on each connection with client metadata refresh
- Trust relationship sorting by most recent connection in web UI (``/www/trust``)

FIXED
~~~~~

**Security Fixes**

- **CRITICAL**: Fixed OAuth2 callback to validate actor ownership before completing authorization (prevents cross-actor authorization attacks in MCP flows)
- Fixed potential account hijacking vulnerability when OAuth2 providers don't return verified email addresses
- Fixed session fixation vulnerability where attackers could trick users into logging into attacker's actor

**OAuth2 and Integration Fixes**

- Fixed OAuth2 CORS preflight (OPTIONS) requests not being routed correctly in FastAPI integration, causing 404 errors on ``/oauth/register`` and ``/oauth/token`` endpoints

CHANGED
~~~~~~~

**Code Quality & Type Safety**

- **Type Checking**: Achieved zero pyright errors and warnings across entire codebase (down from 430+ issues)
- **Linting**: Achieved zero ruff errors (fixed all 15 remaining linting issues)
- **Configuration**: Added pyright to dev dependencies and created ``pyrightconfig.json`` for consistent type checking
- **VSCode Integration**: Updated ``.vscode/settings.json`` for optimal pylance and ruff integration
- **Test Improvements**: Fixed pytest fixture names causing test failures, all 474 tests now passing
- **Type Annotations**: Added comprehensive type ignore comments for test files (228+ annotations)
- **Import Management**: Fixed unused imports, variables, and function warnings throughout codebase
- **Module Declarations**: Fixed lazy-loaded module ``__all__`` declarations with proper pyright ignores (34 modules)

- **Dependencies**: Updated Poetry to 2.2.1 and major package upgrades including ``cryptography`` 45.0.6 → 46.0.3, ``fastapi`` 0.116.1 → 0.120.0, ``mcp`` 1.12.4 → 1.19.0, ``pydantic`` 2.11.7 → 2.12.3, ``pytest-cov`` 6.2.1 → 7.0.0, ``ruff`` 0.12.8 → 0.14.2, and 30+ other dependency updates


v3.3: Oct 4, 2025
-----------------

BREAKING CHANGES
~~~~~~~~~~~~~~~~

**Legacy OAuth System Removed**

- Removed legacy ``OAuth`` class and related third-party service authentication
- Removed ``/<actor_id>/oauth`` endpoints that used legacy OAuth
- Removed legacy OAuth methods from ``Auth`` class (``oauth_get``, ``oauth_post``, etc.)
- Legacy OAuth auth type no longer supported in ``select_auth_type()``

**Migration Path**: Use the new unified third-party service integration system instead:

- Replace ``oauth.OAuth()`` with ``actor.services.get("service_name")``
- Replace manual OAuth configuration with ``app.add_dropbox()``, ``app.add_gmail()``, etc.
- Use clean service API: ``service.get()``, ``service.post()``, etc.

FIXED
~~~~~

- MCP tools/list response now applies client-specific formatting for better compatibility
- Trust relationship descriptions now show friendly client names instead of raw identifiers when available
- OAuth2 client trust relationships maintain proper client metadata across updates
- Trust manager now keeps peer identifier in sync for OAuth2/MCP clients
- Fixed FastAPI extra inadvertently importing Flask, forcing Flask as a dependency
- Fixed trust handler to return empty list instead of 404 for graceful handling
- Reduced logging noise by moving non-essential INFO logs to DEBUG
- Made ``actor.get_config()`` use the dynamic global ``actingweb.__version__``
- Fixed error in ``DbPropertyList`` when properties table was missing in DynamoDB
- Fixed ``trustee_root`` JSON to return stored value instead of input parameter
- Fixed missing ``trustee_root`` in actor creation via REST API
- Fixed handling of ``POST`` to ``/<actor_id>/www/properties`` (including ``_method=DELETE``)
- Fixed base path handling for ``/<actor_id>/www`` (supports non-root base paths consistently)
- Fixed ``www/`` hook not triggered
- Devtest proxy: added Basic-auth fallback (``trustee:<peer passphrase>``) when Bearer trust requests to peer ``/properties`` endpoints receive 302/401/403, avoiding OAuth2 redirects during testing
- Fixed MCP OAuth2 trust relationship creation where MCP clients completed authentication but no trust relationships were created
- Fixed hook permission operation mapping where "get" operations were incorrectly passed as "read"
- Fixed OAuth2 callback ``established_via`` to properly distinguish between MCP and regular OAuth2 flows
- Fixed singleton initialization dependency order causing Permission Evaluator to fail when Trust Permission Store was not yet initialized
- Fixed OAuth2 trust-type filtering logic that was incorrectly placed inside exception handlers, causing 0 available trust types during OAuth2 flows
- Fixed severe OAuth2 performance issue where lazy singleton loading during requests caused 4+ minute hangs during OAuth2 callbacks
- Fixed ``established_via`` field being lost between database save and retrieval in trust relationship management
- Added explicit singleton initialization at application startup to prevent performance degradation during OAuth2 flows
- Replaced all urlfetch HTTP calls with requests library for improved reliability, better timeout handling, and elimination of 30+ second timeout issues

CHANGED
~~~~~~~

- If ``unique_creator=False``, ensure deterministic retrieval of the first actor available when doing OAuth2 auth and log in from root
- Refactored OAuth2 server implementation to use Attributes system instead of underscore-prefixed properties for storing sensitive data (tokens, authorization codes, Google OAuth2 tokens)
- Removed unused default resources in the MCP server (now only existing resources and hooks are presented)
- Removed notes and usage as static resource in the library, leave this to the implementing application
- Cleaned up the actor creation interfaces, ActorInterface.create() is now the only factory to be used.
- Standardized global Attribute buckets for cross-actor data.
- Enhanced ``/trust/{relationship}/{peerid}`` API endpoints to support permission management alongside traditional trust relationship operations
- Modified ``/meta/actingweb/supported`` to dynamically include feature tags based on available system capabilities
- Properties, methods, and actions handlers now integrate with unified permission system while maintaining backward compatibility
- Hook execution system now includes transparent permission checking with authentication context passing
- **Dependencies**: Replaced ``urlfetch ^2.0.1`` with ``requests ^2.31.0`` for more reliable HTTP operations

ADDED
~~~~~

**Integration Test Suite**

- Added comprehensive REST API integration test suite with 117 tests covering all mandatory ActingWeb protocol endpoints
- Added ``tests/integration/`` directory with test harness, fixtures, and test files
- Added Docker Compose configuration for local DynamoDB testing (``docker-compose.test.yml``)
- Added GitHub Actions CI/CD workflow (``.github/workflows/integration-tests.yml``) for automated testing on PRs
- Added ``make test-integration`` target for running integration tests locally
- Added comprehensive testing documentation (``docs/TESTING.md``)
- Test coverage: actor lifecycle, properties (nested/complex), meta, trust relationships, subscriptions with diffs

**MCP Client Management Enhancements**

- Support for ``allowed_clients`` parameter in ``@mcp_tool`` decorator to restrict tool access by client type
- Support for ``client_descriptions`` parameter in ``@mcp_tool`` decorator for client-specific tool descriptions
- Client-specific tool filtering for MCP endpoints based on client type detection (ChatGPT, Claude, Cursor, etc.)
- Enhanced OAuth2 client trust relationship display with friendly client names in web UI
- Automatic enrichment of OAuth2 trust relationships with missing client metadata

**Unified Third-Party Service Integration**

- Added modern service integration system replacing legacy OAuth class
- Added fluent API methods: ``app.add_dropbox()``, ``app.add_gmail()``, ``app.add_github()``, ``app.add_box()``
- Added ``ServiceConfig``, ``ServiceClient``, and ``ServiceRegistry`` classes
- Added automatic token management and refresh for third-party services
- Added ``actor.services.get()`` interface for accessing authenticated service clients
- Added service OAuth2 callback endpoints: ``/{actor_id}/services/{service_name}/callback``
- Added service revocation endpoints: ``DELETE /{actor_id}/services/{service_name}``
- Added comprehensive documentation in ``docs/service-integration.rst``
- Integrated service system with both Flask and FastAPI frameworks

**Bot Handler Improvements**

- Fixed broken bot handler that tried to use removed legacy OAuth system
- Simplified bot authentication to use direct bot token validation from config
- Removed dependency on Auth class for bot endpoints - bots now use simpler token-based validation
- Bot token now passed to hooks for service calls if needed

**Simplified Authentication Interface**

- Added ``require_authenticated_actor()`` method to BaseHandler for one-line auth + authorization
- Added ``authenticate_actor()`` method returning ``AuthResult`` for more granular control
- New interface reduces boilerplate from 6-8 lines to 2-3 lines per handler method
- Maintains full compatibility with existing ``init_actingweb()`` usage
- Automatic HTTP response handling for common authentication and authorization failures

**Unified Access Control System**

- Complete unified access control system with trust types, permissions, and pattern matching
- Trust Type Registry with 6 built-in trust types (associate, viewer, friend, partner, admin, mcp_client) and support for custom types
- Permission Evaluator with glob pattern matching, precedence rules, and fallback to legacy authorization
- Per-relationship permission storage system allowing individual trust relationships to override trust type defaults
- Permission Integration module providing transparent permission checking for all ActingWeb operations
- Enhanced Trust API with permission management endpoints:

  - ``GET /trust/{relationship}/{peerid}?permissions=true`` - Include permission overrides in trust response
  - ``PUT /trust/{relationship}/{peerid}`` - Update permissions alongside trust relationship properties
  - ``GET /trust/{relationship}/{peerid}/permissions`` - Dedicated permission management endpoint
  - ``PUT /trust/{relationship}/{peerid}/permissions`` - Create/update permission overrides
  - ``DELETE /trust/{relationship}/{peerid}/permissions`` - Remove permission overrides

- ``trustpermissions`` feature tag automatically included in ``/meta/actingweb/supported`` when permission system is available
- Transparent hook permission checking - existing hooks automatically get permission filtering without code changes
- Enhanced MCP OAuth2 trust relationship creation with automatic trust type detection
- Zero-migration design - existing applications work immediately while gaining new capabilities
- Comprehensive permission structure supporting properties, methods, actions, tools, resources, and prompts
- Pattern-based permissions with support for glob wildcards (``*``, ``?``) and URI schemes
- Backward compatibility with legacy authorization system as fallback

**Other Additions**

- Added execution of property_hooks in the handler of www/*
- Added support for list of hidden properties as variable to www/properties* templates
- Added support for dynamic generation of resources in MCP based on hooks
- Support for CORS in oauth2 flows
- PKCE support in oauth2 flows
- Support for OPTIONS method on OAUTH2 discovery endpoints
- New explicit interface for managing list properties with `actor.property_lists.listname` syntax
- Distributed list storage bypassing DynamoDB 400KB item limits by storing individual list items as separate properties
- Added `property_lists` attribute to Actor class for list-specific operations
- Lazy-loading iterator for efficient list traversal without loading entire lists into memory
- Added singleton warmup module (``actingweb.singleton_warmup``) for explicit initialization of performance-critical singletons at application startup
- Comprehensive documentation for singleton initialization requirements in both CLAUDE.md and unified-access-control.rst
- Intelligent caching system for MCP endpoint authentication providing 50x performance improvement (50ms → 1ms) for repeated requests with 90%+ cache hit rates
- MCP authentication caching includes token validation, actor loading, and trust relationship lookup with automatic TTL-based cleanup and performance monitoring

**OAuth2 Client Management**

- High-level ``OAuth2ClientManager`` interface for creating, listing, validating, deleting clients, and regenerating client secrets
- Client secret regeneration with verification, audit timestamp (``secret_regenerated_at``), and formatted display values
- Generate access tokens via client-credentials flow directly from ``OAuth2ClientManager.generate_access_token()``

**OAuth2 Authorization Server**

- Added support for ``client_credentials`` grant type with token issuance and discovery updated (``grant_types_supported``)
- Added ``trust_type`` and ``actor_id`` to client registration/discovery responses; improved secret validation diagnostics
- Added client deletion capability to MCP client registry

**MCP Integration**

- Captures and caches MCP ``clientInfo`` during initialize; persists to trust relationship after OAuth2 callback
- Populates trust context on authenticated MCP sessions for permission evaluation
- Added Google OAuth2 token validation via Google TokenInfo API
- Enhanced MCP client information capture and persistent storage across session establishment
- Improved MCP authentication with proper HTTP 401 handling and WWW-Authenticate headers for FastAPI integration
- Added global client info caching during session establishment with automatic cleanup
- Each MCP client now gets unique trust relationship per user email, preventing clients from overwriting each other's identities
- OAuth2 client registration now automatically creates trust relationships, ensuring proper permission evaluation
- All OAuth2 clients must pass permission evaluation before accessing MCP endpoints

**Runtime Context System**

- New ``actingweb.runtime_context`` module providing structured request context for hook functions
- ``RuntimeContext`` class with type-safe context classes: ``MCPContext``, ``OAuth2Context``, ``WebContext``
- ``get_client_info_from_context()`` helper function for unified client detection across all context types
- Support for custom context types via ``set_custom_context()`` and ``get_custom_context()`` methods
- Request-scoped context lifecycle with automatic cleanup support
- Comprehensive documentation and examples for using runtime context in hook functions

**Web UI Enhancements**

- Consistent template URL variables across pages: ``actor_root``, ``actor_www``, and ``url``
- Trust page displays registered OAuth2 clients (name, trust type, created time, status)
- Trust creation form supports selecting trust type; consistent ``form_action`` and redirects
- Property pages: create/delete list properties, edit list metadata (description/explanation), and improved redirects after operations

**Auth Utilities**

- Added ``check_and_verify_auth()`` helper to verify authentication for custom (non-ActingWeb) routes with redirect-aware responses

v3.2.1: Aug 9, 2025
-------------------

**OAuth2 Authentication System and Enhanced Integrations**

ADDED
~~~~~

- **OAuth2 Implementation**:
  - New oauth2.py module with comprehensive OAuth2 authentication using oauthlib WebApplicationClient
  - Support for Google and GitHub OAuth2 providers with automatic provider detection
  - OAuth2CallbackHandler for secure callback processing with state parameter validation
  - Email validation system to prevent identity confusion attacks
  - Login hint parameter support for Google OAuth2 to improve user experience
  - State parameter encryption with CSRF protection and email validation

- **MCP OAuth2 Authorization Server**:
  - Complete RFC 7591/RFC 8414 compliant OAuth2 authorization server for MCP (Model Context Protocol) clients
  - Dynamic Client Registration (DCR) endpoint for MCP client registration
  - OAuth2 authorization and token endpoints with proper scope handling
  - Separate token management system for ActingWeb tokens vs Google tokens
  - Per-actor MCP client credential storage using ActingWeb attribute bucket pattern
  - State parameter encryption with MCP context preservation for OAuth2 flows
  - Global index buckets for efficient MCP client lookup across actors
  - Integration with existing Google OAuth2 for user authentication proxying

- **Enhanced Authentication Flow**:
  - Modified factory endpoint behavior: GET shows email form, POST triggers OAuth2 with email hint
  - Email validation step to ensure authenticated email matches form input
  - User-friendly error templates for authentication failures
  - Security enhancement preventing form email != OAuth2 email mismatch attacks
  - Dual OAuth2 callback handling supporting both ActingWeb and MCP flows

- **FastAPI Integration Enhancements**:
  - Improved FastAPI integration with better async/await handling
  - Enhanced template and static file support for FastAPI applications
  - Better separation of GET/POST handling in factory routes
  - Improved error handling and response formatting for FastAPI

- **Integration Improvements**:
  - Enhanced both Flask and FastAPI integrations with OAuth2 callback handling
  - Improved factory route handling with separate GET/POST methods
  - Better template variable population for authentication forms
  - Enhanced error handling across both integrations

CHANGED
~~~~~~~

- **Authentication System**:
  - Factory routes now handle GET and POST separately for better UX
  - Enhanced OAuth callback processing with comprehensive validation
  - Improved state parameter handling with encryption and validation
  - Better error messaging and user guidance for authentication failures

- **Integration Layer**:
  - Updated both Flask and FastAPI integrations to support new OAuth2 flow
  - Enhanced template rendering with better context and error handling
  - Improved factory handler logic with cleaner separation of concerns
  - Better support for custom authentication flows in integrations

- **Dependency Management**:
  - Updated all dependencies to latest stable versions
  - Major version updates: Flask ^2.0.0 → ^3.1.1, Werkzeug ^2.0.0 → ^3.1.3
  - FastAPI ^0.100.0 → ^0.116.1, uvicorn ^0.23.1 → ^0.35.0
  - Core dependencies: boto3 ^1.26.0 → ^1.40.6, urlfetch ^1.0.2 → ^2.0.1, cryptography ^41.0.0 → ^45.0.6
  - Development tools: pytest ^7.0.0 → ^8.4.1, black ^22.0.0 → ^25.1.0, ruff ^0.1.0 → ^0.12.8
  - Documentation: sphinx ^5.0.0 → ^8.2.3, sphinx-rtd-theme ^1.0.0 → ^3.0.2
  - Restructured optional dependencies into independent extras: flask, fastapi, mcp, and all

FIXED
~~~~~

- **Type Safety**:
  - Fixed all pylance/mypy type annotation errors in OAuth2 implementation
  - Enhanced type safety for OAuth2 classes and methods
  - Better null safety checks in authentication flows
  - Improved Union type handling for request bodies

- **Authentication Issues**:
  - Fixed OAuth callback handling edge cases
  - Resolved state parameter validation issues
  - Fixed email validation logic for OAuth2 providers
  - Enhanced error handling in authentication flows

- **Handler Integration Issues**:
  - Fixed critical auth.py bug where handler objects were incorrectly treated as response objects
  - Resolved AttributeError: 'SubscriptionRootHandler' object has no attribute 'write'
  - Resolved AttributeError: 'SubscriptionRootHandler' object has no attribute 'headers'
  - Updated auth.init_actingweb() to properly access appreq.response.write() and appreq.response.headers
  - Added defensive checks for response object availability in authentication flows

- **DynamoDB Storage Issues**:
  - Fixed DynamoDB ValidationException for authorization codes exceeding 2KB index key size limit
  - Fixed DynamoDB ValidationException for access tokens exceeding size limits
  - Implemented individual property storage pattern for large data structures
  - Separated Google token data storage from index keys to prevent size limit violations
  - Added reference key pattern for efficient lookup of separated token data

SECURITY
~~~~~~~~

- **OAuth2 Security Enhancements**:
  - Implemented comprehensive email validation to prevent identity attacks
  - Added state parameter encryption for CSRF protection
  - Enhanced callback validation with multiple security checks
  - Improved error handling to prevent information leakage

- **MCP Authorization Server Security**:
  - RFC 7591 compliant Dynamic Client Registration with proper client credential generation
  - Per-actor client isolation using ActingWeb security boundary model
  - State parameter encryption with MCP context preservation prevents CSRF attacks
  - Secure token separation between ActingWeb internal tokens and Google OAuth2 tokens
  - Proper scope validation and authorization code flow implementation
  - Client credential storage encrypted at rest using ActingWeb property system

v3.1: Jul 28, 2025
--------------------

BREAKING CHANGES
~~~~~~~~~~~~~~~~

- Removed legacy OnAWBase interface completely
- Removed `actingweb.on_aw` module and `OnAWBase` class  
- Removed `ActingWebBridge` compatibility layer from interface module
- Handler constructors now accept `hooks: HookRegistry` instead of `on_aw: OnAWBase`
- Applications must now use the modern `ActingWebApp` interface exclusively

ADDED
~~~~~

- FastAPI integration with `app.integrate_fastapi()` method
- FastAPI integration automatically generates OpenAPI/Swagger documentation
- Synchronous ActingWeb handlers run in thread pools to prevent event loop blocking
- Pydantic models for all ActingWeb endpoints with automatic validation
- Support for modern `@app.actor_factory` decorator in FastAPI integration

CHANGED
~~~~~~~

- All handlers now use HookRegistry directly instead of OnAWBase bridge pattern
- Flask integration now uses HookRegistry directly
- Fixed hook method call signatures in properties.py, resources.py, and www.py
- Fixed path handling in property hooks to prevent index out of bounds errors
- Standardized hook parameter order across all handlers
- Fixed missing arguments in execute_property_hooks calls
- Resolved callback hook return type issues with any() function usage

v3.0.1: (Jul 17, 2025)
------------------------

BREAKING CHANGES
~~~~~~~~~~~~~~~~
- Minimum Python version is now 3.11+
- Removed deprecated Google App Engine (GAE) database implementation
- Removed migrate_2_5_0 migration flag and related migration code
- Database backend now only supports DynamoDB
- Removed Google App Engine urlfetch abstraction layer
- Environment types updated to remove APPENGINE, added AWS
- Separated application-level callbacks (@app.app_callback_hook) from actor-level callbacks (@app.callback_hook)

ADDED
~~~~~
- Comprehensive type hints using Python 3.11+ union syntax (str | None)
- Custom exception hierarchy: ActorError, ActorNotFoundError, InvalidActorDataError, PeerCommunicationError, TrustRelationshipError
- Constants module with AuthType, HttpMethod, TrustRelationship, ResponseCode enums
- Modern build system with pyproject.toml and Poetry for dependency management
- Modern developer interface with ActingWebApp class and fluent API
- Decorator-based hook system for property, callback, subscription, and lifecycle events
- ActorInterface, PropertyStore, TrustManager, and SubscriptionManager wrappers
- Flask integration with automatic route generation
- /methods endpoint support with JSON-RPC 2.0 protocol compatibility
- /actions endpoint support for trigger-based functionality
- Method hooks (@app.method_hook) and action hooks (@app.action_hook)
- Development tooling (black, ruff, mypy) and comprehensive test suite with pytest
- Type checking support with py.typed marker
- __version__ attribute to actingweb module

CHANGED
~~~~~~~
- Modernized string formatting with f-strings
- Simplified HTTP client code to use urlfetch library directly
- Removed config.env == "appengine" environment checks
- Updated default actor type from gae-demo to demo
- Enhanced type safety with comprehensive None-checking patterns
- Applied systematic None validation patterns to prevent runtime errors
- Improved IDE support with better type inference and error detection
- Complete documentation overhaul with modern interface examples

FIXED
~~~~~
- Eliminated potential bugs from dual interface inconsistencies
- Removed unnecessary abstraction layers improving request handling speed
- Single code path reduces potential for interface synchronization issues
- Better type checking with direct HookRegistry usage instead of generic OnAWBase
- Zero Pylance diagnostics errors across entire codebase
- Comprehensive None safety checks across all core modules
- Fixed handler method signatures for proper positional argument passing
- Enhanced HTTP request safety with proper urlfetch module validation
- Fixed OAuth configuration access with proper None checks
- Applied systematic None safety patterns across all HTTP methods
- Refactored actor creation to reduce coupling between factory handler and bridge implementation
- Fixed template variables not being populated for web form POST to /

QUALITY
~~~~~~~
- Legacy OnAWBase interface completely removed for better maintainability
- Applications using OnAWBase must migrate to ActingWebApp interface
- 95%+ reduction in complexity for handler logic
- Clean separation of concerns with direct hook execution
- Much simpler debugging without bridge layer abstraction
- All tests continue to pass with new interface (30/30)
- 90% reduction in boilerplate code for new applications
- Proper circular import handling with TYPE_CHECKING
- Enhanced developer experience with self-documenting type hints

MIGRATION GUIDE
~~~~~~~~~~~~~~~
**For existing applications using OnAWBase:**

**Before (Legacy - NO LONGER SUPPORTED)**::

    class MyApp(OnAWBase):
        def get_properties(self, path, data):
            return data

        def post_callbacks(self, name):
            return True

**After (Modern Interface - REQUIRED)**::

    app = ActingWebApp("my-app", "dynamodb", "myapp.com")

    @app.property_hook("*")
    def handle_properties(actor, operation, value, path):
        if operation == "get":
            return value
        return value

    @app.callback_hook("*")
    def handle_callbacks(actor, name, data):
        return {"status": "handled"}

**Handler instantiation changes:**
- **Before:** `Handler(webobj, config, on_aw=my_onaw_instance)`  
- **After:** `Handler(webobj, config, hooks=app.hooks)`

**Key Benefits of Migration:**
- 95% less boilerplate code
- Better type safety and IDE support  
- Easier testing and debugging
- Single source of truth for application logic
- No more dual interface maintenance

v2.6.5: Apr 22, 2021
--------------------
- Fix bug in subscription_diff handling by replacing query with scan as query requires hash key

v2.6.4: Apr 11, 2021
--------------------
- Messed up release versioning, bump up to avoid confusion

v2.6.3: Apr 11, 2021
--------------------
- Fix bug in peertrustee handling by replacing dynamodb count() with scan() as count requires a hash key

v2.6.2: Oct 20, 2020
--------------------
- Security fix on oauth refresh

v2.6.1: Aug 30, 2020
--------------------
- Fix token refresh to also use Basic authorisation

v2.6.0: Aug 23, 2020
--------------------
- Add support for optional Basic authorisation in token request (e.g. Fitbit is requiring this)

v2.5.1: Jan 29, 2019
--------------------
- Move some annoying info messages to debug in auth/oauth
- Fix bug in set_attr for store where struct is not initialised (attribute.py:70)
- Enforce lower case on creator if @ (i.e. email) in value

v2.5.0: Nov 17, 2018
--------------------
- BREAKING: /www/properties template_values now return a dict with { 'key': value} instead of list of { 'name': 'key',
  'value': value}
- Add support for scope GET parameter in callback from OAUTH2 provider (useful for e.g. Google)
- Add support for oauth_extras dict in oauth config to set additional oauth paramters forwarded to OAUTH2 provider
  (Google uses this)
- Add support for dynamic:creator in oauth_extras to preset login hint etc when forwarding to OAuth2 auth endpoints
  (if creator==email, this allows you to send Google hint on which account to use with 'login_hint': 'dynamic:creator'
  in oauth_extras in config
- Add support for actor get_from_creator() to initialise an actor from a creator (only usable together with config
  variable unique_creator)
- Add support for get_properties(), delete_properties(), put_properties(), and post_properties in the on_aw() class.
  These allows on_aw overriding functions to process any old and new properties and return the resulting properties
  to be stored, deleted, or returned
- Move all internal (oauth_token, oauth_token_expiry, oauth_refresh_token, oauth_token_refresh_token_expiry,
  cookie_redirect, and trustee_root) data from properties (where they are exposed on GET /<actor_id>/properties) to internal
  variable store (attributes). Introduce config variable migrate_2_5_0 (default True) that will look for properties
  with oauth variable names if not found in internal store and move them over to internal store (should be turned
  off when all actors have migrated their oauth properties over to store)
- Add new interface InternalStore() (attribute.py) for storing and retrieving internal variables on an actor (i.e.
  attributes). All actors now have .store that can be used either as a dict or dot-notation. actor.store.var = 'this'
  or actor.store['var'] = 'this'. Set the variable to None to delete it. All variables are immediately stored to the
  database. Note that variable values must be json serializable
- Add new interface PropertyStore() (property.py) for storing and retrieving properties. Used just like InternalStore()
  and access through actor.property.my_var or actor.property['my_var']
- InternalStore(actor_id=None, config=None, bucket=None) can be used independently and the optional bucket parameter
  allows you to create an internal store that stores a set of variables in a specific bucket. A bucket is retrieved
  all at once and variables are written to database immediately
- Fix issue where downstream (trusts) server processing errors resulted in 405 instead of 500 error code
- Fix bug in oauth.put_request() where post was used instead of put
- Fix issue where 200 had Forbidden text

v2.4.3: Sep 27, 2018
--------------------
- Don't do relative import with import_module, AWS Lambda gets a hiccup

v2.4.2: Sep 27, 2018
--------------------
- Get rid of future requirement, just a pain

v2.4.1: Sep 26, 2018
--------------------
- Fix bad relative imports
- Use extras_require for future (python2 support)

v2.4.0: Sep 22 2018
--------------------
- Support python3

v2.3.0: Dec 27, 2017
--------------------
- Entire API for handlers and Actor() as well as other objects changed to be PEP8 compliant
- Add support for head_request(() in oauth and oauth_head() in auth
- Change all uses of now() to utcnow()
- db_gae for Google AppEngine is not kept updated, so folder deprecated and just kept for later reference
- Full linting/PEP8 review
- Add support for actor_id (set id) on Actor.create()

v2.2.2: Dec 3, 2017
-------------------
- Fix bug in region for properties and attributes resulting in using us-east-1 for these (and not us-west-1 as default)

v2.2.1: Dec 3, 2017
-------------------
- Add support for environment variable AWS_DB_PREFIX to support multiple actingweb tables in same DynamoDB region

v2.2.0: Nov 25, 2017
--------------------
- Add support for attribute.Attributes() and attribute.Buckets() (to be used for internal properties not exposed)
- Various bug fixes to make the oauth flows work

v2.1.2: Nov 12, 2017
--------------------
- Split out actingweb module as a separate pypi library and repository
- Python2 support, not python3
- Support AWS DynamoDB and Google Datastore in sub-modules
- Refactor out a set of handlers to allow easy integration into any web framework
- actingwebdemo as a full-functioning demo app to show how the library is used

Jul 9, 2017
--------------------
- Fix bug with unique actor setting and actor already exists
- Improve handling of enforce use of email property as creator
- Fix auth bug for callbacks (401 when no auth is expected)
- Add support for "lazy refresh" of oauth token, i.e. refresh if expired or refresh token has <24h to expiry
- Add support for Actors() class in actor.py to get a list of all actors with id and creator (ONLY for admin usage)
- Fix various bugs when subscriptions don't exist
- Improve logging when actor cannot be created

Apr 2, 2017
--------------------
- Changed license to BSD after approval from Cisco Systems
- Fix bug in deletion of trust relationship that would not delete subscription
- Add support for GET param ?refresh=true for web-based sessions to ignore set cookie and do oauth
- Fix bug in oauth.oauth_delete() returning success when >299 is returned from upstream

Mar 11, 2017
--------------------
- Fix bug in aw_actor_callbacks.py on does exist test after db refactoring
- Fix bug in handling of www/init form to set properties
- Add support to enforce that creator (in actor) is unique (Config.unique_creator bool)
- Add support to enforce that a creator field set to "creator" is overwritten if property "email" is set 
  (Config.force_email_prop_as_creator bool, default True). Note that username for basic login then changes from
  creator to the value of email property. 
  This functionality can be useful if actor is created by trustee and email is set later
- Add new DbActor.py function get_by_creator() to allow retrieving an actor based on the creator value


Feb 25, 2016
--------------------
- Major refactoring of all database code
- All db entities are now accessible only from the actingweb/* libraries
- Each entity can be accessed one by one (e.g. trust.py exposes trust class) and as a list (e.g. trust.py exposes trusts class)
- actor_id and any parameters that identify the entity must be set when the class is instantiated
- get() must be called on the object to retrieve it from the database and the object
  is returned as a dictionary
- Subsequent calls to get() will return the dictionary without database access, but
  any changes will be synced to database immediately
- The actingweb/* libraries do not contain any database-specific code, but imports
  a db library that exposes the barebone db operations per object
- The google datastore code can be found in actingweb/db_gae
- Each database entity has its own .py file exposing get(), modify(), create(), delete()
  and some additional search/utility functions where needed
- These db classes do not do anything at init, and get() and create() must include all parameters
- The database handles are kept in the object, so modify() and delete() require a get() or create()
  before they can be called
- Currently, Google Datastore is the only supported db backend, but the db_* code can now fairly
  easily be adapted to new databases

Nov 19, 2016
--------------------
- Create a better README in rst
- Add readthedocs.org support with conf.py and index.rst files
- Add the actingweb spec as an rst file
- Add a getting-started rst file
- Correct diff timestamps to UTC standard with T and Z notation
- Fix json issue where diff sub-structures are escaped
- Add 20 sec timeout on all urlfethc (inter-actor) communication
- Support using creator passphrase as bearer token IF creator username == trustee
  and passphrase has bitstrength > 80
- Added id, peerid, and subscriptionid in subscriptions to align with spec
- Add modiify() for actor to allow change of creator username
- Add support for /trust/trustee operations to align with spec
- Add /devtest path and config.devtest bool to allow test scripts
- Add /devtest testing of all aw_proxy functionality

Nov 17, 2016
--------------------
- Renaming of getPeer() and deletePeer() to get_peer_trustee() and delete_peer_trustee() to avoid confusion
- Support for oauth_put() (and corresponding put_request()) and fix to accept 404 without refreshing token
- aw_proxy support for get_resource(), change_resource((), and delete_resource(()
- Support PUT on /resources

Nov 5, 2016
--------------------
- Add support for getResources in aw_proxy.py
- Renamed peer to peerTrustee in peer.py to better reflect that it is created by actor as trustee

Nov 1, 2016
--------------
- Add support for change_resource(() and delete_resource(() in aw_proxy.py
- Add support for PUT to /resources and on_put_resources() in on_aw_resources.py

Oct 28, 2016
--------------
- Add support for establishment and tear-down of peer actors as trustee, actor.getPeer() and actor.deletePeer()

  - Add new db storage for peers created as trustee
  - Add new config.actor section in config.py to define known possible peers
- Add new actor support function: getTrustRelationshipByType()
- Add new AwProxy() class with helper functions to do RPCish peer operations on trust relationships

  - Either use trust_target or peer_target to send commands to a specific trust or to the trust associated with a peer (i.e. peer created by this app as a trustee)
  - Support for create_resource() (POST on remote actor path like /resources or /properties)
- Fix bug where clean up of actor did not delete remote subscription (actor.delete())

  - Add remoteSubscription deletion in aw-actor-subscription.py
  - Fix auth issue in aw-actor-callbacks.py revealed by ths bug

Oct 26, 2016
--------------
- Add support for trustee by adding trustee_root to actor factory
- Add debug logging in auth process
- Fix bug where actors created within the same second got the same id

Oct 15, 2016
--------------
- Added support for requests to /bot and a bot (permanent) token in config.py to do API requests
  without going through the /<actorid>/ paths. Used to support scenarios where users can communicate with a bot to
  initiate creation of an actor (or to do commands that don't need personal oauth authorization.

Oct 12, 2016
--------------
- Support for actor.get_from_property(property-name, value) to initialse an actor from db by looking up a property value
  (it must be unique)

Oct 9, 2016
--------------
- Added support for GET, PUT, and DELETE for any sub-level of /properties, 
  also below resource, i.e. /properties/<subtarget>/<resource>/something/andmore/...
- Fixed bug where blob='', i.e. deletion, would not be registered

Oct 7, 2016
--------------
- Added support for resource (in addition to target and subtarget) in subscriptions, thus allowing subscriptions to
  e.g. /resources/files/<fileid> (where <fileid> is the resource to subscribe to. /properties/subtarget/resource
  subscriptions are also allowed.

Oct 6, 2016
--------------
- Added support for /resources with on_aw_resources.py in on_aw/ to hook into GET, DELETE, and POST requests to /resources
- Added fixes for box.com specific OAUTH implementation
- Added new function oauth_get(), oauth_post(), and oauth_delete() to Auth() class. These will refresh a token if necessary and
  can be used insted of oauth.get_request(), post_request(), and delete_request(()
- Minor refactoring of inner workings of auth.py and oauth.py wrt return values and error codes

Sep 25, 2016
--------------
- Added use_cache=False to all db operations to avoid cache issue when there are multiple instances of same app in gae

Sep 4, 2016
--------------
- Refactoring of creation of trust:
  - ensure that secret is generated by initiating peer
  - ensure that a peer cannot have more than one relationship
  - ensure that a secret can only be used for one relationship

Aug 28, 2016
--------------
- Major refactoring of auth.py. Only affects how init_actingweb() is used, see function docs

Aug 21, 2016: New features
--------------------------
- Removed the possibility of setting a secret when initiating a new relationship, as well as ability to change secret. This is to avoid the possibility of detecting existing secrets (from other peers) by testing secrets

Aug 15, 2016: Bug fixes
------------------------
- Added new acl["approved"] flag to auth.py indicating whether an authenticated peer has been approved
- Added new parameter to the authorise() function to turn off the requirement that peer has been approved to allow access
- Changed default relationship to the lowest level (associate) and turned off default approval of the default relationship
- Added a new authorisation check to subscriptions to make sure that only peers with access to a path are allowed to subscribe to those paths
- Added a new approval in trust to allow non-approved peers to delete their relationship (in case they want to "withdraw" their relationship request)
- Fixed uncaught json exception in create_remote_subscription()
- Fixed possibility of subpath being None instead of '' in auth.py
- Fixed handling of both bool json type and string bool value for approved parameter for trust relationships


Aug 6, 2016: New features
----------------------------
- Support for deleting remote subscription (i.e. callback and subscription, dependent on direction) when an actor is
  deleted

  - New delete_remote_subscription() in actor.py
  - Added deletion to actor.delete()
  - New handler for DELETE of /callbacks in aw-actor-callbacks.py
  - New on_delete_callbacks() in on_aw_callbacks.py

Aug 6, 2016: Bug fixes
----------------------------
- Fixed bug where /meta/nonexistent resulted in 500

Aug 3, 2016: New features
----------------------------
- Support for doing callbacks when registering diffs

  - New function in actor.py: callback_subscription()
  - Added defer of callbacks to avoid stalling responses when adding diffs
  - Added new function get_trust_relationship() to get one specific relationship based on peerid (instead of searching using get_trust_relationships())
- Improved diff registration

  - Totally rewrote register_diffs() to register diffs for subscriptions that are not exact matches (i.e. broader/higher-level and more specific)
  - Added debug logging to trace how diffs are registered
- Owner-based access only to /callbacks/subscriptions
- Support for handling callbacks for subscriptions

  - New function in on_aw_callbacks.py: on_post_subscriptions() for handling callbacks on subscriptions
  - Changed aw-actor-callbacks.py to handle POSTs to /callbacks/subscriptions and forward those to on_post_subscriptions()

Aug 3, 2016: Bug fixes
----------------------------
- Added no cache to the rest of subscriptionDiffs DB operations to make sure that deferred subscription callbacks don't mess up sequencing
- Changed meta/raml to meta/specification to allow any type of specification language

Aug 1, 2016: New features
----------------------------
- Added support for GET on subscriptions as peer, generic register diffs function, as well as adding diffs when changing /properties. Also added support for creator initiating creation of a subscription by distingushing on POST to /subscriptions (as creator to inititate a subscription with another peer) and to /subscriptions/<peerid> (as peer to create subscription)
- Subscription is also created when initiating a remote subscription (using callback bool to set flag to identify a subscription where callback is expected). Still missing support for sending callbacks (high/low/none), as well as processing callbacks
- Added support for sequence number in subscription, so that missing diffs can be detected. Specific diffs can be retrieved by doing GET as peer on /subscriptions/<peerid>/<subid>/<seqnr> (and the diff will be cleared)

Jul 27, 2016: New features
----------------------------
- Started adding log statements to classes and methods
- Added this file to track changes
- Added support for requesting creation of subscriptions, GETing (with search) all subscriptions as creator (not peer), as well as deletion of subscriptions when an actor is deleted (still remaining GET all relationship as peer, GET on relationship to get diffs, DELETE subscription as peer, as well as mechanism to store diffs)

Jul 27, 2016: Bug fixes
----------------------------
- Changed all ndb.fetch() calls to not include a max item number
- Cleaned up actor delete() to go directly on database to delete all relevant items
- Fixed a bug where the requested peer would not store the requesting actor's mini-app type in db (in trust)
- Added use_cache=False in all trust.py ndb calls to get rid of the cache issues experienced when two different threads communicate to set up a trust
- Added a new check and return message when secret is not included in an "establish trust" request (requestor must always include secret)

July 12, 2016: New features
----------------------------
- config.py cleaned up a bit

July 12, 2016: Bug fixes
----------------------------
- Fix in on_aw_oauth_success where token can optionally supplied (first time oauth was done the token has not been flushed to db)
- Fix in on_aw_oauth_success where login attempt with wrong Spark user did not clear the cookie_redirect variable
- Fixed issue with wrong Content-Type header for GET and DELETE messages without json body
