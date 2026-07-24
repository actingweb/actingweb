# Remove the legacy property reverse-lookup machinery (next major release)

**Created:** 2026-07-23 (v3.13 development)
**Trigger:** the next major version bump

v3.13 made lookup-table (v2, digest-keyed) reverse lookup the default and
deprecated everything below. One major release later, remove:

1. **`PropertyLegacy` model + `PropertyIndex` GSI class**
   (`actingweb/db/dynamodb/property.py`) — with it, the legacy-mode table
   creation branch in `DbProperty.__init__` / `DbPropertyList.__init__`
   and the fail-fast RuntimeError for missing GSIs.
2. **The legacy code path in `get_actor_id_from_property`** (both
   backends): the `use_lookup_table=False` branch, and in PG the
   value-only sequential-scan fallback.
3. **The fallback tiers** in the lookup-mode read path:
   - tier 1: v1 lookup-table reads (`DbPropertyLookup.get_v1`, the v1
     `PropertyLookup` model, and the `_property_lookup` table docs),
   - tier 2: legacy GSI reads via `PropertyLegacy.property_index`.
4. **`use_lookup_table` config surface** — once there is only one
   mechanism, the flag, `with_legacy_property_index()`,
   `USE_PROPERTY_LOOKUP_TABLE`, and the mode-conditional in the pre-warm
   can all go (keep `with_indexed_properties()`).
5. **The direct-construction env fallback** in `DbProperty` /
   `DbPropertyList` (`USE_PROPERTY_LOOKUP_TABLE` read in `__init__`) —
   make config injection via the `actingweb.db` factories mandatory
   (raise on missing), per
   `docs/contributing/architecture.rst` "Avoid Direct Instantiation".
   ~40 test call sites construct accessors directly and need updating.

Release notes must tell legacy-GSI holdouts to migrate BEFORE upgrading
(the backfill script must still exist in the release they migrate on),
and remind GSI-cohort deployments they can drop the `property-index` GSI
from `<prefix>_properties` and the `<prefix>_property_lookup` (v1) table.

Related test surfaces to remove/simplify: the fallback tests in
`tests/test_lookup_migration.py`, the v1 tests in
`tests/test_property_lookup_v2.py::TestV1Fallback`, the legacy-mode
tests in `tests/test_property_lookup.py`, and the legacy-shape tests in
`tests/test_conditional_gsi_schema.py`.
