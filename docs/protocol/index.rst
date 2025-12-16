======================
Protocol Specification
======================

**Audience**: Protocol implementers and those who want to understand the ActingWeb protocol itself.

The ActingWeb protocol is an implementation-agnostic specification for building distributed, actor-based systems. Each actor instance has a unique URL and communicates with other actors through RESTful endpoints.

Overview
========

ActingWeb is a protocol for distributed micro-services where each user gets their own "actor" instance with a unique URL. The protocol defines:

- **Actor Identity**: Each actor has a unique root URL (e.g., ``https://domain.com/actor-id``)
- **REST Endpoints**: Standard endpoints for properties, trust relationships, subscriptions, and callbacks
- **Trust Relationships**: Symmetric trust establishment between actors
- **Subscriptions**: Event notification system for property changes
- **Authentication**: Multiple auth methods (basic, OAuth, OAuth2)

Contents
========

.. toctree::
   :maxdepth: 2

   actingweb-spec

Key Concepts
============

Actors
------

An actor represents a user or service instance. Each actor:

- Has a unique URL (``https://domain.com/<actor_id>``)
- Maintains its own state (properties)
- Can establish trust with other actors
- Can subscribe to events from trusted peers

Standard Endpoints
------------------

Every actor exposes these REST endpoints:

- ``/meta`` - Actor metadata and discovery
- ``/properties`` - Key-value storage
- ``/trust`` - Trust relationship management
- ``/subscriptions`` - Event subscription management
- ``/callbacks`` - Incoming event notifications

Trust and Permissions
---------------------

Trust relationships are symmetric - both actors must approve. Trust enables:

- Permission-based access to properties
- Event subscriptions
- Secure data sharing

See the full specification for complete details.
