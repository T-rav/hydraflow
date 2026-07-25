---
id: 0811
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T02:43:04.012261+00:00
status: superseded
corroborations: 1
supersedes: 0704,0705,0706,0707,0708,0709,0710,0711,0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753,0754,0755,0756,0757,0758,0759,0760,0761,0762
superseded_by: 0851
---

# Ship new architecture ratchets with an empty grandfather list, fail closed

When adding a new ratchet to `tests/architecture/test_adr_source_citations_exist.py`, start the grandfather/allowlist empty rather than pre-populating it with currently-known violations.

Example: issue #10440 reprises the #9514 failure mode — a permissive default (or lenient allowlist) let bad citations degrade silently instead of failing CI. Fix all discovered violations (ADR-0049 lines 74–75, ADR-0004 line 34) before merge so the ratchet activates with nothing grandfathered in.

**Why:** A non-empty grandfather list becomes a permanent exemption nobody revisits, recreating the same silent-coverage-loss bug the ratchet was built to prevent.
