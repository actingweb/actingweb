# A subscriber logs a gap timeout and "processed 0" while both sides are in step

**Filed:** 2026-11-22, from a consumer's production report on 4.0.0rc2
(`thoughts/research/2026-11-22-emm-4-0-rc2-production-observations.md`).
Seen once; unverified. After 4.0.0 unless a comparison shows a regression.

On a local stage with two actors on the same host and a subscription
between them, the subscriber logged `Gap timeout exceeded`
(`callback_processor.py:1071` or `:1530`) and `Fetched 7 diffs but
processed 0` (`interface/subscription_manager.py:1741` or `:2778`). The
data arrived and both sides ended in step. The reporter did not check
whether 3.15.1 or rc1 log the same.

First: reproduce with two same-host actors on rc2 and on 3.15.1. If both
log it, the question is whether a resync that finds only duplicates
deserves these levels. If only rc2 does, find what in 4.0 (concurrent
delivery, own-host serialisation) lets a callback arrive after its gap
timer fired.
