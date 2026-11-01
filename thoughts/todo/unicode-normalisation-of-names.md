# NFC and NFD spellings of one name are distinct keys

Found by the 3.14.4 architecture review
(`thoughts/plans/2026-09-02-identifier-matching-and-metadata-fidelity.md`).
Renamed and trimmed in 3.16: the backslash-escape half of this item landed
(`thoughts/plans/2026-11-01-single-mode-and-consumer-primitives.md`, Phase 4:
`glob_to_regex` honours `\*`, `\?` and `\\`).

NFC and NFD spellings of one visible name are different keys, different
permission targets and different storage rows. Same failure shape as the
newline bypass — a rule that visibly covers a namespace does not cover a
byte-different spelling of it — and not closed by that fix. If it is ever
addressed it is a normalisation at the same two choke points that one used —
`_evaluate_rules` and the property/list name write path — and a migration
question for stored names.
