=================
Migration Guides
=================

**Audience**: Users upgrading from previous versions of ActingWeb.

This section provides guides for migrating between ActingWeb versions and avoiding common pitfalls.

.. warning::

   Every guide in this section shows the API **as it was** during that
   migration, not necessarily the current API. Code blocks here must not be
   copied into new code without checking against :doc:`../guides/index` or
   :doc:`../reference/hooks-reference`.

Contents
========

.. toctree::
   :maxdepth: 2

   v3.16
   v3.15
   v3.14
   v3.13
   v3.11
   v3.10
   v3.7
   v3.1
   common-pitfalls

Version Migrations
==================

**v3.16 Migration**
   Guide for upgrading to ActingWeb 3.16, a security release for the actor
   factory. An unauthenticated ``POST /`` could squat an address, and the
   owner's first OAuth login adopted the squatter's actor with the squatter's
   credentials still live. Every actor now records how it was created;
   a sign-in that proves an address over an actor nobody vouched for replaces
   it (factory-created) or cleans it in place (everything else, including
   every actor created before 3.16), with ``actingweb-mark-actors-vouched``
   to opt known-good actors out before the first sign-in. A creator changed
   over ``PUT /<id>/trust/trustee`` now unvouches the actor. Adds
   ``with_open_factory`` to close the factory, the ``actor_adopted`` hook, and
   ``prompt=select_account`` on the SPA sign-in. Database faults now raise
   ``DbError`` (answered 503 with ``Retry-After``) instead of reading as
   absence, which custom backends must follow. Creator uniqueness
   (``with_unique_creator()``, **on by default**) makes the database hold one
   actor per creator; the application refuses to start until Step 0 has run
   (``with_unique_creator(False)`` opts out). The
   legacy reverse lookup (GSI, v1 table, PostgreSQL scan,
   ``USE_PROPERTY_LOOKUP_TABLE``) is removed: ``check_ready()`` refuses a store
   whose indexed property names were never backfilled, and
   ``actingweb-property-lookup`` makes it ready.

**v3.15 Migration**
   Guide for upgrading to ActingWeb 3.15, a security release for the MCP
   OAuth2 server and the trust API. The trust list stops returning peer
   secrets, MCP refresh tokens become single-use, public MCP clients (such
   as Codex) work, and PKCE is enforced on the built-in sign-in pages.
   Connectors added before 3.15 that refresh without their issued secret
   (Codex) need to be removed and added again once. The refresh-token
   grace period becomes a setting (default unchanged), and the SPA guide
   gains how native clients avoid being signed out when a refresh response
   is lost to sleep.

**v3.14 Migration**
   Guide for upgrading to ActingWeb 3.14. Property lists are faster and
   cheaper to work with, especially for code that looks up items by
   position in a loop — the guide shows the new, faster way (``find()``,
   ``remove_where()``, ``update_where()``). Three small breaking changes,
   a fix for a permission gap that let read-only peers write to property
   lists, and a new command-line tool for finding leftover data from
   deleted actors (``actingweb-verify-orphans``).

**v3.13 Migration**
   Guide for upgrading to ActingWeb 3.13. It covers four largely independent
   pieces of work — the DynamoDB scalability change and its **required**
   reverse-lookup backfill, an MCP trust-cache authorization fix, the MCP
   ``structuredContent`` behaviour change, and the property-list storage
   format — and opens with a "Start here" section that says which of them
   apply depending on whether you are coming from 3.12.x or from one of the
   3.13 release candidates. **If you use list properties, do the sweep in
   step 1 before upgrading** — list reads now fail loudly on pre-existing data
   damage that earlier releases silently skipped past, so sweeping and
   repairing comes first.

**v3.11 Migration**
   Guide for upgrading to ActingWeb 3.11, covering the one new PostgreSQL
   migration (chain_id index), DynamoDB TTL for token cleanup, SPA/mobile
   refresh-token rotation hardening, the SPA OAuth redirect_uri allowlist, the
   removal of the optional MCP SDK objects, and the new Apple/GitHub/Google-native
   sign-in providers.

**v3.10 Migration**
   Guide for upgrading to ActingWeb 3.10, covering automatic subscription processing with CallbackProcessor, RemotePeerStore, FanOutManager, and peer capabilities.

**v3.7 Migration**
   Guide for upgrading to ActingWeb 3.7, covering developer API extensions for SubscriptionManager and TrustManager with cleaner APIs and automatic lifecycle hooks.

**v3.1 Migration**
   Guide for upgrading to ActingWeb 3.1, including changes to the developer API, unified access control, and handler architecture.

Common Issues
=============

**Common Pitfalls**
   Frequently encountered issues and their solutions when working with ActingWeb.

Migration Checklist
===================

When upgrading ActingWeb:

1. Read the relevant migration guide
2. Review breaking changes
3. Update your configuration
4. Test in development environment
5. Run your test suite
6. Deploy with monitoring

See Also
========

- :doc:`../quickstart/configuration` - Configuration reference
- :doc:`../guides/troubleshooting` - Troubleshooting guide
- `CHANGELOG <https://github.com/actingweb/actingweb/blob/master/CHANGELOG.rst>`_ - Full changelog
