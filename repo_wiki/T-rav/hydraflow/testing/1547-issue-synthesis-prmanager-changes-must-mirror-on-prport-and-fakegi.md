---
id: 1547
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T01:04:04.294047+00:00
status: active
corroborations: 1
supersedes: 1465
---

# PRManager changes must mirror on PRPort and FakeGitHub

Any new public method or side effect on PRManager must be added to PRPort (src/ports.py) and FakeGitHub (src/mockworld/fakes/fake_github.py) with matching signatures and equivalent behavior.

Example: src/fake_coverage_auditor_loop.py:124 audits FakeGitHub against both PRManager and PRPort; close_issue side effect stripping stage labels must mirror across all three.

**Why:** The fake-coverage auditor enforces triple-parity, and MockWorld scenario tests only catch loop-integration bugs if the fake replicates real adapter semantics.
