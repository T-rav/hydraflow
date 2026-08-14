---
source: feedback_code_review_after_each_pr.md
name: feedback-code-review-after-each-pr
description: Travis wants a code review run after EVERY PR is created, not just for substantial features. Standing workflow step.
status: promoted
issue: 11087
promoted_in: '#11087'
wontfix_reason: null
created: '2026-07-31'
---

**Always run a code review after creating each PR** — every PR, not only big features (2026-08-01).

**Why:** Travis wants a fresh-eyes review pass as a standard gate on the factory's own output, catching defects before merge rather than relying on CI + local quality alone.

**How to apply:** after `gh pr create`, run a code review of the branch diff (e.g. the `feature-dev:code-reviewer` or `code-quality-enforcer` agent, or the `/code-review` flow) and surface/fix findings before (or as part of) enabling auto-merge. Fold it into the standard PR workflow: build → quality → PR → **review** → merge. Note: `/code-review ultra` (cloud ultrareview) is user-triggered and billed — I cannot launch it myself; use an inline review agent instead. Relates to [[feedback_review_before_merge]] and [[project_operational_runbook]].
