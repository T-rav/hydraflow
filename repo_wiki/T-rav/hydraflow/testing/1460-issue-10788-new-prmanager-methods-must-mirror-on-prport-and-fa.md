---
id: 1460
topic: testing
source_issue: 10788
source_phase: plan
created_at: 2026-07-28T09:50:57.002347+00:00
status: active
corroborations: 1
---

# New PRManager methods must mirror on PRPort and FakeGitHub

Any new public method on `PRManager` must be added to `PRPort` (`src/ports.py`) and `FakeGitHub` (`src/mockworld/fakes/fake_github.py`) with matching signatures.

- `src/fake_coverage_auditor_loop.py:124` audits `FakeGitHub` against both `PRManager` **and** `PRPort`.
- A one-layer edit (e.g., only `PRManager`) fails the auditor and breaks `tests/test_ports.py`.

**Why:** The fake-coverage auditor enforces triple-parity; skipping a layer causes CI failures with no obvious connection to the missing method.
