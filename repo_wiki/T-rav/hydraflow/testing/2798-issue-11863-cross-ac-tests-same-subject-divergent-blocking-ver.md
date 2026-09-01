---
id: 2798
topic: testing
source_issue: 11863
source_phase: plan
created_at: 2026-09-01T06:14:33.638615+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Cross-AC tests: same subject, divergent blocking verdicts

When a control standard like `regulated-demo` (#11869) is meant to block where `internal` does not, write a cross-AC test asserting the verdict diverges for the same (standard, subject) pair. Assert the negative: a control charter without the staged violation yields no blocking row.

**Why:** Without cross-AC divergence tests, a verdicts page can silently render `compliant` for what should be `violated`/`blocking`.
