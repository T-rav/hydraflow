---
id: 3476
topic: patterns
source_issue: 11331
source_phase: plan
created_at: 2026-08-16T09:57:29.108959+00:00
status: superseded
corroborations: 1
superseded_by: 3490
---

# ADR citations must be symbol-anchored to avoid drift false-positives

When citing a file in an ADR amendment, prefer a symbol-anchored reference (e.g. `build_ultra_review_command`) over a bare `src/` path. A bare `src/ultra_review.py` citation causes future edits to that file to flag ADR-0092 even when the change is unrelated to the trust boundary.

- `src/review_phase/_phase.py` is already shared-infra-suppressed, so bare path is fine there.
- For reference-only mentions, drop the `src/` prefix entirely.

**Why:** Bare-file ADR citations create noisy drift alerts that train developers to ignore the gate, undermining its value for genuine boundary changes.
