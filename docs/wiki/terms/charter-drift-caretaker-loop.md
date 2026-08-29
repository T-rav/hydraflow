---
id: "01KZ07BBDCF5RAZW7VG2VY4NW7"
name: "CharterDriftCaretakerLoop"
kind: "loop"
bounded_context: "caretaker"
code_anchor: "src/charter_drift_caretaker_loop.py:CharterDriftCaretakerLoop"
aliases: ["charter drift caretaker loop", "charter drift caretaker", "charter drift loop"]
related: [{"kind": "depends_on", "target": "01JZ9FK3C0M01HYR42BF11W0A1"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K7"}, {"kind": "depends_on", "target": "01KY4QF8BE4Y5782543MPQNDQ0"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K2"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K5"}, {"kind": "depends_on", "target": "01JZ9FK3C0M03HYR42BF33W0C3"}, {"kind": "depends_on", "target": "01KWDRENTS7VACCW9PDA7Y488H"}, {"kind": "implements", "target": "01KQV37D10M06PGF32CF77W6K5"}]
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-08-01T00:00:00.000000+00:00"
updated_at: "2026-08-14T05:32:18.123535+00:00"
---

## Definition

Caretaker loop (ADR-0121 as amended by #11748, ADR-0143) that audits each managed repo's live state against its charter (`charter.yaml`) and files deduped `hydraflow-find` drift issues. Mirrors the ADR-drift (ADR-0056) and branch-protection-drift (ADR-0082) caretakers: periodic, contract-diffing, one deduped issue per finding class. Per tick it loads the repo's charter, observes live state, and computes drift — a declared standard whose `docs/standards/<id>/` directory is gone, a declared required artifact that is absent, a missing template layer, a coverage-floor breach, or a missing declared domain gate script. Unknown layer names and unknown standard ids are reported but never file an issue (tolerated, forward-compat), and so is a legacy `rails.yaml` read through the one-cycle fallback. Dedup key is `charter_drift_caretaker:<repo>:<finding_class>`; when a finding class resolves, its open issue is closed and the key cleared so a recurrence re-files.

## Invariants

- One deduped drift issue per (repo, finding class); never one issue per individual failing check.
- A declared standard or artifact that is absent is drift; an undeclared extra of either is fine; an unknown standard id or layer name is reported but never fatal.
- A charter that declares nothing checkable, or whose standard ids cannot be resolved against any registry, is FATAL rather than silently clean — a drift check with an empty subject list reads as coverage.
- The coverage floor is evaluated only when observed coverage is known (fail-open: no drift on an unmeasured value).
- Kill-switch is via `enabled_cb("charter_drift_caretaker")` (ADR-0049), then the static `charter_drift_caretaker_loop_enabled` config gate (default OFF).
- Cadence is config-driven via `charter_drift_caretaker_interval` (default 1 day).
