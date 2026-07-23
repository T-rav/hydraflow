---
id: 0184
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:22:06.631070+00:00
status: superseded
corroborations: 1
supersedes: 0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145,0146,0147,0148,0149,0150,0151,0152,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175
superseded_by: 0218
---

# Extract pure transform functions before moving code to new classes

Identify pure functions (no mutable closure state, no side effects) and extract them to module-level first; only then move to a class if ownership is clear.

Example: extract `_format_label(name)` before creating `LabelFormatter` — the extracted form is independently testable.

**Why:** Pure functions have the smallest blast radius and validate the extraction boundary before higher-risk class restructuring.
