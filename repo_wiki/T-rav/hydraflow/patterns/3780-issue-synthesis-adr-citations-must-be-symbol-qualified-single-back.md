---
id: 3780
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T15:30:55.610274+00:00
status: superseded
corroborations: 1
supersedes: 3635
superseded_by: 3927
---

# ADR citations must be symbol-qualified single backtick spans

Qualify ADR code citations as a single `path:Symbol` backtick span — never a bare file path or a split `path` + `Symbol` pair.

Example: Use `` `src/reviewer.py:ReviewRunner._build_command` ``, not bare `` `src/reviewer.py` ``. In `src/adr_drift.py:65-83`, bare `src/epic.py` triggers `_citation_drifts` on any diff; `src/epic.py:EpicManager.release_epic` scopes it. For shared-infra-suppressed files, bare paths are fine. See also: [patterns] — docs/arch/generated/* is a make arch-regen artifact.

**Why:** Bare or split citations drift-flag every unrelated edit to multi-concern files, producing false-positive ADR-0092 drift alerts that train developers to ignore the gate.
