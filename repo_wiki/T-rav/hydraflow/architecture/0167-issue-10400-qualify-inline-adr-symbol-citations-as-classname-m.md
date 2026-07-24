---
id: 0167
topic: architecture
source_issue: 10400
source_phase: plan
created_at: 2026-07-24T05:41:19.861309+00:00
status: active
corroborations: 1
---

# Qualify inline ADR symbol citations as ClassName.method, not bare method names

When converting a bare ADR source citation to symbol-qualified form, use the dotted form `src/epic.py:EpicManager.on_child_approved`, not a bare method name like `src/epic.py:on_child_approved`. Bare method names still parse via the regex's dotted-symbol support but diverge from the qualified convention already used in ADR-0005 and ADR-0009.

**Why:** Consistency lets `adr_drift` and future audits assume symbol citations are always class-qualified, avoiding ambiguity when multiple classes share a method name across `src/*.py` modules.
