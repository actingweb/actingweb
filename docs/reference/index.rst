==============
API Reference
==============

**Audience**: All users looking for detailed API documentation.

This section provides comprehensive reference documentation for ActingWeb's APIs, configuration options, and module interfaces.

Contents
========

.. toctree::
   :maxdepth: 2

   interface-api
   hooks-reference
   handlers
   routing-overview
   database-backends
   security
   actingweb
   actingweb-db

High-Level API
==============

**Interface API**
   Documentation for ``ActingWebApp``, ``ActorInterface``, and the modern fluent configuration API.

**Hooks Reference**
   Complete reference for all hook decorators and their signatures.

HTTP Handlers
=============

**Handlers**
   Reference for all HTTP handler classes and their methods.

**Routing Overview**
   Complete list of routes, browser redirect behavior, and content negotiation rules.

Database Backends
=================

**Database Backends**
   Detailed comparison of DynamoDB and PostgreSQL backends, performance characteristics, cost analysis, and migration guide.

Configuration & Security
========================

**Security**
   Security best practices and configuration checklist.

Module Reference
================

**actingweb**
   Auto-generated documentation for the actingweb package.

**actingweb.db.dynamodb**
   Documentation for the DynamoDB database backend.

Quick Links
===========

Common tasks and their reference sections:

+---------------------------+--------------------------------+
| Task                      | Reference                      |
+===========================+================================+
| Configure the app         | :doc:`interface-api`           |
+---------------------------+--------------------------------+
| Choose database backend   | :doc:`database-backends`       |
+---------------------------+--------------------------------+
| Register hooks            | :doc:`hooks-reference`         |
+---------------------------+--------------------------------+
| Understand routing        | :doc:`routing-overview`        |
+---------------------------+--------------------------------+
| Security checklist        | :doc:`security`                |
+---------------------------+--------------------------------+
| Handler methods           | :doc:`handlers`                |
+---------------------------+--------------------------------+

See Also
========

- :doc:`../quickstart/configuration` - Configuration guide
- :doc:`../guides/hooks` - Hooks tutorial
- :doc:`../sdk/developer-api` - Developer API guide
