---
id: 3760
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T13:50:50.763458+00:00
status: active
corroborations: 1
supersedes: 3615
---

# Do not override BaseRunner._build_command with a partial copy

If a runner subclass needs the same command shape as `BaseRunner._build_command` (`src/base_runner.py:556`), inherit it — do not copy and drop a parameter. `DiagnosticRunner._build_command` was an identical copy minus `restricted=`, which silently drifted into a `bypassPermissions` path outside ADR-0092's trust boundary. Delete the override; thread new parameters through the base instead.

**Why:** Duplicated chokepoint code desynchronizes from the security-critical base path; inheritance keeps one source of truth.
