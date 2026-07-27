---
id: 1193
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T18:41:12.890723+00:00
status: active
corroborations: 1
supersedes: 1124
---

# ADR citation ratchet must check all candidate tokens

tests/architecture/test_adr_source_citations_exist.py must extract every src/*.py-like candidate substring per ADR and assert _SOURCE_FILE_CITATION_RE.fullmatch succeeds, not just validate already-parsed citations.

Example: exclude placeholders via _is_glob (e.g. `src/<module>.py:<Symbol>`); catch dead tokens like double-colon or trailing parens that fail to parse.

**Why:** Testing only the happy path (parsed citations) can't catch citations that fail to parse in the first place — the exact gap that hid ADR-0049's lost coverage.
