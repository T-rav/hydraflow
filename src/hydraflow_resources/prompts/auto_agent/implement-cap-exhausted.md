# Auto-Agent — implement-cap-exhausted Playbook (#9721 widened HITL intake)

{{> _envelope.md}}

## Sub-label: implement-cap-exhausted

This issue did NOT arrive as a hitl-escalation. It sat idle in the
`hydraflow-hitl` human queue after ImplementPhase spent its full attempt
budget (or bailed on a quality-gate / zero-diff failure) and escalated. Every
in-pipeline retry of the same implementation shape has already failed — you
are the last autonomous attempt before a human is paged.

## Specific guidance

Do NOT repeat the failed implementation shape. Order of operations:

1. Read the issue body, the recent comments (they usually carry the pipeline's
   per-attempt failure summaries), and the prior attempts block. Write down —
   explicitly, before editing anything — WHY each prior attempt failed:
   spec gap, wrong file, failing quality gate, zero diff, flaky test.
2. Classify the failure mode:
   - **Spec gap / stale premise** — the issue's premise no longer matches the
     code (an adjacent PR already landed, the cited symbol moved). If the work
     is genuinely done, say so in the diagnosis and return `resolved` only
     with a real PR; otherwise return `needs_human` naming the stale premise.
   - **Quality-gate failure** — reproduce the exact failing gate locally
     first; fix the gate failure, not just the feature code.
   - **Zero-diff** — the prior agent concluded without committing. Check the
     branch for uncommitted or unpushed work before starting fresh.
3. Take a DIFFERENT approach from the prior attempts: smaller scope, a
   different seam, or a test-first reproduction of the exact failure the
   pipeline hit. Diverse retry beats repeated retry.
4. Write the failing test first (TDD per `docs/wiki/testing.md`), implement
   the smallest change that satisfies it, then run `make quality` before
   pushing.
5. Either push and open a PR (`resolved`) or return `needs_human` with a
   diagnosis a human can act on in one sitting: what was tried, what was
   ruled out, and the single decision you need from them.

Do NOT:
- Re-run the pipeline's implementation prompt shape and hope for a different
  outcome — the attempt cap already proved that path out.
- Force-push over prior attempt branches; start fresh on the loop's
  `agent/auto-agent-<issue>` branch.
- Return `resolved` without a PR URL. A claim without a PR is a `pr_failed`.
