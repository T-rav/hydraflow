---
id: 0288
topic: architecture
source_issue: 10894
source_phase: plan
created_at: 2026-07-31T11:12:50.925648+00:00
status: active
corroborations: 1
---

# Add AuditReport fields with field(default_factory=dict) on frozen dataclass

When adding a structured field to the frozen `AuditReport` dataclass in `src/branch_protection_audit.py`, use `field(default_factory=dict)` so every existing `AuditReport(repo=, drifts=)` construction site stays untouched.

Example: `undeclared_contexts: dict[str, list[str]] = field(default_factory=dict)`.

**Why:** Omitting the default forces all call sites to supply the new argument, churning unrelated code and risking silent `KeyError`s in dedup logic.
