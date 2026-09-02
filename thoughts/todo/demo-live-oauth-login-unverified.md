# `demo.actingweb.io`: one full OAuth login has never been recorded as verified

The last owed step of `thoughts/plans/2026-08-22-demo-app-consolidation.md`
(`status: done`, Phase 5). The site is live and returns 200, the deploy
workflow in `actingwebdemo` is green, and #27 (Google OAuth2 crash fix) and
#28 (devtest re-enabled) both imply someone logged in — but no record says so.

**Action:** complete one OAuth login against `https://demo.actingweb.io/` as a
fresh user, confirm the actor is created and `/<actor_id>/www` renders, then
tick the box in the plan's Phase 5 verification and delete this file. Needs a
browser and a Google account; not doable from a headless session.
