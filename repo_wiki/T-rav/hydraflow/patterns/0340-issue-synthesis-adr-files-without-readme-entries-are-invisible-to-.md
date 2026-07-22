---
id: 0340
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:37:54.883518+00:00
status: active
corroborations: 1
supersedes: 0260,0261,0262,0263,0264,0265,0266,0267,0268,0269,0270,0271,0272,0273,0274,0275,0276,0277,0278,0279,0280,0281,0282,0283,0284,0285,0286,0287,0288,0289,0290,0291,0292,0293,0294,0295,0296,0297,0298,0299,0300,0301
---

# ADR files without README entries are invisible to tooling

Every ADR file in `docs/adr/` must have a corresponding row in `docs/adr/README.md` to be canonically referenceable.

Example: Adding `docs/adr/0055-new-decision.md` requires a matching `| 0055 | New Decision | Accepted |` row in README.

**Why:** `scan_adr_directory()` builds its index from README rows; a file without a row is silently skipped by drift detection and cross-reference tooling.
