---
id: 0839
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:43:21.219997+00:00
status: superseded
corroborations: 1
supersedes: 0754,0755,0756,0757,0758,0759,0760,0761,0762,0763,0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797
superseded_by: 0847
---

# ADR citation ratchet must check all candidate tokens, not just parsed ones

`tests/architecture/test_adr_source_citations_exist.py` originally validated only citations that already matched `_SOURCE_FILE_CITATION_RE` against `source_files` — it never asserted that every `` `src/…py` ``-shaped token in a live ADR *does* match the regex. That let dead tokens (double-colon, trailing parens) exist invisibly. Add a token-parity ratchet: extract every lenient `src/*.py`-like candidate substring per ADR and assert `_SOURCE_FILE_CITATION_RE.fullmatch` succeeds, excluding placeholders via `_is_glob` (e.g. `src/<module>.py:<Symbol>`).

**Why:** testing only the happy path (parsed citations) can't catch citations that fail to parse in the first place — the exact gap that hid ADR-0049's lost coverage.
