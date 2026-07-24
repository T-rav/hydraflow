---
id: 0165
topic: architecture
source_issue: 10400
source_phase: plan
created_at: 2026-07-24T05:41:19.861198+00:00
status: stale
corroborations: 1
stale_reason: source issue #10400 closed
---

# ADR citations drift unless symbol tail shares backtick pair with path

`_SOURCE_FILE_CITATION_RE` only records a `:Symbol` tail into `source_symbols` when the symbol sits inside the SAME backtick pair as the file path. ADR-0012 line 185 cited `src/epic.py` and its methods in separate backtick spans, so it parsed as a bare (symbol-less) citation and drifted on any file-only touch of `epic.py`. Fix: write it as one inline token, e.g. `` `src/epic.py:EpicManager.on_child_approved` ``. Same fix class as ADR-0019/#10384.

**Why:** A non-empty `source_symbols` set is what makes `adr_drift._citation_drifts` (the #9176 design) ignore file-only diffs — splitting path and symbol across backticks silently defeats that protection.
