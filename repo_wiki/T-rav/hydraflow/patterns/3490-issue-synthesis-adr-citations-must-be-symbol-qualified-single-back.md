---
id: 3490
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T12:13:21.827489+00:00
status: active
corroborations: 1
supersedes: 3343,3474,3476
---

# ADR citations must be symbol-qualified single backtick spans

Qualify ADR code citations as a single `path:Symbol` backtick span — never a bare file path or a split `path` + `Symbol` pair.

Example: Use `` `src/reviewer.py:ReviewRunner._build_command` ``, not `` `src/reviewer.py` `` alone or `` `src/reviewer.py` `` + `` `ReviewRunner._build_command` `` as separate spans. In `src/adr_drift.py:65-83`, bare `src/epic.py` triggers `_citation_drifts` on any diff; `src/epic.py:EpicManager.release_epic` scopes it to that symbol. For shared-infra-suppressed files (e.g. `src/review_phase/_phase.py`), bare paths are fine. For reference-only prose mentions, drop the `src/` prefix. See also: [patterns] — docs/arch/generated/* is a make arch-regen artifact.

**Why:** Bare or split citations drift-flag every unrelated edit to multi-concern files, producing false-positive ADR-0092 drift alerts that train developers to ignore the gate.
