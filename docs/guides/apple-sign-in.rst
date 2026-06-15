==================
Sign in with Apple
==================

ActingWeb supports **Sign in with Apple** as a first-class OAuth provider
alongside Google and GitHub, covering the web SPA flow, native iOS, Android
Capacitor (web flow), and the LLM-triggered (MCP) OAuth web form.

Apple's App Store Guideline 4.8 effectively requires offering Sign in with Apple
(or an equivalent privacy-preserving login) whenever you offer Google login in an
iOS app, so this is usually mandatory for Capacitor apps shipping Google login.

.. contents:: On this page
   :local:
   :depth: 2

Why Apple is different
======================

Apple departs from "generic OAuth2" in ways the library handles for you:

- **No userinfo endpoint.** All identity lives in the OIDC ``id_token`` (a JWT).
- **JWT ``client_secret``.** Every token / refresh / revoke request must carry a
  freshly-signed **ES256** JWT built from your Team ID, Key ID and ``.p8`` key
  (not a static string).
- **``response_mode=form_post``.** When ``name``/``email`` scopes are requested,
  Apple **POSTs** the authorization response to your ``redirect_uri``.
- **Dual ``aud``.** Native iOS uses the Bundle ID as ``client_id``; web/Android
  use the Services ID. Validation accepts a list of audiences.
- **Name/email only on first sign-in.** Apple includes the user's name only on
  the very first authorization; persist it on first contact.

Apple Developer Portal setup (runbook)
======================================

For a single product spanning web + iOS + Android Capacitor:

1. **App ID** (e.g. ``com.example.app``) with the *Sign In with Apple*
   capability, marked as **Primary**. This Bundle ID is the ``client_id`` for the
   native iOS plugin.
2. **Services ID** (e.g. ``com.example.web``), **associated with** the primary
   App ID, with your HTTPS return URLs registered. This is the ``client_id`` for
   the web SPA and the Android Capacitor web flow.
3. **Sign in with Apple key** (Keys → ``+`` → *Sign In with Apple*). Download the
   ``.p8`` **once**. Note its **Key ID**. This key is separate from any App Store
   Connect API key.
4. **Team ID** (top-right of the developer portal).

When the Services ID is associated with the primary App ID, the same Apple user
yields the **same ``sub``** across both audiences.

.. note::

   Apple's ``redirect_uri`` must be **HTTPS** — no ``localhost``, no IPs. For
   local development use a tunnel (ngrok/cloudflared) or a real subdomain with a
   certificate.

Configuring the library
=======================

.. code-block:: python

    from actingweb.interface import ActingWebApp

    app = (
        ActingWebApp(
            aw_type="urn:actingweb:example.com:myapp",
            fqdn="myapp.example.com",
            proto="https://",
        )
        .with_oauth(provider="google", client_id="...", client_secret="...")
        .with_apple_sign_in(
            client_id="com.example.web",          # Services ID
            audiences=["com.example.web",          # Services ID (web/Android)
                       "com.example.app"],         # Bundle ID (native iOS)
            team_id="ABCDE12345",
            key_id="KEY1234567",
            private_key_path="/etc/secrets/AuthKey_KEY1234567.p8",
            # Android Capacitor deep link (optional). Apple still POSTs to the
            # HTTPS callback; this is only the final app handoff:
            mobile_redirect_uri="io.example.app://callback",
        )
    )

Key points:

- ``client_id`` is the **Services ID**; ``audiences`` is the list of acceptable
  ``aud`` values (Services ID + Bundle ID). All audience entries are optional
  individually, but the list must be non-empty.
- The ``.p8`` key may be supplied as a **file path** (``private_key_path`` or the
  ``APPLE_PRIVATE_KEY_PATH`` env var) or an **inline PEM**
  (``private_key_pem`` / ``APPLE_PRIVATE_KEY_PEM``). The file path wins if both
  are set. The key is validated eagerly — an unreadable path or unparseable PEM
  raises ``ValueError`` at config-build time, not at first request.
- Setting ``mobile_redirect_uri`` also registers an ``apple-mobile`` provider for
  the Android flow. Apple's ``redirect_uri`` for both the authorize request and
  the token exchange remains the HTTPS ``/oauth/callback/apple``; the custom
  scheme is only the deep link the Capacitor app intercepts.

Environment variables
---------------------

.. code-block:: bash

    # File path wins over inline PEM if both are set
    export APPLE_PRIVATE_KEY_PATH=/etc/secrets/AuthKey_KEY1234567.p8
    # or
    export APPLE_PRIVATE_KEY_PEM="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----"

