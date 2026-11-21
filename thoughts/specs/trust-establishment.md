# Spec: Trust establishment

**Status:** partial (covers: behaviour changed since 2026-11-21)
**Reviewed:** 2026-11-21 by Greger Wedel (with the plan)
**Last changed:** 2026-11-21 by thoughts/plans/2026-11-21-trust-request-answer-secret.md (and its iterations log, entries 2-3)
**ID prefix:** TES

## Summary

A peer's trust request (`POST /<id>/trust/<rel>`, protocol spec 1.5), the
answer it gets, its refusals, and the owner's approval of a request that
did not verify. This partial spec covers what the 2026-11-21 plan changed;
the rest is in `docs/protocol/actingweb-spec.rst` and the wire recordings
(WT1-WT9, WV4).

## Answer to a trust request

- **TES-1** — When a peer's trust request carries no `secret`, the actor
  generates one and the 202 answer carries it. [plan+test]
  `tests/test_trust_re_pair.py::TestTheAnswerCarriesTheSecret::test_a_request_without_a_secret_gets_the_generated_one`,
  `tests/integration/test_trust_flow.py::TestPeerTrustRequest::test_003_request_without_secret_answers_its_secret` (plans/2026-11-21-trust-request-answer-secret.md, AC-1)
- **TES-2** — When a peer's trust request carries a `secret`, the 201 or 202
  answer carries that secret. [plan+test]
  `tests/test_trust_re_pair.py::TestTheAnswerCarriesTheSecret::test_a_request_with_a_secret_gets_it_back` (AC-2)
- **TES-3** — An answer to a trust request (a creation or a re-pair) for a
  row this actor has not approved carries no `verification_token`.
  [plan+test] `tests/test_trust_re_pair.py::TestTheEdgesAfterReverify8::test_a_pending_requests_answer_carries_no_token`,
  `tests/test_trust_answer_flags.py::test_an_unapproved_answer_has_booleans_and_no_token` (AC-3)
- **TES-4** — A proven re-pair's answer carries the new secret it sent; one
  whose read-back row holds another secret answers 403
  `{"error": "Trust was replaced; pair again"}` and no secret. [plan+test]
  `tests/test_trust_re_pair.py::TestTheRePairAnswerAfterReverify9::test_a_re_pair_of_an_unapproved_row_answers_without_its_token`,
  `::TestTheAnswerCarriesTheSecret::test_a_re_pair_answers_only_its_own_secret` (AC-5, AC-11)
- **TES-5** — A creation's answer and its status carry the row written for
  that request, whatever the stored row or the `trust_request_received`
  hook (which gets a copy) does before the answer is sent. [plan+test]
  `tests/test_trust_re_pair.py::TestTheAnswerCarriesTheSecret::test_the_answer_is_the_row_written` (AC-10)

## Pairing without a secret

- **TES-6** — A requester that sent no secret and serves, at its base URI,
  an approved row naming this actor that accepts the answered secret as
  bearer, is approved and verified by the owner's approval; one holding
  another secret is refused (403). [plan+test]
  `tests/test_trust_re_pair.py::TestTheAnswerCarriesTheSecret::test_a_generated_secret_pairs_on_approval`,
  `::test_a_requester_without_the_answered_secret_is_not_approved` (AC-4)

## Refusals

- **TES-7** — A peer's trust request whose `baseuri` is not a plain http(s)
  URL, or whose `id` is not a plain id, answers 400 and stores nothing.
  [plan+test] `tests/integration/test_trust_flow.py::TestPeerTrustRequest::test_002_request_with_invalid_peer_is_refused` (AC-6)
- **TES-8** — Every refusal of a trust request carries a JSON `error`
  naming its reason: a body that is not JSON or not an object, a field that
  is not text, missing `baseuri` or `id`, a reserved relationship, an
  invalid id or base URI, a bearer for a peer with no trust, a re-pair not
  proven, a creation a pending or existing row blocks. A re-pair from a peer
  that proved the trust's secret is told why it was refused (another
  relationship, no new secret, a secret already in use, a row that changed);
  any other caller only "Existing trust not verified". [plan+test]
  `tests/test_trust_re_pair.py::TestTheRefusalsSayWhy`,
  `::TestTheRequestBodyIsChecked`, `::TestTheLastRefusalsSayWhy` (AC-12; iterations entries 2-3)
- **TES-9** — A trust request whose body is not a JSON object, or whose
  `baseuri`, `id`, `secret`, `desc`, `verify` or `type` is not text (`null`
  is absent), answers 400 naming the field and stores nothing, also on a
  re-pair. [plan+test] `tests/test_trust_re_pair.py::TestTheRequestBodyIsChecked` (iterations entry 2)

## Approval

- **TES-10** — The owner's approval of a request that did not verify, and
  still does not, answers 403 and leaves the row unapproved. [plan+test]
  `tests/integration/test_trust_flow.py::TestPeerTrustRequest::test_006_owner_cannot_approve_unverified_request` (AC-7)

## Pending status

- **TES-11** — A pending row's own peer, with its secret as bearer, reads
  the row: 202, without `verification_token`. [plan+test]
  `tests/integration/test_trust_flow.py::TestPeerTrustRequest::test_004_peer_reads_its_pending_row` (AC-8)

## Decisions in force

- **TES-D1** — The answer to a trust request carries only a secret its
  receiver sent or was issued for that request, and never the verification
  token while unapproved. (plans/2026-11-21-trust-request-answer-secret.md, owner 2026-11-21)
- **TES-D2** — A request without a secret is accepted; requesters SHOULD
  send one, and a lost answer to such a request is the owner's to clear.
  (plans/2026-11-21-trust-request-answer-secret.md, owner 2026-11-21)

## Untested

- TES-4's read-back guard is tested with `replace_trust_secret` stubbed; no
  test drives a real delete and re-request between the swap and the
  read-back on either backend.
- TES-8: the reasons "no trust row" and "the row could not be read back"
  from `replace_trust_secret` are not mapped; a proven peer is told
  "Existing trust not verified" for them
  (verifications/2026-11-21-trust-request-answer-secret.md, issue 2).
