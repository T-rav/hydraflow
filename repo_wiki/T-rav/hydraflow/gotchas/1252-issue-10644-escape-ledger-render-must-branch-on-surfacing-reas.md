---
id: 1252
topic: gotchas
source_issue: 10644
source_phase: plan
created_at: 2026-07-26T12:01:31.012769+00:00
status: active
corroborations: 1
---

# Escape ledger render must branch on surfacing reason

`_render_finding` in `src/escape_ledger_loop.py` must emit a reason-scoped resolution block because `_surfacing_answered` uses a different closure field per reason: `aging` checks `encoded_as != "none-yet"`, `low-confidence` checks `attribution_confidence != "low"`.

- Aging block: `--encoded-as <value>` only.
- Low-confidence block: `--encoded-as <value> --confidence <high|medium|low>`.

The CLI (`scripts/resolve_escape.py`) and `_surfacing_answered` are already correct; only the render path needs branching.

**Why:** A reason-agnostic render block emits a command that cannot satisfy the closure check for its own surfacing reason, stranding the issue forever.
