---
id: 0214
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:22:06.641721+00:00
status: active
corroborations: 1
supersedes: 0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145,0146,0147,0148,0149,0150,0151,0152,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175
---

# ADR files without README entries are invisible to tooling

Every ADR file in `docs/adr/` must have a corresponding row in `docs/adr/README.md` to be canonically referenceable.

Example: adding `docs/adr/0055-new-decision.md` requires a matching `| 0055 | New Decision | Accepted |` row in README.

**Why:** `scan_adr_directory()` builds its index from README rows; a file without a row is silently skipped by drift detection and cross-reference tooling.
