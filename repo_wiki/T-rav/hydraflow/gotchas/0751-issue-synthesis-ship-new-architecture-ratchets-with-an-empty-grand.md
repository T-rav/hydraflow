---
id: 0751
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T15:44:16.320726+00:00
status: active
corroborations: 1
supersedes: 0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671,0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703
---

# Ship new architecture ratchets with an empty grandfather list, fail closed

When adding a new ratchet to `tests/architecture/test_adr_source_citations_exist.py`, start the grandfather/allowlist empty rather than pre-populating it with currently-known violations.

Example: issue #10440 reprises the #9514 failure mode — a permissive default (or lenient allowlist) let bad citations degrade silently instead of failing CI. Fix all discovered violations (ADR-0049 lines 74–75, ADR-0004 line 34) before merge so the ratchet activates with nothing grandfathered in.

**Why:** A non-empty grandfather list becomes a permanent exemption nobody revisits, recreating the same silent-coverage-loss bug the ratchet was built to prevent.
