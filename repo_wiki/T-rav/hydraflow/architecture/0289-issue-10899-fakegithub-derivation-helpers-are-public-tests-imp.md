---
id: 0289
topic: architecture
source_issue: 10899
source_phase: plan
created_at: 2026-07-31T11:25:57.702241+00:00
status: active
corroborations: 1
---

# FakeGitHub derivation helpers are public — tests import cross-module

Derivation helpers in `fake_github.py` must not use a leading underscore. Tests import them cross-module (e.g. `tests/regressions/test_issue_10899.py` reconciles against the slug rule).

- Reuse `tests/helpers.make_pr_manager` for test construction — do not add new helpers.
- The WARNING for display-name-as-file-name queries passes a literal format string with `%s` args.
- No hardcoded workflow-name table mirroring `.github/workflows/` — derivation is rule-based with `workflow_file=` as the escape hatch.

**Why:** Privatizing the helper forces tests to duplicate slug logic, which drifts from the fake's behavior; the escape hatch prevents over-clever slug rules from mangling acronyms.
