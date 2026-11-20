# A start that serves 503 while its check repeats

**Filed:** 2026-11-19, by `thoughts/plans/2026-11-19-emm-4-0-adoption-findings.md` (the rest of the consumer's M2).

4.0 retries a faulting start-up check three times within a two-second
budget and then refuses the start (`StoreNotReady.unavailable` is True).
On a function platform a refused initialisation is retried by the platform;
on a long-running server it stops the process. The ask: a mode that starts,
answers 503 while the check is repeated in the background, and serves once
it passes. A new start mode with its own failure cases (what a request sees
before the first answer, how a check that later answers "not ready" is
surfaced). Waits for the consumer's report of what a failed function
initialisation does on its platform.
