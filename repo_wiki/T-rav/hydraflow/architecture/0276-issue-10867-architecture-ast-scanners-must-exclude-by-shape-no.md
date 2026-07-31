---
id: 0276
topic: architecture
source_issue: 10867
source_phase: plan
created_at: 2026-07-31T03:20:17.216740+00:00
status: active
corroborations: 1
---

# Architecture AST scanners must exclude by shape, not by name

When scanning `src/**/*.py` for duplicate class definitions per ADR-0027, skip `Protocol`, `ABC`, `Enum`/`StrEnum`, `Exception` subclasses and non-data-model classes by inspecting base classes and decorators — never by hardcoded name.

- `LLMClient` (2× Protocol), `_PRPort` (3× Protocol), `GateDecision` (StrEnum vs dataclass) are excluded automatically by shape.

**Why:** Name-based exclusion lists go stale and re-encode the manual review the automation is meant to replace.
