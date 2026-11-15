=====================================
ActingWeb Specification - version 1.5
=====================================

Introduction
============

This Document
-----------------------------

*This specification is written in the format of an
`IETF <http://www.ietf.org>`_ draft. However, there is currently no
effort to submit this draft to a working group, nor to make it go
through the process of becoming an IETF proposed standard or have any
other official status. This may or may not be appropriate at some point,
but the text is written in this format because people are used to
reading specifications in this format and it is a well-proven approach*.

Copyright Notice
-----------------------------

This specification is Copyright, Greger Teigre Wedel, 2007-2026.

Permission is granted to copy, distribute, or communicate this
specification without modification. No modification of this
specification is allowed without the explicit permission of the
copyright holder.

All work, including code, derived from the concepts, specifications, and
other instructions found in this specification do not require any
license or permission, and may be distributed under any copyright or
license.

Changelog
-----------------------------

**Version 1.5** (November 2026)

Each normative difference from 1.4 as released (January 2026), marked *Added* (new text where 1.4 was
silent), *Clarified* (1.4 was ambiguous or contradicted itself; the rule
now says one thing) or *Changed* (a requirement of 1.4 is different, or
its level is).

Option tags, the actor and ``/meta``:

- Added: the option tags ``callbacks`` and ``mcp`` are defined in the
  Option tags list.
- Clarified: ``permissionquery`` and ``permissioncallback`` (added in 1.4)
  are defined in the Option tags list, as the actor's capabilities to serve
  the query endpoint and to send and accept permission callbacks.
- Added: an implementation MAY advertise tags not defined here, which a
  peer MUST ignore.
- Added: implementations MAY serve paths beyond those defined here; a peer
  MUST NOT depend on them.
- Clarified: an actor MUST advertise the tag of each OPTIONAL path it
  serves; the ``oauth`` and ``mcp`` tags name capabilities, not paths
  under the actor's root.
- Added: an actor SHOULD NOT advertise a tag for something it does not
  serve.
- Clarified: ``subscriptionresync`` is the receiver's capability; a
  publisher SHOULD send resync callbacks only to a subscriber that
  advertises it.
- Changed: ``oauth`` means that an OAuth2 login is available for the
  mini-application; the per-actor ``/oauth`` binding is no longer defined
  (an implementation MAY offer one).
- Added: a factory MAY be closed, answering 403; a mini-application MAY
  require unique creators (403 for a creator another actor holds, 400 for a
  reserved creator value).
- Changed: a passphrase not supplied at creation MUST be generated at
  random; no fixed default passphrase.
- Added: the creation response body (``id``, ``creator``, ``passphrase``,
  ``trustee_root``) and the body of a GET on the actor root.
- Added: the actor MUST NOT disclose its passphrase to a peer; GET on the
  actor root returns it to the creator and the trustee only.
- Clarified: the 201 and *Location* rule on creation is for API clients; a
  browser form MAY be answered with a page or a redirect.
- Clarified: a creation that fails for a reason other than a temporary or
  server problem answers 400, except the 403 cases above.
- Clarified: the trustee may delete the actor; a successful DELETE of an
  actor answers 204, a refused one 401 or 403, an incomplete one 503 with
  ``Retry-After``.
- Clarified: every scalar ``/meta`` path is ``text/plain``.
- Changed: ``/meta/info`` returns the URI as a ``text/plain`` body (200),
  not a 302 redirect.
- Changed: ``/meta/version`` is any version string chosen by the
  mini-application (dotted, MAY carry a suffix); a peer MUST NOT assume
  single digits.
- Changed: ``/meta/actingweb/version`` is ``1.5``; a peer MUST NOT refuse
  to interoperate because the announced version differs, and SHOULD decide
  by option tags.
- Changed: ``/meta`` returns one flat object (``id``, ``type``,
  ``version``, ``desc``, ``info``, ``specification``, ``trustee_root``,
  ``aw_version``, ``aw_supported``, ``aw_formats``, optionally
  ``aw_trust_types``), not a nested ``actingweb`` object.
- Added: ``/meta/specification``, ``/meta/trustee_root`` and
  ``/meta/actingweb/trust_types`` are defined (OPTIONAL).
- Clarified: ``/meta/actingweb/formats`` lists the formats accepted and
  returned and MAY include ``json``.

``/properties``:

- Changed: a successful PUT answers 204 No Content (was 201), for a
  property and for a list item.
- Changed: a PUT to a name the actor does not accept answers 400 (was
  404); an actor MAY accept any name.
- Clarified: "MUST NOT apply logic" binds the protocol; a mini-application
  MAY validate, transform or refuse a write (a refused PUT is 400), and what
  was stored is what a GET returns and a diff carries.
- Changed: one content-type rule: a single value that is not a JSON
  document is ``text/plain``; everything else is ``application/json``.
- Changed: a POST to /properties applies its attributes independently (not
  atomically); it answers 201 with the written attributes, 403 when the
  mini-application skipped every attribute, and a write that stops part
  way (400, 409, 413 or 503) keeps what was written before it (was: all or
  nothing, 409).
- Added: a POST to a single name that is not a list answers 400.
- Added: a PUT to /properties itself answers 405; a DELETE of /properties
  deletes every simple property (not the lists) and answers 204; a DELETE
  of a name that is not set answers 204 (of a nested path that does not
  exist, 404); a nested PUT under a value with no parts answers 409.
- Added: a GET of all properties (or of a nested value) leaves out what
  the caller may not read instead of refusing; a mini-application MAY
  treat a hidden attribute as not set (404).
- Changed: a name collision between a list and a regular property MUST
  answer 409 on every route, with nothing written (was SHOULD).
- Added: how a list property is created (a POST with ``{"_type":
  "list"}``).
- Clarified: an item path is a canonical non-negative integer under an
  existing list; access to an item is decided on the list's name.
- Changed: the list append's Location header is SHOULD (was MAY).
- Added: a list the actor cannot read MAY be reported with an ``error``
  member or fail the request (409 or 503); responses MAY carry further
  members.
- Clarified: the item answers defined are those of the path forms; other
  item-addressing forms an implementation offers MAY answer differently.

Optional endpoints and ``/mcp``:

- Changed: a successful action answers 200 OK, or 201 Created when it names
  a new action instance (was 201 only); an action the actor does not offer
  fails with a 4xx.
- Changed: unauthenticated requests to /callbacks answer 401; the
  "anonymous POST from a non-ActingWeb application" is no longer generally
  allowed. An implementation MAY let a mini-application accept an
  unauthenticated POST on a callback it names (never the subscription or
  permission callback paths), which then authenticates its caller itself.
- Changed: an authenticated request to a callback nothing handles MUST
  answer 403 (was SHOULD); the subscription and permission callbacks MUST
  come from the peer the path names (403 otherwise, the creator included).
- Changed: ``_method`` on a POST to /resources is no longer defined; a
  /resources request for a resource the actor does not offer answers 404;
  a POST that creates a resource SHOULD answer 201.
- Clarified: /methods arguments may come from the body or the query; the
  example is a POST; an RPC protocol MAY report errors inside a 200.
- Changed: the endpoint summary table: ``/callbacks`` takes DELETE (the
  end of a subscription), ``/subscriptions`` takes PUT and DELETE,
  ``/resources`` states only that GET does not change state, and the
  per-actor ``/oauth`` row is removed.
- Clarified: the /callbacks example carries a JSON callback body.
- Changed: ``/www/init`` no longer requires a form or HTTP Digest; a /www
  path the actor does not serve answers 404; /www pages SHOULD be served
  only to the creator; an unauthenticated browser (on /www or the actor
  root) MAY be redirected to a login page.
- Clarified: the MCP concept mapping is typical, not required; MCP access
  is decided by the permission categories (``tools``, ``prompts``,
  ``resources``, the last shared with /resources), not "identically to
  REST".
- Changed: an MCP request is resolved to an actor per session or, without
  a session, per request; argument validation is MAY (was SHOULD).
- Changed: the MUST to provide a configuration mechanism for MCP exposure
  is removed (how functionality is selected is implementation-defined);
  added that functionality not selected MUST NOT be exposed through MCP.
- Clarified: the ``trustpermissions`` sentence moved from the MCP chapter
  to Permission Management API.

``/trust``:

- Changed: the verification field is ``verification_token`` (was
  ``verificationToken``).
- Changed: a GET on a relationship answers 202 while it is not approved and
  200 when approved (was 201), 404 when it is gone; there is no "refused"
  403: a refused relationship is deleted. The creator (and trustee) get the
  same codes as the peer; another peer (an admin peer included) gets 403
  for a relationship that is not approved. The approval notification is
  answered 204.
- Added: the trust list SHOULD be filterable by the query parameters
  ``relationship``, ``peerid`` and ``type``.
- Changed: the shared secret and verification token are returned to the
  creator, the trustee and the relationship's own peer only, never to
  another peer (an admin peer included); the list never carries them (was:
  readable by admin).
- Clarified: the field table's MANDATORY applies to every representation
  except ``secret``; further fields MAY be present; flags are JSON
  booleans in every response, the creation responses included.
- Added: the body of the 201 and 202 creation responses (without secret and
  verification token while unapproved).
- Added: what a receiver of a trust request requires (``baseuri`` and
  ``id``; 400 otherwise) and MAY accept without (``secret``, ``type``).
- Changed: the approval notification is ``{"approved": true}`` (a JSON
  boolean) and only approvals are notified; a refusal is a deletion.
- Changed: a PUT on a relationship accepts ``approved`` only as the JSON
  boolean ``true`` or the text ``true`` in form data (anything else is 400
  with nothing changed), and ``permissions``; answers 204.
- Added: a peer other than an admin peer MUST NOT change the approval of
  its relationship or the permissions granted to it; an admin peer MAY
  manage the actor's relationships.
- Added: a relationship request for a peer B already holds verified or
  approved MUST NOT replace it: B accepts it only as a re-pair from that
  peer, authenticated with the current secret, replacing only the secret
  (SHOULD be conditional on the secret it authenticated with), answering
  201 or 202 as stored; otherwise 403. A stored, unverified and unapproved
  relationship MAY be replaced by a request that verifies.
- Added: B MUST treat a relationship as verified only when the
  verification succeeds and the requester's base URI serves its claimed id;
  B MUST NOT approve automatically unless it verified, and MAY refuse a
  manual approval of an unverified one; until approval B SHOULD grant the
  requester nothing beyond the relationship's own URL.
- Added: A MUST NOT return the verification token from a relationship it
  has not approved, and B MUST NOT treat a verification as successful when
  the answering relationship is not approved.
- Added: Deleting a Trust Relationship (both sides, 204 and 404, 502 when
  the peer cannot be reached, local-only deletion).
- Added: initiation failures (400 for a missing ``url`` or a reserved type;
  any failure with the peer an error status, MAY be 408).
- Added: the relationship names ``creator``, ``trustee``, ``owner`` and
  ``any`` are reserved (400); a peer never gets the creator's or trustee's
  access by its relationship's name; further types MAY be offered.
- Changed: "MAY NOT hold more than one relationship" is MUST NOT.
- Clarified: the two permission endpoints' shapes (the /trust one returns
  the stored form, flat; the query endpoint returns the merged effective
  form); a GET for a relationship of a type the actor does not define
  answers 404 on both GET endpoints.
- Changed: the creator and an admin peer may also use the permission query
  endpoint for any peer (was: only the peer itself); 403 for anyone else,
  decided before the lookup; 503 on a storage fault.
- Changed: the ``resources`` permission category is one grant for the
  ``/resources`` path and MCP resources alike (GET is read, PUT and POST
  write, DELETE delete) (was: MCP resources only).
- Added: pattern matching: a backslash escapes ``*``, ``?`` and itself;
  matching is case-sensitive without character classes.
- Added: an exclusion covers its path's descendants, which are removed
  from data returned for an ancestor (a read, a listing, a diff).
- Changed: permission evaluation step 5: a category the grant mentions and
  does not match is denied; a category it does not mention follows the
  access rules of the relationship type (was "default to deny"); the deny
  is a MUST (was part of a SHOULD list).
- Changed: the OAuth2 client metadata example is removed; further fields
  in a relationship's representation are not defined here.
- Changed: only the creator and the trustee may change the trustee root or
  the creator (PUT and DELETE on /trust/trustee); a peer of any type gets
  403 (was: admin or creator). The answers (204, 400, 409) are defined.
- Changed: trustee access requires no trust relationship (the MUST that
  required one is removed); it ends only when the passphrase, the creator
  or the trustee root changes. The trustee root MUST be set for it.
- Clarified: the passphrase strength MAY be estimated from length and
  alphabet; the trustee MAY be given further paths.
- Added: the creator MAY be authenticated by other means (an OAuth2 login);
  invalid credentials are refused (401 or 403).
- Clarified: the second trust sequence table's step numbers and the
  verification URI (it is the requesting actor's).

``/subscriptions``:

- Changed: a new subscription's sequence is 0 and its first diff 1 (was:
  "the number is 1 for each new subscription").
- Added: sequence numbers MAY have gaps.
- Added: a granularity other than ``high``, ``low`` or ``none`` answers
  400.
- Clarified: read access is checked when a subscription is created and
  again when a diff is delivered or polled; a diff the subscriber may read
  none of is not pushed, keeps its sequence number and is polled as ``{}``.
- Added: the 201 body of a new subscription (``subscriptionid`` included).
- Changed: the subscription's Location SHOULD be absolute (was relative); a
  subscriber accepts either.
- Added: the answers of ``POST /subscriptions`` (204 with Location, 400,
  an error status MAY be 408), which an actor SHOULD refuse from a peer
  (403); the subscription list's element fields (both directions), a peer
  seeing only its own; and Deleting a Subscription, including the
  publisher's DELETE on the subscriber's callback URI (only from the named
  peer; 204, or 404 when the subscriber holds no such subscription).
- Clarified: a change MUST be recorded whichever interface made it (REST,
  web pages, the mini-application itself).
- Added: a diff for a write deeper than a subscribed resource carries the
  resource's whole stored value.
- Added: suspension and resume.
- Changed: a delete is ``""`` at the deleted level and ``{name: ""}`` above
  a deleted property, with a sequence number, at every level (1.4 implied
  a deletion only above the deleted level); a subscriber treats ``""`` as
  absent (a stored empty string cannot be told from a deletion), and
  SHOULD treat ``null`` as a deletion.
- Added: a resource subscription is told (``""``) when its resource went
  away with its parent.
- Added: a DELETE of /properties is one diff per subscriber, naming every
  deleted property.
- Changed: a write below a sub-target sends subscriptions on the target or
  the sub-target the sub-target's whole stored value (was only the changed
  part); the worked examples are corrected.
- Added: the diff carries the stored value, after the mini-application's
  transformation.
- Clarified: a sub-target or resource diff is relative to the subscribed
  level on both sides, except the full state sent to a subscriber without
  resync support, which is keyed by name at every level; list diffs are wrapped in the list's name only for a
  target-level subscription.
- Added: the list operations ``insert``, ``pop`` (with a negative index),
  ``clear``, ``delete_all``, ``extend`` (an empty ``extend`` creates a
  list) and ``metadata`` are defined; full state as ``clear`` then
  ``extend``; the list diff reference form (``spanned`` and ``bytes``).
- Added: the callback URI is derived from the trust's base URI.
- Added: a low-granularity subscriber MUST fetch the diff under the
  publisher's base URI stored for the trust and MUST NOT send its
  credentials to a URL taken from the callback body.
- Changed: callback and poll timestamps are ISO 8601 UTC with microseconds
  and ``Z``; each diff carries the time it was recorded; a receiver SHOULD
  NOT depend on timestamps for ordering.
- Changed: a 2xx answer to a callback does not clear the diff (was: MUST be
  cleared).
- Added: the subscriber's answers to a subscription callback (204, 400,
  403, 503 with ``Retry-After``); a callback with ``data`` and no
  ``sequence`` is invalid (400), and so is a ``type`` other than ``diff``
  or ``resync`` (an absent ``type`` is ``diff``).
- Changed: a GET on a diff's own URL consumes the diff (a second GET is
  404); a subscriber that lost the answer recovers by reading the
  subscribed resource or from a resync (was: repeated GETs MUST give the
  same result).
- Changed: ``{"sequence": 0}`` in a clearing PUT clears nothing; the PUT
  answers 204, 400 for a sequence that is not a number.
- Clarified: the low-granularity callback example is valid JSON.

Resync, permission callbacks, delivery:

- Added: a subscriber without a callback endpoint finds its resync as a
  diff with ``"type": "resync"``, a ``url`` and empty ``data``, and SHOULD
  act on it as on a resync callback.
