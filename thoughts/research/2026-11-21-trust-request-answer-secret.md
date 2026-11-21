# Research: the BlazeMeter trust flow against 4.0.0rc1

**Date:** 2026-11-21
**Plan:** [`plans/2026-11-21-trust-request-answer-secret.md`](../plans/2026-11-21-trust-request-answer-secret.md)
**Checked against:** `master` at `add5a4d` (no library or `examples/demo/`
difference from `v4.0.0rc1`), and `v3.15.1`.

The BlazeMeter suite "Trust actingweb actor flow" failed on the demo
(demo.actingweb.io, 4.0.0rc1) on 2026-11-20 at 21:46 UTC: 39 requests, 73 of
107 assertions, 12 failed steps. It passed on 3.15.1. The other three suites
sent no failure. This note holds outcomes only: the report's request URLs
include a deployment secret, which is not copied here.

## Source of the test

The live definition is not in any repository. The Runscope export it was
built from is in `../actingwebdemo` history (`tests/Trust actingweb actor
flow.json`, last present before `5f297bc`). It matches the live report step
for step: 37 steps plus the two NUKE steps the live test added, and the same
assertion count on every step compared (9, 9 and 7 on the steps that carry
the most). The one difference: the live test names the relationship
`associate` where the export says `friend`. The two peer-style creation
bodies are therefore taken from the export, which is an inference from that
match, not a read of the live editor:

- `POST <actor1>/trust/associate`, `{"baseuri": "testurl", "id": "testid",
  "type": "urn:actingweb:actingweb.org:gae-demo", "desc": ...}`, no secret
- the same for trust2 with `"baseuri": "test", "id": "test"`

The integration port (`tests/integration/test_trust_flow.py`, from
`plans/2025-10-02-rest-test-suite-implementation.md`) replaced these two
steps with the initiator flow (`POST /trust` with `url`). Nothing in the
integration suite sends a peer's trust request with a base URI that does not
verify, so release validation could not see this.

## Replays

The export's first 16 steps were replayed against the demo in local QA mode
(`DEMO_QA_BASIC_AUTH=true`, DynamoDB Local, `:5055`, devtest on), with
`associate` substituted. A `friend`/`associate` mismatch in the export's
assertions is the export's age and is ignored below.

| Run | Bodies | Result |
| --- | --- | --- |
| A | as the live test | Exactly the live report: both creates 400, `GET /trust` and the search 200, every step that needs the trust URL unsent |
| B | base URIs made valid (`https://testurl.example`), no secret | creates 202; the answer has no `secret`; approve 403; peer GET after it 403; the change, wrong-credential and delete steps pass |
| C | as B, plus a secret the test chose | as B, except the peer's GET of its own pending row with its secret answers 202 with the row (3.x: 403) |

## Root cause per failed step

| Live step | 4.0 behaviour | Since | Documented |
| --- | --- | --- | --- |
| Create a new trust relationship (400) | A peer's `baseuri` must be a plain http(s) URL and its `id` a plain id, else `400 Invalid id or baseuri` | `b737efad` | CHANGELOG (rc1), migration guide, spec 1.5 |
| Create another trust relationship (400) | the same (`"baseuri": "test"`) | `b737efad` | as above |
| The ten `https://None` steps | never sent: no `Location` after the 400 | — | — |

Hidden behind the 400, with a valid base URI (runs B and C):

| Live step | 4.0 behaviour | Since | Documented |
| --- | --- | --- | --- |
| Create: "secret Not Empty" | the 201/202 answer drops `secret` while the row is unapproved | `16f5972` (iteration 78 of `plans/2026-11-06-peer-authorisation-fixes.md`) | spec 1.5 only; the CHANGELOG names the verification token, not the secret |
| Approve the new trust relationship (204 expected) | an owner approves only a verified request; a fake peer never verifies: 403 | peer-authorisation fixes | CHANGELOG (rc1) |
| Get the new trust relationship as peer, after approval | follows from the two above | — | — |
| Get … as peer, before approval (403 expected) | a pending row's own peer reads its status: 202 | peer-authorisation fixes | CHANGELOG (rc1) |

The wrong-token, wrong-peer, wrong-password, wrong-user, change, get-changed
and delete steps pass on 4.0 once the trust URL exists.

## Why the answer dropped the secret

