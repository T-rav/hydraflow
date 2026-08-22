# Auto-Agent — review-stuck Playbook (ADR-0063 W1)

{{> _envelope.md}}

## Sub-label: review-stuck

ReviewPhase escalated. Most commonly this is a sandbox/CI red — but the
SandboxFailureFixerLoop already runs for those, so by the time the issue
reaches you, the failure-fixer either gave up or wasn't applicable.

## Specific guidance

Identify the failure class from the escalation context:

- **CI / sandbox red** — read the test transcript (in escalation context),
  pair the failing test name(s) to the recent commit that touched the
  closest surface. Fix the test or the production code, push, return
  `resolved`.
- **Visual-validation failure** — HITL-by-design (ADR-0063 §Decision).
  Return `needs_human` with the failing screenshot path; do not attempt
  a fix.
- **Merge conflict with main** — HITL-by-design when the conflict touches
  files outside the PR's stated scope. Otherwise, rebase, run
  `make quality`, and push.

If the failure class is ambiguous, the diagnosis goes in the audit and the
issue gets `needs_human` — don't guess. The wiki entries above often encode
the regression pattern explicitly.

Do NOT:
- Modify visual-validation baselines without a human signing off.
- "Fix" failures by deleting tests. If a test is genuinely wrong, change
  the assertion (with a code comment explaining why) — never delete the
  test.
