---
id: 1075
topic: testing
source_issue: 10567
source_phase: plan
created_at: 2026-07-25T23:37:32.613851+00:00
status: superseded
corroborations: 1
superseded_by: 1085
---

# New PRPort/IssuePort methods need 5 surfaces or CI fails

Adding a method to `PRPort` (src/ports.py) isn't done until it lands on all five surfaces: the Protocol, `PRManager` impl (src/pr_manager.py), `FakeGitHub` (src/mockworld/fakes/fake_github.py), an ADR-0047 cassette (tests/trust/contracts/cassettes/github/), and `docs/arch/generated/ports.md` via `make arch-regen`. `tests/trust/contracts/test_cassette_surface_parity.py` uses an empty, shrink-only baseline, so a fake method with no cassette is a hard CI fail, not a warning.
**Why:** partial Port additions pass unit tests locally but redden the contract-parity gate at merge time.
