---
id: 0172
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T20:34:46.631096+00:00
status: active
corroborations: 1
supersedes: 0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122,0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133
---

# ADR files without README entries are invisible to tooling

Every ADR file in `docs/adr/` must have a corresponding row in `docs/adr/README.md` to be canonically referenceable.

Example: adding `docs/adr/0055-new-decision.md` requires a matching `| 0055 | New Decision | Accepted |` row in README.

**Why:** `scan_adr_directory()` builds its index from README rows; a file without a row is silently skipped by drift detection and cross-reference tooling.
