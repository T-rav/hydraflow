---
id: 0321
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T21:56:41.019263+00:00
status: active
corroborations: 1
supersedes: 0256,0257,0258,0259,0260,0261,0262,0263,0264,0265,0266,0267,0268,0269,0270,0271,0272,0273,0274,0275,0276,0277,0278,0279,0280,0281,0282,0283,0284,0285,0286,0287,0288,0289,0290,0291,0292,0293,0294
---

# Validate sys.modules cleanup with multiple random seeds

Run `pytest --randomly-seed=<N>` with at least two different seeds to confirm that module-level import side effects do not leak between tests.

Example: Execute the test suite with `--randomly-seed=1` and `--randomly-seed=42` to verify isolation.

**Why:** Cleanup failures only surface under specific test orderings; a single seed may never trigger the problematic sequence.
