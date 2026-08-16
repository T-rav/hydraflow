---
id: 2659
topic: testing
source_issue: 11284
source_phase: plan
created_at: 2026-08-16T01:29:44.315618+00:00
status: active
corroborations: 1
---

# New Port methods require three-layer mirror: ports, PRManager, FakeGitHub+MockWorld

Adding a method to any Port in `src/ports.py` requires synchronized updates across all three layers: the Port interface (`src/ports.py`), the real implementation (`src/pr_manager.py`), and the fake+wiring (`src/mockworld/fakes/fake_github.py` + `tests/scenarios/fakes/mock_world.py`). Missing any layer leaves MockWorld scenarios silently unwired — tests pass but the scenario never exercises the new method. Example: `PRPort.branch_ahead_of_base` added in #11284 touched all four files. A dedicated mirror test is mandatory.

**Why:** The three-layer mirror is load-bearing for scenario fidelity; a silent miss produces green tests that validate nothing.
