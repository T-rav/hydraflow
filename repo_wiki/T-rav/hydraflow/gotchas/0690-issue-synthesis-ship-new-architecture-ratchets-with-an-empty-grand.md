---
id: 0690
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:40:13.488994+00:00
status: active
corroborations: 1
supersedes: 0593,0594,0595,0596,0597,0598,0599,0600,0601,0602,0603,0604,0605,0606,0607,0608,0609,0610,0611,0612,0613,0614,0615,0616,0617,0618,0619,0620,0621,0622,0623,0624,0625,0626,0627,0628,0629,0630,0631,0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642
---

# Ship new architecture ratchets with an empty grandfather list, fail closed

When adding a new ratchet to `tests/architecture/test_adr_source_citations_exist.py`, start the grandfather/allowlist empty rather than pre-populating it with currently-known violations.

Example: issue #10440 reprises the #9514 failure mode — a permissive default (or lenient allowlist) let bad citations degrade silently instead of failing CI. Fix all discovered violations (ADR-0049 lines 74–75, ADR-0004 line 34) before merge so the ratchet activates with nothing grandfathered in.

**Why:** A non-empty grandfather list becomes a permanent exemption nobody revisits, recreating the same silent-coverage-loss bug the ratchet was built to prevent.
