---
id: 1588
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T01:04:04.378316+00:00
status: superseded
corroborations: 1
supersedes: 1506
superseded_by: 1671
---

# Doc-typo ADR fixes still need parser-consumer regression tests

For a citation-repoint fix on an ADR (e.g. ADR-0049), the regression test must assert against parse_adr_file() output — source_files includes the expected modules and source_symbols maps them to the expected symbols.

Example: tests/regressions/test_issue_10444.py asserts ADR-0049's source_files includes src/base_background_loop.py and source_symbols maps to LoopDeps / BGWorkerManager.is_enabled.

**Why:** An ADR text edit with no test would let the citation format regress again with no CI signal.
