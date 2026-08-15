---
id: 0348
topic: architecture
source_issue: 11202
source_phase: plan
created_at: 2026-08-15T03:13:32.213234+00:00
status: active
corroborations: 1
---

# Frozen per-file baseline + monotonic ratchet for legacy violations

When widening an architecture gate surfaces pre-existing violations, grandfather them into a frozen per-file baseline JSON with a monotonic ratchet — never wildcards or directory-level suppression.

`tests/architecture/ignored_test_baseline.json` mirrors `tests/architecture/test_adr_enforcement_ratchet.py` + `adr_enforcement_baseline.json`. Format: `{"baseline_snapshot": {"<path>": <count>}, "resolved": ["<path>"]}`; live grandfathered = snapshot − resolved. Generate only via `scripts/regen_ignored_test_baseline.py`.

**Why:** Hand-written baselines with 50+ entries drift from reality and immediately red CI; per-file counts ensure the ratchet can only shrink, never grow.
