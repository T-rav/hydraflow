---
source: feedback_backlog_to_loop_reflection.md
name: feedback_backlog_to_loop_reflection
description: When manually clearing a recurring backlog a bg worker should own, run the backlog-to-loop reflection and spec a resolver
status: wontfix
issue: null
promoted_in: null
wontfix_reason: 'No code surface. A lint cannot see that a session is grooming rather
  than building, and a loop that files ''you should have reflected'' is the detector-without-resolver
  shape the rule itself warns about. Resolved as CAPTURED on #12054 per the convention
  guarded by tests/regressions/regression_issue_10292.py. The rule stays live in docs/methodology/backlog-to-loop-reflection.md.'
created: '2026-07-18'
---

When you catch yourself (or a session) **manually clearing a recurring backlog the factory should own** — HITL pile-ups, batches of near-identical issue closes/fixes, "why am I poking at this again?" — STOP and run the **backlog-to-loop reflection**, then file a `hydraflow-find` for the loop that should do it next time. Travis asked for this explicitly (2026-07-19): "I do not want to keep poking at things... document this reflection step so we know to do it again."

**Why:** repeated manual grooming is a missing loop. Every poke that repeats is evidence the fleet has a detector but no resolver.

**How to apply:** the 4 questions (playbook: `docs/methodology/backlog-to-loop-reflection.md`):
1. Write the process as a state machine — DETECT → TRIAGE → RESOLVE → ESCALATE; note who does each today (the factory usually does DETECT + ESCALATE; the human silently does TRIAGE + RESOLVE — that's the gap).
2. Which signal is missing? Almost always a **triage judgment** (an LLM call classifying a detector's finding FP-vs-fixable), not more detection.
3. Amend or create? Default: **create a thin resolver tier** that consumes the detector's existing output (issues/labels = ready work queue) → triage → {auto-close FP with audit comment / dispatch fix to the `hydraflow-find` pipeline / HITL only on low confidence}. Keep the detector cheap (no LLM); fail closed. Precedent: `SandboxFailureFixerLoop`; detection/resolution split per ADR-0080/0081.
4. Spec it as `hydraflow-find` with the manual sweep as the reference implementation (prompts + verdicts + audit-comment wording become the classifier's few-shot).

Fires at **N=1 when repetition is within the batch** (lighter than the N=2 [[learning-cycle-manual-to-factory]] outer cycle). The anti-pattern: **detector-without-resolver** — escalates to HITL on retry-exhaustion, never asking "is this even real?", so HITL becomes the default sink.

Worked example: the 2026-07-18/19 ADR-drift sweep (~33 issues cleared by hand) → #9976 (`AdrDriftResolverLoop`) + #9662 (amplification). **Counter-example too:** both loops and the auditor they served were retired (#10540) and deleted (ADR-0136) for a ~70% false-positive rate — reflecting a backlog into a loop only pays when the backlog is a real signal; here the right answer was a deterministic gate, not a second loop to triage the first one's noise. Related: [[project_repo_wiki_feature]], ADR-0056 (superseded by ADR-0136).
