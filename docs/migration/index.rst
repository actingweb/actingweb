=================
Migration Guides
=================

**Audience**: Users upgrading from previous versions of ActingWeb.

This section provides guides for migrating between ActingWeb versions and avoiding common pitfalls.

Contents
========

.. toctree::
   :maxdepth: 2

   v3.14
   v3.13
   v3.11
   v3.10
   v3.7
   v3.1
   common-pitfalls

Version Migrations
==================

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
