# ADR-0144: Trace-grounded retrospective findings — anchors, not advice

**Status:** Proposed
**Date:** 2026-08-31
**Enforcement:** enforced
**Enforced by:**
- pytest:tests/test_retro_findings.py::TestAnchorsAreMandatoryByConstruction::test_every_anchor_field_rejects_blank
- pytest:tests/test_retro_signals.py::TestSignalsNeverKeyOnSucceeded::test_codex_shaped_span_produces_no_tool_error_signal
- pytest:tests/test_retro_evidence.py::TestPrefixCoverageIsDerivedNotSpelled::test_every_issue_keyed_prefix_has_a_gather_glob
- pytest:tests/test_retrospective_evidence_wiring.py::TestTheProsePatternsAreGone::test_retired_machinery_is_absent
- pytest:tests/regressions/test_issue_11890_retro_loop_reports_real_counts.py::test_filed_findings_reach_the_loop_result
**Binds:** factory
**Supersedes:** none
**Superseded by:** none

**Precedent:** Blameless postmortems that require a concrete corrective action with an owner and an artifact, rather than a narrative conclusion (Allspaw; Google SRE Workbook ch. 10)
**Divergence:** a postmortem's discipline is social — a reviewer refuses a vague action item. Here the refusal is structural: a finding without a resolvable anchor cannot be represented, and one whose anchor does not resolve against the working tree is dropped and counted before any human reads it. (receipt: ADR-0074's detector shipped four unanchorable prose branches that no review caught for the loop's entire life; #11890 — the same loop reported `patterns_filed: 0` throughout, and #11891 — the class of fields pinned only by hand-constructed tests)

## Context

[ADR-0074](0074-retrospective-loop.md) established `RetrospectiveLoop` as a
durable-queue consumer that detects cross-pipeline patterns. Its detector read
`RetrospectiveEntry` — thirteen fields of PR metadata — and emitted four
hardcoded threshold branches whose entire output vocabulary was advice:

> "Consider strengthening the implementation prompt to emphasize running `make quality`."
> "Consider improving the planner prompt to better analyze dependencies."
> "The implementation prompt likely needs strengthening to produce higher-quality first drafts."
> "The planner should be made aware that this file commonly needs changes."

None names a file, a command, an error, or a guard, and no amount of prompt
tuning could make them do so: no field on `RetrospectiveEntry` can carry a
repro. The loop had no evidence channel.

It did not need a new one. `src/trace_collector.py` has been writing
`SubprocessTrace` per phase per run, keyed by issue number, the whole time —
[ADR-0044](0044-hydraflow-principles.md) P8.6 states the dependency in its own
remediation text ("without traces, session retros have nothing to mine") — and
the retro never read it. `BaseRunner._save_transcript` likewise writes phase
transcripts the retro never opened.

## Decision

The retrospective reads evidence and emits **anchored artifacts**. Five pure
stages plus one emission stage:

1. **`retro_evidence.gather`** — an issue's `SubprocessTrace` JSONs and phase
   transcripts. Total: missing data yields an empty bundle, never an error.
2. **`retro_signals.extract`** — tool-error clusters, crash signatures, skill
   failures and tool thrash, each carrying a count, the issues it spans, and
   the verbatim evidence text.
3. **`retro_finder`** — a model proposes candidate findings, grounded only in
   those signals.
4. **`retro_findings.validate`** — the gate.
5. **`retro_emitter.emit`** — `GATE`/`BUGFIX` file one class issue via
   `file_or_fold`; `POLICY` goes to the HITL memory path.

**The vagueness fix is structural, not a prompt asking for specificity.** Each
finding kind declares required, non-empty anchor fields, so a finding without a
concrete artifact is unconstructable. `validate` then resolves every anchor
against the real tree: `guard_path` must sit inside the enforcement allowlist;
`repro_file` and `doc_path` must exist; `error_excerpt` must appear **verbatim**
in the cited signal's evidence; `observed` must literally restate the signal's
count. Failures are dropped **with a reason and a count**, so a confabulating
model surfaces as a rising drop rate rather than as board spam.

**Signals key on `ToolCallSpan.error`, never on `succeeded`.** A Codex span ends
`succeeded=False, error=None` because Codex has no completion handler — "never
closed", not "failed". Keying on `succeeded` would score every Codex tool call
as a failure. This constraint outlives the current gap: it holds until
[#11889](https://github.com/T-rav/hydraflow/issues/11889) lands Pi and Codex
error capture.

**`POLICY` findings never file issues.** A rule that changes how the factory
behaves is signed by a human. This preserves the harnessed-not-autonomous
property recorded in the wiki and in ADR-0044's P-series.

## Consequences

- The retro's output becomes actionable without a builder re-deriving context:
  every finding names a file, a command, or a guard location.
- The anchor requirement cannot regress by prompt drift, because it is not
  enforced by the prompt.
- One lightweight model spawn per tick that has signals, bounded by
  `retro_evidence_max_chars` and `retro_findings_max_per_tick`, degrading to
  zero findings rather than to failure when credits are out.
- Issues predating trace collection yield nothing. This is a floor on coverage,
  not a defect.
- The four prose branches, `_file_improvement_issue`, and the `filed_patterns`
  `DedupStore` are retired; dedup moves to the durable class-key marker in the
  issue body.
- `_handle_retro_patterns` now returns real counts. It previously returned a
  hardcoded `patterns_filed: 0` ([#11890](https://github.com/T-rav/hydraflow/issues/11890)),
  so the loop reported zero for its entire life.

## Alternatives considered

- **Tune the four prose branches.** Rejected: the branches were not badly
  worded, they were unanchorable. `RetrospectiveEntry` has no field that could
  hold a repro.
- **Deterministic findings only, no model.** Rejected as insufficient: tool-error
  clusters and crash signatures are countable without a model, but turning a
  cluster into a *proposed guard or rule* is judgement. The validator, not the
  absence of a model, is what makes the output trustworthy.
- **Let the model file issues directly.** Rejected: an unvalidated model writing
  to the board is precisely the failure the drop-and-count path exists to
  prevent.

## Related

- [ADR-0074](0074-retrospective-loop.md) — the loop this extends
- [ADR-0029](0029-caretaker-loop-pattern.md) — caretaker loop pattern
- [ADR-0049](0049-trust-loop-kill-switch-convention.md) — kill-switch convention
- [ADR-0044](0044-hydraflow-principles.md) — P8.6, the trace-collector requirement
