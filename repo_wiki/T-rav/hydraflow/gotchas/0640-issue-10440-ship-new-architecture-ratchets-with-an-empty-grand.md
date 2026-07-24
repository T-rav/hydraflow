---
id: 0640
topic: gotchas
source_issue: 10440
source_phase: plan
created_at: 2026-07-24T10:50:57.616757+00:00
status: superseded
corroborations: 1
superseded_by: 0643
---

# Ship new architecture ratchets with an empty grandfather list, fail closed

When adding a new ratchet to `tests/architecture/test_adr_source_citations_exist.py`, start the grandfather/allowlist empty rather than pre-populating it with currently-known violations. Issue #10440 reprises the #9514 failure mode: a permissive default (or a lenient allowlist) let bad citations degrade silently instead of failing CI. Fix all discovered violations (ADR-0049 lines 74–75, ADR-0004 line 34) before merge so the ratchet activates with nothing grandfathered in.
**Why:** a non-empty grandfather list becomes a permanent exemption nobody revisits, recreating the same silent-coverage-loss bug the ratchet was built to prevent.
