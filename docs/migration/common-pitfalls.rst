===============
Common Pitfalls
===============

Actor vs ActorInterface
-----------------------
- Use ``ActorInterface`` in applications. ``Actor`` is internal and may change.
- Import from ``actingweb.interface``; avoid reaching into core modules directly.

Hooks: returning None
---------------------
- Property hooks: ``None`` during GET hides the value; ``None`` during PUT/POST/DELETE denies the change.
- Wildcard hooks ("*") run after specific-name hooks; be explicit with path checks.

Properties vs Property Lists
----------------------------
- Regular properties: small key/value data; simple updates.
- Property lists (``actor.property_lists.<name>``): ordered collections that can grow beyond DynamoDB size limits; use for notes, events, logs.

Base paths in templates
-----------------------
- Never use relative paths like ``../www``. Use provided variables:
  - ``actor_root`` for non‑www routes (e.g., ``{{ actor_root }}/properties``)
  - ``actor_www`` for web UI routes (e.g., ``{{ actor_www }}/properties``)

OAuth providers
---------------
- GitHub: set ``User-Agent`` and ``Accept: application/json``; no refresh tokens.
- Email privacy: GitHub may not expose email; code handles fallbacks, but expect missing emails in tests.

DynamoDB local vs AWS
---------------------
- Use DynamoDB Local for development; set local AWS env vars (no real credentials needed).
- In AWS, create tables and least‑privilege IAM policies before load. Monitor item size limits and indices.

Devtest endpoints
-----------------
- Dev only. Enable with ``with_devtest(True)``. Hidden from API docs; see CONTRIBUTING for details.

