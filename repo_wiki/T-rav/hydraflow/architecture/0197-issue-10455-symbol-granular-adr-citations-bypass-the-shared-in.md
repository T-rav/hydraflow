---
id: 0197
topic: architecture
source_issue: 10455
source_phase: plan
created_at: 2026-07-24T12:32:23.750682+00:00
status: active
corroborations: 1
---

# Symbol-granular ADR citations bypass the _SHARED_INFRA_MODULES allowlist

Adding a path to `_SHARED_INFRA_MODULES` in `src/adr_drift.py` only suppresses bare `path`-only citations; a citation like `src/review_advisor.py:ReviewAdvisor.plan` still drifts normally when that symbol changes. This is validated in `tests/regressions/test_issue_10455.py` as an explicit GREEN-before/GREEN-after case, not just the suppressed-path case. **Why:** the escape hatch preserves precision drift detection for ADRs that actually pin a symbol, so the allowlist can't be used to silence a real contract change by accident.
