# Subscription docs: callback status codes and `FanOutManager` samples

**Found** 2026-11-13 while `thoughts/plans/2026-11-13-attribute-list-v2-port.md`
(Phase 4) updated `docs/guides/subscriptions.rst`; not changed by that plan,
whose diff does not touch the handler's status codes or `FanOutManager`.
Verify each against the tree before editing.

- The subscription callback handler answers 204 (handled), 503 with
  `Retry-After` (another delivery in progress) or 400 (back-pressure
  included); it never answers 201, 202 or 429. The status table in
  `docs/guides/subscriptions.rst`, its back-pressure/429 sections, the
  asserts shown in `docs/contributing/testing.rst` (about lines 516 and
  534-551) and the troubleshooting entry "Subscriber Returning 429" say
  otherwise.
- The `FanOutManager` samples in `docs/guides/subscriptions.rst` do not match
  the class: its constructor keywords differ, the method is
  `deliver_to_subscribers`, the result fields are `total`, `successful` and
  `failed`, and `get_circuit_breaker_status()` takes no peer. `spec-1-5`
  removes `FanOutManager`; if it lands first, delete the samples instead.
- `docs/migration/v3.10.rst` keeps the old `auto_delete_on_revocation` text
  and a positional `apply_callback_data("items", ...)` call: a historical
  guide, so at most a note that 3.16 changed both.
