# Six `get_bucket(...)` sites fold a fault into "empty"

Deferred from 3.14.4
(`thoughts/plans/2026-09-02-identifier-matching-and-metadata-fidelity.md`,
Phase 2), which made the distinction available: `DbAttribute.get_bucket()`
now returns `{}` for an empty bucket on **both** backends and reserves `None`
for a caught fault. Verified at the 3.14.4 tree.

- `actingweb/attribute_list_store.py:60`
- `actingweb/callback_processor.py:547`
- `actingweb/remote_storage.py:200` and `:297`
- `actingweb/fanout.py:256`
- `actingweb/oauth2_server/client_registry.py:272` (`list_clients_for_actor`,
  added 2026-09-27 from the PR #148 review). One layer up: it reads through
  `Attributes.get_bucket()`, which reports a backend fault as an empty
  bucket and exposes the difference only as `Attributes.loaded` (3.15).
  `if not bucket_data: return []` therefore reports "no clients" on a
  fault. Its only caller is `OAuthClientManager.list_clients` (display),
  so nothing acts on the empty answer today; the fix is `store.loaded`, as
  `ActingWebTokenManager._snapshot_bucket` does.

Each reads `db.get_bucket() or {}` and proceeds as if the bucket were empty
when it could not be read. Not a regression — before 3.14.4 `None` already
meant "empty or fault" on PostgreSQL — but the same shape 3.14.3's
`fetch_all_including_lists() ... or {}` had, which emptied a list. Audit each
site for what "empty" makes it do next (`fanout` and `callback_processor` act
on the result) and raise or bail on `None` where the action is not idempotent.
