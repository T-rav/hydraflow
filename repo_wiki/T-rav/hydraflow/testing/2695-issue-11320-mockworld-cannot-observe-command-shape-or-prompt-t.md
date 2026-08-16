---
id: 2695
topic: testing
source_issue: 11320
source_phase: plan
created_at: 2026-08-16T08:37:33.480366+00:00
status: active
corroborations: 1
---

# MockWorld cannot observe command shape or prompt text

State MockWorld as N/A in PRs for changes to `DiagnosticRunner` command construction or prompt text. `_mockworld_diagnosis` short-circuits before any command build or spawn, so no MockWorld scenario can assert on `--permission-mode`, `--allowedTools`, `--disallowedTools`, or fenced-region content.

- Cover those assertions via `tests/regressions/test_issue_11320.py` and `tests/test_diagnostic_runner.py` instead.
- Sandbox e2e is also N/A when no docker/UI/wiring surface changes.

**Why:** Relying on MockWorld for command-shape coverage produces false-green tests that never exercise the changed code path.
