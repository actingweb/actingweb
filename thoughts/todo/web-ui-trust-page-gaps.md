# The web UI's trust page gaps

Found by the browser walk of `verifications/2026-11-09-peer-authorisation-fixes-reverify-6.md`
(demo in local QA mode, `/<id>/www/trust` and `/<id>/www/trust/new`). All
four predate the peer-authorisation plan; none is on its path. The demo's web
UI is the library's (`actingweb/templates/aw-actor-www-trust*.html`,
`actingweb/handlers/www.py`), so a fix lands in the library.

- **Peer approval is never shown (medium).** A row's Status shows only the
  own side's approved/pending and verified; `peer_approved` is not
  rendered, so "approved by me, waiting on the peer" and "mutual" look the
  same. Screenshot evidence in the verification's QA run (03, 14).
- **Nothing links to the new-trust form (medium).** `/www/trust/new` is
  reached only by typing its URL: neither `/www/trust` nor the dashboard
  links to it.
- **Errors from the new-trust POST are a bare text page (low).** A 400 with
  `<html><body>Error: …</body></html>`, no way back and the input lost
  (`handlers/www.py`, `_handle_new_trust_relationship`).
- **Creating a trust that already exists redirects silently (low).** A 302
  back to the list with no message.
