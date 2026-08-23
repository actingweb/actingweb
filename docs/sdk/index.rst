=================
SDK Documentation
=================

**Audience**: two groups, not one. **Developer API**, **Actor Interface**,
**Attributes and Buckets**, and **Authenticated Views** are core reference
for any application developer using ActingWeb -- the property/attribute/
trust/subscription APIs your hooks call every day, just documented in more
depth than the quickstart guides. **Handler Architecture**, **Custom
Framework Integration**, and **Advanced Topics** are for developers
extending ActingWeb itself or integrating a framework it doesn't ship
support for -- skip these unless you're doing that.

This section provides in-depth documentation for advanced users and developers building on top of ActingWeb.

Contents
========

.. toctree::
   :maxdepth: 2

   developer-api
   authenticated-views
   handler-architecture
   async-operations
   custom-framework
   actor-interface
   advanced-topics
   attributes-buckets

Overview
========

The ActingWeb SDK documentation covers:

**Developer API**
   The high-level interfaces (ActorInterface, PropertyStore, TrustManager, SubscriptionManager) used in hooks and custom code.

**Authenticated Views**
   Permission-enforced access patterns for peer and client access to actor resources.

**Handler Architecture**
   How ActingWeb's HTTP handlers work internally and delegate to the developer API.

**Async Operations**
   Async variants for peer communication in FastAPI and other async frameworks.

**Custom Framework Integration**
   Integrating ActingWeb with Django, Starlette, or other Python web frameworks.

**Actor Interface**
   Detailed reference for the ActorInterface wrapper class.

**Advanced Topics**
   Database operations, migrations, and low-level internals.

**Attributes and Buckets**
   A second, app-facing storage API alongside properties -- for data that
   should never be reachable through a trust relationship (secrets, service
   credentials, internal state), not an internal-only mechanism.

Learning Path
=============

For SDK developers, we recommend this order:

1. **Developer API** - Understand the core interfaces
2. **Authenticated Views** - Learn permission enforcement
3. **Handler Architecture** - See how handlers use the developer API
4. **Async Operations** - Master async patterns for peer communication
5. **Custom Framework** - Build integrations for other frameworks

Prerequisites
=============

Before diving into SDK documentation, you should:

- Complete the :doc:`../quickstart/index`
- Understand :doc:`../guides/trust-relationships`
- Be familiar with :doc:`../guides/hooks`

See Also
========

- :doc:`../quickstart/index` - Getting started guide
- :doc:`../guides/index` - Feature guides
- :doc:`../reference/index` - API reference
