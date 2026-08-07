# ADR-0131: Spec intake gate — stress-testing prose before it becomes a setpoint

- **Status:** Proposed
- **Date:** 2026-08-06
- **Related:** #10829 (setpoint erosion — the parent this companions); #10819 (stillness — *event-triggered on submission, not a cron loop*, the damper-zero rule); [ADR-0126](0126-golden-baseline-finder-calibration.md) / #10821 (a prose critic is a generative sensor with no natural zero — golden-baseline calibration is the follow-up); #10673 (the lineage pass that consumes *divergent-but-uncontradicted* output); `src/assumption_surfacer.py` (the existing issue-stage assumption surfacer this borrows the seam pattern from); [ADR-0116](0116-prompts-as-a-measured-contract.md) / [ADR-0129](0129-adr-checkable-assertion-density.md) (sibling "measure the form, not just the claim" instruments)
- **Enforcement:** enforced
- **Enforced by:** `pytest:tests/test_spec_intake_gate.py`
- **Binds:** factory
- **Addresses:** #10830 (spec intake gate — stress-test prose before it becomes a setpoint)

> **This is a Proposed ADR — a design ruling for decision, not an accepted commitment.** It records the schema, the load-bearing guardrails, and — deliberately — what is *deterministic and live today* (the falsifiability metric + verdict schema + ledger) versus *deferred* (the model reviewer wiring, and golden-baseline calibration of the prose critic). Accept, amend, or reject.

## Context

The `advisory-review-then-refine-then-plan` pass — a read-only Opus read of each spec against the real code before planning — already stress-tests prose by hand. But it records no verdict and keeps no trend, so it cannot answer whether specs are improving or degrading, and it runs only when a human remembers. #10830 turns it into an instrument: an event-triggered gate that records a verdict per spec/ADR/proposal and **never edits the document** (proposal-only write surface).

Prose is where the *meaning gap* lives — a confused junior asks; a model resolves ambiguity silently in whichever direction the nearest context points. A spec that becomes a setpoint carries that ambiguity into everything built from it.

## Decision

Ship `src/spec_intake_gate.py` — a pure engine with the verdict schema and the deterministic companion metric, plus an injected model seam for the checks that need a reviewer. The design is constrained by four guardrails the issue makes load-bearing:

1. **Two divergence classes, never one score** (`DivergenceKind`). "Contradicted by fact" is a defect; "diverges from established practice" is **not** — it is where HydraFlow's genuinely novel material lives (plant-edits-controller, generative sensors), and a consensus check that merged the two would flag the contributions as defects. Divergent-but-uncontradicted is *useful* output and feeds the lineage pass (#10673). The ledger row keeps the counts separate.

2. **No aggregate score.** A mean over findings destroys severity and dependency (and scores invite gaming and defensiveness; questions invite revision). The headline is `SpecIntakeVerdict.headline_severity` — the **max** severity over the load-bearing assertions — never a blended number. The three contradiction checks (`INTERNAL` / `CORPUS` / `CODE`) are reported separately, not summed.

3. **A falsifiability companion metric is required, and it is the deterministic core.** A document with no checkable claims passes any stress test perfectly, so a claim-free spec must itself be flaggable — otherwise the gate trains authors toward mush (the #10829 failure mode). `falsifiability_report` measures claim density (the fraction of statements carrying a falsifiable marker — a normative keyword, code span, path, number, or named symbol) and flags the hedge-only, claim-free statements to revise first. This runs with no reviewer.

4. **The prose critic needs golden-baseline calibration** (#10821): a generative sensor has no natural zero, so what the reviewer flags on ADRs already considered sound must be measured before its flags on new specs are trusted. Deferred as a documented follow-up.

The three contradiction checks and the unstated-assumption surfacing are model work behind the `SpecReviewer` protocol seam (routed out-of-family per judge-independence in Phase-2 wiring). `assess()` runs the deterministic metric always and folds in the reviewer's findings when one is injected; verdicts append to `<data_root>/spec_intake/spec_intake_verdicts.jsonl`.

## Consequences

- The advisory-review pass gains a recorded verdict + a trend, and a *falsifiability* metric that catches the mush a contradiction-only critic would pass.
- Because the falsifiability metric is deterministic, it is live today; the contradiction/assumption checks are inert until the `SpecReviewer` seam is wired (Phase 2), and their calibration (#10821) is a further step. The claim-density heuristic is intentionally coarse (a marker-based proxy, not semantic understanding) — it answers "does this assert anything checkable?", not "is the assertion true"; the latter is the reviewer's job.
- Event-triggered wiring (run on spec/ADR/proposal submission) and a diagnostics surface are the remaining integration; the on-demand pure `assess()` is the building block.
