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
- Google: refresh tokens available; GitHub: no refresh tokens.
- GitHub: only verified primary emails are accepted for actor linking. Unverified primary emails are skipped to prevent account-linking attacks via the GitHub ``/user/emails`` API.
- Expect 401 at protected endpoints with a proper `WWW-Authenticate` header.
- When multiple providers are configured, 401 redirects go to the factory login page (not directly to a provider) to let the user choose.
- **SPA/mobile session tokens** (``/oauth/spa/token``) use single-use rotating refresh tokens with reuse detection. A reuse beyond the ~60s concurrency grace window revokes only the offending **rotation family** (the lineage from one login), not all of the actor's tokens — so one stale/leaked token can't log the user out everywhere. Within the grace window a reuse still gets a full rotation, so a client that dropped a rotation recovers. Clients should single-flight refreshes and treat a ``401`` as "session expired" (route to login), never leaving a blank page. See :doc:`../guides/spa-authentication`.
- **Used refresh tokens** are retained only for a short reuse-detection window (``SPA_REFRESH_TOKEN_REUSE_WINDOW``, 2 days) and purged automatically; ensure DynamoDB TTL is enabled on the attributes table (PostgreSQL purges itself). See :doc:`../guides/database-maintenance`.

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

