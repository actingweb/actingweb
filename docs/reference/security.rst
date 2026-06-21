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