- Changed: on a resync the subscriber fetches from the publisher's base URI
  at the level of its stored subscription (not from the body's ``url``),
  removes what the fetched state no longer has, and, when the fetch fails,
  answers 503 without advancing its sequence or applying an empty state.
- Changed: a ``none`` subscription is never sent a resync callback; it
  finds the resync as a ``type: resync`` diff when it polls, and SHOULD
  clear that marker only after the fetched state was applied.
- Added: a publisher MAY send a resync callback to a subscriber whose tags
  it does not yet know; after resuming suspended subscriptions it MUST tell
  each subscriber (resync callback, resync diff, or full state).
- Added: a resync takes a sequence number; ``subtarget`` is an empty
  string or ``null`` when unset (a receiver accepts both) and ``resource``
  is not sent; a 2xx answer means delivered; an
  undelivered resync MAY be sent again at the next resume.
- Added: to a subscriber without ``subscriptionresync`` the publisher sends
  the full state as low-granularity diffs (a ``clear`` of the lists, then
  the whole state).
- Changed: deleting per-relationship permissions sends a permission
  callback (with the type's defaults); a change of a trust type's defaults
  MAY notify (was SHOULD).
- Changed: a receiver of a permission callback that answers 503 MAY get
  the same body resent a bounded number of times; this resend is a MAY and
  the one exception to the rule against automatic retries.
- Clarified: a permission callback carries every category, ``actions``
  included; its timestamp MAY end in ``Z`` or ``+00:00``; a sender MAY send
  without checking tags; the receiver's answers (204, 400, 403, 503); an
  older callback is ignored entirely (nothing stored, nothing removed, no
  reaction) and answers 204.
- Added: a publisher MAY send the callbacks for one change concurrently,
  and how it bounds them is an implementation matter; of two dependent
  callbacks to one subscriber, the second is sent only after the first was
  answered with a 2xx, and not at all otherwise; a receiver MAY hold out-of-order
  callbacks briefly before polling, and diffs a gap poll applies are
  applied like callback diffs.
- Added: a change whose diff can be neither recorded nor given its
  sequence number is answered with an error (a 5xx), never dropped
  silently; the subscriber may then not learn of it until a resync.
- Changed: payload limits, back-pressure, the circuit breaker and
  compression are OPTIONAL mechanisms; an implementation without them
  conforms (the recorded diff and polling are the recovery). In detail:
  enforcing a payload limit is MAY (was SHOULD); the action over the limit
  is MAY (was "the actor MUST either"); splitting a large ``extend`` is MAY
  (was SHOULD); "Receivers MUST handle partial operations" is removed (a
  sender that splits makes each part an ordinary diff); the circuit
  breaker is MAY (was SHOULD); a sender that does not act on 429 or 503
  treats them as a failed delivery.
- Changed: a 503 from a receiver concerns that callback, not the whole
  actor; a sender that acts on it backs off that subscription (was: stop
  all callbacks to the actor). A receiver MAY refuse a callback it cannot
  hold with 400 instead of 429.
- Clarified: a receiver that advertises ``callbackcompression`` MUST
  accept compressed payloads (one that does not MAY), and only such a
  receiver MUST handle both forms; a sender MUST NOT compress to one that
  does not advertise it.
- Changed: the informational headers for a downgraded or truncated
  callback are no longer named.
- Changed: overlapping subscriptions: each subscription is delivered
  independently (was: one callback per change, to the most specific
  subscription); the subscriber MUST apply a change once and SHOULD store
  from the whole-target subscription, not from a narrower one to the same
  peer. The "Explicit Duplication" rules are removed.

Security Considerations:

- Clarified: https is a MUST ("MANDATORY" is not a keyword); the
  relationship validation list has four elements.
- Added: what belongs to the creator and the trustee is never given to a
  peer.
- Added: a temporary storage fault SHOULD answer 503 with ``Retry-After``,
  never a false success or a false 404.
- Changed: ``_method`` (and ``X-HTTP-Method-Override``) is MAY, on the
  paths and methods an actor chooses (was MUST wherever a method other
  than GET and POST is specified); an actor that accepts ``_method`` on a
  GET MUST refuse such a request from another site.

**Version 1.4** (January 2026)

- Added ``sequence`` field requirement to GET subscription response (``/subscriptions/<peerid>/<subid>``)
- The subscription's current sequence number MUST now be included at the top level of the response
- Added Permission Callback (OPTIONAL) section for push-based permission change notifications
- Added Permission Query Endpoint (OPTIONAL) section for pull-based permission discovery
- Added ``subscriptionresync`` option tag for resync callback support
- Added Resync Callback section for bulk operation synchronization
- Callbacks now support optional ``type`` field (``"resync"`` or ``"diff"``)
- Added Granularity Selection Guidelines with recommendations for large properties and high subscriber counts
- Added Callback Delivery Semantics section clarifying at-most-once delivery and recovery mechanisms
- Added Callback Payload Limits with RECOMMENDED 256KB maximum and automatic downgrade behavior
- Added Callback Back-Pressure mechanism using HTTP 429/503 responses and circuit breaker pattern
- Added Callback Compression support (OPTIONAL) using standard HTTP content encoding
- Added Subscription Scope and Overlap clarification for handling multiple overlapping subscriptions
- Added List Property and Regular Property Namespace section clarifying namespace exclusivity
- Renamed list property metadata field ``item_count`` to ``count`` for consistency
- Added ``format`` query parameter for list property GET requests (``format=short`` returns metadata only, ``format=full`` returns all items)
- Added new option tags: ``subscriptionresync``, ``callbackcompression``, ``permissioncallback``, ``permissionquery``

**Version 1.3** (December 2025)

- Added List Property Subscriptions with structured diff payloads
- List property subscriptions use clean property name (no prefix) in subtarget
- Diff payloads include ``operation``, ``item``, ``index``, and ``items`` fields
- Updated ``listproperties`` option tag to include subscription capabilities

**Version 1.2** (November 2025)

- Added ``listproperties`` option tag for ordered collections
- Added List Properties section with full CRUD operations and metadata
- Added Response Conventions: empty collections return ``200 OK`` with ``[]``, not ``404``
- Added ``/meta/trusttypes`` endpoint for SPA client trust type discovery
- Changed empty ``/properties`` to return ``200 OK`` with ``{}``

**Version 1.1** (October 2025)

- Added ``trustpermissions`` option tag for per-relationship permission management
- Reformatted option tags documentation for clarity
- Updated copyright year range

**Version 1.0** (November 2016)

- Initial specification release
- Core endpoints: ``/properties``, ``/meta``, ``/trust``, ``/subscriptions``
- Optional endpoints: ``/actions``, ``/resources``, ``/methods``, ``/sessions``, ``/www``, ``/oauth``
- Trust relationship model with verification flows
- Subscription and callback mechanisms

Terminology
-----------------------------

In this document, the key words "**MUST**", "**MUST NOT**", "**REQUIRED**", "**SHALL**",
"**SHALL NOT**", "**SHOULD**", "**SHOULD NOT**", "**RECOMMENDED**", "**NOT RECOMMENDED**",
"**MAY**", and "**OPTIONAL**" are to be interpreted as described in BCP 14, RFC
2119 and indicate requirement levels for compliant ActingWeb
implementations.

Abstract
-----------------------------

The ActingWeb micro-services model and protocol defines a bot-to-bot and
micro-service-to-micro-service communication that allows extreme
distribution of data and functionality. This makes it very suitable for
holding small pieces of sensitive data on behalf of a user or "things"
(as in Internet of Things). These sensitive data can then be used and
shared in a very granular and controlled way through the secure and
distributed ActingWeb REST protocol. This allows you to expose e.g. your
location data from your phone directly on the Internet (protected by the ActingWeb
security framework) and to be used by other services `on your
choosing`. You can at any time revoke access to your data for one
particular service without influencing anything else.

The programming model in ActingWeb is based on an extreme focus on only
representing one small set of functionality and for only one user or
entity. This is achieved by not allowing any other way of calling the
service (in ActingWeb called a "mini-application") than through a user
and the mini-app's REST interface (a user's instance of a
mini-application is called an `actor` in ActingWeb). From a practical
point of view, getting xyz's location through the REST protocol is as
simple as doing a GET
`http://mini-app-url/xyz/properties/location`.

There is absolutely no way of getting xyz's and yyz's location
information in one request, and the security model enforces access based
on user (i.e. actor), so even if you have access to
`http://mini-app-url/xyz/properties/location`, you will not have
access to `http://mini-app-url/yyz/properties/location`.

Any functionality desired across actors, for example xyz sharing
location information with yyz `MUST` be done through the ActingWeb
REST protocol. However, since the ActingWeb service-to-service REST
protocol is standardised, `any` service implementing the protocol
can easily share data with other services.

The ActingWeb REST protocol specifies a set of default endpoints (like
`/properties`, `/trust`, `/subscriptions` etc) that
are used to implement the service-to-service communication, as well as a
set of suggested endpoints (like `/resources`, `/actions`
etc) where the mini-applications can expose their own functionality. All
exchanges are based on REST principles and a set of flows are built into
the protocol that support exchanging data, establishing trust between
actors (per actor, not per mini-application), as well as subscribing to
changes.

The security model is based on trust between actors, not
mini-applications. This means that each instance of the mini-application
holding the sensitive data for one particular person or thing
`must` be connected through a trust relationship to another
ActingWeb actor, but it doesn't have to be a mini-application of the
same type (like location sharing), but could be a location sharing actor
establishing a trust relationship with 911 authorities to allow
emergency services to always be able to look you up.

There are currently two ways of establishing trust between actors:
either through an explicit OAuth flow where an actor is tied to
somebody's account somewhere else (like Google, Box.com, etc) or through
a flow where one actor requests a trust relationship with another, which
then needs to be approved either interactively by a user or
programatically through the REST interface.

Overview of operations
----------------------

The ActingWeb is an application-layer communication protocol used
between independent software components that can reside on any
computer-powered device. These software components or services, referred
to as mini-applications, implement the ActingWeb protocol to expose
data, resources, and services to other ActingWeb mini-applications or to
clients of the ActingWeb services (that not themselves are ActingWeb
mini-applications). ActingWeb is targeted towards machine-to-machine
communication, and can be used to build Internet of Everything (IoT)
type functionality.

ActingWeb assumes a programming model where you can only access data and
services through individual instances of the mini-application and where
there is one and only one user or entity that is represented. That is, there
is no concept of “get all instances” of something, only “get this data
for this specific instance.”

Thus, in ActingWeb terminology, an *actor* is an instance that is
running and exposing the mini-application's services for one specific
entity/user/device, i.e. a mini-application may implement location
awareness functionality, and a single actor (an instance of the
mini-application) may represent one physical mobile device and keep
track of that device's current GPS position, as well as allow other
actors to access that device's GPS position. This is contrary to typical
web applications, where one application normally implements a set of
functionality for many entities/users. However, another mini-application
could offer location services for users specifically (and not a device)
and then multiple location-aware devices and services associated with a
single user could serve data to that user’s actor. The scope of a
mini-application is thus not a rigid concept, but rather a design
principle.

In order to access an actor's data, a set of credentials is required.
The credentials identifying the requesting actor are unique for the
relationship between the two actors. Each such relationship has a trust
level, controlling which level of access the requesting actor has to the
actor's data. Hence, a mini-application is always contacted through a
specific actor, and the credentials give access to the actor's data. The
actors establish trust relationships with each other in many-to-many
relationships where each relationship is bi-directional (optionally
one-way) and has a trust level. The trust relationship is then used as
authentication when requesting access. The mini-application itself
specifies which access rights are given to which data, resources, and
services for each trust level and thus outside the scope of this
document, while the method used to create a trust relationship is
specified in this document.

The mini-application functionality of the actor is accessed through a
set of pre-defined URIs. The ActingWeb protocol for interaction
**between** actors is based on RESTful principles, while RPC-style
methods like SOAP can also be exposed as part of the mini-applications
accessible functionality if desired. The ActingWeb protocol specifies a
basic set of URIs (*endpoints*) that must be supported.
Mini-applications may (indeed is likely to) offer also other resources
and services than those specified in this document.

Each actor implements one and only one mini-application. The
mini-application functionality and interface may be described in human
or machine-readable form, dependent on the preference of the creator. A
description of a mini-application is similar to the interface of a class
in object-oriented terminology and exhaustively describes the
mini-application so that it can be used by creators of other actors for
the purpose of communication between the actors.

Each actor also offers a subscription endpoint, where actors and clients
can request to be notified about changes to a given endpoint path (like
/resources/target/12345). The notification is either a callback to an
URI provided by the requestor or, optionally, as a subscription resource
that can be polled.

An actor typically resides on a web server and is thus accessible via a
root URI for that specific actor, ex.
https://actingweb.net/apps/app1/897JGHGY76HGhgK/

An important aspect of actors is how they relate to traditional user
accounts found in interactive (and SOAP/REST-based) web sites and
services: In a classic web site/web service implementation, the root URL
is the entry point to a login page asking for login credentials or
authentication. Credentials, including a username, are thus required as
part of the web service request. An ActingWeb actor's root URL will
typically not only identify the account in question, but the account's
specific functionality, for example the voicemail inbox. The credentials
used to access the actor are never an account username and password, but
rather the credentials of a trust relationship that has been established
between the requesting and requested actor. This trust can for example
be established using OAuth or through an approval process as described
in this document.

Structure of the Protocol
-------------------------

As a REST-based protocol, the ActingWeb protocol utilises the http
protocol specification. All communication between actors is based on
usage of the basic principles of an http envelope with a message type,
headers and corresponding values, and a payload. Http responses are also
re-used.

::

  | Actor | ---- http(s) -----| Actor |

*Figure, http(s) as transport*

This specification defines the URI interface each actor must implement,
which http methods shall be used to accomplish what, which http response
codes shall be used in which situations, as well as definitions of the
representations to be used in http requests and responses. There is a
set of mandatory URI paths that any actor must respond to, as well as a
set of optional paths to be used for specific pre-defined purposes.

The protocol also specifies how trust relationships shall be
established, how to use them for authentication and authorisation, as
well as how they are terminated.

Finally, the protocol specifies what a subscription is, how a
subscription can be established, fulfilled, and cancelled.

Definitions
-----------

Endpoint:
  The ActingWeb protocol specifies a set of endpoints directly
  under the root URI of the actor that is used to get access to the
  functionalities offered by an actor

Actor:
  A software component that exposes the ActingWeb protocol
  interface and is accessible to other actors or clients

Action:
  An action is a resource exposed by an actor or an agent (see
  definition) that results an in external action like turning a lightbulb
  on or off, to be executed (i.e. external to the actor). The response may
  even be an OK, as in "action executed"

Agent:
  A software component that implements partial or in whole a
  mini-application according to the ActingWeb Specification and which
  offers not only data, but also resources, actions, or methods that are
  callable. As opposed to an actor, an agent is typically not publicly
  available (could be on and off due to battery limitations or
  connectivity) and often has a Proxy as peer that can receive requests on
  behalf of the Agent

Client:
  A software component that uses the ActingWeb protocol to access
  data, resources, or services from an actor, but which does not implement
  the ActingWeb protocol interface itself and thus cannot be contacted as
  an actor

Method:
  A method is an RPC (Remote Procedure Call) style service that is
  accessible through a specific URI

Mini-application:
  A set of functionality that can be instantiated to
  many actors. Consists of a set of data, resources, methods, and actions
  that other actors and clients can request and operate on. Defined by the
  mini-application definition.

Mini-application definition:
  Either a human- or machine-readable
  description of the data, resources, methods, and actions a
  mini-application implements. A human-readable format can be of any type,
  as long as it is complete enough for somebody to use the actors
  implementing the mini-application.

Mini-application type:
  A URN string prefixed with ActingWeb that
  uniquely identifies the mini-application, ex.
  urn:actingweb:domain.com:myapp

Resource:
  A resource is an entity exposed through a URI and other actors
  or clients can manipulate the resource through commands according to
  RESTful principles

Root URI:
  All actors have a root URI where it can be contacted using
  http type methods, either directly (if the URI is http/https) or encoded
  in the protocol used (i.e. \_method=…)

Peer:
  An actor that has an established trust relationship with another
  actor. An actor will have many peers

Proxy:
  A software component that implements a mini-application according
  to the ActingWeb Specification, but which does not offer anything beyond
  data and proxying capabilities. A proxy has a peer Agent that implements
  the same mini-application that it is a proxy for. The agent is using the
  proxy as a publicly available storage and proxy for communication with
  other actors. The proxy may store requests for resources, actions, and
  methods and forward these when the agent comes online

The Mini-Application Model
==========================

What Is a Mini-Application?
-----------------------------

The mini-application is the central element in the ActingWeb. The
concept is very flexible, practically any tiny functionality, like
holding one value, can be wrapped into a mini-application, or you can
create one actor implementing all the functionality you need. If you
have an existing web service, it may be tempting to just create one
ActingWeb mini-application to expose your web service in the ActingWeb.
However, you gain a lot more by creating mini-applications that follow
the principles of the ActingWeb: user-centric, atomic, 24x7 alive, and
isolated. These principles are explained in more detail further below.

The mini-application can in many ways be compared to a class from
object-oriented programming languages. The class has private and public
data, as well as methods that can be called with certain parameters and
return values. The mini-application offers the same (and more) through
an interface definition. A class has a name; the mini-application has a
type. Both can be instantiated, the class into an object, and the
mini-application into an actor.

The Mini-Application's Type
---------------------------

Each mini-application MUST have a type name in the form of a urn
prefixed with `actingweb`. A unique namespace MUST be chosen by
using either a rightfully owned domain name or email address. All other
urns are reserved for use by a coordinating body, currently
actingweb.org. Examples of valid mini-application types:
`urn:actingweb:payment:creditcard`,
`urn:actingweb:mydomain.com:coolapps:app1`,
`urn:actingweb:user@domain.com:myapp2`

Any given mini-application type can have zero, one, or many actual
implementations (for example in different programming languages, for
different server platforms etc). A mini-application type MUST correspond
to one and only one human- or machine-readable description.

Option tags
-----------------------------

Option tags are textual tags indicating support for a specific
functionality as specified in this specification (i.e extensions). The
*/meta/actingweb/supported* path MUST return a list of comma-separated
option tags to indicate which OPTIONAL functionalities that the
mini-application has implemented and thus the actor supports.

The following option tags (optional parts) may be advertised. Only actor creation/deletion and the
``/properties`` and ``/meta`` paths are mandatory. Many actors also support ``/callbacks`` and
``/www`` for web interaction; third‑party integrations often use ``/oauth``.

An actor MUST advertise the tag of each OPTIONAL path it serves (see
Endpoints), and SHOULD advertise any other tag exactly when it serves the
behaviour the tag names; it SHOULD NOT advertise a tag for something it
does not serve. An implementation MAY advertise tags this specification does not
define; a peer MUST ignore a tag it does not know and MUST NOT infer a
capability from it. Implementations MAY also serve paths beyond those defined
here (for example login pages, OAuth2 endpoints or discovery documents at the
root of the mini-application, or further paths under an actor's root URI); a
peer MUST NOT depend on such a path unless it is defined here or by the
mini-application's definition.

callbacks
  The ``/callbacks`` path is available to receive callbacks (subscription callbacks, permission
  callbacks and any callbacks the mini-application defines). See the ``/callbacks`` section.

trust
  The trust endpoint is available to request and establish regular, two‑way trust relationships
  between actors. If trust is available, the actor SHOULD be able to receive callbacks on ``/callbacks``.

onewaytrust
  A more restrictive trust model: A can have trust to B without implying the reverse.

subscriptions
  The subscriptions endpoint is available to establish subscriptions on the actor’s data, actions, or resources.

actions
  The ``/actions`` path is available for triggering operations (e.g., ``/actions/turn-lights-off``).

resources
  The ``/resources`` path is available for non‑ActingWeb data relevant to the actor (e.g., ``GET /resources/lights``).

methods
  The ``/methods`` path is available for non‑REST API access (e.g., ``/methods/soap/sendMessage``).

sessions
  The ``/sessions`` path is available for session‑based functionality (e.g., ``/sessions/SIP/<id>``).

www
  The ``/www`` path is available for human web‑based interaction with the actor.

oauth
  An OAuth2 login is available for the mini-application: a user can sign in through an external
  OAuth2 provider to reach (or create) the actor they own. Where the login is served is
  implementation-defined (see the ``/oauth`` section).

mcp
  The actor can be reached as a Model Context Protocol (MCP) server. See the ``/mcp`` chapter.

proxy
  The actor implements proxy capabilities.

nestedproperties
  Support for deeper, nested JSON structures in ``/properties`` (beyond basic attribute/value pairs).

listproperties
  Support for list properties under ``/properties``, allowing ordered collections of items with
  individual item CRUD operations, list-level metadata (description, explanation), and structured
  subscription diff payloads containing operation type, item data, and index information.

trustpermissions
  The trust endpoint supports per‑relationship permission management (enhanced trust API and ``/permissions``).

permissionquery
  The permission query endpoint ``GET /{actorid}/permissions/{peerid}`` is available (see
  Permission Query Endpoint).

permissioncallback
  The actor sends permission callbacks to its peers when what it grants them changes, and
  accepts permission callbacks from its peers on ``/callbacks/permissions/{peerid}`` (see
  Permission Callback).

subscriptionresync
  Support for the resync callback mechanism, as a receiver: the actor accepts
  ``type: "resync"`` callbacks on its subscription callback URIs and acts on them by fetching
  the subscribed state (see Resync Callback). A publisher reads the tag from the subscriber
  to decide whether it may send a resync callback; an actor that also publishes MAY send
  resync callbacks to a subscriber that advertises the tag.

callbackcompression
  Support for compressed callback payloads using standard HTTP content encoding (gzip, br).
  Receivers advertising this tag accept ``Content-Encoding`` headers on callback requests.

Response Conventions
-----------------------------

**Empty Collections (SPA-Friendly Behavior)**

When an endpoint returns a collection of items (such as trust relationships, subscriptions,
properties, or list items), the following convention applies:

- If the collection exists but is empty, the endpoint MUST return ``200 OK`` with an empty
  array ``[]`` or an object containing an empty array.
- A ``404 Not Found`` response MUST only be used when a specific individual resource does not
  exist (e.g., a specific property name, a specific trust relationship by peer ID, or a
  specific list item by index).

This convention enables Single Page Applications (SPAs) and API clients to distinguish between
"no items found" (empty collection, 200 OK) and "resource does not exist" (404 Not Found),
simplifying client-side state management and error handling.

**Examples:**

- ``GET /actor/trust`` with no trust relationships → ``200 OK`` with ``[]``
- ``GET /actor/trust/friend/nonexistent-peer`` → ``404 Not Found``
- ``GET /actor/properties`` with no properties → ``200 OK`` with ``{}``
- ``GET /actor/properties/nonexistent`` → ``404 Not Found``
- ``GET /actor/properties/mylist`` (empty list) → ``200 OK`` with ``[]``
- ``GET /actor/properties/mylist/99`` (index out of range) → ``404 Not Found``

.. note::

   This convention was introduced in ActingWeb Specification version 1.2. Implementations
   based on version 1.1 or earlier may return ``404 Not Found`` for empty collections.
   Clients SHOULD handle both behaviors for backward compatibility with older implementations.

The Actor
==========

What is an Actor?
-----------------------------

An actor is a running software component that is ready to respond to
external requests, as well as internal events or requests (for example
if residing on a mobile phone). The actor implements a small and finite
set of functionality with the purpose of offering parts or all of that
functionality to the outside world. An actor is not a replacement for a
SOAP or REST-based web service, and is not a part of a web site for
human interactions. Actors are made for machine-to-machine
communication, and is ideal for e.g. bot-to-bot communication.

Each actor is, in the object-oriented terminology, an instantiation of a
class, and thus can be seen as an object. The mini-application
definition corresponds to the class definition and the mini-application
itself to the class declaration. Like objects in object-oriented
programming languages, actors can access other actors' data (if they are
public) and call methods.

All actors MUST have a globally, unique root URI. The root URI can be in
the form of a http or https URL, or any other type of URI that can allow
two-way communication and which are specified in this or associated
specifications. The root of the URI SHALL uniquely identify the actual
actor, i.e. the mini-application instance:
http://www.actingweb.net/miniapp1/my\_actor\_id/. In the case of an
email, the full email address SHALL uniquely identify the instance:
mailto:my\_actor\_id@Actingweb.net.

The same holds for SIP URIs, example: sip:my\_actor\_id@actingweb.net or
possibly sip:myapp@actingweb.net;gruu=my\_actor\_id

Identity
-----------------------------

Each actor's root URI MUST be globally routable and, unless the actor is
offline, behind NAT or otherwise, a request to this URI MUST reach the
actor. Each actor MUST have an id that is created at creation
(instantiation) and which is valid throughout the lifetime of the actor.

The id MUST be globally unique. It is RECOMMENDED that a version 5
(SHA-1) UUID (RFC 4122) is used with the base URI of the location of
actor as name input to the algorithm. The resulting UUID MUST be added
to the base URI using the standard encoding. Example:
*​*\ http://actingweb.net/myapp/f81d4fae7dec11d0a76500a0c91e6bf6

Data Representation
-----------------------------

All input and output representation specified throughout this document
MUST by in UTF-8 unless otherwise specified. The default data
representation is the JSON format and MUST be supported. Alternative
data representations, like urlencoded form-data, XML or others, can also
be supported and MAY be announced as a capability through the formats
element in /meta/actingweb (see /meta endpoint section). Content formats
should be negotiated with standard http header mechanisms.

Instantiation of Actors
-----------------------------

Actors can be instantiated in several ways dependent on their context
and environment. For example, an installed application on a computer or
mobile phone that implements a mini-application as an actor, is
instantiated the first time it runs. Such instantiation is based on
installing the software on a new device, a factory- or manual process.

Actors that reside on a web server MUST implement dynamic instantiation
through a mini-application factory present at the level right above the
actors' root URIs, ex: *​*\ http://www.actingweb.net/miniapp1. The actor
or client requesting instantiation sends an http POST to the factory URI
with the following OPTIONAL application/json data:

::

  {
    “creator”: “username”,
    “passphrase”: “secret”,
    “trustee_root”: “uri”
  }

A special creator user, with the username and the passphrase given in
the request, MUST have full access to manage and access the actor through http basic
authentication. If “creator” is not supplied, “creator” MUST be the
default username. If “passphrase” is not supplied, the actor MUST generate
a random passphrase (it is returned in the response, see below); a fixed
default passphrase MUST NOT be used.

The 'trustee_root' value is a URI pointing to the root URI of an actor that
will act as a validator and manager of trust relationships for the new
actor. This is typically used when another actor is instantiating a new
actor to get access to some new functionality.

A mini-application MAY close its factory to such requests (for example
when actors are only created through an OAuth2 login). A closed factory
MUST answer a creation request with 403 Forbidden and create nothing.

A mini-application MAY require that no two actors have the same creator.
A creation request that names a creator another actor already holds MUST
then be answered with 403 Forbidden and create nothing. A creator value
the mini-application reserves for its own use MUST be answered with 400
Bad Request.

If the creation of a new instance was successful, a 201 Created MUST be
returned with the *Location* header set to the full root URI of the new
actor instance. The response body is an application/json object with the
new actor's ``id``, ``creator`` and ``passphrase``, and ``trustee_root`` when
one was set::

  {
    "id": "f81d4fae7dec11d0a76500a0c91e6bf6",
    "creator": "creator",
    "passphrase": "f0c5...generated...",
    "trustee_root": "https://trustee.example.com/app/9a1b..."
  }

The 201 and *Location* rule applies to API clients (a JSON request, or a
client that asks for JSON). A creation submitted from a browser form MAY
instead be answered with a page or a redirect, for example to the new
actor's web interface, or, when the form names a creator that already has
an actor, to a login page.

Except as above (a closed factory, a creator another actor holds, 403),
if the instantiation failed for a reason other than a temporary or server
problem (the input parameters, or the mini-application refusing to create
the actor), a 400 Bad Request MUST be returned. Temporary problems in
instantiating a new actor (for example a storage fault) SHOULD result in a
503 Service Temporarily Unavailable. Other server errors SHOULD result in
the 500 Internal Server Error return code.

**Reading the actor root**

An authenticated GET on the actor's root URI returns an application/json
object with the actor's ``id`` and ``creator``, and ``trustee_root`` when one
is set. The ``passphrase`` is included only when the request is made by the
creator or the trustee (see Using a Trustee To Manage Relationships); an
actor MUST NOT disclose its passphrase to a peer, of any relationship. A
browser that is not authenticated MAY be redirected to a login page.

Deleting Actor Instances
-----------------------------

An actor instance can be deleted with all its data by sending a DELETE
request to the root URI of the actor. The request MUST be authenticated
and only the creator, the trustee (see Using a Trustee To Manage
Relationships) or ‘admin' relationships are allowed to delete an actor
(see the section on trust relationships). Upon receiving a valid
DELETE, the actor SHOULD clean up its data, any 3\ :sup:`rd` party
webhooks, and stop responding to requests on and below its root URI. A
successful deletion MUST be answered with 204 No Content. A request that
does not authenticate as a caller allowed to delete the actor MUST be
refused (401 or 403) and change nothing. An
actor that cannot complete the deletion
now (a storage fault, or another deletion of the same actor still in
progress) SHOULD answer 503 Service Unavailable with a ``Retry-After``
header; a repeated DELETE then completes the deletion. If
the actor is deleted after being migrated to a newer version/new actor,
it MAY choose to respond with 301 Moved Permanently where the Location
header is set to the root URI of the new actor.

Endpoints
---------

ActingWeb actors communicate by sending http requests to each other on
pre-defined URI paths with pre-defined meanings and representations.
These messages can be sent over http/https or any other transport that
can support such exchanges.

The available endpoints are the most important structural elements of
the protocol specification. Any actor or client will expect another
actor implemented according to the ActingWeb specification to respond to
a certain set of paths right beneath the root URI of the actor. These
so-called endpoints have a defined purpose and use, and the use of http
methods and representations are specified in this document.

Below is a summary of the defined endpoints and a summary of their
purpose. Details on how to use these endpoints can be found later in
this specification in the Endpoints chapter, as well as separate
chapters for /trust and /subscriptions. Each of the OPTIONAL access
paths in the table below has a corresponding options tag (as found in
meta/actingweb/supported) with the same name as the path. I.e. if the
/www path is implemented, the meta/actingweb/supported options MUST
include “www” as an options tag.

.. list-table::
   :header-rows: 1
   :widths: 15 10 55 20

   * - **Endpoint**
     - **Status**
     - **Description**
     - **httpd methods**
   * - /meta
     - MUST
     - Meta-information about the actor and it's mini-application.
     - GET
   * - /properties
     - MUST
     - Simple, public data that the actor for simplicity would like to expose in a unified way to simplify read and write. The interface is RESTful where the URI specifies the property or the part of the property tree to operate on. The data are in simple attribute/value pairs.
     - GET, PUT, DELETE, and POST
   * - /actions
     - OPTIONAL
     - Actors may be able to execute actions that are not directly connected to data or resources, but where the action causes an external (maybe physical) event. A GET to an action returns status for the action, while a PUT or POST executes the action.
     - GET, PUT, POST
   * - /callbacks
     - OPTIONAL
     - This URI is used by the actor to receive callbacks: subscription callbacks (and the DELETE that ends a subscription), permission callbacks, and callbacks the mini-application defines for itself.
     - POST, DELETE (and any method a mini-application's own callbacks define)
   * - /resources
     - OPTIONAL
     - Any resources the actor wants to expose within a RESTful framework may reside here. The in and out representations can be freely defined by the mini-application. The URI path must specify the resource to operate on. GET MUST NOT change state; the other methods are the mini-application's (typically PUT changes, DELETE deletes and POST creates a resource). A resource the actor does not offer answers 404.
     - GET, PUT, DELETE, and POST
   * - /methods
     - OPTIONAL
     - Any RPC style web service that an actor wants to expose MUST be exposed under this path. There are no restrictions on how to use http methods or on representations. Thus, any RPC-type service (ex. SOAP, XMLRPC) can be exposed here. An http GET can thus give side-effects.
     - any
   * - /sessions
     - OPTIONAL
     - Session-based communication (bi-directional messages or streams) can have their own signalling and media/content protocols. Two actors may want to establish a two-way session over a time-period for communication that is not suited to do over the signalling or media protocols. The /sessions path is made for this purpose. Also, an actor implementing a session-protocol may want to allow http-based access to session data and/or actions. The /sessions path may implement websockets for bi-directional flows.
     - any
   * - /www
     - OPTIONAL
     - If the actor wants to expose a web application for human consumption, this path can be used. A special path /www/init MAY present a page for humans to initialise a newly instantiated actor.
     - GET and POST
   * - /subscriptions
     - OPTIONAL
     - Other actors use this endpoint to establish new subscriptions or check state of an existing. A POST to /subscriptions/<peerid> will create a new subscription and return the path to the newly created subscription in the Location header of the http response. A GET on the subscription returns status and pending diffs; a PUT clears diffs; a DELETE ends the subscription.
     - GET, POST, PUT, DELETE
   * - /trust
     - OPTIONAL
     - Other actors use this endpoint to create or remove relationships. A POST to /trust/trusttype will request the creation of a new relationship of type trusttype. The path to the new trust relationship is returned in the Location header.A DELETE to the trust URI will terminate the relationship. GET on the URI will send status information about the relationship (ex. approved, pending etc).
     - GET, PUT, DELETE, POST

The ``oauth`` and ``mcp`` option tags name capabilities, not paths under
the actor's root URI: an OAuth2 login (see /oauth) and an MCP server (see
/mcp) are located where the implementation chooses.

Agents
-----------------------------

Agents are actors that together with a proxy implement a
mini-application fully and according to the principles outlined in this
specification. Together, an agent/proxy pair MUST implement all
mandatory aspects of the mini-application. However, as opposed to the
actor, agents MAY be temporarily unavailable or accessible only through
an actor acting as a proxy for the agent. For simpler functionality and
low-powered devices, a client can instead be used. It can be as simple
as just holding credentials that allow updating values, e.g. posting GPS
coordinates once in a while through a POST.

Proxies
-----------------------------

A proxy is an actor that implements /meta, /properties, /trust, and
/subscriptions according to the definition of a mini-application, and
that has a special proxy relationship with an agent that is just
partially available to other actors. Together, the proxy and the agent
MUST implement the mini-application fully. These two actors, the proxy
and the agent, together form a pair representing the same entity or
data. The proxy MUST be available to other actors on the Internet
through a URI (or on a meaningfully defined private network), while the
agent can be intermittently unavailable and will typically only
communicate with its proxy. They MUST have a two-way trust relationship
of the type proxy.

An important characteristics of a proxy is that it MAY be implemented
totally generically for any type mini-application and only needs a
configuration that defines the /properties endpoint to respond to. In
this case, all other endpoints like /actions, /resources etc will just
be proxied to its agent. However, a proxy MAY implement more
mini-application specific functionality to offload from the agent or if
it otherwise makes sense.

A paired proxy and the agent SHOULD have implicit subscriptions to each
others /properties access paths in order to synchronise their
/properties data.

**Being a Proxy For Endpoints Proxied To The Agent**

A proxy MAY implement endpoints on behalf of the proxy/agent pair. These
MUST be implemented just like any other actor. However, a proxy MAY also
implement endpoints that are proxied to the agent that is not available
directly. Such a request to a path like /actions/dosumthin MUST give a
http 307, Temporarily Moved. This indicates to the requestor that this
is a proxy, and that the request should be sent as a subscription
creation request to /subscriptions using the path as target (target =
actions, sub-target=dosumthin) and with the parameter “proxied” set to
true in the payload. If the proxy sees a subscription request with the
parameter proxied set to true, it MUST treat the “data” element of the
payload in the subscription request as the original payload to the
endpoint, and thus forward this payload to the agent when forwarding.

Endpoints
==========

/meta (MUST)
-----------------------------

Each actor has a set of meta-information used to facilitate effective
discovery communication and is optionally a part of trust establishment
if the requesting actor wants to validate that a given URL for an actor
actually points to an actor of a certain and/or version. The
meta-information can be found under the /meta path directly below the
root URI of the actor. The http GET method is readable without a trust
relationship. OPTIONAL paths that are not supported MUST result in 404
Not found.

These are the paths available. Every scalar path (all but ``/meta``,
``/meta/trusttypes`` and ``/meta/actingweb/trust_types``) returns 200 OK with
a ``text/plain`` body.

.. list-table::
   :header-rows: 1
   :widths: 25 10 65

   * - **Path**
     - **Status**
     - **Description**
   * - /meta/id
     - MUST
     - The id of the actor and is identical to the id embedded in the actor's root path.
   * - /meta/type
     - MUST
     - Returns mini-application type in a 200 OK with a one-line text/plain body containing the urn type of the mini-application.
   * - /meta/version
     - MUST
     - Returns the version of the mini-application (the application, not this specification) in a
       200 OK with a one-line text/plain body. The value is a version string chosen by the
       mini-application; it SHOULD be a dotted version such as ``a.b`` or ``a.b.c`` and MAY carry a
       pre-release or build suffix (``2.1.0rc1``). A peer MUST NOT assume each part is a single digit.
   * - /meta/desc
     - MUST
     - Returns a human-readable description of the actor. The description MAY be based on a
       mini-application template, where information about this actor instance is substituted (for
       example its id). Ex. "This actor allows deposits and withdrawals on Bob Bobson's account
       #1234556 in the Bank of Lutitia".
   * - /meta/info
     - OPTIONAL
     - Returns a 200 OK with a one-line text/plain body containing the URI of a general
       human-readable web page about the mini-application.
   * - /meta/specification
     - OPTIONAL
     - Returns a 200 OK with a one-line text/plain body containing a URI where the
       mini-application's definition (see Mini-application definition) can be found, or an empty
       body when none is published.
   * - /meta/trustee_root
     - OPTIONAL
     - Returns a 200 OK with a one-line text/plain body containing the actor's trustee root URI
       (see Using a Trustee To Manage Relationships), or an empty body when none is set.
   * - /meta/actingweb/version
     - MUST
     - Returns a 200 OK with a text/plain body containing the version number of this
       specification that the mini-application supports, i.e. ``1.5``. A peer MUST NOT refuse to
       interoperate with an actor because the version it announces is higher (or lower) than its
       own, and SHOULD decide what to use from the option tags, not from the version.
   * - /meta/actingweb/supported
     - MUST
     - Returns a 200 OK with a text/plain body with a comma-separated list of tags identifying the
       supported OPTIONAL options found in this specification: option1,option2 See the Option tags
       section earlier in this document. An empty list means that only the mandatory requirements in
       this specification is supported.
   * - /meta/actingweb/formats
     - OPTIONAL
     - Returns a 200 OK with a text/plain body with a comma-separated list of the data formats the
       actor accepts and returns: e.g. ``json`` or ``json,xml``. The list MAY include the mandatory
       ``json``. The format name MUST be the standardised mime-type file extension. Only formats with
       standardised mime-types are allowed. An actor that accepts urlencoded form data (for example
       from a browser form) is not required to list it.
   * - /meta/raml
     - OPTIONAL
     - A mini-application MAY choose to represent the mini-application through a RAML file
       (`http://raml.org <http://raml.org>`__) Returns a URI to where the RAML file is found.
   * - /meta
     - OPTIONAL
     - Returns a 200 OK with an application/json body: one flat JSON object with an element for
       each scalar path above. The elements are named ``id``, ``type``, ``version``, ``desc``,
       ``info``, ``specification``, ``trustee_root``, and, for the ``/meta/actingweb/`` paths,
       ``aw_version``, ``aw_supported`` and ``aw_formats``. An actor MAY add ``aw_trust_types``, the
       list of the names of the trust relationship types it offers. Example::

         {
           "id": "f81d4fae7dec11d0a76500a0c91e6bf6",
           "type": "urn:actingweb:domain.com:mytestapps:app1",
           "version": "0.1",
           "desc": "Some description of this actor",
           "info": "https://domain.com/mytestapps/app1",
           "specification": "",
           "trustee_root": "",
           "aw_version": "1.5",
           "aw_supported": "option1,option2",
           "aw_formats": "json",
           "aw_trust_types": ["associate", "friend", "admin"]
         }

       Note that elements (both OPTIONAL and MUST), but empty, MAY be left out or returned as empty
       elements. A peer SHOULD accept an element it does not know and ignore it.
   * - /meta/trusttypes
     - OPTIONAL
     - Returns a 200 OK with an application/json body listing available trust relationship types
       and the default type. Useful for SPA clients to present trust type options during OAuth2
       authorization. Example::

         {
           "trust_types": {
             "friend": {"display_name": "Friend", "description": "Standard access"},
             "admin": {"display_name": "Admin", "description": "Full administrative access"}
           },
           "default_trust_type": "friend"
         }

   * - /meta/actingweb/trust_types
     - OPTIONAL
     - Returns a 200 OK with an application/json array describing each trust relationship type
       the actor offers, one object per type with at least ``name`` and ``description``, and
       optionally ``display_name`` and ``created_by``. Example::

         [
           {"name": "friend", "display_name": "Friend", "description": "Standard access",
            "created_by": "system"}
         ]

   * - /meta/
     - --
     - All other meta paths are reserved for future use. An implementation MAY serve further
       paths below ``/meta``; a peer MUST NOT depend on a path not defined here.


/properties (MUST)
-----------------------------

Quick interactions between actors are important in ActingWeb. The
/properties access path facilitates easy read and write of simple data.
If you need to read and write more complex data structures or XML
documents, you can use the access paths /resources (for RESTful access
to data) or /methods (for RPC-style access like SOAP and XMLRPC).

The /properties path is meant to contain the basic, most important data
for the actor's functionality. Most often a newly instantiated actor
needs some properties set before proper functioning. However,
/properties is not for static configurations only, but also for dynamic
data. This implies that the actor MUST use current /properties data in
its execution (and not treat them as a configuration file).

The /properties path supports the http methods GET, PUT, DELETE, and
POST. The requests can be unauthorised or authorised through a trust
relationship by presenting credentials in the Authorization header of
the http method. A PUT MUST name an attribute: a PUT to /properties itself
MUST be answered with 405 Method Not Allowed.

All attributes under /properties MUST be writable by the admin role.

**Attribute/value pairs**

The properties that can be stored under /properties are untyped, UTF-8
encoded attribute/value pairs. The semantics of the attribute/value pair
(as defined in the mini-application definition) must be used to convert
representations into their specific types, for example a
string-representation of an integer ("1234") into the integer value
1234.

The below table shows the relationship between the attribute name, it's
value, and the URI where the value is stored.

+-----------------+-------------+-----------------------------------------------------------+
| **Attribute**   | **Value**   | **URI to attribute**                                      |
+-----------------+-------------+-----------------------------------------------------------+
| **name**        | Alice       | http://www.actingweb.org/app/78hjh76yug/properties/name   |
+-----------------+-------------+-----------------------------------------------------------+

Note that to facilitate use of proxies, actors MUST NOT apply any logic
or process on semantics when a property is changed using PUT or POST.
Syntax SHOULD be checked. This implies that any processing logic in an
actor using /properties values must assume that the values can be
semantically invalid or even harmful and must do error handling
accordingly. The rule binds the protocol, not the mini-application: a
mini-application MAY validate, transform or refuse a write to an attribute
it defines. A refused PUT is answered with 400 Bad Request and changes
nothing (a caller without access gets 401 or 403, as below); for a POST
see below. What the
actor stored, after any such transformation, is what a later GET returns
and what a subscription diff carries.

A mini-application MAY choose to support the value for each attribute as
either a blob or a json structure. A GET on /properties MUST return a proper
application/json document with all the attribute value pairs. A
mini-application MAY also support targeting nested json structs in the
path, i.e. /properties/address/street/number, but MUST not assume that
such support is present in peer actors. Such support SHOULD be announced
as an options tag, *nestedproperties*.

**GET**

GET methods are used to retrieve properties. A GET can be done for a
specific attribute or for the whole set of attributes. A successful GET
MUST be answered with 200 OK.

The content type follows one rule. A GET of the whole set of attributes,
of a list property, or of a value that is a JSON document (an object, an
array, a number, a string in JSON quotes, ``true``, ``false``, ``null``) is
answered with ``application/json``. A GET of a single value that is not a
JSON document (plain text as it was written) is answered with
``text/plain`` and the text as the body. Example::

  GET /app/78hjh76yug/properties/firstname

  200 OK
  Content-Type: text/plain; charset=utf-8

  Alice

A GET for an empty /properties (i.e. no attribute/value pairs set) MUST return
a 200 OK with an empty JSON object ``{}``. A GET for a non-set attribute MUST
result in a 404 Not Found from the actor.
If the attribute is not accessible without a trust relationship,
a 401 Unauthorised MUST be returned. If the request's current trust
relationship is not sufficient, a 403 Forbidden MUST be returned.
A GET of the whole set of attributes (or of an attribute that holds
nested values) is not refused because the caller may not read some of
them: the actor MUST leave out the names (and the nested parts) the caller
may not read and answer 200 OK with the rest (a single value the actor
cannot filter, for example one nested too deeply to inspect, MAY instead be
refused with 403). A mini-application MAY also treat an attribute it
chooses not to reveal to a caller as not set (404).

If the actor supports list properties (see *listproperties* option tag), the
GET /properties endpoint supports two optional query parameters: ``format``
and ``metadata``. These parameters are mutually exclusive; using both in the
same request MUST return 400 Bad Request.

**Default response** (same as ``?format=short``):

Simple properties are returned as key-value pairs or dictionaries. List properties are
included as markers with ``_list`` and ``count`` fields::

  GET /app/78hjh76yug/properties

  {"name": "Alice", "age": "30", "notes": {"_list": true, "count": 2}}

**Full format** (``?format=full``):

Simple properties are returned as-is. List properties include items,
description, and explanation::

  GET /app/78hjh76yug/properties?format=full

  {
    "name": "Alice",
    "notes": {
      "_list": true, "count": 2,
      "description": "Personal notes",
      "explanation": "Store notes and reminders",
      "items": [{"id": "1", "content": "Remember to call"}, ...]
    }
  }

**Metadata only** (``?metadata=true``):

Returns structural metadata without property values. Useful for discovering
property names and sizes::

  GET /app/78hjh76yug/properties?metadata=true

  {
    "simple": {
      "properties": ["name", "age"],
      "total_bytes": 1234
    },
    "lists": {
      "notes": {"count": 2, "total_bytes": 2048, "description": "...", "explanation": "..."}
    }
  }

A list the actor cannot read (for example because its stored form is
damaged) MAY be reported in any of these responses by an object with an
``error`` member in place of its entry, or the actor MAY answer the whole
request with an error status (409 Conflict for a damaged list, 503 Service
Unavailable for a temporary fault). Implementations MAY add further
members to a list's entry or metadata (for example ``"_list": true`` in the
metadata response); a client MUST ignore members it does not know.

