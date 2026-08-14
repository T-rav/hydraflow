---
id: "01KZ07BBDCF5RAZW7VG2VY4NW7"
name: "RailsDriftCaretakerLoop"
kind: "loop"
bounded_context: "caretaker"
code_anchor: "src/rails_drift_caretaker_loop.py:RailsDriftCaretakerLoop"
aliases: ["rails drift caretaker loop", "rails drift caretaker", "rails manifest drift loop"]
related: [{"kind": "depends_on", "target": "01JZ9FK3C0M01HYR42BF11W0A1"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K7"}, {"kind": "depends_on", "target": "01KY4QF8BE4Y5782543MPQNDQ0"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K2"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K5"}, {"kind": "depends_on", "target": "01JZ9FK3C0M03HYR42BF33W0C3"}, {"kind": "depends_on", "target": "01KWDRENTS7VACCW9PDA7Y488H"}, {"kind": "implements", "target": "01KQV37D10M06PGF32CF77W6K5"}]
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-08-01T00:00:00.000000+00:00"
updated_at: "2026-08-14T05:32:18.123535+00:00"
---

## Definition

Caretaker loop (ADR-0121, #10936) that audits each managed repo's live state against its rails manifest (`rails.yaml`) and files deduped `hydraflow-find` drift issues. Mirrors the ADR-drift (ADR-0056) and branch-protection-drift (ADR-0082) caretakers: periodic, contract-diffing, one deduped issue per finding class. Per tick it loads the repo's manifest, observes live state, and computes drift — a missing declared layer, a coverage-floor breach, or a missing declared domain gate script. Unknown/future layer names are reported but never file an issue (tolerated, forward-compat with the Book-3 operator-agent pack). Dedup key is `rails_drift_caretaker:<repo>:<finding_class>`; when a finding class resolves, its open issue is closed and the key cleared so a recurrence re-files.

## Invariants

- One deduped drift issue per (repo, finding class); never one issue per individual failing check.
- A missing declared layer is drift; an undeclared extra rail is fine; an unknown/future layer name is reported but never fatal.
- The coverage floor is evaluated only when observed coverage is known (fail-open: no drift on an unmeasured value).
- Kill-switch is via `enabled_cb("rails_drift_caretaker")` (ADR-0049), then the static `rails_drift_caretaker_loop_enabled` config gate (default OFF).
- Cadence is config-driven via `rails_drift_caretaker_interval` (default 1 day).
