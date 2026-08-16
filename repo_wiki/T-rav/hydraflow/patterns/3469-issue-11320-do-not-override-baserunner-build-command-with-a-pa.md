---
id: 3469
topic: patterns
source_issue: 11320
source_phase: plan
created_at: 2026-08-16T08:37:33.480320+00:00
status: active
corroborations: 1
---

# Do not override BaseRunner._build_command with a partial copy

If a runner subclass needs the same command shape as `BaseRunner._build_command` (`src/base_runner.py:556`), inherit it — do not copy and drop a parameter. `DiagnosticRunner._build_command` was an identical copy minus `restricted=`, which silently drifted into a `bypassPermissions` path outside ADR-0092's trust boundary.

- Delete the override; thread new parameters through the base instead.
- The `agent_unrestricted_tools` escape hatch stays functional via the base's `restricted=` flag.

**Why:** Duplicated chokepoint code desynchronizes from the security-critical base path; inheritance keeps one source of truth.
