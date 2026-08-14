# ADR-0115: Auto-diagnose before human for audit + escape surfaces

**Status:** Accepted
**Date:** 2026-07-27
**Enforcement:** enforced
**Enforced by:**
- pytest:tests/regressions/test_escape_auto_diagnose_before_human.py::TestEscapeAutoDiagnoseBeforeHuman::test_real_and_encoded_is_auto_resolved_no_human_surface
- pytest:tests/regressions/test_escape_auto_diagnose_before_human.py::TestEscapeAutoDiagnoseBeforeHuman::test_inconclusive_still_reaches_a_human
- pytest:tests/regressions/test_sampled_audit_auto_adjudicate_before_human.py::TestSampledAuditAutoAdjudicateBeforeHuman::test_upheld_self_applies_label_and_crosslinks
- pytest:tests/regressions/test_sampled_audit_auto_adjudicate_before_human.py::TestSampledAuditAutoAdjudicateBeforeHuman::test_inconclusive_leaves_it_for_a_human
- pytest:tests/test_escape_auto_diagnose.py::TestClassifyDiagnosis::test_bug_label_stays_inconclusive_not_dismissed
- pytest:tests/test_audit_adjudicate.py::TestParseAdjudication::test_unparseable_is_inconclusive_not_upheld

**Precedent:** Automated triage / auto-remediation before paging — the SRE incident-response tradition in which a known alert first runs its remediation runbook, and a human is paged only for what the runbook cannot resolve (Beyer et al., *Site Reliability Engineering*, O'Reilly 2016 — "reduce toil", auto-remediation before human escalation).
**Divergence:** that tradition assumes a *deterministic runbook keyed to a known alert*, so the machine step is a fixed script; here the two surfaces are ambiguous signals with no fixed runbook — a **low-confidence escape attribution** (which merge introduced this?) and an **adversarial re-audit disagreement** (is this a real escape?) — so the rule is that the machine runs a bounded, **fail-safe DIAGNOSE** (evidence-gated resolve / dismiss / adjudicate) that self-answers the surface when it can, and only an *inconclusive* diagnosis pages a human (receipt: #10748, #10749, #10750, #10751 — ~5 manual human-resolutions in one operating session that were all machine-resolvable confirm-or-dismiss-with-evidence).

## Context

Two read-only ADR-0029 caretaker loops file `hydraflow-find` / HITL findings:

- **`EscapeLedgerLoop`** (`src/escape_ledger_loop.py`, #10367) surfaces a
  `SURFACE_REASON_LOW_CONFIDENCE` finding when a detected escape's mechanical
  *attribution* is `low` — asking a human to confirm the label. The manual move
  that answered these (#10748 / #10749) was mechanical: trace the escape's
  `detection_ref` commit → the bug it fixed → check whether that bug is already
  regression-encoded (`git grep tests/regressions/`); if real + encoded, record
  the resolution at `--confidence high --encoded-as regression-test`; if a false
  positive, dismiss with evidence.
- **`SampledAuditLoop`** (`src/sampled_audit_loop.py`, #10370) files a finding
  for every adversarial re-audit *disagreement* and then waits for a human to
  apply `audit-upheld` / `audit-refuted`. The manual move (#10750 / #10751) was
  to fetch the merged diff + the auditor's claim, adjudicate (upheld → needs
  fix; refuted → close with evidence) and apply the label — **never**
  `human-required`.

Both surfaces routed to a human *before* the machine attempted the resolution,
even though the resolution was a mechanical / adversarial-adjudication step the
factory can run itself. In one operating session this forced ~5 human
resolutions that were all machine-resolvable. This is the exact HITL-scatter
anti-pattern the formal give-up window ([ADR-0105](0105-autonomous-convergence-via-decomposition.md),
#10735) fixed for the plan-retry route-back: *non-convergence / ambiguous signal
is a MECHANISM problem — the machine self-solves (retry → decompose → diagnose)
and the human is the LAST resort.* That contract had not yet been extended to
the falsification-instrument surfaces.

The wrinkle: these loops are **read-only Pattern B** — "senses and records; never
opens a fix PR, never gates." An auto-diagnose that *records a ledger
resolution*, *applies an adjudication label*, or *closes a find issue* is a new
active behavior for a sensor, so the boundary is recorded here rather than
slipped in.

## Decision

Insert a machine **auto-diagnose** step before each human surface, reusing the
give-up window's "self-solve before human" shape. Both are **feature-gated**
(default **off**, mirroring `giveup_window_enabled`) for safe rollout.

### 1. Escape ledger — mechanical auto-diagnose (`src/escape/auto_diagnose.py`)

Gated by `escape_ledger_auto_diagnose_enabled`. Before filing a
`SURFACE_REASON_LOW_CONFIDENCE` finding, for each eligible row run a **purely
mechanical** pass (git reads + `PRPort` issue-label reads, **no LLM spawn**, so
it is air-gap-safe and deterministic):

- **Trace** the `detection_ref` commit → the bug it closed (`Fixes #N`) + any
  introducing sha.
- **Check encoding** — `git grep` `tests/regressions/` for the bug (issue number
  as a whole word, or an introducing sha), plus any regression pin the detecting
  commit added itself.
- **`RESOLVED_ENCODED`** (real + encoded) → auto-record the resolution via
  `escape.resolve.resolve_escape` at `attribution_confidence="high"`,
  `encoded_as="regression-test"`. The low-confidence surface now self-answers
  (`_surfacing_answered`), so no human finding is filed; the row correctly enters
  the CONFIRMED escape count.
- **`DISMISSED`** (clear false positive — the referenced issue carries a non-bug
  label and NO bug label) → record the dismissal in the sidecar only. It does
  **not** mutate the ledger, so a false positive never inflates the
  confirmed-escape count.
- **`INCONCLUSIVE`** (anything else — thin evidence, a bug-labelled but unencoded
  escape) → file the human surface **unchanged**.

### 2. Sampled audit — adversarial auto-adjudicate (`src/audit/adjudicate.py`)

Gated by `sampled_audit_auto_adjudicate_enabled` **and**
`sampled_audit_reaudit_enabled` (the air-gapped sandbox pins re-audit off, so no
adjudicator `claude` is reachable there either). For each pending filed
disagreement not yet adjudicated, a fresh adversarial adjudicator re-reads the
merged diff + the auditor's finding and self-applies the disposition:

- **upheld** → apply `audit-upheld` (the existing reconcile then crosses it into
  the escape ledger as a `sampled-audit` detection);
- **refuted** → apply `audit-refuted` + close with evidence (auditor false
  alarm);
- **inconclusive** → leave the finding unlabelled for a human (the genuine
  escalation path, preserved).

### 3. Fail-safe is load-bearing, in both directions

The default verdict is `INCONCLUSIVE` (→ human). A resolution is recorded only on
a concrete regression encoding; a dismissal only on a concrete non-bug label; an
`upheld`/`refuted` only on an explicit adjudicator verdict, and `parse_*` is
fail-soft **toward `inconclusive`** so a malformed response reaches a human
rather than fabricating an `upheld` (a false escape cross-link) or a `refuted`
(a suppressed real escape). A genuinely-unresolved real bug is never auto-closed.

## Consequences

- **HITL scatter on these surfaces is eliminated for machine-resolvable
  findings.** The ~5-per-session manual resolutions become zero; the human sees
  only genuinely inconclusive cases. This is the same selectivity ADR-0105 gave
  the plan-retry terminal, now extended to the audit + escape instruments.
- **The genuine escalation path is preserved.** Inconclusive diagnoses (and any
  diagnose/adjudicate failure) fall through to the existing human surface — the
  change is selectivity, not suppression.
- **A read-only sensor now performs bounded active moves.** The Pattern-B
  contract is amended (not broken): the sensor may auto-answer *its own* low-
  confidence / aging / disagreement surface (record a resolution, apply a
  disposition label, close a find issue), but still never opens a fix PR and
  never gates. The active surface is confined to the finding it would
  otherwise have filed. The escape pass diagnoses every surfacing reason
  (`SURFACE_REASON_LOW_CONFIDENCE` and `SURFACE_REASON_AGING`) the same way —
  an aging `none-yet` row whose encoding is already on disk self-answers
  exactly like a low-confidence one (#11161).
- **Off by default; air-gap-safe.** Both flags default off for staged rollout.
  The escape pass is LLM-free; the audit pass is double-gated behind re-audit, so
  the sandbox reaches no spawn.
- **Auditable.** Escape dismissals/resolutions record a reason in
  `escape_diagnoses.jsonl`; audit adjudications post the verdict + rationale as a
  comment — the same audit trail a human resolution would leave.

## Alternatives considered

**File the finding but route it to the diagnose *label* (auto-agent pipeline).**
Rejected for the escape surface: the resolution is mechanical (a `git grep`), so
spawning an agent per low-confidence row is disproportionate; and for the audit
surface the disposition is exactly the `audit-upheld`/`audit-refuted` label the
reconcile already consumes, so applying it inline reuses the whole existing path
instead of forking a second one.

**Mutate the ledger for a dismissal (a `dismissed` confidence value).** Rejected:
adding a value to the `AttributionConfidence` literal ripples through the
confirmed-count / collapse / rank logic, and a false positive must not touch the
confirmed-escape count at all. A sidecar dismissal record is the minimal, honest
representation.

**Always on (no feature flag).** Rejected: this is load-bearing factory routing
touching read-only sensors; it ships behind a default-off flag like every other
new-autonomy switch (`giveup_window_enabled`) for a safe, reversible rollout.

## Related

- [ADR-0105](0105-autonomous-convergence-via-decomposition.md) — self-solve
  before `human-required` for the plan-retry terminal (the shape this extends);
  the give-up window (#10735) is its enforcement.
- [ADR-0099](0099-orchestration-as-a-control-system.md) — orchestration as a
  control system; "human as last resort" is a control-policy decision.
- [ADR-0050](0050-auto-agent-hitl-preflight.md) — the auto-agent HITL preflight /
  diagnose path this mirrors for the two sensor surfaces.
- [ADR-0029](0029-caretaker-loop-pattern.md) — the read-only Pattern B caretaker
  contract this amends (a sensor may auto-answer its own finding).
- [ADR-0094](0094-two-level-convergence-gate-and-ledger.md),
  [ADR-0095](0095-approve-path-gating-and-converged.md) — the audit / convergence
  ledger context.
- `src/escape/auto_diagnose.py`, `src/escape_ledger_loop.py:EscapeLedgerLoop` —
  the escape auto-diagnose and its wiring.
- `src/audit/adjudicate.py`, `src/sampled_audit_loop.py:SampledAuditLoop` — the
  audit auto-adjudicate and its wiring.
- #10748, #10749, #10750, #10751 (this decision's receipts — the machine-
  resolvable findings that reached a human).
