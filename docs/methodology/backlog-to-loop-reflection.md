# Backlog-to-Loop Reflection — turn manual grooming into an autonomous resolver

**Status:** Methodology
**Last updated:** 2026-07-19
**Cross-references:**
- [`learning-cycle-manual-to-factory`](learning-cycle-manual-to-factory.md) — the heavier N=2 *outer* cycle for building **new** capabilities. This doc is its lightweight sibling for **existing detectors that don't resolve**.
- [`factory_operation/README.md`](../standards/factory_operation/README.md) §"Self-modifying maintenance mode" — the *inner* cycle (runtime recurring failures → caretaker loops).

---

## What this is

A short reflection to run **whenever you catch yourself manually clearing a recurring backlog the factory should own** — HITL pile-ups, batches of near-identical issues you close/fix by hand, "why am I poking at this again?" The output is a `hydraflow-find` spec for a loop (usually a *resolver*) that does the work next time.

Unlike the outer learning-cycle (which needs N=2 across *different domains* before extracting), this reflection fires at **N=1 when the repetition is *within* the batch** — clearing 20 near-identical ADR-drift rollups in one sitting is already 20 data points of the same shape. The pattern is real; automate it.

**Trigger test:** *"Did I just make the same judgment call more than a handful of times, and could an LLM + a bounded tool call have made it?"* If yes, run the four questions.

---

## The four questions

### 1. What was the process? Write it as a state machine.
Name each step and **who does it today**. The recurring shape is almost always:

```
DETECT ──► TRIAGE ──► RESOLVE ──► ESCALATE
(a loop)   (you)      (you)       (HITL, rarely)
```

The factory usually does DETECT and ESCALATE; the human is silently doing TRIAGE and RESOLVE. Those two are the gap.

### 2. What signals drove it, and from where? Which is *missing*?
Make a table: `signal | source | exists?`. The missing row is nearly always a **triage judgment** — an LLM call that classifies a detector's finding (false-positive vs auto-fixable vs genuinely-needs-a-human), **not** more detection. Detection is cheap and usually already there; judgment is the capability the fleet lacks.

### 3. Amend or create? → default to a thin **resolver tier**
The dominant anti-pattern is a **detector that escalates to HITL on retry-exhaustion** — it re-detects the same finding N times, then dumps it on a human, having never asked *"is this even a real problem?"* HITL becomes the default sink instead of the last resort.

- **Keep the detector cheap** (scan + file, no LLM). Don't bolt judgment into the scanner — it couples two concerns and makes every tick heavy.
- **Create a resolver** that consumes the detector's existing output (its issues/labels are a ready-made work queue) and does: **triage → {auto-close false-positive with an audit comment / dispatch a fix to the normal `hydraflow-find` pipeline / HITL only on low confidence}**.
- **Fail closed**: never auto-close something you can't confidently call a false positive. Low confidence → human.
- Precedent: `SandboxFailureFixerLoop` (consumes a label → fix or escalate); detection/resolution separation is house style (ADR-0080/0081).

### 4. Spec it as a `hydraflow-find` — with the manual sweep as the reference implementation
The batch you just cleared *is* the shape-phase artifact: your triage prompts, your close-vs-fix verdicts, and your audit-comment wording become the classifier's prompt and few-shot examples. Cite the specific PRs/closed issues so the implementer mines them instead of re-deriving. Require the full test pyramid (the classifier's routing is load-bearing).

---

## Worked example (the reflection that produced this doc)

| Step | 2026-07-18/19 ADR-drift sweep |
|---|---|
| Manual work | Cleared ~33 ADR issues by hand: ~20 drift rollups + HITLs, citation-rot, tooling bugs, supersede/refresh |
| 1 — process | DETECT (`AdrTouchpointAuditorLoop`, ✅) → TRIAGE (me: ADR *Decision* vs cited-PR diff) → RESOLVE (close FP / edit ADR → PR) → ESCALATE (HITL, should be rare) |
| 2 — missing signal | the **triage judgment** — an LLM call over (ADR Decision) × (cited-PR diff). Detection already existed; judgment didn't. ~70% of findings were false positives. |
| 3 — amend/create | **create** `AdrDriftResolverLoop` (consume `hydraflow-adr-drift` rollups); leave the auditor as a pure detector |
| 4 — spec | filed **#9976** (`hydraflow-find`); cross-linked **#9662** (the amplification half). The manual sweep's PRs (#9953, #9963) + closed-rollup comments are the reference implementation |

The anti-pattern it fixed: the auditor escalated on *"re-filed 3× without closure"* (#9929/#9513/#9514) — retry-exhaustion, never *"is this a false positive?"*.

---

## Generalization

The **detector-without-resolver** shape is fleet-wide, not ADR-specific. The same triage-before-escalate tier applies to any caretaker that files HITL-eligible findings (fake-coverage, principles-drift, live-corpus drift). Prove it once on ADR drift; if it holds, promote the triage-then-{close/dispatch/HITL} into a shared `ResolverLoop` base other detectors plug into. Scope each `hydraflow-find` to one detector (YAGNI) — don't spec the shared base until the first resolver has shipped and earned it.

## Anti-patterns

- **Poking as a habit.** If you find yourself clearing the same backlog on consecutive nights, you've skipped this reflection. Every repeated poke is a missing loop.
- **Amending the detector to also judge.** Makes the cheap scanner heavy and entangles two lifecycles. Add a resolver tier instead.
- **Auto-closing on weak judgment.** A resolver that closes real drift is worse than one that escalates too much. Fail closed; tune the confidence threshold down only with evidence.
- **HITL as the default sink.** If a detector's normal outcome is "human, please look," it's missing its resolver.
