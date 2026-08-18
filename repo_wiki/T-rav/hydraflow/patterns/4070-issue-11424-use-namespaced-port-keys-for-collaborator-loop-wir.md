---
id: 4070
topic: patterns
source_issue: 11424
source_phase: review
created_at: 2026-08-18T09:01:27.985879+00:00
status: active
corroborations: 1
---

# Use namespaced port keys for collaborator loop wiring

Use namespaced port-key conventions (`<loop_prefix>_<port_name>`) when wiring collaborator loops into builders, not bare names. Staging uses `escape_ledger_auto_diagnoser` and `skill_prompt_refine_llm`; bare forms like `auto_diagnoser`/`refine_llm` are incompatible and will conflict.

Example: `tests/scenarios/catalog/loop_registrations.py` on staging expects the namespaced form.

**Why:** Inconsistent port-key conventions cause silent mis-wiring when multiple loops share similarly-named ports across different builders.
