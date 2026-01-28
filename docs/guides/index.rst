======
Guides
======

**Audience**: App developers who want to learn about specific ActingWeb features in depth.

This section provides detailed guides for implementing ActingWeb features in your application.

Contents
========

.. toctree::
   :maxdepth: 2

   authentication
   oauth2-setup
   spa-authentication
   access-control-simple
   access-control
   trust-relationships
   subscriptions
   property-lists
   hooks
   async-hooks-migration
   mcp-quickstart
   mcp-applications
   web-ui
   service-integration
   database-maintenance
   postgresql-migration
   logging-and-correlation
   troubleshooting

Authentication & Authorization
==============================

- **Authentication** - Overview of ActingWeb's authentication system (basic, OAuth, OAuth2)
- **OAuth2 Setup** - Configure OAuth2 with Google, GitHub, or custom providers
- **SPA Authentication** - Single Page Application authentication patterns, including browser redirect behavior
- **Access Control (Simple)** - Quick guide to ActingWeb's unified access control
- **Access Control** - Detailed guide to permissions, trust types, and access patterns

Trust & Relationships
=====================

- **Trust Relationships** - Establishing and managing trust between actors
- **Subscriptions** - Event notification system for property changes

Data Management
===============

- **Property Lists** - Working with list-type properties and metadata
- **Hooks** - Implementing lifecycle hooks for custom business logic
- **Async/Await Hooks Migration** - Migrating to async hooks for better performance with FastAPI

Integration
===========

- **MCP Quickstart** - Quick start guide for Model Context Protocol integration
- **MCP Applications** - Building AI-accessible applications with MCP
- **Web UI** - Server-rendered web interface templates and SPA mode configuration
- **Service Integration** - Integrating ActingWeb with external services

Operations
==========

- **Database Maintenance** - TTL configuration and cleanup for both DynamoDB and PostgreSQL
- **PostgreSQL Migration** - Complete guide for migrating from DynamoDB to PostgreSQL
- **Logging and Request Correlation** - Request tracing and context-aware logging for debugging

Troubleshooting
===============

- **Troubleshooting** - Common issues and solutions
