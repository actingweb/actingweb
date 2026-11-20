# Spec: Actor creation

**Status:** partial (covers: behaviour changed since 2026-11-19)
**Reviewed:** 2026-11-19 by Greger Wedel (with the plan)
**Last changed:** 2026-11-20 by thoughts/plans/2026-11-19-emm-4-0-adoption-findings.md
**ID prefix:** ACR

## Summary

How actors come to exist (the factory `POST /`, sign-in, peers creating
trustees) and what is recorded about them. This partial spec covers the
factory default, vouching and adoption.

## Factory

- **ACR-1** — When a provider builder was called and the application did
  not call `with_open_factory`, `POST /` answers 403; otherwise it creates
  an actor. The default sign-in page offers the provider buttons, and the
  email form when the factory is open or the default provider (the one a
  form POST redirects through) is enabled: with a provider the form signs
  in. [plan+test] `tests/test_factory_open_switch.py::TestClosedByDefaultWithAProvider`, `::TestSignInPageValues`; browser walks 2026-11-20 (plans/2026-11-19-emm-4-0-adoption-findings.md, AC-18, AC-19, AC-47; iterations 1, 17)
- **ACR-2** — When a peer's factory refuses a trustee creation, the caller
  logs a WARNING. [plan+test] `tests/test_actor_peer_creation.py::test_a_closed_factory_is_warned` (plans/2026-11-19-emm-4-0-adoption-findings.md, AC-46)

## Vouching

- **ACR-3** — When `is_vouched()` is called, it answers for the actor's
  current creator and raises when the marker could not be read. [plan+test]
  `tests/test_is_vouched_public.py` (plans/2026-11-19-emm-4-0-adoption-findings.md, AC-20)

## Adoption

- **ACR-4** — When a sign-in cleans or replaces an actor, one
  `ACTOR_ADOPTED:` line records it, with no address. [plan+test]
  `tests/test_adoption_log_line.py` (plans/2026-11-19-emm-4-0-adoption-findings.md, AC-12)

## Faults

- **ACR-5** — When the store faults under `get_by_id` or `get_by_creator`,
  `DbError` is raised. [plan+test] `tests/test_db_fault_callers.py::TestActorInterfaceLookups` (plans/2026-11-19-emm-4-0-adoption-findings.md, AC-7)

## Decisions in force

- **ACR-D1** — A marker being present does not mean vouched; `is_vouched()`
  is the test. A marker with no bound address is vouched for any creator
  (written before the address was recorded). (plans/2026-11-19-emm-4-0-adoption-findings.md)

## Untested

- None known.
