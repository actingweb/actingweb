=====================
Security Cheatsheet
=====================

Quick, practical defaults for secure apps.

Properties and Hooks
--------------------

- Return `None` from a property hook to hide/deny:
  - GET → hide property in UI and API
  - PUT/POST → make property read-only/immutable
- Store sensitive data in Attributes (buckets), not regular properties.

Access Control
--------------

- Prefer built-in trust types: `viewer`, `friend`, `partner`, `admin`, `mcp_client`.
- Add custom trust types only when necessary; use pattern-based permissions.
- Precedence: Explicit deny > explicit allow > trust type allow > default deny.
- **Permission merging**: Individual overrides UNION with base patterns (fail-safe).
- To restrict access, use `excluded_patterns`; base `patterns` cannot be narrowed.
- Use `merge_base=False` only when explicit full override is needed.
- **Resource URI patterns are not normalised.** ``notes://`` is matched as
  ``notes://*``, and a target such as ``notes://../../security/key`` matches
  it: ``..`` segments and percent-encoding are not resolved. A resource
  reader that maps URIs to storage validates its own path.
- **A GET never changes state from another site.** Every handler that
  honours a ``_method`` override on ``GET`` refuses one that carries an
  ambient credential (the session cookie, or basic auth) unless the
  request shows it came from the application's own pages
  (``Sec-Fetch-Site: same-origin``, or a same-origin ``Origin`` or
  ``Referer``); a request with none of these passes unless it carries the
  session cookie. Web UI ``POST`` forms are refused when the browser
  reports a cross-site request, and the integrations do not let the
  session cookie, or a Basic header (except on ``/oauth/token``),
  authenticate a
  state-changing request another site (sibling subdomains included)
  started. Both rely on the
  browser's ``Sec-Fetch-Site``, ``Origin`` and ``Referer`` reaching the
  application: do not strip them at a proxy. A cross-site request with
  cached basic-auth credentials and no browser headers at all passes:
  prefer OAuth2 sessions for browser use.
- **Peer-supplied trust fields are shapes, not markup.** A peer's id and
  base URI are checked when trust is requested in either direction and when
  a peer changes its base URI (an id of letters, digits and
  ``_ . : @ + = -``; a plain ``http(s)`` base URI).
  Templates of your own must not interpolate values inside inline event
  handlers: HTML escaping does not protect a JavaScript string there; use a
  ``data-`` attribute.
- **REST property permission checks fail closed.** When the permission
  check itself raises for a peer (the evaluator cannot be built, or the
  legacy check behind a no-rule result raises), the property, list-metadata
  and list-item handlers deny (403) rather than answer with the legacy
  ``access`` table; a database fault still answers 503. An error inside rule
  evaluation already denies.
- **MCP ``*/list`` filters fail closed.** When the permission evaluator
  cannot be constructed, ``tools/list``, ``resources/list`` and
  ``prompts/list`` answer an empty list; an item whose evaluation raises is
  left out. A database fault still answers 503.

MCP Multi-Client Trust
------------------------

- **``v3.13.0rc3`` fixed an MCP trust-cache authorization bypass** affecting
  every release from ``v3.3`` (2025-10-04) through ``v3.13.0rc2`` (roughly
  ten months): on an actor with more than one registered MCP client, one
  client's resolved trust/permissions could be served to a different
  client's requests once the cache was warm. See the ``SECURITY`` section
  of ``CHANGELOG.rst`` and ``docs/migration/v3.13.rst`` before upgrading a
  deployment that predates ``rc3`` and serves multiple MCP clients per
  actor.
- **Trust-row client metadata is not an audit trail.** ``client_name``,
  ``client_version``, ``client_platform``, ``last_accessed``, and
  ``last_connected_via`` are a live cache, overwritten by whichever client
  last connected — they reflect *current* state only. For any trust row
  touched during the affected window above, historical values of these
  fields may reflect a different client than the one that actually holds
  the credential; current values self-heal on that client's next request.
- Missing/unresolvable trust is fail-closed (no access), not fail-open,
  as of ``rc3`` — see :doc:`../guides/troubleshooting` if an MCP client
  unexpectedly sees an empty tool list or ``-32003`` after upgrading.

OAuth2
------