Iteration 78 made one answer body for a creation and a re-pair
(`_trust_request_answer`, `actingweb/handlers/trust.py:261`). The finding
behind it (reverify-9 Issue 4) was the **verification token** in a re-pair's
202: a third party filing a request at two actors under each other's ids,
with one secret, could otherwise answer each verification with the token of
the row filed at the other (`CHANGELOG.rst`, the rc1 entry on the
verification). The secret was dropped with it on the reasoning that "the
secret is the requester's own". No finding asked for that.

The reasoning fails for a request without a secret. Spec 1.5 lets a receiver
accept one (`docs/protocol/actingweb-spec.rst`, "B MAY accept a request
without `secret`"): `Trust.create` then generates the secret
(`actingweb/trust.py:509`). The requester never learns it, so it cannot
store it in its own row. The verification repeated at the owner's approval
(GET to the requester's row with that secret) can then never succeed, and
the row can never be approved. In 3.15.1 the answer was the whole row
(`json.dumps(new_trust)`), and this two-step pairing worked.

## Is returning the secret safe

What the answer can carry, read from the code:

- **A creation:** the row `create_verified_trust` wrote. `Trust.get()`
  returns the dict `Trust.create` just built (`actingweb/trust.py:136`), not
  a re-read, so a concurrent request that replaces a pending row cannot put
  its secret into another requester's answer. The secret is the one the
  request sent, or the one generated for it.
- **A re-pair:** only for a caller whose bearer is the row's current secret
  (`_re_pair`, `proven`). Correction (plan evaluation, same day): the answer
  is a fresh read after the conditional swap (`actor.py:3238`), not the
  values written. If the owner deletes the row and a stranger files a new
  request between the swap and that read, the re-pair caller would be
  answered the stranger's row. The window is narrow, and the caller has
  proven the previous secret. Today the stripped secret hides it; once the
  secret is answered, `_re_pair` must check the read-back.
- **An application hook:** `trust_request_received` receives the same dict
  that is then answered (`handlers/trust.py:593`, `:609`). This is reachable
  by application code only, not by a peer.

With those two closed, the answer never carries a secret its receiver did
not send or was not issued. Holding a generated secret gives the requester
no more than choosing one would. Before approval it can reach the row's
status, its deletion, and the `peer_approved` notification
(`handlers/trust.py:841`). The repeated verification at approval relies on
the secret and an approved row, not on the token;
approval still needs a verification at the claimed base URI with that
secret, which the real host of a borrowed base URI does not hold. The
verification token is what closes the mirrored-request hole, and it stays
out of an unapproved answer.

## Recorded behaviour that changes with the fix

- `tests/integration/wire/rows.toml` WT3 (`test_wire_trust.py::test_wt3_new_peer`,
  both topologies): the reason line "the 202 answer to a request that waits
  carries no secret or verification_token (reverify-8 Issue 7, iteration 73)".
- `tests/test_trust_re_pair.py`: `test_a_pending_requests_answer_carries_no_token`
  and `test_a_re_pair_of_an_unapproved_row_answers_without_its_token` assert
  `"secret" not in body`.
- `tests/test_trust_answer_flags.py::test_an_unapproved_answer_has_booleans_and_no_token`.

## Replay of the whole flow on the rc2 branch

The whole exported flow (37 steps, `associate`) was replayed on
2026-11-21 against `fix/4.0.0-rc2-consumer-fixes` with phase 1 applied: the
demo in local QA mode with `ENABLE_DEVTEST=true` (the selfproxy steps need
it), DynamoDB Local, a fresh prefix. The BlazeMeter edits of the plan's
Follow-up were applied: base URIs `https://testurl.example` and
`https://test.example`; step 4 (peer GET before approval) expects 202;
step 5 (approve) expects 403; step 6 (peer GET after it) expects 202 with
`approved: false`.

- Steps 0-31 and 33, 35, 36 pass. Step 2's answer carries `secret`, so
  `secret1` and `secret2` are set and every later trust step is sent.
- Step 32 (`test1["var1"]`): a JSON-path assertion the replay script does
  not evaluate; the response is 200 with the value. Not a library result.
- Step 34 (GET `/devtest/proxy/properties` after the delete) answers
  `200 {}` locally where the export expects 404: the selfproxy reads the
  actor's properties as a peer, and the demo's own properties
  (`created_at`, `demo_version`, `interface_version`) stay, outside what
  that peer reads. The branch does not touch properties or devtest; the
  live rc1 run passed this step, so it is a local difference. Check it on
  the rc2 deploy.
