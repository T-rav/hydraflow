---
id: 0016
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.314407+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# Extract pure transform functions before moving code to new classes

Identify pure functions (no mutable closure state, no side effects) and extract them to module-level first; only then move to a class if ownership is clear.

Example: extract `_format_label(name)` before creating `LabelFormatter` — the extracted form is independently testable.

**Why:** Pure functions have the smallest blast radius and validate the extraction boundary before higher-risk class restructuring.
