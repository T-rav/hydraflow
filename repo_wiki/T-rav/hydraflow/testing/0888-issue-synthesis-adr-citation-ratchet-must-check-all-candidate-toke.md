---
id: 0888
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:22:24.565335+00:00
status: superseded
corroborations: 1
supersedes: 0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0825,0826,0827,0828,0829,0830,0831,0832,0833,0834,0835,0836,0837,0838,0839,0840,0841,0842,0843,0844,0845,0846
superseded_by: 0896
---

# ADR citation ratchet must check all candidate tokens, not just parsed ones

`tests/architecture/test_adr_source_citations_exist.py` originally validated only citations that already matched `_SOURCE_FILE_CITATION_RE` against `source_files` — it never asserted that every `` `src/…py` ``-shaped token in a live ADR *does* match the regex. That let dead tokens (double-colon, trailing parens) exist invisibly. Add a token-parity ratchet: extract every lenient `src/*.py`-like candidate substring per ADR and assert `_SOURCE_FILE_CITATION_RE.fullmatch` succeeds, excluding placeholders via `_is_glob` (e.g. `src/<module>.py:<Symbol>`).

**Why:** testing only the happy path (parsed citations) can't catch citations that fail to parse in the first place — the exact gap that hid ADR-0049's lost coverage.