The flows
=========

Web SPA
-------

1. The SPA POSTs to ``/oauth/spa/authorize`` with ``provider=apple``. The library
   stores the full state server-side and returns an Apple authorization URL whose
   ``state`` is an opaque single-use nonce and whose ``response_mode`` is
   ``form_post``.
2. The browser authenticates with Apple; Apple **POSTs** ``code``, ``state``,
   ``id_token`` and (first sign-in only) ``user`` to ``POST /oauth/callback/apple``.
3. The library consumes the nonce (rejecting forged/replayed POSTs), exchanges the
   code with Apple using the ES256 ``client_secret``, validates the ``id_token``,
   merges the first-sign-in ``user`` name, creates/looks-up the actor, fires
   ``oauth_success``, and redirects back to the SPA with a session token.

Native iOS
----------

The Capacitor plugin returns an ``id_token`` directly. The app submits it to the
JWT-bearer grant (see :ref:`apple-jwt-bearer`).

Android Capacitor
-----------------

Android has no native Apple SDK, so the app opens Apple's web flow in a Custom
Tab. Apple POSTs to the HTTPS ``/oauth/callback/apple`` with ``provider=apple-mobile``;
the library persists the IdP ``code`` against an opaque **ticket** and deep-links
the app (``io.example.app://callback?ticket=...``) — **no ActingWeb token in the
deep link**. The app then redeems the ticket:

.. code-block:: text

    POST /oauth/spa/token
    {"grant_type": "apple_mobile_ticket", "ticket": "<ticket from deep link>"}

.. _apple-jwt-bearer:

Native id_token (JWT-bearer) grant
==================================

Native apps that already hold a provider ``id_token`` (Apple via the iOS plugin,
or Google via ``with_google_native``) exchange it for an ActingWeb session:

.. code-block:: text

    POST /oauth/spa/token
    {
      "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
      "provider": "apple-mobile",          # or "google-native"
      "assertion": "<the id_token JWT>",
      "nonce": "<the nonce the app sent to the IdP>"
    }

Security properties:

- The validator is selected by the declared ``provider`` and the token ``iss``
  **must** match that provider — a Google ``id_token`` submitted as
  ``apple-mobile`` is rejected.
- ``nonce`` is required and must match the token's ``nonce`` claim.
- Each ``id_token`` is single-use (replay-protected) within its validity window.

Configure Google native sign-in with:

.. code-block:: python

    app.with_google_native(
        client_id="WEB_CLIENT_ID.apps.googleusercontent.com",
        ios_client_id="IOS_CLIENT_ID.apps.googleusercontent.com",
        android_client_id="ANDROID_CLIENT_ID.apps.googleusercontent.com",
    )

The normalized ``user_info`` shape
==================================

Before ``oauth_success`` fires, the library normalizes provider-specific name
fields so your hook reads one shape regardless of provider:

==================  ===========================================
Field               Source
==================  ===========================================
``given_name``      Apple ``firstName`` / Google ``given_name``
``family_name``     Apple ``lastName`` / Google ``family_name``
``display_name``    derived, or GitHub ``name``
``email``           ``email`` claim (or merged from Apple ``user``)
``sub``             provider subject claim (passthrough)
==================  ===========================================

.. warning::

   Apple sends the user's name **only on the first sign-in**. Persist it then —
   you cannot retrieve it later (the user would have to revoke the app in iOS
   Settings to re-trigger first-login behavior).

Account deletion and token revocation
=====================================

Apple (Technote TN3194) requires apps to call Apple's ``/auth/revoke`` with the
user's refresh token when the account is deleted. The library's ``revoke_token()``
supports Apple's ES256 ``client_secret``; call it from your own ``actor_deleted``
hook (best-effort / rate-limited):

.. code-block:: python

    @app.lifecycle_hook("actor_deleted")
    def on_actor_deleted(actor):
        provider = actor.store.oauth_provider or ""
        refresh = actor.store.oauth_refresh_token
        if provider.startswith("apple") and refresh:
            from actingweb.oauth2 import create_apple_authenticator
            create_apple_authenticator(actor.config).revoke_token(refresh)

``actor.store.oauth_provider`` is written on every sign-in, so it reflects the
most recent provider.

MCP / LLM-triggered web form
============================

Apple is also offered in the LLM-triggered OAuth web form (MCP). The encrypted
MCP state is wrapped in the same server-side nonce so Apple's form_post callback
can dispatch back to the MCP completion path. Only the web ``apple`` variant is
offered in the form; ``apple-mobile`` / ``*-native`` variants are native-only.