**PUT**

The PUT method is used to add or change an attribute/value pair. A PUT
to an existing attribute will change the value of that attribute.

All actors MUST accept PUT requests to change a specific element.
Successful change of the value MUST result in a 204 No Content response.

::

  Example:

  PUT /app/78hjh76yug/properties/firstname

  Alice

  204 No Content

An actor MAY accept a PUT to any attribute name. A mini-application that
refuses a name or a value MUST answer 400 Bad Request and change nothing.
If the attribute is not writable without a
trust relationship, a 401 Unauthorised MUST be returned. If the
request's current trust relationship is not sufficient, a 403 Forbidden
MUST be returned.

A PUT body can be of type application/json and MAY be stored as a blob
by the mini-app, however, it MAY support nested json and thus MAY also
support PUT /app/78hjh76yug/properties/people/person1/firstname. A nested
PUT changes the named part of the stored JSON object and keeps its other
parts. When the stored value has no parts to change (it is text, an array
or a scalar), the actor MUST answer 409 Conflict and change nothing.

**POST**

The POST method is used to add or change a collection of attribute/value
pairs. Only the /properties root endpoint MUST support POST. Content
type application/json MUST be supported and
application/x-www-form-urlencoded MAY be supported if the application
supports web-based interactions.

The attributes in a POST are applied one by one, each as an independent
write: a POST is not atomic. A successful POST MUST be answered with
201 Created and an application/json body naming the attributes that were
written (with their values; for an attribute that created a list, the
value is not defined). An attribute the mini-application refuses MAY be
skipped while the others are applied; when every attribute was skipped
(none was written), the actor MUST answer 403 Forbidden. When a write
stops part way (an attribute with an invalid name or value, 400 Bad
Request; a name collision, 409 Conflict; a value too large to store, 413
Payload Too Large; a storage fault, 503 Service Unavailable), the
attributes written before it stay written, and their changes are reported
to subscribers as any other write.

::

  Example:

  POST /app/78hjh76yug/properties

  {"firstname": "Alice", "lastname": "Smith"}

  201 Created

  {"firstname": "Alice", "lastname": "Smith"}

If any of the attributes are not writable without a trust relationship, a
401 Unauthorised MUST be returned. If the request's current trust
relationship is not sufficient for one or more of them, a 403 Forbidden MUST
be returned and nothing written.

A POST to a single name (``POST /properties/<name>``) is defined only for
a list property, where it appends an item (see List Property POST); for
any other name the actor MUST answer 400 Bad Request.

**DELETE**

A DELETE of a single attribute deletes it and MUST be answered with 204 No
Content. A DELETE of an attribute that is not set MUST also be answered
with 204 No Content; a DELETE of a nested path (/properties/a/b) that does
not exist in the stored value is answered with 404 Not Found. A DELETE of
/properties itself deletes every simple
attribute and MUST be answered with 204 No Content; list properties are not
deleted by it (each is deleted by a DELETE of its own name). A caller needs
delete access to every simple attribute for a DELETE of /properties; access
to the lists is not required.

**List Properties (OPTIONAL)**

In addition to simple attribute/value pairs, actors MAY support list properties
for storing ordered collections of items. List properties are useful when an
actor needs to maintain sequences of related data, such as notes, messages,
or history entries. Support for list properties SHOULD be announced using the
*listproperties* option tag in ``/meta/actingweb/supported``.

A list property differs from a regular property in that it contains an ordered
sequence of items rather than a single value. Each item in a list property
MAY be a simple value or a JSON object. Items are accessed by their zero-based
index position within the list: the second path segment, after the list's
name, addresses an item when it is a canonical non-negative integer (``0``,
``7``; not ``-1`` or ``01``) and the first segment names an existing list.
Any other second segment keeps the meaning it has for the name (a nested
key of a simple property, or ``metadata``, see List Property Metadata).
Access to an item, for every method, is decided on the list's name, as for
the list itself.

**List Property Creation**

A list property is created by a POST to /properties whose body names it with
the value ``{"_type": "list"}``, optionally with ``description`` and
``explanation`` members. The new list is empty. The 201 Created body names
the attribute; the value it gives there is not defined::

  POST /app/78hjh76yug/properties
  Content-Type: application/json

  {"notes": {"_type": "list", "description": "Personal notes"}}

  201 Created

An implementation MAY offer other ways of creating a list (for example a
form field in a web interface).

The following table shows the relationship between a list property, its items,
and the URIs where items are accessed:

+--------------------+---------------------+----------------------------------------------------------------+
| **List Property**  | **Item Index**      | **URI to item**                                                |
+--------------------+---------------------+----------------------------------------------------------------+
| **notes**          | 0                   | http://www.actingweb.org/app/78hjh76yug/properties/notes/0     |
+--------------------+---------------------+----------------------------------------------------------------+
| **notes**          | 1                   | http://www.actingweb.org/app/78hjh76yug/properties/notes/1     |
+--------------------+---------------------+----------------------------------------------------------------+

**List Property GET**

A GET request to a list property MUST return the complete list of items as a
JSON array. The response MUST be a 200 OK with content type application/json::

  GET /app/78hjh76yug/properties/notes

  [
    {"id": "1", "content": "Remember to call", "created": "2025-01-15T10:30:00Z"},
    {"id": "2", "content": "Buy groceries", "created": "2025-01-15T14:00:00Z"}
  ]

A GET request MAY include a ``format`` query parameter to control the response
format:

- ``format=full`` (or no format parameter): Returns the complete list of items as
  a JSON array (default behavior).
- ``format=short``: Returns only list metadata without items. This is useful for
  efficiently checking list size and properties without transferring all items::

    GET /app/78hjh76yug/properties/notes?format=short

    {
      "_list": true,
      "count": 2,
      "description": "Personal notes",
      "explanation": "Store notes and reminders"
    }

A GET request to a specific item index MUST return that item only. If the index
is out of range, a 404 Not Found MUST be returned::

  GET /app/78hjh76yug/properties/notes/0

  {"id": "1", "content": "Remember to call", "created": "2025-01-15T10:30:00Z"}

If the list property does not exist, a 404 Not Found MUST be returned. If the
list property exists but is empty, a 200 OK with an empty array ``[]`` MUST be
returned. Authorization requirements are the same as for regular properties.

**List Property and Regular Property Namespace**

Property names and list property names share the same namespace under
``/properties``. An actor MUST NOT allow both a regular property and a list
property to exist with the same name. Attempting to create a list property when
a regular property with that name exists MUST result in a 409 Conflict error.
Similarly, attempting to write a regular property (by PUT, by a nested PUT,
or as an attribute of a POST) when a list property with that name exists MUST
also result in a 409 Conflict error. In both cases nothing is written under
that name. This ensures namespace exclusivity and prevents ambiguity in
property access.

**List Property POST**

A POST request to a list property appends a new item to the end of the list.
The request body MUST contain the item to be added. A successful append MUST
return 201 Created. The response SHOULD include a Location header pointing to the
newly created item (an absolute or a relative URI); the index in it is the
position the append took, which under concurrent appends need not be the
length the client read before::

  POST /app/78hjh76yug/properties/notes
  Content-Type: application/json

  {"id": "3", "content": "New note", "created": "2025-01-16T09:00:00Z"}

  Response: 201 Created
  Location: /app/78hjh76yug/properties/notes/2

**List Property PUT**

A PUT request to a specific item index replaces that item with the new value.
If the index does not exist, the actor MAY create it (if the index equals the
current list length) or MUST return 404 Not Found (if the index is beyond the
list length)::

  PUT /app/78hjh76yug/properties/notes/0
  Content-Type: application/json

  {"id": "1", "content": "Updated note content", "created": "2025-01-15T10:30:00Z"}

  Response: 204 No Content

