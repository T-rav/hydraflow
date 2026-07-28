---
id: 1465
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-28T14:38:21.720324+00:00
status: active
corroborations: 1
supersedes: 1377,1460
---

# PRManager changes must mirror in FakeGitHub and PRPort

Any new public method or side effect on `PRManager` (`src/pr_manager.py`) must be added to `PRPort` (`src/ports.py`) and `FakeGitHub` (`src/mockworld/fakes/fake_github.py`) with matching signatures in the same change.

Example: `src/fake_coverage_auditor_loop.py:124` audits `FakeGitHub` against both `PRManager` and `PRPort`; a one-layer edit fails the auditor and `tests/test_ports.py`.

**Why:** MockWorld scenario tests only catch loop-integration bugs if the fake replicates real adapter semantics, and the fake-coverage auditor enforces triple-parity — skipping a layer causes CI failures with no obvious connection to the missing method.