- Always validate provider config; use the provider-agnostic factory.
- **Close the actor factory when OAuth is the sign-in.** The actor factory (``POST /``) creates an actor for any address from unauthenticated input. An OAuth-only deployment should call ``with_open_factory(False)``; see :doc:`../quickstart/configuration`.
- **Creator uniqueness is on by default** (3.16; ``with_unique_creator(False)`` opts out). It makes the database hold one actor per creator (a ``creators`` table written in the same transaction on DynamoDB, a partial unique index on PostgreSQL), which closes the check-then-create race two concurrent sign-ins or factory posts could both win. A second create for a held creator is refused whatever the passphrase (the factory no longer returns the existing actor for a matching passphrase, which also removes a passphrase-guessing oracle), and the factory form redirects to ``/login`` without naming an actor id. Run ``actingweb-unique-creators report``, ``resolve --apply`` and ``enable --apply`` before the deploy; the application refuses to start until the database enforces it. See :doc:`../migration/v3.16`.
- **A sign-in that proves an address does not inherit an unvouched actor** (3.16). Every actor records how it was created in ``auth_method`` (``_internal`` store). An actor is *vouched* when that value is a non-empty string other than ``factory``, ``email_unverified`` or ``creator_changed`` **and** ``email_verified`` is not ``"false"``; an actor with no marker (created before 3.16) is unvouched. A creator set through ``PUT /<id>/trust/trustee`` is marked ``creator_changed`` (except ``trustee`` and the actor's own stored email; with ``force_email_prop_as_creator`` any other address is refused), so renaming one's own actor to someone else's address does not hand it to them vouched. When a provider login, or the emailed verification link, proves the creator address over an unvouched actor, the actor is **replaced** if it was created through ``POST /`` (marker ``factory``: deleted and recreated, so the owner gets a new actor id) and otherwise **cleaned in place**: passphrase rotated, every trust relationship, subscription, SPA session and MCP token removed, properties kept and their names reported to the ``actor_adopted`` hook, then marked vouched. The actor's registered OAuth2 clients are deleted with it. No request leaves the process during either, because the peer URLs on an unvouched actor were chosen by whoever created it. If the wipe cannot be confirmed (a read on the way faults, which raises ``DbError`` under the 3.16 fault contract, or a write or delete it relies on cannot be confirmed: the marker is read back and the session revoke confirms each delete), the sign-in fails closed and the next one retries; a replacement that stopped part-way is finished by the next sign-in. ``actingweb-mark-actors-vouched`` (run with 3.16 installed, before the first sign-in) marks actors you know are legitimate so a sign-in leaves them alone. With ``with_unique_creator()`` a replacement moves the creator from the ``factory`` actor to its successor in one database step before removing it; if the creator no longer names that actor, the sign-in looks up once more and signs in to the actor a concurrent sign-in created, and otherwise fails closed. A vouch is bound to the address it proved (``vouched_creator``), so a rename landing during a sign-in, or two concurrent renames, never leave an actor vouched under an address nobody proved; the emailed link proves only the address it was sent to. **Limitations:** a provider access token or ``oauth_token`` cookie matched by email in ``auth.py`` does not adopt; sibling actors that share a creator (``unique_creator`` off, the opt-out) are not touched; with ``unique_creator`` off two concurrent first sign-ins may both run the rule (a replacement reuses a successor the other one already created, which narrows but does not close the race; with it on, the database refuses the second); properties a squatter prefilled on a cleaned-in-place actor are reported, not removed. ``devtest`` must be off: it lets a caller write ``_internal``, including ``auth_method``.
- Google: refresh tokens available; GitHub: no refresh tokens.
- GitHub: only verified primary emails are accepted for actor linking. Unverified primary emails are skipped to prevent account-linking attacks via the GitHub ``/user/emails`` API.
- Expect 401 at protected endpoints with a proper `WWW-Authenticate` header.
- When multiple providers are configured, 401 redirects go to the factory login page (not directly to a provider) to let the user choose.
- **SPA/mobile session tokens** (``/oauth/spa/token``) use single-use rotating refresh tokens with reuse detection. A reuse beyond the grace window (60 seconds by default; see below) revokes only the offending **rotation family** (the lineage from one login), not all of the actor's tokens — so one stale/leaked token can't log the user out everywhere. Within the grace window a reuse still gets a full rotation, so a client that dropped a rotation recovers. Clients should single-flight refreshes and treat a ``401`` as "session expired" (route to login), never leaving a blank page. See :doc:`../guides/spa-authentication`.
- **Logout and revoke end the refresh chain** (3.15.1). ``/oauth/logout`` and ``/oauth/revoke`` revoke the whole refresh-token chain of the presented access or refresh token, on the same fault contract as the MCP store: a store fault answers 503 with ``Retry-After: 5`` and keeps the token as the retry handle, never a false "logged out". Login access tokens carry their chain id, so an access token can end its chain, and the theft response kills it too. On DynamoDB this is one scan of the two SPA token buckets per call, acceptable while they stay under about 1 MB (about 3,000 rows); a WARNING is logged when one bucket passes 1,000 rows, and a GSI on a promoted ``chain_id`` is the growth path. PostgreSQL uses an index. See :ref:`spa-logout`.
- **The refresh grace period** is 60 seconds by default for both grants and is set with ``ActingWebApp.with_refresh_token_grace(seconds)``, from 0 to 60 (``ValueError`` outside that range, wherever it is set). Inside it, whoever presents a consumed token gets a new branch of the rotation family, which reuse detection flags only if that branch later replays one of its own consumed tokens; a lower value narrows that window. ``0`` means no grace: every reuse inside the two-day reuse window is answered as theft and its chain revoked, which also signs out a client's own concurrent duplicate and a retry of a refresh that consumed its token but failed to store the new one; of two requests presenting the same token at once, the one that consumed it may keep its new tokens, depending on timing, so ``0`` does not reliably stop a simultaneous replay (see :ref:`spa-refresh-grace`). A client that loses a refresh response across a sleep is not helped by any allowed value; see :ref:`spa-refresh-reliably`.
- **MCP refresh tokens** (``/oauth/token``) rotate the same way since 3.15: single-use, a grace period (60 seconds by default) in which a replay rotates again, a two-day window in which a replay revokes the chain and answers ``400 invalid_grant`` (the SPA endpoint answers 401; the MCP endpoint follows RFC 6749 §5.2). Authorization codes are single-use atomically, and the built-in authorize pages require PKCE ``S256``. Public MCP clients (``token_endpoint_auth_method: none``) are supported and must use PKCE.
- **Revocation is per process**: rotating or revoking an MCP token clears the MCP cache of the process that did it; other workers or containers may honour a revoked access token for up to 300 seconds from their own cache.
- **A token-store fault fails closed**: ``/mcp`` answers 503 rather than treating an unreadable store as an invalid token, and ``validate_mcp_token`` raises ``TokenStoreUnavailable``.
- **Used refresh tokens** are retained only for a short reuse-detection window (``SPA_REFRESH_TOKEN_REUSE_WINDOW``, 2 days) and purged automatically; ensure DynamoDB TTL is enabled on the attributes table (PostgreSQL purges itself). See :doc:`../guides/database-maintenance`.

Trust API and client-supplied text
----------------------------------

- ``GET /{actor_id}/trust`` never returns ``secret`` or ``verification_token``; the per-relationship GET returns them to creator and admin only.
- MCP ``clientInfo``, registration ``client_name`` and User-Agents are client-supplied and unauthenticated. ActingWeb sanitises them (``actingweb.client_text``) before storing, logging or returning them, and the trust GET routes sanitise ``desc`` too. Treat them as untrusted text anyway when you render them, especially into LLM context.

Logging
-------

- The peer proxy (``actingweb.aw_proxy``), the MCP authorize endpoint and the FastAPI trust routes log request bodies as a summary (``keys=[...] bytes=N``), never their values. Key names of a property write are property names; keep ``actingweb.aw_proxy`` above DEBUG in production if those are sensitive.

Mobile OAuth2
-------------

- **PKCE recommended**: Use PKCE (``S256``) for mobile apps even when ``client_secret`` is available. Mobile apps are public clients and PKCE prevents authorization code interception.
- **Custom URL scheme security**: Ensure only your app registers a given custom URL scheme (e.g., ``io.actingweb.myapp://callback``). On Android, use App Links (verified ``https://`` schemes) when possible for stronger guarantees.
- **BFF pattern**: The backend holds the ``client_secret``; the mobile app never sees it. The authorization code is exchanged server-side via ``POST /oauth/spa/token``.
- **Token storage**: Use platform-secure storage -- iOS Keychain Services and Android Keystore / EncryptedSharedPreferences. Never store tokens in plain SharedPreferences or UserDefaults.
- **Redirect URI validation**: The ``redirect_uri`` is validated at the OAuth provider level. Register only the exact custom URL scheme in the provider's console; ActingWeb passes it through during code exchange.

Custom Routes
-------------

- For custom routes, use `auth.check_and_verify_auth()` instead of ad-hoc authentication.
- Always validate the `actor_id` parameter matches the authenticated user.
- Handle OAuth2 redirects properly (302 responses with Location header).

Web UI
------

- Enable UI only when needed; it enforces OAuth2 when configured.
- Never use relative links in templates; use `actor_root` and `actor_www`.

Data Backend
------------

- Local dev: use DynamoDB Local with `AWS_DB_HOST` set.
- Production: use IAM with least privilege and do not set `AWS_DB_HOST`.
- Production with IaC-managed tables: set ``AWS_DB_AUTO_CREATE_TABLES=false``
  (or ``with_dynamodb(auto_create_tables=False)``) and drop
  ``dynamodb:CreateTable`` and ``dynamodb:DescribeTable`` from the runtime
  role.
- **Data mapping / GDPR**: indexed property values (emails, OAuth IDs)
  used for reverse lookup are stored in the DynamoDB lookup table only as
  SHA-256 digests — no plaintext copy. This is pseudonymisation, not
  anonymisation: low-entropy values remain dictionary-attackable, and the
  properties table itself stores values in plaintext, so include *both*
  tables in your data map. On PostgreSQL the lookup table stores plaintext
  values (same database and access surface as the properties table).