A successful item PUT MUST return 204 No Content, as a PUT of a property does.
Paths and answers defined here are those of the path-addressed forms; an
implementation MAY offer other ways of addressing items (for example a query
parameter or a batch request), with answers of their own.

**List Property DELETE**

A DELETE request to a list property MUST delete the entire list and all its
items. A successful deletion MUST return 204 No Content::

  DELETE /app/78hjh76yug/properties/notes

  Response: 204 No Content

A DELETE request to a specific item index removes that item from the list.
Subsequent items MUST be re-indexed to maintain a contiguous sequence::

  DELETE /app/78hjh76yug/properties/notes/1

  Response: 204 No Content

If the item index does not exist, a 404 Not Found MUST be returned.

**List Property Metadata**

Actors MAY support a ``/properties/{name}/metadata`` endpoint to manage
descriptive metadata about a list property. This endpoint is useful for clients
that need to display or configure list property information.

GET ``/properties/{name}/metadata`` returns the metadata for a list property::

  GET /app/78hjh76yug/properties/notes/metadata

  {
    "name": "notes",
    "description": "Personal notes and reminders",
    "explanation": "Use this to store important notes",
    "count": 2
  }

PUT ``/properties/{name}/metadata`` updates the metadata. Only the ``description``
and ``explanation`` fields are writable; other fields such as ``name`` and
``count`` are read-only::

  PUT /app/78hjh76yug/properties/notes/metadata
  Content-Type: application/json

  {
    "description": "Updated description",
    "explanation": "Updated explanation"
  }

  Response: 204 No Content

The metadata endpoint requires the same authorization as the property itself.
A 404 Not Found MUST be returned if the list property does not exist.

/actions (OPTIONAL)
-----------------------------

Choosing between the /actions or other endpoints like /methods and
/resources cannot be done according to clear-cut rules, but each
endpoint has some restrictions that may or may not suit what you are
trying to accomplish and the one matching what you are trying to do, is
the best.

The /actions path is dedicated to operations or actions that not only
changes the state of a resource or updates a database, but where
triggering the action actually does something outside the actor. An
example may be a video recorder where its actor can be requested to
record on a specific channel at a specific time.

Any action below the /actions path (ex. /actions/record) MUST respond to
POST. This will create or execute a new action. The data representation
to be used in the body of the POST is specific to the mini-application.
If the actor offers a callback functionality for status updates, the
callback URL should be included in the request data representation. The
/callbacks endpoint MAY be used by adding an element to the path, e.g.
/callbacks/actions.

A successful action MUST return a 2xx code: 200 OK when the action was
executed and its outcome is in the body, or 201 Created when the response
names a new action instance in a Location header (below). A request for an
action the actor does not offer MUST fail with a 4xx code (404 Not Found or
400 Bad Request). The body of the response
MAY contain a mini-application specific data representation detailing
the outcome of the action. The response MAY include a Location header
pointing to a URL representing the action requested (e.g.
/actions/record /3421433). This URL MUST respond to GET requests
containing a representation of the action status/progress. The data
representation is specified by the mini-application. If allowed, the
cancellation of an action SHOULD be available through a DELETE request
to the given location, while a PUT to the specific action URI MAY be
used to change the action while in progress (for example, temporarily
suspend a process).

/callbacks (OPTIONAL)
-----------------------------

When an actor is requesting subscriptions, actions, sessions or other
functions where a callback is required, the actor MUST create a new leaf
node under the /callbacks path. The URI MUST expect POST requests with a
data representation according to the requested path the callback was
established for. It is up to the mini-application to keep track of the
format expected for each callback by establishing sub-paths below
/callbacks, e.g. /callbacks/subscriptions/… to handle callbacks on
subscriptions and so on.

All requests to /callbacks from other actors or clients MUST be
authenticated using the shared secret as bearer token (*Authorization
Bearer xxxxxxx*). All /callbacks requests without authentication data MUST
return 401 Authentication required, regardless of the callback URI
exists or not, with the one exception below. Requests with authentication
data for a /callbacks URI that nothing on the actor handles MUST return 403
Forbidden. (A request that reaches a handler, which then declines it,
gets whatever answer the handler gives.)

The callbacks the protocol defines for a peer,
``/callbacks/subscriptions/{peerid}/{subscriptionid}`` and
``/callbacks/permissions/{peerid}``, MUST be accepted only from the peer the
path names, authenticated with that trust relationship's secret; anyone
else, the actor's creator included, MUST receive 403 Forbidden. A callback
for a subscription the actor did not make MUST receive 403 Forbidden.

The exception: an implementation MAY let a mini-application accept an
unauthenticated POST on a callback the mini-application names itself (for
example a webhook from a third-party service that cannot hold an
ActingWeb secret). Such a callback MUST be enabled explicitly, per name, by
the mini-application; it MUST NOT be enabled for the subscription or
permission callback paths, for every name at once, or for any method but
POST; and the mini-application MUST then authenticate the caller by its own
means (for example a signature or a shared secret in the request), since
the actor knows nothing about it. An implementation MAY bound the size of
such a request (413 Payload Too Large). Every other unauthenticated request
to /callbacks still answers 401.

Differentiating between various types of callbacks and authentication
SHOULD be done be adding a path to callbacks/, e.g.
callbacks/{callback\_type}.

A successfully received POST MUST result in a 204 No Content or 200 Ok
(with content). For a subscription callback, a 2xx tells the sender only
that the callback was received; it does not clear the diff (see Clearing
Callback Status).

