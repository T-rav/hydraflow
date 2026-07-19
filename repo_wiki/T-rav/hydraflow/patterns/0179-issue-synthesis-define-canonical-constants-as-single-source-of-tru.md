---
id: 0179
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:22:06.629464+00:00
status: active
corroborations: 1
supersedes: 0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145,0146,0147,0148,0149,0150,0151,0152,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175
---

# Define canonical constants as single source of truth for label lists

Establish a canonical constant (e.g., `ALL_LIFECYCLE_LABEL_FIELDS`) and derive every label list from it; never duplicate the list inline.

Example: reset code, validators, and display logic all reference `ALL_LIFECYCLE_LABEL_FIELDS` — no magic strings.

**Why:** Duplicated label lists diverge silently; a canonical constant makes omissions a grep-findable gap, not a runtime miss.
