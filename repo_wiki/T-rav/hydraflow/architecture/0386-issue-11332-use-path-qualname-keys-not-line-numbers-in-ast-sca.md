---
id: 0386
topic: architecture
source_issue: 11332
source_phase: plan
created_at: 2026-08-16T10:18:33.580107+00:00
status: active
corroborations: 1
---

# Use path::qualname keys, not line numbers, in AST scanner baselines

When building baseline keys for AST-based architecture tests, use `"<repo-relative path>::<dotted qualname>"` (e.g. `src/triage.py::TriageRunner._build_command`) rather than line numbers.

`test_adr0092_restricted_declaration.py` uses this format for `_UNDECLARED_BASELINE` keys.

**Why:** Line numbers rot with every edit; qualnames survive reformatting and code movement, keeping the baseline stable across unrelated PRs.