::

  Example of a callback:

  1. Actor B is interested in actor A's /properties and establishes a
    subscription on actor A's /properties. A callback is established by B
    on : <rooturiB>/callbacks/subscriptions/<actorAid>/afb343f3edfe
  2. Actor A's /properties/firstname changes and it uses B's callback
    URI to notify about the change

  Actor B thus receives a POST request on its callback URL (Actor B’s root
  URI is
  http://www.actingweb.net/myapp/f81d4fae-7dec-11d0-a765-00a0c91e6bf.
  Actor A’s id is 9f1c331a3e3b5cf38d4c3600a2ab5d54:

  POST
    http://www.actingweb.net/myapp/f81d4fae-7dec-11d0-a765-00a0c91e6bf/callbacks/subscriptions/9f1c331a3e3b5cf38d4c3600a2ab5d54/afb343f3edfe
    Authorization: Bearer <shared secret>
    Content-Type: application/json

    {
      "id": "9f1c331a3e3b5cf38d4c3600a2ab5d54",
      "subscriptionid": "afb343f3edfe",
      "target": "properties",
      "sequence": 1,
      "timestamp": "2016-11-15T13:47:02.375880Z",
      "granularity": "high",
      "data": {"firstname": "Bob"}
    }

  204 No content

  Actor B receives the content in POST (in the case of /properties
  changes, the content is application/json) and can immediately identify
  this as a callback from actor A, as well as identify the specific
  subscription this is a callback for.

/resources (OPTIONAL)
-----------------------------

The /resources access path is reserved for an actor's exposure of
resources according to RESTful principles
(`http://en.wikipedia.org/wiki/Representational\_State\_Transfer <http://en.wikipedia.org/wiki/Representational_State_Transfer>`_).
The exposure of resources MUST follow the following rules:

-  Resources and sub-parts of a resources MUST be addressable by a URI
   where the path identifies the part of the resource that the request
   targets
-  GET requests MUST not change state
-  Any http method MAY be supported

Data representations and other decisions are up to the mini-application.
A request for a resource the actor does not offer MUST be answered with 404
Not Found. A POST that creates a resource SHOULD be answered with 201
Created.

/methods (OPTIONAL)
-----------------------------

The /methods access path is reserved for RPC (Remote Procedure Call)
methods like XML-RPC, JSON-RPC, SOAP, etc. The paths address methods and a GET
request MAY change state.

The intention of this path is to allow actors to expose
traditional/existing RPC-style methods and isolate such methods to avoid
unexpected state change through GET requests on other access paths.

::

  Example:

  POST /methods/persons/add
  Content-Type: application/json

  {"firstname": "Bob", "lastname": "Bobson"}

Whether a method reads its arguments from the request body, from query
parameters or from both is up to the mini-application; a client SHOULD
send arguments in the body unless the method's definition says otherwise.
There are no http response codes, data representations, or other
restrictions for this access path (an RPC protocol carried here, such as
JSON-RPC, MAY report its own errors inside a 200 OK).

/sessions (OPTIONAL)
-----------------------------

The /sessions access path is reserved for session-type communication
between two actors and will always have two parties. The purpose is to
enable two actors to create a way to share state and keep track of that
state over time. An actor can provide a session type by exposing the
session type right below the /sessions path, ex. /sessions/im to
identify im, instant messaging sessions. This location MUST respond to
POST requests by returning 201 Created with a Location header pointing
to a newly created session, ex.
/sessions/<requesting-actors-id>/fbe654aacef where fbe654aacef is a
session id uniquely identifying this session.

The POST request MAY have an application/json body containing a callback
URI that is URL-encoded (“callback”: “uri”). If not, the requesting
actor MUST respond to requests on the “mirrored” URL,
/sessions/<requested-actors-id>/<sessionid>, and the requested actor
MUST start sending session-related requests to this URL. If the session
creation fails, a 400 Bad request MUST be returned, or if the failure is
caused by a server problem, 500 Internal Server Error SHOULD be
returned.

Subsequent communication between the two actors SHOULD continue on the
returned new session URI and callback URIs using http methods and data
representations as specified by the actors' mini-applications.
Extensions may specify the http methods and data representations for
specific type sessions and it is RECOMMENDED that if such extensions
exist, the actors use the extension to facilitate session-type exchanges
between different types of mini-applications.

A DELETE request to the session URI MUST terminate the session and
return a 200 Ok. If there was a problem terminating the session, a 500
Internal Server Error SHOULD be returned.

Sessions may of course be established outside the ActingWeb actor
implementation. The actor MAY choose to expose on-going sessions on
other protocols through the /sessions path to allow simple signalling
and session updates without the explicit creation of the session as
described above. An example could be a SIP-based calling application
where an on-going session (for example an instant messaging session) can
be exposed through the URI /sessions/*SIP Call-Id*. This can for example
allow non-SIP actors to insert messages into the dialog.

/www (OPTIONAL)
-----------------------------

The /www access path is a special path as it is not meant for actor to
actor communication, but rather allows humans to interact with the actor
in a simple way. An actor may choose to expose a full web application
below this path.

The /www path does not have any particular restrictions except on
/www/init, see next section. A path below /www that the actor does not
serve MUST be answered with 404 Not Found. The pages are for the actor's
creator and SHOULD be served only to a caller authenticated as the creator
(by http basic authentication with the creator's username and passphrase,
or by any other means the implementation offers for the creator, such as an
OAuth2 login). An unauthenticated browser MAY be redirected to a login
page. A browser that requests the actor's root URI MAY likewise be
redirected to the actor's web pages or to a login page.

**/www/init**

If the /www/init path exists, it is intended to allow a newly created actor
to be initialised by a human being, for example with data in /properties.
What it presents is up to the mini-application. A form on it that posts
to /properties sends form data, so a mini-application offering such a form
MUST, in addition to application/json, support POST of form data to
/properties.

/oauth (OPTIONAL)
-----------------------------

An OAuth2 login lets a human sign in to a mini-application through a
3\ :sup:`rd` party OAuth2 provider (for example a mail or identity
provider) instead of with the creator's username and passphrase. Similar
to the /www endpoint, it assumes human interaction: an unauthenticated
browser is redirected to the provider's authorisation page and back.
How a mini-application then uses the provider's tokens on the user's
behalf (for example to expose /actions/message\_me, letting other actors
send text messages through the user's account) is up to the
mini-application.

The ``oauth`` option tag means that an OAuth2 login is available: a user
can sign in through an external OAuth2 provider to reach the actor that
user owns (and an implementation MAY create the actor at the first
sign-in). The login MUST handle the OAuth2 flow with a redirect back
where the code URL parameter is set. Where the login and its redirect
URI are served is implementation-defined: typically one URL at the
mini-application's root (for example actingweb.net/myapp/oauth/callback)
registered with the 3\ :sup:`rd` party OAuth service, which finds the actor
from the identity the provider returns, or from the state parameter of
the initial OAuth2 request. This specification does not define a
per-actor ``/oauth`` path; an implementation MAY offer one, and MAY offer
further OAuth2 endpoints (for example to let clients of the actor
authorise themselves), which are outside this specification.

/mcp - Model Context Protocol (OPTIONAL)
========================================

Overview
-----------------------------

ActingWeb actors MAY expose their capabilities through the Model Context Protocol (MCP) so that MCP clients can discover and use actor functionality.

Concept mapping between ActingWeb and MCP (a typical mapping, not a
requirement; how an implementation produces its MCP tools, resources and
prompts from the actor's functionality is implementation-defined):

- **Actions** (/actions) → **Tools** (operations with side effects)
- **Resources** (/resources) → **Resources** (data retrieval/streaming)
- **Methods** (/methods) → **Prompts** (templated interactions)

Normative Requirements
-----------------------------

If an actor supports MCP, the implementation MUST:

1. Provide a bridge that translates between ActingWeb semantics and MCP messages according to the MCP specification (transport and message framing follow MCP).
2. Enforce the actor’s trust and permission model for all MCP operations. Access is decided by the permission categories of the caller's trust relationship (see Permission Structure): ``tools`` for MCP tools, ``prompts`` for MCP prompts, and ``resources`` for MCP resources, the same grant that governs the ``/resources`` path. An MCP operation the caller's grant does not admit MUST be refused, whatever the REST access rules would allow on the corresponding path.
3. Only expose actions/resources/methods that the actor is explicitly configured to make available via MCP.
4. Resolve every MCP request to a specific actor before serving it. Where the transport keeps a session, the session is bound to one actor; where it does not, the actor is resolved from the credentials of each request. The mechanism for authentication and actor selection is implementation-defined.
5. Advertise MCP support with the ``mcp`` option tag in ``/meta/actingweb/supported``.

Transport and Endpoint Location
--------------------------------

This specification does not mandate a path or transport. Implementations MAY expose MCP over any MCP-compliant transport (e.g., WebSocket, Server-Sent Events, stdio, or others supported by MCP) and at any URL or connection point appropriate for the deployment.

Authentication and Actor Binding
--------------------------------

How a requester authenticates and how that identity maps to an actor is implementation-defined. Examples include OAuth2-based web authentication, session cookies, API tokens, or mutual trust credentials. Regardless of method, the authenticated principal MUST resolve to a single actor identity for the lifetime of the MCP session or, without a session, for each request.

Feature Exposure
----------------

Which actions, resources, and methods are exposed as MCP tools, resources, and prompts is selected by the mini-application (how is implementation-defined); functionality that was not selected MUST NOT be exposed through MCP. Implementations SHOULD support per-item descriptions and schemas to match MCP expectations, and MAY validate a tool's arguments against its schema before calling it (otherwise the tool itself is responsible for checking them).

Security Considerations
-----------------------------

1. **Consent and Scope**: Do not expose functionality through MCP without explicit configuration. Limit scope to least privilege.
2. **Access Control**: Apply the actor’s trust/permission rules to all MCP requests and responses.
3. **Rate Limiting**: Consider rate limits and resource usage safeguards for automated clients.
4. **Auditability**: Maintain logs sufficient to trace MCP interactions where appropriate.

Implementation Guidance (Non‑Normative)
---------------------------------------

- Deployments commonly offer a convenient connection point (for example, a web path like "/mcp"), but this is not required.
- Web transports (WebSocket/SSE) are frequently used in hosted environments; local tools may use stdio.
- Exposed tools/resources/prompts should include human-readable descriptions to aid client discovery.

Option Tags
-----------------------------

Actors supporting MCP MUST advertise the ``mcp`` option tag (see Option tags) so that clients can adapt accordingly.

/trust - Trust Relationships (OPTIONAL)
=======================================

Trust Model
-----------------------------

Trust relationships form the basis of interaction between actors and is
the primary reason for why accounts (with usernames and passwords) are
not necessary. Each actor only needs to know the relationships itself
has to other actors (with the exception of the creator user
credentials). The trust relationship credentials are then used in all
communication between the actors using existing methods for
authentication.

Each actor (agent or proxy) is responsible for its own set of trust
relationships with other actors. Each relationship is bi-directional
where one actor initiates a trust relationship that then needs to be
approved by the other actor. A mini-application can choose to implement
one-way trust levels if necessary for its application, but this is not
mandatory to implement. Each actor is responsible for storing and
recognising actors it has trust relationships with. Each trust
relationship has one out of a set of trust levels as defined in this
specification.

A newly formed actor has no trust relationships, and new relationships
are formed by requesting a trust relationship. The request is processed
by the actor and the request can be approved in real-time or at a later
time.

Once a trust relationship has been granted, the actor includes
authentication details in all subsequent requests through a bearer
token. Access to an actor's resources can thus be granted based on the
relationship.

Trust relationships are managed authoritatively by the actor that
granted the request, and a relationship can be revoked unilaterally at
any time by either the granting or accepting actor (see Deleting a Trust
Relationship for how each side learns of it).

This specification specifies how to use the http Bearer token method for
authentication after exchanging a shared secret as part of the trust
relationship creation. An optional verification process is also
specified to ensure that both actors can trust the authenticity of the
domain hosting the actor. Using https, the actors can mutually assure
that their root URIs are correct. However, this specification does not
specify how an actor decides on whether a given domain should be
trusted. Also, while the methods described here are sufficient for most
Internet-based applications, the specification does not provide methods
on a security level where each request's integrity can be assured.

Determining Which Relationship to Request
-----------------------------------------

The definition of the mini-application SHOULD contain information about
what type of access is given for each type of trust relationship. The
actor requesting the access will have some knowledge of the
mini-application in order to use it, however, it may be useful to
request a human-readable description for each trust relationship
directly from the actor. This information can be presented to a user to
determine if a given trust relationship is desired or to choose which
relationship type to request. A GET to the uri of the trust relationship
type + /desc MAY return such a human-readable description. Unlike the
/meta/desc description, the text may be generic for the
mini-application.

::

  Example:

  Request to server *​*\ https://actingweb.net/ GET
  /myapp/f81d4fae-7dec-11d0-a765-00a0c91e6bf6/trust/friend/desc

  200 OK

A friend can deposit and withdraw money as frequently as monthly, but
limited up to an amount of $100. A specific friend relationship will
also most likely establish an explicit limit at the requested amount.

Relationships and their data
-----------------------------

The 'creator' user and 'admin' relationship MUST allow the retrieval of
trust relationships through a GET to /trust. The content is
application/json. The list SHOULD be filterable by query parameters:
``relationship`` (the relationship type), ``peerid`` (the peer's id) and
``type`` (the peer's mini-application type, a ``urn:``), e.g.
``GET /trust?relationship=friend``. A GET on /trust/'relationship\_type'
MAY also be supported and filter on a specific relationship, but give the
same output; an actor that does not support it answers 404 Not Found. If no
relationships exist, a 200 OK with an empty array ``[]`` MUST be returned. A
404 Not Found MUST otherwise only be returned when a specific trust
relationship (by peer ID) does not exist.

The list response MUST NOT include the shared secret or the verification
token; those are read from the individual relationship URI (see Reading
Trust Relationship Data).

::

  Example:

  Request to server http://actingweb.net/
  GET /myapp/f81d4fae-7dec-11d0-a765-00a0c91e6bf6/trust?relationship=friend

  200 OK

  [
  {
    "verified": false,
    "peerid": "e41f4aae-4dee-10d0-b725-0af0a413bcf2",
    "relationship": "friend",
    "baseuri":
    "http://actingweb.net/myotherapp/e41f4aae-4dee-10d0-b725-0af0a413bcf2",
    "desc": "Test friend relationship",
    "peer\_approved": true,
    "type": "urn:actingweb:actingweb.org:gae-demo",
    "id": "f81d4fae-7dec-11d0-a765-00a0c91e6bf6",
    "approved": false
  },
  {
    "verified": true,
    "peerid": "testid",
    "relationship": "friend",
    "baseuri": "testurl",
    "desc": "Test friend relationship",
    "peer\_approved": true,
    "type": "urn:actingweb:actingweb.org:gae2-demo",
    "id": "f81d4fae-7dec-11d0-a765-00a0c91e6bf6",
    "approved": true
  }
  ]

'creator' and 'admin' MUST also be allowed to do a GET on a specific
relationship to retrieve its status. For the creator (and the trustee) the
status codes MUST be the same as the ones the peer of the relationship
gets for its own relationship (see Creation of a Trust Relationship): 200
OK when the relationship is approved, 202 Accepted while it is not, 404
Not Found when it does not exist. An 'admin' peer reading another peer's
relationship gets 200 OK when it is approved and 403 Forbidden while it is
not. The content differs only in the credentials: see Reading Trust
Relationship Data.

The fields below are MANDATORY in every representation of a relationship,
except ``secret``, which is present only where Reading Trust Relationship
Data says it is (never in the list). A relationship's representation
MAY carry further fields (for example when and how it was established, when
it was last used, or the peer's announced version and option tags; see
Further Fields below); a client MUST ignore fields it
does not know. The flags are JSON booleans in every response, including
the responses to the requests that create a relationship.

+------------------+-----------------------------------------------------------------------------------------------------------------+
| **Field**        | **Description**                                                                                                 |
+------------------+-----------------------------------------------------------------------------------------------------------------+
| id               | Actor id of the actor owning the relationship, i.e. MUST be the same as the actor identified in the request     |
+------------------+-----------------------------------------------------------------------------------------------------------------+
| type             | The urn: prefixed type of the peer in this relationship                                                         |
+------------------+-----------------------------------------------------------------------------------------------------------------+
| baseuri          | The root URI of the peer in the this relationship                                                               |
+------------------+-----------------------------------------------------------------------------------------------------------------+
| relationship     | The relationship type                                                                                           |
+------------------+-----------------------------------------------------------------------------------------------------------------+
| peerid           | The id of the peer. This is also embedded in the baseuri                                                        |
+------------------+-----------------------------------------------------------------------------------------------------------------+
| secret           | The shared secret to be used as bearer token                                                                    |
+------------------+-----------------------------------------------------------------------------------------------------------------+
| verified         | Bool that specifies if the remote peer has been verified as reachable on the baseuri                            |
+------------------+-----------------------------------------------------------------------------------------------------------------+
| approved         | Bool that specifies if this relationship has been approved                                                      |
+------------------+-----------------------------------------------------------------------------------------------------------------+
| peer\_approved   | Bool that specifies if this relationship has been approved by the peer                                          |
+------------------+-----------------------------------------------------------------------------------------------------------------+
| desc             | Human-readable description of the relationship                                                                  |
+------------------+-----------------------------------------------------------------------------------------------------------------+

Creation of a Trust Relationship
--------------------------------

When actor A wants to establish a trust relationship with B, it MUST
send a POST request (step 1 in table below) to B's /trust/<trustlevel>.
The request does not carry authentication and has an application/json
body. Actor B responds (step 2). If actor B through the request can
immediately approve the relationship, it MUST respond with 201 Created.
If actor B immediately can deny the request, a 403 Forbidden MUST be
returned. If the request is well-formed and actor B is ready and willing
to process the request, B MUST respond with 202 Accepted. In both cases,
the URL of the newly created relationship MUST be returned in the
Location header in the response. The URL MUST be formatted the following
way: /<baseuri-with-actor-id>/trust/<trustlevel>/<requesting-actor-id>.
The body of a 201 or 202 response is the new relationship's
representation (see Relationships and their data), as an application/json
object with boolean flags; while B has not approved the relationship, it
MUST NOT carry ``secret`` or ``verification_token``.

B MUST answer 400 Bad Request, and store nothing, when the request lacks
``baseuri`` or ``id``, when they are not a plain base URI and a plain actor
id, or when the relationship type in the URL is reserved (see Types of
Relationships). The requesting actor MUST send ``secret``, ``baseuri``,
``id`` and ``type``, but B MAY accept a request without ``secret`` or
``type``; a relationship requested without a secret cannot be verified and
so cannot be approved automatically.

If actor B already holds a verified or approved relationship with the
requesting actor, the request MUST NOT replace it. B MUST accept it only as
a re-pair from the requesting actor itself, authenticated with the current
shared secret as bearer token, and then only replace the secret (an
implementation SHOULD make the replacement conditional on the relationship
still holding the secret the request authenticated with); the relationship, its
approval and the base URI stay, and the response follows the stored
approval (201 or 202). Otherwise B MUST answer 403 Forbidden and change
nothing. B MUST treat a new relationship as verified only when the
verification succeeds and the requesting actor's base URI serves its claimed
id (its ``/meta`` ``id``). (A relationship B stored without verifying it, and has not
approved, MAY be replaced by a request that verifies, and is not re-paired.)
B MUST NOT approve a relationship automatically unless it verified. B MAY
also refuse a manual approval of a relationship it has not verified, after
repeating the verification (a request filed under another actor's id, with
that actor's base URI, holds a secret only its requester knows, which the
real actor's host does not answer to). Until B approves a relationship, B
SHOULD grant the requesting actor no access beyond the relationship's own
URL (its status and its deletion; never its verification token), unless the
relationship type is one B allows unapproved (see the associate
relationship). A verification proves that
the requesting actor controls its base URI, not that it is the actor whose
id it claims: actor ids are self-asserted, and the requesting actor answers
its own ``/meta``.

If the requested actor wants to do a verification of the requesting
actor, it MUST use baseuri, id, secret, and verify attributes to do a
GET request to <baseuri>/trust/<trustlevel>/<requested-actor-id> using
the secret as the Bearer token in the Authorization header. If the
requesting actor supports verification, it MUST accept a GET request to
this "reverse" URL, verify the shared secret, and then return the same
secret as sent in "verify" as part of the trust relationship request, in
the ``verification_token`` attribute (named ``verificationToken`` in
versions of this specification before 1.5; an actor MUST use
``verification_token``). If verification is not supported, the
regular trust relationship attributes should be returned in
application/json content.

The relationship that answers a verification is the one the requesting
actor created, approved, before it sent its request (a ``200 OK``, see
Verification below). A MUST NOT return the verification token from a
relationship it has not approved, and B MUST NOT treat a verification as
successful when the answering relationship is not approved (a ``202``, or
``approved`` false). Otherwise a third party could file a request at B
under A's id and a second request at A under B's id with the same secret:
each actor's verification would read the relationship the third party
filed at the other.

B will later try to notify A about an approved trust relationship at the
reverse URI /<requestor-id>/trust/<trustlevel/<requested-actor-id>, or a
GET poll to the relationship's URL can be used to retrieve status.

The defined attribites to include in the POST request:

+-----------------+------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| **Attribute**   |            | **Description**                                                                                                                                                                                                                                                                                            |
+-----------------+------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| **secret**      | MUST       | Value is the shared secret that actor A will use when authenticating with actor B and the other way around. The requesting actor needs to supply the secret in order for the requested actor to verify the requesting actor.                                                                               |
+-----------------+------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| **baseuri**     | MUST       | The base URI of the requesting actor (with id).                                                                                                                                                                                                                                                            |
+-----------------+------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| **id**          | MUST       | The id of the requesting actor.                                                                                                                                                                                                                                                                            |
+-----------------+------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| **type**        | MUST       | The urn: type of the mini-app.                                                                                                                                                                                                                                                                             |
+-----------------+------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| **desc**        | OPTIONAL   | Human-readable description that explains what the relationship is meant for. Should be phrased to allow a human to evaluate whether to approve or reject the request and later to recognise what the relationship is doing. Ex. "Service subscription of monthly $29.95 for the Geekly Review magazine."   |
+-----------------+------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| **verify**      | OPTIONAL   | The value should be a secret that is used to verify the baseuri and the authenticity of the requestor.                                                                                                                                                                                                     |
+-----------------+------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+

::

  Example:

  Request to server `*http://actingweb.net/* <http://actingweb.net/>`_

  POST /myapp/f81d4fae-7dec-11d0-a765-00a0c91e6bf6/trust/friend

  {
    "secret": "8f4e4e86f249599c4be21aa4445065d4e6905cd4",
    "baseuri": "http://myserver.org/app2/e41f4aae-4dee-10d0-b725-0af0a413bcf2",
    "id": "e41f4aae-4dee-10d0-b725-0af0a413bcf2",
    "type": "urn:actingweb:actingweb.net:myapp",
    "desc": "A friend relationship between actors from myapp and myotherapp",
    "verify": "66b6691aae69fb75919e754976a8e2eb6d2719ac"
  }

  202 Accepted

It is RECOMMENDED to use https in this POST exchange as this will
protect the shared secret from eavesdropping. Using http SHOULD be
reserved for trust requests between actors in a controlled environment
like inside an IPsec tunnel where eavesdropping can be ruled out.

After the initial request and response, the URI location of the new
trust relationship (i.e. as in the path in the example above) MUST
respond to GET requests as follows. If the request has not yet been
concluded or evaluated (B has not approved it), 202 Accepted MUST be
returned, with the relationship's representation (without its
verification token). If the relationship has been approved, 200 OK MUST be
returned. A refused relationship is deleted: B deletes it (see Deleting a
Trust Relationship), and a GET then answers 404 Not Found. Such GET
requests MUST be authenticated using the secret as a bearer token in the
Authorization header, thus ensuring that only actor A can request an
update of the status; another peer MUST receive 403 Forbidden for a
relationship B has not approved.

The below table shows an overview of the process where actor A creates a
trust relationship with Actor B (i.e. actor B trusts actor A).

+--------------------------------------------+-------------------------------------------------------------------------------------------------------+----------------------------------------------------------------------------------+
| **Step**                                   | **ACTOR A:                                                                                            | **ACTOR B: http://actingweb.net/myapp/f81d4fae-7dec-11d0-a765-00a0c91e6bf6**     |
|                                            | http://myserver.org/app2/e41f4aae-4dee-10d0-b725-0af0a413bcf2**                                       |                                                                                  |
+--------------------------------------------+-------------------------------------------------------------------------------------------------------+----------------------------------------------------------------------------------+
| **1. Request relationship**                | POST request to initiate request for trust relationship                                               |                                                                                  |
|                                            |                                                                                                       |                                                                                  |
|                                            | POST\ */myapp/f81d4fae-7dec-11d0-a765-00a0c91e6bf6/trust/friend*                                      |                                                                                  |
+--------------------------------------------+-------------------------------------------------------------------------------------------------------+----------------------------------------------------------------------------------+
| **2. Immediate response to request**       |                                                                                                       | POST response                                                                    |
|                                            |                                                                                                       |                                                                                  |
|                                            |                                                                                                       | | Returns http response to indicate acceptance or not:                           |
|                                            |                                                                                                       | | 201 Created, 202 Accepted, 403 Forbidden                                       |
+--------------------------------------------+-------------------------------------------------------------------------------------------------------+----------------------------------------------------------------------------------+
| **3. Polling for result (OPTIONAL)**       | Awaits B's processing; polls (200 approved, 202 pending, 404 refused).                                |                                                                                  |
|                                            | GET */myapp/f81d4fae-7dec-11d0-a765-00a0c91e6bf6/trust/friend/e41f4aae-4dee-10d0-b725-0af0a413bcf2*   |                                                                                  |
+--------------------------------------------+-------------------------------------------------------------------------------------------------------+----------------------------------------------------------------------------------+
| **4. Notification of result (OPTIONAL)**   |                                                                                                       | POST */trust/friend/f81d4fae-7dec-11d0-a765-00a0c91e6bf6*                        |
|                                            |                                                                                                       |                                                                                  |
|                                            |                                                                                                       | Sends the approval of the request in an application/json body:                   |
|                                            |                                                                                                       |                                                                                  |
|                                            |                                                                                                       | {                                                                                |
|                                            |                                                                                                       |                                                                                  |
|                                            |                                                                                                       |  "approved": true                                                                |
|                                            |                                                                                                       |                                                                                  |
|                                            |                                                                                                       | }                                                                                |
+--------------------------------------------+-------------------------------------------------------------------------------------------------------+----------------------------------------------------------------------------------+

**Accepting Or Rejecting A Request For Trust Relationship**

It is entirely up to the actor receiving the trust request to use
whatever methods or processes necessary to evaluate and conclude upon
the request. How this is done is outside the scope of this
specification. An actor may for example refuse to accept requests with
base uris that are not known by the actor and auto-approve requests from
other base uris. Criteria for accepting a trust relationship request
SHOULD be documented in the mini-application definition.

**Use of Callback To Verify**

A callback can be used for verification of requesting actor and for
notification of the result of the request. The table below shows on
overview of the steps involved. Only notification of result is shown as
polling was shown in the above section. The below section specifies in
detail how the verification is done.

+------------------------------------------+-------------------------------------------------------------------------------------------+-----------------------------------------------------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| **Step**                                 | **ACTOR A: http://myserver.org/app2/e41f4aae-4dee-10d0-b725-0af0a413bcf2**                |                                                           | **ACTOR B: http://actingweb.net/myapp/f81d4fae-7dec-11d0-a765-00a0c91e6bf6**                                                                                                             |
+------------------------------------------+-------------------------------------------------------------------------------------------+-----------------------------------------------------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| **1. Establish trust callback**          | Creates verification callback URI on /trust/friend/f81d4fae-7dec-11d0-a765-00a0c91e6bf6   |                                                           |                                                                                                                                                                                          |
+------------------------------------------+-------------------------------------------------------------------------------------------+-----------------------------------------------------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| **2. Request relationship**              | POST */myapp/f81d4fae-7dec-11d0-a765-00a0c91e6bf6/trust/friend*                           | POST request to initiate request for trust relationship   |                                                                                                                                                                                          |
+------------------------------------------+-------------------------------------------------------------------------------------------+-----------------------------------------------------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| **3.Verification of requesting actor**   |                                                                                           |                                                           | *GET <A baseuri>/trust/friend/f81d4fae-7dec-11d0-a765-00a0c91e6bf6*\ with the secret from step 2 as Bearer token; match "verify" from step 2 with the "verification_token" returned.     |
+------------------------------------------+-------------------------------------------------------------------------------------------+-----------------------------------------------------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| **4. Response to request**               |                                                                                           | Response to POST                                          | Returns http response to indicate acceptance or not:                                                                                                                                     |
|                                          |                                                                                           |                                                           | 201 Created, 202 Accepted, 400 Bad Request, 403 Forbidden                                                                                                                                |
+------------------------------------------+-------------------------------------------------------------------------------------------+-----------------------------------------------------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+

**Verification**

Whether to do verification is up to the requested actor B. Actor A's
provided baseuri parameter and Actor B’s id are used to create the
verification URI used in the above step 3 (it is A's URI:
<A baseuri>/trust/<trustlevel>/<B id>). If Actor A wants to provide
verification (because B's mini-application requires or recommends it),
it MUST, before sending the initial POST request, make sure that a GET
request to its 'baseuri'/'ownid'/trust/'trustlevel'/'actorB-id' will be
responded to with a 200 OK (step 1 in table above). The GET request MUST
be authenticated using the shared secret that actor A will send in the
POST request to B as bearer token, thus ensuring that only actor B can
request the URI.

::

  Example:

  Request to server `*​http://myserver.org/* <http://myserver.org/>`__ GET
  /app2/e41f4aae-4dee-10d0-b725-0af0a413bcf2/trust/friend/f81d4fae-7dec-11d0-a765-00a0c91e6bf6

  200 Ok

Note that by using https both in the initial trust creation and for the
verification, one can ensure that the root URIs of each of the actors
are authentic (through https session setup and certificate validation).
With appropriately loaded root certificates on each web server hosting
the actors, one can also selectively accept a group of servers and thus
actors. An actor may also choose to verify a trust relationship on
criteria or methods outside the scope of this specification.

**Notification of Result**

Once actor B has approved a relationship for which it returned a 202
Accepted to actor A when receiving the initial POST request, actor B MUST
send a POST request, authenticated with the shared secret as bearer token,
to the same URI used for verification with an application/json body
holding the JSON boolean ``true`` in ``approved``::

  {"approved": true}

A receives it and answers 204 No Content. Only an approval is notified
this way. A refusal is not: B deletes the relationship (see Deleting a
Trust Relationship), which A learns from that deletion or from a 404 Not
Found on its next GET.

**Updating a Trust Relationship**

The actor owning the trust relationship can update the relationship by
sending a PUT request to the relationship URI with a application/json
body with attribute/value pairs of the attributes that are to be
changed. The attributes that can be changed are ``baseuri``, ``desc``,
``approved`` and, where permission management is supported, ``permissions``
(see Permission Management API). ``approved`` accepts only the JSON
boolean ``true``, or the text ``true`` in form-encoded data (an approval
cannot be withdrawn by a PUT; a relationship is refused or ended by
deleting it): any other value MUST be answered with 400 Bad Request and
nothing changed. A successful PUT MUST be answered with 204 No Content.
The owning actor is its creator (or trustee); an 'admin' peer MAY also
manage the actor's relationships. A peer other than an admin peer MUST NOT
change the approval of its relationship or the permissions granted to it.

**Reading Trust Relationship Data**

'admin' relationships and the 'creator' user MUST be allowed to read the
trust relationship data through an authenticated GET to
/myapp/'actorid'/trust/friend/'friendid'. The shared secret and the
verification token are returned only to the creator (and the trustee) and
to the peer the relationship belongs to (to the peer, the verification
token only while the relationship is approved). An actor MUST NOT return
them to any other peer, an 'admin' peer included: with another peer's
secret, a peer could act as that peer. The list of relationships (a GET on
/trust) never carries them.

::

  Example:

  Request to server `*​http://actingweb.net/* <http://actingweb.net/>`__
  GET
  /myapp/f81d4fae-7dec-11d0-a765-00a0c91e6bf6/trust/friend/e41f4aae-4dee-10d0-b725-0af0a413bcf2

  200 OK

  {
    "secret": "66b6691aae69fb75919e754976a8e2eb6d2719ac",
    "verified": true,
    "peerid": "e41f4aae-4dee-10d0-b725-0af0a413bcf2",
    "relationship": "friend",
    "baseuri": "https://actingweb.net/myotherapp/e41f4aae-4dee-10d0-b725-0af0a413bcf2",
    "desc": "Service subscription of monthly $29.95 for the Geekly Review magazine. ",
    "peer_approved": false,
    "type": "urn:actingweb:actingweb.net:myotherapp",
    "id": "f81d4fae-7dec-11d0-a765-00a0c91e6bf6",
    "approved": true
  }

**Deleting a Trust Relationship**

A relationship is deleted by a DELETE on its URI, which MUST be answered
with 204 No Content when it is deleted and 404 Not Found when it does not
exist. Either side can delete it:

- When the owning actor's creator (or trustee, or an 'admin' peer)
  deletes a relationship, the actor MUST also delete the peer's side by a
  DELETE, authenticated with the shared secret, on the peer's URI for the
  relationship. If the peer cannot be reached, the actor MAY keep its own
  relationship and answer 502 Bad Gateway, so the deletion can be repeated;
  an implementation MAY offer its creator a way to delete only its own side
  (for a peer that no longer exists).
- When the peer deletes the relationship (its DELETE is authenticated with
  the shared secret), the actor deletes its own side only and does not call
  the peer back. A peer MAY delete a relationship the actor has not
  approved. A request MAY carry the query parameter ``peer=true`` to ask
  for the same local-only deletion.

Deleting a relationship SHOULD also end the subscriptions between the two
actors and remove the permissions granted to the peer.

**Further Fields**

An implementation MAY carry further fields in a relationship's
representation, for example metadata about a client that was given a
relationship through an OAuth2 login (its name, when it last connected).
Such fields are not defined by this specification; a client MUST ignore
fields it does not know.

**Verification and Approval**

There are two mechanisms for validating a trust requests. As seen in the 
above example, there are three attributes stored for each trust relationship:
*verified*, *peer_approved*, and *approved*. Verification is done as part of the initial
trust request where the receiving actor does a request back to the requesting actor
on the requesting actor's trust URL. The shared secret and a verification token are 
used as mutual authentication to verify that the two actors have a clear, trusted
communication channel.  The requesting actor is assumed to implicitly have verified
(or pre-verified, see below) the actor before sending a trust request and it's verified
is true as default.

The approval is an explicit mutual approval that can happen automatically based on some
criteria (including passed verification) or through an external process either through
a trustee or a human. The *approved* attribute is set when the local actor has approved,
*peer_approved* is set when the peer actor has approved the relationship.

Initiating a trust request
-----------------------------

In some cases it is necessary for an external actor or maybe the creator
to request an actor to initiate a trust relationship. This is done
through a POST request sent to <actorid>/trust with an application/json
body specifying the url of the actor to initiate with and the trust
level to request.

::

  Example:

  {
    "url": "https://actingweb.net/myapp/3973895dbe8457f68cdee59b0810d70a",
    "relationship": "friend"
  }

If successful, a 201 Created should be returned with an application/json
body equal to the body in a GET request to the location of the new
relationship. Also, a Location header with the newly created trust
relationship MUST be returned. A request without ``url``, or for a
reserved relationship type (see Types of Relationships), MUST be answered
with 400 Bad Request. When no relationship results from the exchange with
the peer (the peer cannot be reached, does not answer as an actor, or
refuses the request), the actor answers with an error status and keeps no
relationship; it MAY use 408 Request Timeout for every such failure, so a
client SHOULD treat any 4xx or 5xx as "not created".

The actor MAY choose to accept a *type* attribute as a mandatory type that
the actor responding to the URL should have. In any case, the actor MAY
implement a request to the peer actor to-be's /meta path to verify type,
response, and get information about actor capabilities.

Types of Relationships
-----------------------------

When a new relationship is requested by an actor, the relationship has a
type as specified in the URL path (i.e. /trust/friend/...). The actor
receiving the request supports a number of trust relationship types. The
mini-application's definition SHOULD define exactly what a 'friend'
relationship means in terms of access. For example, one mini-application
may allow 'friends' to update most of its properties, while another
mini-application may only allow 'friends' to read parts of the
properties.

In this section, a small number of relationship types are specified. It
is RECOMMENDED that mini-applications use these relationship types (and
fill them with own meaning), but only the ‘admin’ relationship type
(besides the 'creator' user) MUST be supported. If the mini-application
requires more relationship types, it MAY define new relationship types
and specify these in its definition. The guidelines for how to use the
specified relationship types should thus be used as a recommendation. It
is also conceivable that mini-applications allow actor instances to
dynamically change what each trust relationship gives access to. Such
dynamic access rights SHOULD be documented in the mini-application
definition, but is beyond the scope of this specification.

Below is an overview of the trust relationships. There are only three
regular trust relationships meant for access to mini-application
functionality/operations: associate, friend, and partner. The proxy and
admin relationships have special uses. An actor MUST NOT hold more than
one relationship with a given other actor (a repeated request from the
same peer is a re-pair, see Creation of a Trust Relationship).

The names ``creator``, ``trustee``, ``owner`` and ``any`` are reserved: they
name the creator, the trustee and roles in an actor's access rules, never a
peer. An actor MUST refuse a relationship of a reserved type (400 Bad
Request, on a request and on an initiation) and MUST NOT give a peer the
access of the creator or the trustee because of its relationship's name.
An actor MAY offer relationship types beyond those listed here (for
example a read-only ``viewer`` type, or a type for MCP clients), and MAY
accept a request for a type it has not defined, which then gives the peer
only what the actor's access rules give that name (often nothing).

+---------------------------------+------------+-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| **Regular relationship name**   |            | **Description**                                                                                                                                                                                                                                                                                       |
+---------------------------------+------------+-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| **associate**                   | OPTIONAL   | The lowest level of trust (apart from no relationship). An actor will likely have the most relationships of this type and it will normally give read access.                                                                                                                                          |
+---------------------------------+------------+-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| **friend**                      | OPTIONAL   | The friend relationship allows more access than for 'associates'. The friend actor has typically been verified to be friendly and can thus be allowed to write and/or request actions/methods.                                                                                                        |
+---------------------------------+------------+-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| **partner**                     | OPTIONAL   | A partner is more than a friend. A partner actor may be stronger verified than a friend and can be trusted to the most important properties and actions/methods of the actor.                                                                                                                         |
+---------------------------------+------------+-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| **proxy**                       | OPTIONAL   | A proxy actor MUST be of the same mini-application type. A subscription from the agent to the proxy on /properties SHOULD be set up to ensure that the the proxy's properties are up to date. If the proxy only is updated through a client and based on client POSTs/PUTs, this is not necessary.    |
+---------------------------------+------------+-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| **admin**                       | OPTIONAL   | The admin relationship has full access to an actor's data and functions similar to the creator user.                                                                                                                                                                                                  |
+---------------------------------+------------+-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+

**The Associate Relationship**

The associate relationship is the lowest relationship level. The rights
given to this relationship are dependent on the mini-application.
Validation of an associate may be limited as the damage an associate can
do should be very limited. Normally, an associate should not be able to
affect the operations of the actor beyond the scope of its own
relationship.

For example, a mini-application made to hold one person's contact
information may allow read access to the person's basic contact
information to anybody without a trust relationship, while an associate
may get access to the full business contact information. The associate
relationship can be used for creating networks of actors sharing
information. Ex. a two-way associate relationship between two actors
with contact information may allow a person to keep a real-time updated
address book if each actor subscribes to the others' contact information
of interest.

Use of the associate relationship MAY be allowed either unapproved (i.e.
no explicit approbal) or auto-approved (possibly in combination with
lists of pre-approved base URIs).

**The Friend Relationship**

The friend relationship is an intermediate step from associate to a
partner relationship. The friend actor should be trusted to affect the
basic operations of an actor. The validation before approving a new
relationship should thus be appropriate for such access. Ex. a friend
may be allowed to ask the actor to initiate a new trust relationship
with another contact information actor. This would allow a trusted
contact to introduce a new friend.

**The Partner Relationship**

The partner relationship is the most trusted level that gives access to
actor operations. The partner may be trusted access to some or most of
the inner workings of the actor. Ex. a partner may be allowed to update
the actor's contact information. This relationship can then be used to
implement synchronisation between different sources of a person's
contact information. In particular, more dynamic contact information
like presence can then be updated. If each presence source (like a
mobile phone's current profile or Messenger/AIM/Skype status) has an
actor representing the presence status, the contact information actor
can have partner relationships with each presence actor and allow
presence information to be consolidated in one place.

**The Proxy Relationship**

The proxy relationship is a reserved relationship between two actors of
the same mini-application type. A proxy relationship MUST always be
two-ways such that if one relationship fails, the other MUST be removed.
In a proxy relationship, the /properties access path SHOULD always be
synchronised through a one-way or two-way subscription (dependent on
application). These two subscriptions SHOULD be set up at the time of
creation of the proxy relationship. Once set up, the two actors act as
one entity to implement the mini-application's functionality. See also
the section on the proxy actor.

**The Admin Relationship**

The admin relationship has full access to all data and functions of an
actor. See also the section on trustees as an alternative to using an
admin relationship as this approach allows access to managing
relationships without getting full access to the actor.

An admin relationship can also delete an actor (take it completely out
of action). An admin peer does not receive what belongs to the creator and
the trustee: the actor's passphrase, another peer's shared secret, and the
right to change the trustee root or the creator (see Using a Trustee To
Manage Relationships). An admin peer keeps access only as long as its
relationship exists, and nothing it was given SHOULD outlive the
relationship.

**The Creator Special User**

The creator user is established at the point of instantiating an actor,
and can later be changed only by the creator or the trustee (see Using a
Trustee To Manage Relationships). The creator relationship has two primary
objectives:

-  other actors can instantiate a new actor and immediately administrate
   the new actor
-  the creator credentials can be either supplied by a human user when
   instantiating the actor or conveyed to a user and thus allow the user
   to initialise the actor using the /www/init form or the web front-end
   supplied by the actor at /www

The creator MUST have all access rights similar to the 'admin'
relationship. A creator is a user authenticated with username and
password, not a trust relationship. The default user name for a creator
is 'creator' unless another username is provided as part of the
instantiation of the actor. An implementation MAY also authenticate the
creator by other means, for example an OAuth2 login whose identity is the
creator's (see Authentication).

**Assigning Individual Rights To An Instance Of A Trust Relationship**

A mini-application MAY implement assigning of rights to a specific
instance of a trust relationship (i.e. rights per actor). This allows
granular access control. For example allowing home contact information
to be available to some actors, while others only get access to business
information.

**Permission Management API (RECOMMENDED)**

To support per-relationship permission customization, mini-applications
SHOULD implement the following API extensions to the /trust endpoint.
Actors supporting per-relationship permission management SHOULD include
``trustpermissions`` in their supported option tags returned by
/meta/actingweb/supported. This indicates support for:

* Enhanced trust relationship endpoints with permission query parameters
* Dedicated permission management endpoints (``/trust/{relationship}/{peerid}/permissions``)
* Per-relationship permission overrides that modify trust type defaults
* Standardized permission structures for interoperability

**Enhanced Trust Relationship Endpoint**

The GET /trust/{relationship}/{peerid} endpoint MAY support a 
``permissions`` query parameter to include permission override information:

GET /{actorid}/trust/{relationship}/{peerid}?permissions=true

If permission overrides exist for the relationship, the response SHOULD include
a ``permissions`` field containing the custom permission rules.

The PUT /trust/{relationship}/{peerid} endpoint MAY accept a ``permissions``
field in the request body to update permission overrides alongside standard
trust relationship properties.

**Dedicated Permission Management Endpoints (OPTIONAL)**

For applications requiring extensive permission customization, the following
endpoints provide dedicated permission management:

``GET /{actorid}/trust/{relationship}/{peerid}/permissions``
  Retrieve the permissions stored for a specific trust relationship, for
  managing them: the per-relationship override as stored (not merged with
  the defaults), or, when there is none, the default permissions of the
  trust type. The permission categories are members of the top-level
  object (not nested under ``permissions``), beside ``actor_id``,
  ``peer_id``, ``trust_type``, and ``is_custom`` and ``source`` to indicate
  permission origin; further members (who made the override, when, a note)
  MAY be present. A peer that wants its effective permissions uses the
  Permission Query Endpoint below, which merges them.

``PUT /{actorid}/trust/{relationship}/{peerid}/permissions``
  Create or update permission overrides for a trust relationship.
  Requires the trust relationship to exist.

``DELETE /{actorid}/trust/{relationship}/{peerid}/permissions``
  Remove permission overrides, reverting to trust type defaults.

On these endpoints, a relationship that does not exist, or whose type is
not the one in the path, MUST be answered with 404 Not Found. A GET for a
relationship whose type the actor does not define (it has no default
permissions to return) MUST also be answered with 404 Not Found, on this
endpoint and on the Permission Query Endpoint below.

Permission Query Endpoint (OPTIONAL)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Actors MAY provide an endpoint for peers to query what permissions they've been granted.
This supports proactive permission discovery, complementing the reactive callback-based
push mechanism.

``GET /{actorid}/permissions/{peerid}``
  Query what permissions the actor has granted to a specific peer.

**Authorization:**
  - A peer may query only its own permissions: it authenticates as
    ``{peerid}`` with its relationship's shared secret, whatever its
    relationship type
  - The actor's creator and an ``admin`` peer may query any peer's
    permissions
  - Any other caller receives 403, and so does a peer querying an id that
    is not its own, whether or not a relationship with that id exists
    (authorisation is decided before the relationship is looked up)

**Request:**

.. code-block:: http

   GET /{actorid}/permissions/{peerid} HTTP/1.1
   Host: example.com
   Authorization: Bearer {bearer_token}

**Response (200 OK):**

.. code-block:: json

   {
     "actor_id": "actor-uuid-123",
     "peer_id": "peer-uuid-456",
     "permissions": {
       "properties": {
         "patterns": ["notes_*", "profile/*"],
         "operations": ["read", "write"],
         "excluded_patterns": ["notes_private_*"]
       },
       "methods": {
         "allowed": ["sync_*", "get_*"],
         "denied": ["delete_*"]
       },
       "actions": {
         "allowed": ["refresh", "export"],
         "denied": []
       },
       "tools": {
         "allowed": ["search", "fetch"],
         "denied": []
       },
       "resources": {
         "patterns": ["data://*"],
         "operations": ["read"],
         "excluded_patterns": []
       },
       "prompts": {
         "allowed": ["*"]
       }
     },
     "source": "custom_override",
     "trust_type": "reader"
   }

**Response Fields:**

``source`` (string)
  Indicates the source of permissions:
  - ``"custom_override"`` for per-trust overrides merged with base trust-type defaults
  - ``"trust_type_default"`` for default permissions of the relationship type, as the actor defines it (no overrides exist)

When ``source`` is ``"custom_override"``, the permissions represent the full *effective*
permissions: base trust-type defaults merged with per-relationship overrides. This ensures
peers can accurately detect changes by comparing with their cached copy, without needing
to independently know the base trust-type defaults.

``trust_type`` (string)
  The trust relationship type (e.g., "reader", "friend", "partner")

**Error Responses:**

- **403 Forbidden**: The caller is not authorized to query this peer's
  permissions (decided first, see Authorization)
- **404 Not Found**: The trust relationship does not exist, or its type is
  one the actor does not define (no default permissions exist for it)
- **503 Service Unavailable**: A temporary storage fault
- **500 Internal Server Error**: Permission retrieval failed

**Use Cases:**

1. **Initial Permission Discovery**: When trust is established, peers can query
   their initial permissions to understand what they can access.

2. **Permission Refresh**: Peers can periodically refresh cached permissions to
   ensure consistency.

3. **Callback Recovery**: If a permission callback is missed, peers can query
   to get current permissions.

**Relationship with Permission Callbacks:**

This query endpoint provides **pull-based** permission discovery, complementing
the **push-based** permission callback mechanism (see Permission Callback section).
Together they form a robust hybrid architecture:

- **Callbacks**: Real-time notifications when permissions change
- **Query Endpoint**: On-demand permission discovery and refresh

Applications supporting both mechanisms advertise both ``permissioncallback``
and ``permissionquery`` in their ``/meta/actingweb/supported`` endpoint.

**Permission Structure**

Permission overrides SHOULD follow this structure to ensure interoperability:

``properties``
  Controls access to actor property storage with patterns, operations, and 
  excluded patterns for fine-grained property access control.

``methods``
  Controls ActingWeb method calls with allowed and denied lists supporting
  glob patterns for method name matching.

``actions``  
  Controls ActingWeb action execution with allowed and denied lists for
  specific action permissions.

``tools`` (for MCP clients)
  Controls MCP tool access with allowed and denied lists for tool-specific
  permissions.

``resources``
  Controls resource access with patterns and operations: the ``/resources``
  path of a peer request and MCP resources alike (one grant; GET is ``read``,
  PUT and POST ``write``, DELETE ``delete``).

``prompts`` (for MCP clients)
  Controls MCP prompt access with allowed patterns for prompt-specific
  permissions.

**Permission Response Format**

The Permission Query Endpoint (``GET /{actorid}/permissions/{peerid}``)
SHOULD return a JSON response with these fields (the dedicated management
endpoint under /trust returns the stored form described above instead):

``actor_id`` (string)
  The actor granting permissions.

``peer_id`` (string)
  The peer receiving permissions.

``permissions`` (object)
  The full effective permissions, containing all permission categories
  (``properties``, ``methods``, ``actions``, ``tools``, ``resources``, ``prompts``).
  When custom overrides exist, these are merged with base trust-type defaults.

``source`` (string)
  Indicates the source of permissions: ``"custom_override"`` for effective permissions
  (base merged with overrides) or ``"trust_type_default"`` for unmodified trust type defaults.

``trust_type`` (string)
  The trust relationship type (e.g., ``"reader"``, ``"friend"``, ``"partner"``).

Example response with custom overrides (effective permissions)::

    {
        "actor_id": "actor123",
        "peer_id": "peer456",
        "permissions": {
            "properties": {
                "patterns": ["displayname", "email", "notes_travel"],
                "operations": ["read"],
                "excluded_patterns": []
            },
            "methods": {"allowed": []},
            "actions": {},
            "tools": {
                "allowed": ["search", "fetch", "create_note"],
                "denied": ["delete_*"]
            },
            "resources": {"patterns": [], "operations": ["read"]},
            "prompts": {"allowed": []}
        },
        "source": "custom_override",
        "trust_type": "reader"
    }

Note: The ``permissions`` object contains the full effective permissions — base
trust-type defaults merged with per-relationship overrides. For example, if the
base ``reader`` type grants ``["displayname", "email"]`` and the override adds
``["notes_travel"]``, the response contains the union ``["displayname", "email",
"notes_travel"]``.

Example response with default permissions (no overrides)::

    {
        "actor_id": "actor123",
        "peer_id": "peer456",
        "permissions": {
            "properties": {
                "patterns": ["displayname", "email"],
                "operations": ["read"],
                "excluded_patterns": []
            },
            "methods": {"allowed": []},
            "actions": {},
            "tools": {"allowed": []},
            "resources": {"patterns": [], "operations": ["read"]},
            "prompts": {"allowed": []}
        },
        "source": "trust_type_default",
        "trust_type": "reader"
    }

**Permission Evaluation**

When evaluating permissions for a trust relationship, the system SHOULD:

1. Start with base permissions defined by the trust type
2. Apply any per-relationship permission overrides  
3. Evaluate patterns using glob matching with ``*`` (any characters) and ``?`` (single character); a backslash escapes ``*``, ``?`` and itself (``\*`` is a literal ``*``), and matching is case-sensitive without character classes
4. Apply precedence: explicit deny > explicit allow > trust type defaults
5. Treat an exclusion (a deny) of a path as covering its descendants, and
   remove excluded descendants from data returned for an ancestor of the path
   (a read of the parent, a listing, a subscription diff)

When no pattern matches, the system MUST decide as follows: a request in a
category the grant mentions (for example ``properties`` with a list of
patterns) and that no pattern of it admits MUST be denied; a request in a
category the grant does not mention at all follows the actor's access
rules for the relationship type (the rules that apply without
per-relationship permissions).

This approach provides standardized per-relationship permission management
while maintaining backward compatibility with existing trust relationship
implementations.

Using a Trustee To Manage Relationships
---------------------------------------

**The Use of Trustees**

Managing trust relationship request can be one of actor's the most
complex operations and may require validation of the requesting actor's
identity, seeking approval from a human or applying some other logic to
evaluate the request. Also, managing trust relationships over time
requires maintenance actions, for example deleting a relationship after
a certain time period or on a human's request. To simplify this process,
another (possibly dedicated) actor called a 'trustee' can take over the
relationship management.

A trustee actor can take many forms, two examples may be:

1. A web application that presents a web page to a user and allows the
user to approve or reject the request. The user can be authenticated
using for example the Google Account API to validate Google credentials
for the Google account stored as the trustee's "owner".

2. A desktop application that graphically and dynamically depicts
relationships between actors and that allows a human being to create new
relationships through connecting and disconnecting icon representations
using drag and drop.

For example, a desktop application may allow a user to choose a bank
account as a focal point and then visualise drawn lines to actors that
represent subscription services that are allowed to withdraw money from
the bank account. Hoovering over the relationship line can show details
about the relationship, for example restrictions on amount and how often
money is allowed to be transferred.

**Assigning and Forwarding To a Trustee**

A trustee can be assigned either at the instantiation of an actor (by
specifying trustee root URI on instantiation in the application/json
body using the attribute 'trustee\_root') or by changing the trustee's
root URI by PUTing a new URI to /trust/trustee with application/json
content and the URL in the attribute 'trustee_root'. In the same PUT, the
'creator' attribute MUST also be available to allow changing creator to
'trustee' (or to any other username). A DELETE on /trust/trustee clears
the trustee root.

Only the creator and the trustee MAY change the trustee root or the
creator: a PUT or DELETE on /trust/trustee from a peer, of any
relationship type, an 'admin' peer included, MUST be answered with 403
Forbidden and change nothing (an admin peer could otherwise arm trustee
access for itself and keep it after its relationship was deleted). A
successful PUT or DELETE MUST be answered with 204 No Content. A ``creator``
value the actor reserves MUST be answered with 400 Bad Request, and, where
creators are unique (see Instantiation of Actors), a ``creator`` another
actor holds MUST be answered with 409 Conflict; in both cases nothing is
changed. The trustee MAY use the same PUT to hand the actor back by
setting the creator to a username of its choice.

The 'creator' user's passphrase/secret MAY
then be used as a bearer token to do trustee REST requests if 'creator' is
set to 'trustee'. As a passphrase is
supplied at instantiation time for creator, it is RECOMMENDED that the
passphrase is checked for security strength if the trustee\_root
attribute is set.

However, the token MUST NOT give access as bearer token in requests unless
the trustee root is set, the 'creator' user is 'trustee' and the bit
strength of the passphrase is > 80 bits. The strength MAY be estimated
from the passphrase's length and alphabet (for example, the length times
log2(94) for a passphrase of printable ASCII characters).

Trustee access requires no trust relationship: it is granted on these
three conditions alone, and it ends only when one of them stops holding
(the passphrase, the creator or the trustee root changes). An actor MUST NOT
disclose its passphrase to a peer (see Reading the actor root), so a peer
cannot gain trustee access by reading it.

A trustee MUST have access to the /trust and /subscription endpoints, as well
as the root (like creator) using the passphrase as bearer token. It is
RECOMMENDED that any other endpoint access is done and accepted only with
a regular trust relationship; an implementation MAY give the trustee
access to further paths of its own.

It is RECOMMENDED that a trustee also establishes a regular relationship
with the actor (of any type), as a trust relationship allows verification
and possibly explicit approval through an external process. (Note that if
trustee\_root is set as part of an instantiation, the creator username
and password can be used to send requests as creator to the new actor
even before trustee access with passphrase as bearer token is allowed.)

A typical use of a trustee is automatic creation of a new actor by
another actor to create an ActingWeb network of actors. Let's say a bot
instantiating a new text messaging actor before handing over to the user
to authenticate the new actor with the 3\ :sup:`rd` party text messaging
service. The actor instantiating a new actor may then initiate a new
trust relationship and then use the creator credentials to approve the
relationship directly.

Authentication
-----------------------------

Authentication of an actor is necessary when the actor is sending a
request to another actor where a trust relationship is required to gain
the required access. At the time of creating a trust relationship, the
actor receiving and approving the request MUST store the actor's id,
base URI, and the relationship's shared secret in its authentication
store.

The authentication method is based on the http Bearer authentication
method. Please refer to https://tools.ietf.org/html/rfc6750 for details
on the use of bearer tokens.

Note that the passphrase created at actor instantiation time together
with the (default) username ‘creator’ MUST use http basic
authentication. An implementation MAY also authenticate the creator by
other means it offers, for example a bearer token from an OAuth2 login
whose identity matches the actor's creator; such a token gives the access
of the creator, not of a peer. A request whose credentials are not valid
MUST be refused (401 Unauthorised or 403 Forbidden) and change nothing.

/subscriptions - Subscriptions (OPTIONAL)
=========================================

Establishing a Subscription
-----------------------------

The subscription model is based on the concept of creating a
subscription on a specific actor path with three elements: target,
sub-target, and resource. The most narrow subscription is on a resource.
Sub-target and target are then mandatory specified in the subscription
request. If a subscription targets all resources within a sub-target,
then sub-target and target are specified in the request. Finally, if the
entire endpoint is targeted in the subscription, only target is
specified in the request.

The /properties endpoint allows easy sharing of simple json data, while
the endpoints /actions, /resources, /methods, and /sessions enable
sharing of more complex data and execution of procedures. Once an actor
has a trust relationship, it can use subscriptions to receive updates
about changes and activities. The main use of a subscription is to make
sure that one actor gets efficient and near real-time access to changes
that occur to another actor.

An actor can establish a new subscription by sending a peer
authenticated POST request to /subscriptions/<peerid> where peerid is
the actor id of the requesting actor. A json body MUST as a minimum
include the attribute “target”. The most common targets are properties,
resources, actions, methods, and sessions, but a subscription MAY be of
any target the mini-app will recognise. Additionally, "subtarget" and
"resource" can be specified, thus identifying a sub-path to subscribe
to, e.g. /resources/folders/12345.

The "granularity" attribute controls how the subscribing actor wants to
be notified. The possible values are "high", "low", and "none", where
"high" sends a callback to the subscribing actor with a full
application/json body of the update, "low" sends a notification with an
application/json body with a single attribute "url" with a URL to where
a full json body of the update can be retrieved, and "none" suppresses
all notifications and GET polling on the subscription is necessary to
retrieve updates. If "granularity" is not present, "none" is assumed. Any
other value MUST be answered with 400 Bad Request and no subscription
created; a subscriber SHOULD refuse to send one.

The requesting actor MUST have a relationship allowing minimum read
permissions on the requested path, and the actor receiving the request
MUST validate the access rights upon receiving the request (a refusal is
403 Forbidden). It MUST also validate that the bearer token is valid for
the peer specified in the POST URI. Read access is checked again whenever a
diff is delivered or polled (see Getting Subscription Updates): a
subscription does not keep access the peer has lost.

If approved, a 201 Created MUST be returned with the Location header
pointing to the URI of the newly created subscription in the
format <actor root URI>/subscriptions/<subscriber-actor-id>/<subscription-id>.
The Location SHOULD be an absolute URI; a subscriber MUST accept an
absolute or a relative one. The response body MUST be an application/json
object describing the new subscription, with at least ``subscriptionid``,
``target``, ``subtarget``, ``resource``, ``granularity`` and ``sequence``
(``0`` for a new subscription, see The Diff and Update Model). A
subscriber needs ``subscriptionid`` to recognise its callbacks.

In the below example, a new subscription with id
9d60853cb4915b699f89d7ae13efb382 is created at actor (requested)
b373e63030a451b2991c9995438fccf1 from actor (requesting)
f08ce818ea515526adcbd157eeaf0ab0.

::

  Example:

  POST
  /b373e63030a451b2991c9995438fccf1/subscriptions/f08ce818ea515526adcbd157eeaf0ab0

  {
    "target": "resources",
    "subtarget": "folders",
    "resource": "12345",
    "granularity": "high"
  }

  201 Created

  Location:
  https://actingweb.net/myapp/b373e63030a451b2991c9995438fccf1/subscriptions/f08ce818ea515526adcbd157eeaf0ab0/9d60853cb4915b699f89d7ae13efb382

  {
    "subscriptionid": "9d60853cb4915b699f89d7ae13efb382",
    "target": "resources",
    "subtarget": "folders",
    "resource": "12345",
    "granularity": "high",
    "sequence": 0
  }

An actor is RECOMMENDED to support callbacks, but MUST support polling
of subscriptions. If a callback is requested by specifying "granularity"
other than "none", but it is not supported by the mini-application, a
501 Not Implemented MUST be returned. The requesting actor may then
choose to resend the subscription request without a granularity
attribute or {"granularity": "none"}.

When a subscription has been registered, the actor MUST record and act
upon any changes that are done to the path, from whichever interface the
change was made (the REST endpoints, the actor's web pages or the
mini-application itself). The actor MAY reject a
subscription request to any path on which it does not support
subscriptions. A subscription to /actions and /methods indicates a wish
to get updates on any requests to these paths.

An actor MAY suspend the subscriptions to a target or subtarget for a
while (for example around a bulk change). While suspended, a change
records no diff and uses no sequence number. When the subscriptions are
resumed, the actor MUST tell each subscriber that its state may have
changed: by a resync callback to a subscriber that advertises
``subscriptionresync`` (see Resync Callback), by a resync diff the
subscriber polls (for a subscription with granularity ``none``, or one
the actor cannot call), or by the full state as ordinary diffs to a
subscriber that does not support resync (see Resync Callback).

Initiating and Enumerating Subscriptions
----------------------------------------

Sometimes it can be necessary to request an actor to create a
subscription with another actor. Actors supporting subscriptions MUST
support POST requests to /<actorid>/subscriptions with an
application/json body with "peerid" identifying the peer to send a
subscription request to, as well as all the attributes to use when
requesting a subscription. This request is the actor's creator's (or
trustee's); an actor SHOULD refuse it from a peer (403 Forbidden). When the
peer created the subscription, the actor answers
204 No Content with a Location header holding the URI of the
subscription at the peer. A request without ``peerid`` or ``target``, or
with an unknown granularity, MUST be answered with 400 Bad Request. When
the peer does not create the subscription, the actor answers with an
error status (it MAY use 408 Request Timeout for every such failure). A
repeated request creates another subscription.

It is RECOMMENDED that a mini-application supports GET on /subscriptions
and /subscriptions/<peerid> with creator or admin rights and peer rights
respectively (a peer sees only its own subscriptions). The body returned
with 200 Ok MUST contain the below elements. See the next section for
explanation of the sequence attribute. The list holds the subscriptions
in both directions: those peers hold at this actor and those this actor
holds at peers. Each element carries ``peerid``, ``subscriptionid``,
``target``, ``subtarget``, ``resource``, ``granularity`` and ``sequence``,
and MAY carry more: ``callback`` (true for a subscription this actor holds
at the peer, false for one the peer holds here) and ``id`` (this actor's
id) are common.

The below example is for a GET to subscriptions. A GET to
subscriptions/<peerid> carries "peerid" on the root level; its elements
MAY carry it too.

::

  GET /b373e63030a451b2991c9995438fccf1/subscriptions

  {
    "id": "b373e63030a451b2991c9995438fccf1",
    "data": [
      {
        "peerid": "f08ce818ea515526adcbd157eeaf0ab0",
        "resource": "",
        "target": "properties",
        "sequence": 1,
        "granularity": "high",
        "subtarget": "data2",
        "subscriptionid": "6f9c496966d35b3b9d3fa2c9efc2934a"
      },
      {
        "peerid": "794edccea3705c0c96defb13857374ae",
        "resource": "45",
        "target": "properties",
        "sequence": 1,
        "granularity": "low",
        "subtarget": "data3",
        "subscriptionid": "016edb81538351b0af3034a6a751b003"
      }
    ]
  }

A mini-app MAY support GET search parameters like *?target=<value>&subtarget=<value2>&resource=<value3>*.

**Deleting a Subscription**

A subscription is ended by a DELETE on its URI
(/subscriptions/<peerid>/<subscriptionid>), answered with 204 No Content,
or 404 Not Found when it does not exist. The subscriber may delete the
subscription it holds at the publisher (its DELETE is authenticated as the
peer the path names); the actor's creator may delete any. Both sides
remove what they hold for the subscription (its diffs at the publisher).
When the actor's creator deletes a subscription this actor holds at a
peer, the actor MUST also delete it at the peer; a DELETE that comes from
the peer itself is not sent back to it.

When the publisher deletes a subscription a peer holds (its creator ends
it, or the publisher removes it), it tells the subscriber with a DELETE on
the subscription's callback URI,
``<subscriber base URI>/callbacks/subscriptions/<publisher id>/<subscriptionid>``,
authenticated with the trust relationship's shared secret as bearer
token. The subscriber MUST accept this DELETE only from the peer the path
names (403 Forbidden otherwise, see /callbacks); it deletes its own record
of the subscription and answers 204 No Content, or 404 Not Found when it
holds no such subscription.

Getting Subscription Updates
-----------------------------

**The Diff and Update Model**

The hierarchy of subscriptions is important for how the subscription
callbacks and diffs work:

::

  |… ourtarget |… sub-target1 |… resource1
               |              |… resource2
               |              |… resource3
               |… sub-target2 |… resource1
                              |… resource2

Let's start with the simplest case, the subscription targets *resource1*
of *sub-target1* in *ourtarget*. The data in the body of an update MUST
in this case be the full resource representation (json or other data
representation) and not a diff. In fact, the data MAY be anything the
mini-app chooses to send as an update. It can be a blob or a data object
that has nothing to do with the previous subscription update, as long as
it communicates a state change on the resource, and the data
representation is documented by the mini-app.

This flexibility allows the subscription mechanism to be used for any
resource state change that is desired to be communicated to another
actor.

For subscriptions to a target or a sub-target, the expectation is that
the changes per update can be found in a json struct following the
hierarchy relative to the subscription. I.e. If resource2 in sub-target2
has changed, the diff MUST follow the following example format for a
subscription to *ourtarget*:

::

  {
    "sub-target2": {
      "resource2": "full_representation"
    }
  }

and the following for a subscription to *ourtarget*, *sub-target2*:

::

  {
    "resource2": "full_representation"
  }

This means that every time something happens on a
resource/endpoint/path, all subscriptions within scope MUST be processed
and a specific diff created for each subscription where the json struct
follows the hierarchy below the subscription. Each subscription is
processed independently: a peer holding two subscriptions whose scopes
both include a change receives a diff on each (see Subscription Scope and
Overlap). The diff format is simple:
only sub-targets or resources that have changed are included in a diff,
and an empty attribute is defined as the same as a non-existent
attribute, thus an attribute can be deleted by setting it to "". For
/properties, the entry of a changed sub-target is its whole stored value,
not only the changed part below it (see What a write sends); the
partial form shown above is for targets whose mini-app defines it.

A diff for a subscription to a sub-target or a resource is relative to that
sub-target or resource: it carries the sub-target's (or the resource's)
value itself, not wrapped in its name. A subscriber MUST apply it to the
sub-target or resource it subscribed to, on both sides of the exchange
(the publisher does not repeat the subscribed path inside the diff). The
one exception is the full state a publisher sends as ordinary diffs to a
subscriber without resync support (see Resync Callback): those diffs are
keyed by name at every level, a sub-target subscription's included, and a
subscriber unwraps the entry named by its sub-target.

Each diff MUST have a sequence number. A new subscription has the
sequence number 0 (as the subscription's ``sequence`` shows); its first
diff is numbered 1, and each later diff of the subscription takes the
next number. Sequence numbers increase but MAY have gaps: a number taken
for a diff that then could not be stored is not handed out again, so no
diff ever carries it. A subscriber MUST NOT wait indefinitely for a number
a poll does not return; it continues from the highest number the poll
showed, and MAY re-read the subscribed state, since the change behind the
gap is not available as a diff.

**Deletions**

In a diff, ``""`` means deleted, at every level. When a name, a nested key
or a resource is deleted, the subscription on the deleted level receives
``""`` as its diff. When a whole property is deleted, a subscription
above it (on /properties) receives the deleted name with the value ``""``,
e.g. ``{"test": ""}`` when ``test`` was deleted. When a part below a
property is deleted, a subscription on the property or on /properties
receives the property's whole stored value after the deletion, as for any
write below a sub-target (see What a write sends). Each such diff takes a
sequence number and is delivered and polled like any other diff. A subscriber MUST
treat ``""`` as "absent": a value stored as the empty string cannot be told
apart from a deletion, so a mini-application SHOULD NOT give an empty
string a meaning distinct from an absent value. A publisher MUST use ``""``
for a deletion; a subscriber SHOULD treat a ``null`` value as a deletion
too.

A subscription on a resource MUST be told when its resource went away with
its parent: when the sub-target holding it is deleted, or overwritten by a
value without that resource. Such a subscription receives ``""``. It
receives it only when the resource existed before the write; a write that
never touched an existing resource sends that subscription nothing.

A DELETE of /properties (all simple properties, see /properties) is one
change: a subscription on /properties receives one diff, with one sequence
number, naming every deleted property with the value ``""``. A
subscription on one of the deleted properties (or below it) receives the
deletion of its own name, as for a single DELETE. List properties are not
deleted by it, and their subscriptions receive nothing.

**What a write sends**

The value in a diff is the value the actor stored, after any
transformation the mini-application applied to the write (see /properties).

A subscriber applies a sub-target's value in a diff as the sub-target's
whole new value. So when a write changes a part below a sub-target (a
nested PUT to /properties/test/var1), a subscription on the target or on
the sub-target receives the sub-target's whole stored value after the
write, not only the changed part; a subscription on the changed resource
receives that resource's new value. Likewise, a write deeper than a
subscribed resource (a PUT to /properties/test/var1/x for a subscription
on /properties/test/var1) sends that subscription the resource's whole
stored value after the write.

Further examples with /properties

Initial data POSTed to /properties:

::

  {
    "data1": {
      "str1": "initial",
      "str2": "initial"
    },
    "data2": "initial",
    "test": {
      "var1": "initial",
      "var2": "initial",
      "resource": "initial"
    }
  }

If a PUT to /properties/test has the content { "var1": "hey"}
(overwriting test), the resulting /properties will be:

::

  {
    "data1": {
      "str1": "initial",
      "str2": "initial"
    },
    "data2": "initial",
    "test": {
      "var1": "hey"
    }
  }

and the diff to a subscription on /properties MUST be:

::

  {
    "test": {
      "var1": "hey"
    }
  }

And a subscription to /properties/test MUST give the following diff:

::

  {
    "var1": "hey"
  }

A subscription to /properties/test/resource (and one to
/properties/test/var2) MUST give ``""``: the resource existed and the write
removed it. A subscription to /properties/test/var1 gives ``"hey"``.

If instead a PUT is done to /properties/test/var1 to change it to
"change2" (starting again from the initial data), the subscription diff
for a /properties subscription will be the whole stored value of test:

::

  {
    "test": {
      "var1": "change2",
      "var2": "initial",
      "resource": "initial"
    }
  }

A subscription to /properties/test receives the same value without the
``"test"`` wrapper, and a subscription to /properties/test/var1 receives
``"change2"``. The resource and var2 attributes in the test struct have not
been touched and are still present, and the diff shows them, so a
subscriber that applies the diff keeps them.

A DELETE of /properties/test/resource (again from the initial data) sends
``""`` to a subscription on /properties/test/resource, the remaining value
``{"var1": "initial", "var2": "initial"}`` to a subscription on
/properties/test, and ``{"test": {"var1": "initial", "var2": "initial"}}``
to a subscription on /properties. A DELETE of /properties/test sends ``""``
to a subscription on /properties/test and to each subscription on a
resource of test that existed, and ``{"test": ""}`` to a subscription on
/properties.

A mini-app MAY implement more advanced diff methods, but this diff
method MUST be used for the /properties endpoint.

**List Property Subscriptions (OPTIONAL)**

This section applies only to actors that support the *listproperties* option tag.
Subscriptions to list properties follow a modified diff format that provides
additional context about list mutations. To subscribe to changes on one
list property, the subscription request names the list directly as the
subtarget: for a list property named ``notes``, ``subtarget: "notes"``. A
subscription to the whole /properties target also receives the list's
diffs.

As for any diff (see The Diff and Update Model), the level of the
subscription decides the wrapping: a subscription on the list
(``subtarget: "notes"``) receives the list diff object itself, unwrapped;
a subscription on /properties receives it under the list's name, as in
``{"notes": {...}}``. The examples below show the wrapped form a
subscription on /properties receives.

The diff payload for list property changes differs from regular property diffs
in that it provides structured metadata about the mutation operation. The diff
data MUST include the following fields:

+----------------+-------------+----------------------------------------------------------------+
| **Field**      | **Required**| **Description**                                                |
+----------------+-------------+----------------------------------------------------------------+
| ``list``       | REQUIRED    | The name of the list property                                  |
+----------------+-------------+----------------------------------------------------------------+
| ``operation``  | REQUIRED    | The mutation type: ``append``, ``insert``, ``update``,         |
|                |             | ``delete``, ``pop``, ``extend``, ``clear``, ``remove``,        |
|                |             | ``delete_all``, or ``metadata``                                |
+----------------+-------------+----------------------------------------------------------------+
| ``length``     | REQUIRED    | The current length of the list after the operation. Advisory:  |
|                |             | it MAY derive from the sender's tracked count rather than a    |
|                |             | fresh count of the rows, so under concurrent mutation it can   |
|                |             | be momentarily off by a bounded amount. Receivers MUST NOT     |
|                |             | use it to address rows                                         |
+----------------+-------------+----------------------------------------------------------------+
| ``item``       | OPTIONAL    | The item data for ``append``, ``insert``, and ``update``       |
|                |             | operations                                                     |
+----------------+-------------+----------------------------------------------------------------+
| ``index``      | OPTIONAL    | The index affected for ``append``, ``insert``, ``update``,     |
|                |             | ``delete``, and ``pop`` operations. For ``append`` diffs the   |
|                |             | value is advisory in the same way ``length`` is (it is derived |
|                |             | from it): a receiver SHOULD apply an append by appending       |
|                |             | ``item``, never by writing at ``index``                        |
+----------------+-------------+----------------------------------------------------------------+
| ``items``      | OPTIONAL    | Array of items for ``extend`` operations                       |
+----------------+-------------+----------------------------------------------------------------+
| ``old_item``   | OPTIONAL    | For an ``update`` diff whose mutation was addressed by the     |
|                |             | item's value rather than its position: the item's value before |
|                |             | the update. ``index`` MAY be absent from such a diff entirely  |
|                |             | -- a value-addressed update does not require a position. A     |
|                |             | receiver that understands ``old_item`` SHOULD locate the row   |
|                |             | by matching its current value against ``old_item``, but only   |
|                |             | when that match is unique: diff delivery between independent   |
|                |             | peers is not guaranteed reliable or ordered, so a peer's list  |
|                |             | can already have drifted from the sender's by the time a diff  |
|                |             | arrives, and if two or more rows currently hold that value     |
|                |             | which one the sender meant is genuinely ambiguous. The         |
|                |             | receiver MUST fall back to ``index`` when the value match is   |
|                |             | ambiguous or absent, and if no ``index`` is present either,    |
|                |             | MUST treat the diff as inapplicable rather than guess. A       |
|                |             | receiver that does not recognize ``old_item`` MAY ignore it    |
|                |             | and match by ``index`` alone, as it always has --              |
|                |             | understanding that an ``update`` diff with no ``index`` then   |
|                |             | has nothing to match on.                                       |
+----------------+-------------+----------------------------------------------------------------+

A ``remove`` diff whose mutation was addressed by the item's value rather
than its position carries the removed item's full value in ``item``
rather than an ``index`` -- the same field the ``append``/``insert``/
``update`` operations already use for item data, not a new field.

Example diff for appending an item to the ``notes`` list property::

  {
    "notes": {
      "list": "notes",
      "operation": "append",
      "length": 3,
      "item": {"id": "3", "content": "New note"},
      "index": 2
    }
  }

Example diff for extending a list with multiple items::

  {
    "notes": {
      "list": "notes",
      "operation": "extend",
      "length": 5,
      "items": [{"id": "4", "content": "Note 4"}, {"id": "5", "content": "Note 5"}]
    }
  }

Example diff for updating an item at a specific index::

  {
    "notes": {
      "list": "notes",
      "operation": "update",
      "length": 5,
      "item": {"id": "1", "content": "Updated content"},
      "index": 0
    }
  }

Example diff for a value-addressed update -- the item's value identifies
the row, not its position, so ``index`` is absent::

  {
    "notes": {
      "list": "notes",
      "operation": "update",
      "length": 5,
      "item": {"id": "1", "content": "Updated content", "status": "done"},
      "old_item": {"id": "1", "content": "Updated content", "status": "open"}
    }
  }

Example diff for deleting an item at a specific index::

  {
    "notes": {
      "list": "notes",
      "operation": "delete",
      "length": 4,
      "index": 2
    }
  }

The same delete as a subscription on the list itself (``subtarget:
"notes"``) receives it::

  {
    "list": "notes",
    "operation": "delete",
    "length": 4,
    "index": 2
  }

The operations not shown above:

- ``insert`` carries ``item`` and the ``index`` it was inserted at; the
  items from that index on move up by one.
- ``pop`` removes one item and carries its ``index``. The index MAY be
  negative, counted from the end of the list as the sender held it (``-1``
  is the last item); a receiver MUST resolve a negative index against its
  own list's length. Every other operation's ``index`` is zero or positive.
- ``remove`` removes one item addressed by its value (``item``), as
  described above.
- ``clear`` empties the list and keeps it; ``length`` is ``0``.
- ``delete_all`` deletes the list itself, with all its items (a DELETE of
  the list property); ``length`` is ``0``. A receiver removes the list, not
  only its items.
- ``extend`` appends every element of ``items`` in order. The creation of a
  new, empty list is sent as an ``extend`` with an empty ``items`` array and
  ``length`` ``0``; a receiver creates the list if it does not hold it.
- ``metadata`` says that the list's descriptive metadata (description,
  explanation) changed, or that the sender maintained the list's storage
  without changing its items. It carries no item and need not carry the
  new metadata; a receiver that keeps the metadata re-reads it (see List
  Property Metadata), and a receiver that does not MAY ignore the diff. Its
  items are unchanged either way.

When a sender sends a subscriber the full state of a list as ordinary
diffs (for example to a subscriber that does not support resync, see
Resync Callback), it sends a ``clear`` of the list and then, in a later
diff with a higher sequence number, an ``extend`` with all its items, so a
receiver that already holds the list does not append the items to the
copy it has. (A list sent as a reference, see below, needs no ``clear``.)

**List diff references**

A list diff whose values are too large to send (or to store as one diff)
MAY be sent as a *reference*. A reference is the diff with its value
fields (``item``, ``old_item``, ``items``) removed and two fields added:
``"spanned": true`` and ``"bytes"``, the encoded size of the values that
were left out. Every other field (``list``, ``operation``, ``length``,
``index`` when present) is kept::

  {
    "list": "notes",
    "operation": "append",
    "length": 3,
    "index": 2,
    "spanned": true,
    "bytes": 420117
  }

A receiver MUST NOT apply a reference as the operation it names (it does
not carry the values). It treats the list as out of step and re-reads it:
by reading the list from the publisher, or by the recovery it uses after a
resync (see Resync Callback). A receiver that does not know references sees
an ``append``, ``insert``, ``update`` or ``extend`` without its values and
SHOULD refuse it rather than apply it.

The ``item``, ``index``, and ``items`` fields allow subscribers to receive the
modified data directly in the callback without needing to make additional GET
requests to the list property endpoint. This is particularly useful for
high-frequency updates where minimizing API calls is important.

**Getting the Updates**

There are two ways to get updates on a subscription: polling on the
subscription URI or receive callbacks on the subscription callback URI.

The subscription callback URI is derived from the subscriber's base URI
as stored for the trust relationship, not taken from the subscription
request: ``<subscriber base URI>/callbacks/subscriptions/<publisher id>/<subscriptionid>``.

What a subscriber is sent, by callback or by poll, is filtered by what it
may read at the time (see Permission Evaluation): the publisher MUST apply
the subscriber's current access to every diff it delivers or serves. A
diff of which the subscriber may read nothing is not sent as a callback;
it keeps its sequence number and a poll shows it with ``{}`` as its data
(a change that changes nothing), so the subscriber sees no gap.

If the granularity is set to high, the callback is a POST with peer
bearer authentication to the subscription callback URI with the following
format:

::

  {
    "id": "26597c23469e5ab2b3489b786cf553f5",
    "target": "properties",
    "sequence": 6,
    "timestamp": "2016-11-15T13:47:02.375880Z",
    "granularity": "high",
    "subscriptionid": "552a0d7ec4ab553ea6c912baeb4459eb",
    "data": {
      "test": {
        "resource": "change5"
      }
    }
  }

The data attribute contains the actual diff relative to the
subscription, while the other attributes identifies the actor id
originating the update, the target (and subtarget and resource if
relevant), the timestamp in UTC, the granularity of the subscription,
the subscriptionid, as well as the sequence number of the update. In
this case, 6 indicates that this is the 6\ :sup:`th` diff produced for
this specific subscription as identified by subscriptionid. ``subtarget``
and ``resource`` are present when the subscription has them.

Every timestamp in a subscription callback (diff and resync) and in a
poll answer is an ISO 8601 date-time in UTC with a ``T`` separator,
microseconds and a ``Z`` suffix, as in ``2016-11-15T13:47:02.375880Z``.
Each diff carries the time it was recorded. A receiver SHOULD NOT depend on
the timestamp for ordering; the sequence number orders diffs.

A peer bearer token authenticated GET on the subscription id MUST offer
a similar format, but here an array of data elements MUST represent one
or more diff updates. The response MUST include a ``sequence`` attribute
at the top level indicating the subscription's current sequence number.
This allows peers to detect gaps in received diffs without examining
individual diff sequence numbers.

In the below example, the first diff was retrieved
earlier, now diff 2 - 6 are collected.

::

  {
    "subscriptionid": "26f9bb085fb351c7ba40d395af18a381",
    "id": "26597c23469e5ab2b3489b786cf553f5",
    "resource": "",
    "target": "properties",
    "subtarget": "test",
    "sequence": 6,
    "data": [
      {
        "timestamp": "2016-11-15T13:46:51.906980Z",
        "data": "change1",
        "sequence": 2
      },
      {
        "timestamp": "2016-11-15T13:46:53.967370Z",
        "data": "change2",
        "sequence": 3
      },
      {
        "timestamp": "2016-11-15T13:46:57.012820Z",
        "data": "change3",
        "sequence": 4
      },
      {
        "timestamp": "2016-11-15T13:47:00.509530Z",
        "data": {
          "some": "data",
          "resource": "change4"
        },
        "sequence": 5
      },
      {
        "timestamp": "2016-11-15T13:47:03.059410Z",
        "data": {
          "resource": "change5"
        },
        "sequence": 6
      }
    ]
  }

In the case of callbacks to the subscription callback URI, any 2xx
response from the subscriber indicates that the update has been received.
A 2xx does not clear the diff: it stays available to a GET on the
subscription until the subscriber clears it (see Clearing Callback
Status). A subscriber MAY clear the diffs it has applied from callbacks;
one that does not leaves them for its next poll, which shows them again
(a subscriber applies a diff once, by its sequence number).

The subscriber answers a subscription callback as follows:

- ``204 No Content`` (or another 2xx): received. This includes a callback
  the subscriber holds to apply later because an earlier sequence number
  is still missing.
- ``400 Bad Request``: the callback cannot be used: its body is not a JSON
  object, its ``type`` is present and is neither ``diff`` nor ``resync``, it carries ``data``
  without a ``sequence``, or the subscriber cannot hold it (for example
  because it already holds as many out-of-order callbacks as it allows).
- ``403 Forbidden``: the callback is not from the peer the path names, or
  is for a subscription the subscriber did not make (see /callbacks).
- ``503 Service Unavailable``, with ``Retry-After``: this one callback
  cannot be processed now (the same sequence number is being processed by
  another request, a storage fault, or, for a resync or a low-granularity
  callback, the fetch from the publisher failed). The subscriber has not
  advanced its sequence for it.

A callback whose ``sequence`` is missing is not a valid diff; a subscriber
MUST NOT treat it as sequence 0 or as a duplicate.

If the callback is not answered with a 2xx, the actor SHOULD not
retry, and it SHOULD be up to the receiving actor to do a GET poll when
it detects a gap in the sequence or triggered by another event. An actor
MAY implement a re-try mechanism with an exponential back-off.

**Low Granularity and Polling**

In the case of granulerity = low, the callback to the subscription
callback URI MUST contain application/json content with the following
format:

::

  {
    "subscriptionid": "26f9bb085fb351c7ba40d395af18a381",
    "id": "26597c23469e5ab2b3489b786cf553f5",
    "target": "properties",
    "subtarget": "test",
    "timestamp": "2016-11-15T13:47:02.915030Z",
    "granularity": "low",
    "sequence": 6,
    "url": "https://actingweb.net/myapp/26597c23469e5ab2b3489b786cf553f5/subscriptions/e3c47b6114ec558dade20d6c45855820/26f9bb085fb351c7ba40d395af18a381/6"
  }

The data element is here replaced by a url attribute identifying where
the subscribing actor can retrieve a specific diff. It is RECOMMENDED
that the URL is composed of the subscription URL with the sequence
number trailing at the end.

The subscribing actor MUST fetch the diff under the base URI stored for
the trust relationship (the subscription URL at the publisher with the
sequence number appended), and MUST NOT send its credentials to a URL taken
from the callback body.

The response content on this URL MUST be similar to a GET on the
subscription following this example:

::

  {
    "subscriptionid": "26f9bb085fb351c7ba40d395af18a381",
    "id": "26597c23469e5ab2b3489b786cf553f5",
    "target": "properties",
    "subtarget": "test",
    "resource": "",
    "timestamp": "2016-11-15T13:46:48.893650Z",
    "sequence": 6,
    "data": {
      "resource": "initial",
      "var1": "initial",
      "var2": "initial"
    }
  }

A GET on a specific diff's URL (subscription URL + '/seqnr') consumes
that diff: the publisher MUST answer it once and then clear the diff, so
a second GET on the same URL answers 404 Not Found. This is the one GET in
this specification that changes state. A low-granularity subscriber
therefore has one fetch per diff. A subscriber that lost the answer (a
timeout, a dropped connection) cannot fetch that diff again, and a poll of
the subscription no longer shows it; it recovers by reading the
subscribed resource itself (a GET on the target, sub-target or resource it
subscribed to), or from a resync (see Resync Callback).

**Clearing Callback Status**

Subsequent GET requests to the subscription URL MUST give the same result,
except that they MUST also return new diffs: a GET on the subscription URL
does not clear anything.

When a GET is done to the subscription URL and the subscribing actor
wants to clear all diffs received, a PUT MUST
be sent to the subscription URL with an application/json body with one
attribute "sequence" and the sequence number that was the last sequence
retrieved. All diffs with lower and equal sequence number than this MUST
be cleared and no longer appear in GET requests to the subscription URL,
and the PUT MUST be answered with 204 No Content. A ``sequence`` of ``0``
clears nothing (there is no diff 0); a value that is not a number MUST be
answered with 400 Bad Request.
GET requests to the diff specific URL (subscription URL + '/seqnr') MUST
return 404 Not found after clearing has been done.

::

  PUT
  /myapp/26597c23469e5ab2b3489b786cf553f5/subscriptions/e3c47b6114ec558dade20d6c45855820/26f9bb085fb351c7ba40d395af18a381

  {
    “sequence”: 2
  }

  204 No content

Resync Callback (OPTIONAL)
--------------------------

An actor MAY support the resync callback mechanism. A subscriber that
accepts resync callbacks advertises it by including the
``subscriptionresync`` option tag in ``/meta/actingweb/supported``.

A publisher MAY send a resync callback to indicate that the peer should
fetch the subscribed state, rather than processing individual diffs. This
is useful after bulk operations where many changes occurred and sending
individual diffs would be inefficient, and when suspended subscriptions are
resumed (see Establishing a Subscription). A publisher SHOULD send a resync
callback only to a subscriber that advertises ``subscriptionresync``; when
it does not (yet) know the subscriber's tags it MAY send one anyway. To a
subscriber
that does not advertise the tag, the publisher instead sends the full
subscribed state as ordinary diffs, each delivered as a low-granularity
callback and in this order: first, when the state holds list properties, a
diff with a ``clear`` for each of them; then, under the next sequence
number, one diff with the whole state, each list as an ``extend`` with all
its items (see List Property Subscriptions). Unlike other diffs, both are
keyed by name at every subscription level, a sub-target subscription's
included (``{"notes": {...}}`` for a subscription on ``notes``).

A subscription with granularity ``none`` is never sent a resync callback.
The publisher records the resync as a diff the subscriber finds when it
polls (see below), so a ``none`` subscriber still learns that its state
may have changed. The same applies to a subscriber the publisher cannot
call (one without a callback endpoint).

**Resync Callback Format**

The resync callback includes a ``type`` field set to ``"resync"``::

  {
    "id": "actor123",
    "subscriptionid": "sub456",
    "target": "properties",
    "subtarget": "notes_travel",
    "sequence": 7,
    "timestamp": "2026-01-15T12:00:00.000000Z",
    "granularity": "high",
    "type": "resync",
    "url": "https://example.com/actor123/properties/notes_travel"
  }

The ``type`` field:

- ``"resync"`` - Peer should GET full state for the subscription
- ``"diff"`` or absent - Normal diff callback (backward compatible)

A resync takes a sequence number like a diff. ``subtarget`` is an empty
string or ``null`` when the subscription has none (a receiver MUST accept
both); ``resource`` is not sent. ``granularity``
is the subscription's. ``url`` names the subscribed state at the
publisher, for information. A 2xx answer means the subscriber received
the resync; anything else (a refused connection, a timeout, a 503 from a
subscriber that could not fetch the state) means it was not delivered.

On receiving a resync callback, the peer SHOULD:

1. Fetch the current state of what the subscription covers (see the
   requirements on the fetch below).
2. If the fetch fails, answer ``503 Service Unavailable`` with
   ``Retry-After``, keep its sequence where it was, and keep its cached
   state. It then recovers the state later (on its next callback, poll or
   resync).
3. Replace its cached state for the subscription with the fetched state:
   apply what the fetch returned, and remove what it holds in the
   subscription's scope that the fetched state no longer has (a name
   deleted at the publisher while the subscription was suspended). A
   subscriber holding several subscriptions to the same peer removes only
   what no other of them covers.
4. Update local sequence tracking to the callback's sequence number.
5. Respond with ``204 No Content``.

Whatever else it does, the subscriber MUST fetch the state from the
publisher's base URI stored for the trust relationship, at the level of
the subscription as the subscriber stored it (target, sub-target or
resource), and MUST NOT send its credentials to the ``url`` of the
callback body or follow it outside that base URI. It MUST NOT apply an
empty state in place of a failed fetch (an empty, successful answer is a
valid state).

A publisher MUST NOT retry a resync callback that was not delivered on its
own schedule; it MAY send the resync again the next time it resumes the
subscriptions (see Callback Delivery Semantics).

A subscriber with no callback endpoint (it reads its diffs by polling), or
with granularity ``none``, finds its resync as a diff: a GET on the
subscription (or on the diff's own URL) then shows that sequence with
``"type": "resync"``, the ``url`` and an empty ``data`` object. The ``url``
is the subscription's target or lies under it. The subscriber SHOULD act on
it as on a resync callback (steps 1 to 4), replacing only the cached state
the ``url`` names, and SHOULD clear the marker only after the fetched state
was applied (a failed fetch leaves it, so the next poll tries again). Its
GET happens after every diff in the same answer was stored, so it already
reflects the changes they make to what the ``url`` names: the subscriber
SHOULD skip those parts of the diffs after the marker, apply the rest as
usual, and take the answer's highest sequence as its own. One that does not
know the type merges ``{}``, a change that changes nothing.


Permission Callback (OPTIONAL)
------------------------------

Actors MAY support permission callbacks to notify peers when their granted
permissions change. This enables reactive permission synchronization without
polling.

**Option Tag**: ``permissioncallback``

**Callback URL Pattern**

The callback URL follows the existing ``/callbacks/{type}/{identifier}`` pattern
used by subscription callbacks::

  /callbacks/permissions/{granting_actor_id}

Where:

- ``permissions`` is the callback type (analogous to ``subscriptions`` for subscription callbacks)
- ``granting_actor_id`` is the ID of the actor who granted/modified permissions

**Rationale for URL Pattern:**

Unlike subscription callbacks which use ``/callbacks/subscriptions/{peer_id}/{subscription_id}``,
permission callbacks omit the subscription_id because:

1. Permissions are tied to trust relationships, not subscriptions
2. Each trust relationship has exactly one set of permissions
3. The granting actor's ID uniquely identifies the permission source

This parallels how the trust endpoint uses ``/trust/{relationship}/{peer_id}/permissions``
rather than requiring a separate permission ID.

**Callback URL Comparison:**

+------------------------+------------------------------------------------+
| Callback Type          | URL Pattern                                    |
+========================+================================================+
| Subscription           | ``/callbacks/subscriptions/{peer_id}/{sub_id}``|
+------------------------+------------------------------------------------+
| Permission             | ``/callbacks/permissions/{granting_actor_id}`` |
+------------------------+------------------------------------------------+

**Permission Callback Format**

Permission callbacks use target ``"permissions"`` and include the full
effective permission grant structure (base trust-type defaults merged with
per-relationship overrides), with every category the actor defines
(``properties``, ``methods``, ``actions``, ``tools``, ``resources``,
``prompts``), each in the shape of the Permission Structure section::

  POST /{receiving_actor_id}/callbacks/permissions/{granting_actor_id}
  Content-Type: application/json
  Authorization: Bearer {bearer_token}

  {
    "id": "granting_actor_id",
    "target": "permissions",
    "timestamp": "2026-01-15T12:00:00.000000+00:00",
    "type": "permission",
    "data": {
      "properties": {
        "patterns": ["notes_*", "profile/*"],
        "operations": ["read", "subscribe"],
        "excluded_patterns": ["notes_private_*"]
      },
      "methods": {
        "allowed": ["sync_*"],
        "denied": []
      },
      "actions": {
        "allowed": ["refresh"],
        "denied": []
      },
      "tools": {
        "allowed": ["search", "fetch"],
        "denied": ["delete_*"]
      },
      "resources": {
        "patterns": ["data://*"],
        "operations": ["read"],
        "excluded_patterns": []
      },
      "prompts": {
        "allowed": ["*"]
      }
    }
  }

The ``timestamp`` is an ISO 8601 date-time in UTC, with a ``Z`` suffix or
a ``+00:00`` offset; a receiver MUST accept both, and SHOULD refuse (400) a
timestamp it cannot parse or one far ahead of its own clock, since a
future timestamp would make every later update look older. A callback
without a ``timestamp`` is taken as sent now.

**Key Characteristics:**

- Permission callbacks do NOT use sequence numbers (sequence field is 0 or absent)
- Permission callbacks are idempotent - receiving the same permissions multiple times is safe
- The ``data`` field contains the FULL effective permissions (base trust-type defaults
  merged with per-relationship overrides), not a diff or override-only subset
- Receivers should replace cached permissions entirely, not merge

**Callback Type Field**

The ``type`` field distinguishes permission callbacks:

- ``"permission"`` - Full permission grant/update
- ``"diff"`` or absent - Normal subscription callback
- ``"resync"`` - Resync callback

**Triggering Permission Callbacks**

Permission callbacks SHOULD be sent when:

1. Trust relationship permissions are modified via ``PUT /trust/{rel}/{peerid}/permissions``
   (or the ``permissions`` field of a PUT on the relationship)
2. Per-relationship permissions are deleted (``DELETE /trust/{rel}/{peerid}/permissions``):
   the callback then carries the trust type's default permissions, which now apply
3. An actor explicitly revokes specific permissions

A callback MAY also be sent when trust type default permissions change
(a bulk notification to all affected peers).

A sender MAY send permission callbacks without checking the peer's option
tags. A peer that does not accept them answers 403 (an authenticated
callback to a path nothing handles, see /callbacks), and the sender treats
that as not delivered; the peer can still learn its permissions from the
Permission Query Endpoint.

**Receiver Behavior**

A permission callback MUST be authenticated as the peer the path names (see
/callbacks); any other caller is answered 403 Forbidden. On receiving a valid
permission callback, the receiver SHOULD:

1. Validate the callback is from a trusted peer
2. Store the received permissions in local cache
3. Trigger any application-specific reactions (e.g., sync newly-granted data)
4. Clean up local data for revoked permissions (OPTIONAL)
5. Respond with ``204 No Content``

A body that is not a JSON object, whose ``data`` is not an object, or whose
``timestamp`` is refused, is answered with ``400 Bad Request``.
A receiver that cannot store the callback for a transient reason (a
concurrent update it lost, a storage fault, a failed cleanup of data the
callback revokes) MAY answer ``503`` with
``Retry-After``; the sender MAY then resend the same body, timestamp
included, a bounded number of times (the one exception to the rule against
automatic retries, see Callback Delivery Semantics).

**Timestamp-Based Ordering**

Because permission callbacks use full replacement semantics without sequence numbers,
receivers SHOULD compare the ``timestamp`` field to prevent stale updates from
overwriting newer permissions. If the received timestamp is older than the cached
timestamp, the callback SHOULD be ignored: the receiver stores nothing from it, removes
no data and runs no application reaction for it, and answers ``204 No Content``. (It
MAY instead ask the sender for its current permissions with the Permission Query
Endpoint, when the two disagree.)


Granularity Selection Guidelines
--------------------------------

Implementations SHOULD consider the following factors when selecting or recommending
a granularity level for subscriptions:

+------------------------------------------+-------------------------+-----------------------------------------------+
| **Scenario**                             | **Recommended**         | **Rationale**                                 |
+------------------------------------------+-------------------------+-----------------------------------------------+
| Property < 64KB, subscribers < 10        | ``high``                | Efficient, immediate delivery                 |
+------------------------------------------+-------------------------+-----------------------------------------------+
| Property < 64KB, subscribers >= 10       | ``low``                 | Reduces fan-out bandwidth                     |
+------------------------------------------+-------------------------+-----------------------------------------------+
| Property >= 64KB                         | ``low``                 | Prevents callback payload explosion           |
+------------------------------------------+-------------------------+-----------------------------------------------+
| List property (any size)                 | ``high``                | Diffs are already incremental                 |
+------------------------------------------+-------------------------+-----------------------------------------------+
| Real-time requirements                   | ``high``                | Minimizes round-trips                         |
+------------------------------------------+-------------------------+-----------------------------------------------+
| Bandwidth-constrained environments       | ``low`` or ``none``     | Peer fetches on-demand                        |
+------------------------------------------+-------------------------+-----------------------------------------------+

Implementations MAY automatically downgrade from ``high`` to ``low`` granularity when the
payload size exceeds a configurable threshold. If automatic downgrade occurs, the callback
MUST still increment the sequence number normally and SHOULD include the ``url`` attribute
pointing to where the full diff can be retrieved (the diff's own URL, as for a
low-granularity subscription). An implementation MAY add an informational header saying
that the callback was downgraded; it does not change the callback's meaning.

Callback Delivery Semantics
---------------------------

ActingWeb subscription callbacks provide **at-most-once** delivery semantics by default.
Implementations MUST NOT automatically retry failed callbacks unless explicitly configured
to do so with appropriate safeguards. The one exception is a permission callback
answered with ``503``, which the sender MAY resend a bounded number of times (see
Permission Callback). A resync that was not delivered MAY be sent again the next time
the publisher resumes the subscriptions (see Resync Callback); that is a new resync, not
a retry.

Every diff is recorded (with its sequence number) before its callback is sent, and stays
available to a poll until the subscriber clears it or fetches it by its own URL. That is
the recovery every implementation has: a subscriber that misses a callback, for whatever
reason, finds the diff by polling. A change whose diff can be neither recorded nor
given its sequence number is not silently dropped: the actor answers the request that
made the change with an error (a 5xx, 503 Service Unavailable for a storage fault). The
subscriber may then not learn of that change until a resync.

A publisher MAY send the callbacks for one change to different subscribers concurrently,
and MAY bound how many it sends at a time and how long it waits for them; whether and how
it does so is an implementation matter. The callbacks for one subscription MUST carry its
sequence numbers in the order the diffs were recorded, but a subscriber MUST NOT assume
they arrive in that order: two changes in quick succession may be delivered out of order,
and the sequence number orders them. Where a publisher sends one subscriber two callbacks
that depend on each other (the ``clear`` and the full state of Resync Callback), it MUST
send the second only after the first was answered with a 2xx; if the first was not,
the second is not sent.

**Rationale**: Automatic retries can cause:

- Duplicate processing if the receiver succeeded but the response was lost
- Cascading failures under load conditions
- Unpredictable ordering when combined with sequence numbers

**Recovery Mechanisms**

Receivers detecting gaps in sequence numbers have several recovery options:

1. **Polling**: Perform a GET on the subscription endpoint to retrieve missed diffs.
   This is the RECOMMENDED recovery mechanism.

2. **Resync Callback**: If the receiver advertises ``subscriptionresync``, the sender MAY
   send a ``type: "resync"`` callback to indicate the receiver should fetch full state.

3. **Sequence Gap Detection**: Receivers SHOULD track the expected next sequence number.
   When a gap is detected (received sequence > expected + 1), the receiver SHOULD
   initiate recovery via polling. Since callbacks can arrive out of order, a receiver
   MAY first hold a callback that arrives after a gap for a short time, applying it
   when the missing callbacks arrive, and poll only when they do not; it MAY bound how
   many callbacks it holds this way. Diffs a gap poll applies are applied like
   diffs from callbacks (the subscriber's reactions to a diff run for them too), and
   the callback that revealed the gap is applied unless the poll already brought it.

**Implementation Guidance**

Implementations wanting stronger delivery guarantees SHOULD:

- Use ``granularity="low"`` to reduce payload size and enable reliable fetching
- Implement idempotent handlers that can safely process duplicate callbacks
- Use subscription polling as a periodic backup mechanism
- Consider the ``subscriptionresync`` option for bulk operation scenarios

Optional Delivery Mechanisms
----------------------------

The mechanisms in this section (payload limits, back-pressure, a circuit breaker and
compression) are OPTIONAL. An implementation that offers none of them conforms to this
specification: the recorded diff and polling, described above, are the recovery every
implementation has. Where an implementation offers one, it follows the rules here so that
its peers can rely on what it does.

Callback Payload Limits (OPTIONAL)
----------------------------------

Implementations MAY enforce a maximum callback payload size. The RECOMMENDED limit,
for an implementation that enforces one, is **256KB** for the complete callback JSON body.

**When Payload Exceeds Limit**

For regular properties, when the payload would exceed the configured limit, an actor
that enforces a limit MAY either:

a. Send a ``type="resync"`` callback with a ``url`` attribute pointing to the full state, OR
b. Automatically use ``granularity="low"`` semantics for this specific callback

For list properties the reference form (see List Property Subscriptions) is the defined
way to send a diff whose values are too large. With large batch operations (e.g.,
``extend`` with many items), the actor MAY instead split the operation into multiple
callbacks. An actor that splits:

- MUST give each callback its own sequence number
- MUST make the ``operation`` field accurately reflect each partial operation, so that a
  receiver applies each part as an ordinary diff of that operation (several ``extend``
  diffs in a row, for example)

An implementation MAY add informational headers to a callback whose payload was modified
due to size limits (for example the original size). They are informational only and do
not change the callback's meaning.

Callback Back-Pressure (OPTIONAL)
---------------------------------

Actors MAY implement back-pressure signaling to handle overload conditions gracefully.
This section describes RECOMMENDED patterns for back-pressure handling. A sender that does
not implement them treats a ``429`` or ``503`` answer as a failed delivery, like any other
non-2xx answer: the diff stays recorded and the subscriber recovers it by polling.

**HTTP Response Codes for Back-Pressure**

``429 Too Many Requests``
  Indicates the receiver is temporarily overwhelmed and cannot process callbacks at the
  current rate. A receiver MAY answer it; a receiver that holds out-of-order callbacks
  MAY instead refuse a callback it cannot hold with ``400`` (see Getting the Updates).
  A sender that acts on it SHOULD:

  - Temporarily stop sending callbacks to this subscription
  - Store the diff in the subscription's pending data for later delivery or polling
  - Retry after the period specified in the ``Retry-After`` header

  Example response::

    HTTP/1.1 429 Too Many Requests
    Retry-After: 30
    Content-Type: application/json

    {"error": "rate_limit_exceeded", "retry_after": 30}

``503 Service Unavailable``
  Indicates the receiver could not process this callback now. It does not by itself mean
  the whole actor is unavailable: a receiver answers 503 for conditions of one callback
  (the same sequence is being processed, a storage fault, a failed fetch from the
  publisher), with ``Retry-After``. A sender that acts on it SHOULD:

  - Back off callbacks to this subscription, for the ``Retry-After`` period when one is
    given; it MAY extend this to all callbacks to the actor when 503 answers persist
    across subscriptions
  - Accumulate diffs for later delivery via polling
  - Implement exponential backoff for retry attempts

  Example response::

    HTTP/1.1 503 Service Unavailable
    Retry-After: 120

**Sequence Number Handling During Back-Pressure**

When back-pressure is active, the sender MUST continue incrementing sequence numbers
for each change. The diffs MUST remain available via GET on the subscription endpoint.
Receivers can detect missed callbacks via sequence gaps and fetch via polling.

**Circuit Breaker Pattern**

Implementations MAY implement a circuit breaker pattern for callback delivery:

- **Closed** (normal operation): Callbacks are sent normally
- **Open** (after N consecutive failures, RECOMMENDED: 5): Stop attempting callbacks
  for a cooldown period (RECOMMENDED: 60 seconds)
- **Half-Open** (after cooldown): Attempt a single callback; if successful, return to
  Closed; if failed, return to Open with extended cooldown

During the Open state, diffs accumulate and are available via polling. This prevents
cascading failures when a peer is experiencing problems.

Callback Compression (OPTIONAL)
-------------------------------

An actor that advertises the ``callbackcompression`` option tag MUST accept compressed
callback payloads using standard HTTP content encoding; an actor that does not advertise
it MAY accept them, but a sender MUST NOT rely on that.

**Requesting Compression Support**

When creating a subscription, the requesting actor MAY indicate compression support
by including an ``accept_encoding`` attribute::

  {
    "target": "properties",
    "subtarget": "data",
    "granularity": "high",
    "accept_encoding": ["gzip", "br"]
  }

The ``accept_encoding`` array lists supported compression algorithms in order of preference.
Supported values are: ``gzip``, ``br`` (Brotli), ``deflate``. A publisher that does not
compress ignores the attribute.

**Sending Compressed Callbacks**

When the receiver supports compression and the payload exceeds a threshold (RECOMMENDED: 1KB),
the sender SHOULD compress the payload::

  POST /callbacks/subscriptions/peer123/sub456
  Content-Type: application/json
  Content-Encoding: gzip

  [gzip-compressed JSON body]

**Requirements**

- A sender MUST NOT compress a callback to a receiver that does not advertise the
  ``callbackcompression`` tag
- Compression MUST NOT change the logical content or affect sequence numbering
- If compression fails or is unavailable, the sender MUST fall back to uncompressed delivery
- The ``Content-Length`` header MUST reflect the compressed size
- A receiver that advertises ``callbackcompression`` MUST handle both compressed and
  uncompressed callbacks regardless of subscription settings (compression is a hint, not
  a guarantee)

Subscription Scope and Overlap
------------------------------

A peer MAY hold several subscriptions at the same actor whose scopes overlap.

**Scope Hierarchy**

Subscriptions have a natural hierarchy based on specificity:

1. Target only (e.g., ``properties``) - broadest scope
2. Target + subtarget (e.g., ``properties/config``) - medium scope
3. Target + subtarget + resource (e.g., ``properties/config/theme``) - narrowest scope

A broader subscription includes all changes that would be covered by narrower
subscriptions within its scope.

**Each Subscription Is Delivered Independently**

The publisher processes each subscription on its own (see The Diff and Update Model).
When a change matches several subscriptions from the same peer, each of them gets its
own diff, with its own sequence number, shaped for its level, and its own callback
according to its granularity. The publisher does not merge or suppress them: nothing on
the wire marks two diffs on different subscriptions as the same change.

**The Subscriber Applies a Change Once**

A subscriber holding overlapping subscriptions MUST apply each change to its state once.
Applying it from each subscription would, for example, append a list item twice. Since
the two diffs cannot be matched on the wire, the subscriber decides by subscription: it
SHOULD store from the subscription to the whole target and not from a narrower
subscription to the same peer (a narrower subscription's diffs are then received and
answered, but not stored a second time), whatever the granularity of each. A subscriber
MAY use the narrower subscription's callbacks for other purposes (for example to react
to changes in one sub-target only).

**Example**

::

  Peer has subscriptions:
  - Sub A: target=properties (all properties)
  - Sub B: target=properties, subtarget=config

  Change occurs to "config" property

  Result: a callback on Sub A ({"config": ...}) and one on Sub B (the config
  value itself); the peer stores the change from Sub A only

  Change occurs to "profile" property

  Result: ONE callback, on Sub A (only matching subscription)

**Rationale**

This behavior:

- Keeps each subscription's sequence numbers complete, so gap detection works per
  subscription
- Leaves the choice of which subscription to store from to the subscriber, which knows
  why it holds each one
- Requires no state at the publisher that relates one subscription to another


Security Considerations
=======================

There are many security considerations, some are well known for
any http-based communication, while some are specific to ActingWeb, in
particular the trust model.

Any non-trivial implementation MUST use https. Some of the validation of
peers MAY be based on validation of server-side certificates. This require
proper configuration of the web server hosting the mini-app.

Validation and approval of a relationship MAY be based on four elements:

1. Root host of the requesting actor (confirmed by TLS certificate)
2. Callback verification
3. Explicit approval list, static or dynamic, of peer root URL
4. Manual approval

The use of a bearer token in the http Authorization header is subject to the 
same security concerns as OAuth2 Bearer tokens. 

Care must be taken to make sure that the bearer token is sufficiently random and 
long enough for the security level required.

There is no expiry of ActingWeb peer tokens. However, the relationship can be 
terminated at any time and thus offers a revocation method. Also, a mini-app
MAY enforce automatic expiry of relationships and thus force a new trust
establishment flow.

What belongs to the creator and the trustee (the passphrase, the right to
change the trustee root or the creator, and the shared secrets of other
peers) MUST NOT be given to a peer of any relationship type, since a peer
could keep using it after its relationship was deleted. A peer's
relationship name never gives it the access of the creator or the trustee
(see Types of Relationships).

**Storage faults**

An actor that cannot complete a request because of a temporary storage
fault SHOULD answer 503 Service Unavailable with a ``Retry-After`` header,
and MUST NOT answer as if the request succeeded or as if the data did not
exist (a 404 Not Found or an empty result would tell the caller something
false). A client or peer SHOULD retry such a request later.

**Use of HTTP methods**

Some firewalls and proxies may filter http methods like PUT and DELETE
and may only allow GET and POST. Also, some application frameworks or
browsers may not support other methods. An actor MAY accept the parameter
\_method='true\_method' (and MAY accept the http header
X-HTTP-Method-Override: 'true\_method') as an alternative way to specify the
intended http method, typically on a GET or a POST from a browser form; it
need not accept it on every path or for every method. A client MUST NOT
depend on it.

A request whose ``_method`` makes it change state is subject to cross-site
request forgery: a page on another site can make a browser send it with
the user's credentials. An actor that accepts ``_method`` on a GET MUST
refuse such a request when the browser marks it as coming from another
site (for example by the ``Sec-Fetch-Site`` header or the ``Origin``
header), and SHOULD apply the same check to state-changing form POSTs that
rely on browser credentials.


IANA Considerations
===================

Currently, ActingWeb.org controls the namespaces that IANA might be
responsible for. Dependent on how this specification is moved forward,
that may or may not change.

References and Endnotes
=======================
