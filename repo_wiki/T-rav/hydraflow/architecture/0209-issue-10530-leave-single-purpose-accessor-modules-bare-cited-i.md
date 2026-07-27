---
id: 0209
topic: architecture
source_issue: 10530
source_phase: plan
created_at: 2026-07-25T09:44:02.075244+00:00
status: active
corroborations: 1
---

# Leave single-purpose accessor modules bare-cited in ADRs, not :Symbol

When an ADR wholly owns a small single-purpose module (e.g. `src/state/_auto_agent.py`, `_sandbox_failure_fixer.py`, `_convergence.py` under ADR-0097), keep its citation bare rather than qualifying to `:Symbol` — any touch to that file is genuinely in scope for the ADR, so file-level drift is correct signal, not noise. Only qualify multi-concern modules like `src/implement_phase.py` or `src/retrospective.py` where the ADR owns just one symbol among many unrelated ones.

**Why:** over-qualifying an ADR that wholly owns a file would silence legitimate drift detection for real in-scope changes.
