# Four per-process caches on the permission path grow with traffic, not config

Found by the 3.14.4 scalability review
(`thoughts/plans/2026-09-02-identifier-matching-and-metadata-fidelity.md`),
which bounded the one cache that was in the changed function
(`PermissionEvaluator._pattern_cache`, cleared past 1024 entries) and left
these. Verified at the 3.14.4 tree.

- `actingweb/trust_permissions.py:97` — `TrustPermissionStore._cache`, keyed
  per `(actor, peer)`.
- `actingweb/peer_profile.py:113` — `PeerProfileStore._cache`.
- `actingweb/peer_permissions.py:226` — `PeerPermissionsStore._cache`.
- `actingweb/peer_capabilities.py:480` — `PeerCapabilitiesStore._cache`.

Each is a plain dict on a config-bound singleton with no size bound and no
TTL-driven eviction of the *key* (some entries carry a TTL, the dict keeps the
slot). In a long-lived process serving many actors the working set is the
number of distinct trust pairs ever seen. `[[mcp-cache-lifecycle-and-revocation]]`
§2 (cross-process invalidation) is the design that would replace them; until
then a bound plus LRU on each is the cheap holding fix.
