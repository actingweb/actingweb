# Handler refusals: readable bodies

**Provenance:** `plans/2026-11-21-trust-request-answer-secret.md`, phase 1
and its first iteration (2026-11-21). They gave every refusal of
`POST /<id>/trust/<rel>` a JSON `{"error": …}` body, validated that
request's body, fixed the basic-auth parse that answered 500 on a malformed
`Authorization` header, and stopped the creator commands recording reserved
creators. What is left was judged too wide for an rc (owner decision).

## What is still open

- **The other bare refusals in `actingweb/handlers/`** answer a status line
  and an empty body (about 240 `set_status(4xx, …)` calls). A JSON client
  sees no reason. The pattern to reuse is
  `TrustRelationshipHandler._refuse_request` (and
  `_refuse_unverified_approval` for the browser/JSON split). Do it per
  handler, with the wire rows that record each refusal re-recorded under a
  plan phase.
