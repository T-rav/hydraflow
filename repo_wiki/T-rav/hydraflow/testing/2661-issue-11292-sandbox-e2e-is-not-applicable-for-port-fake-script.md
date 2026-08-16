---
id: 2661
topic: testing
source_issue: 11292
source_phase: plan
created_at: 2026-08-16T01:48:07.890799+00:00
status: active
corroborations: 1
---

# Sandbox e2e is not applicable for Port + fake + script-only changes

When a change touches only `src/ports.py`, `src/pr_manager.py`, FakeGitHub, and `scripts/*.py` with no docker/UI/phase wiring, skip sandbox e2e — document the non-applicability judgment in the PR body. Cover with unit + regression + MockWorld scenario instead.

**Why:** Sandbox e2e exercises real `gh` + docker + UI flows; running it for Port/fake/script layers adds latency without coverage gain. The testing-standards applicability judgment is a first-class decision, not a skip.
