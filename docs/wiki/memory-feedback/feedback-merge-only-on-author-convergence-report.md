---
source: feedback_merge_only_on_author_convergence_report.md
name: feedback_merge_only_on_author_convergence_report
description: A substantial PR merges ONLY on an explicit convergence report from its
  author. Green CI, a stable head, a clean worktree, and an idle process count are
  all indistinguishable from a builder pausing between review passes. Cost three corrective
  PRs in one night (2026-08-22/23).
status: promoted
issue: 11948
promoted_in: 12017
wontfix_reason: null
created: '2026-08-23'
---

**Rule: a substantial PR merges only when its author says "pass N found nothing material."** Never on CI green, never on a stable head across polls, never on a clean working tree, never on an idle process count.

**Why:** every builder here pauses *between* review passes. From outside, "finished" and "resting before pass 7" produce identical signals — no running process, nothing uncommitted, all checks green. There is no observable difference. The only thing that distinguishes them is the author saying so.

Three failures in one night proved it, each costing a corrective PR:

- **#11655** (Fable P3) auto-merged at its **first** commit → **7 real defects**, including one where *arming* the canary required a restart while only *disarming* was live. → #11657.
- **#11627** (ADR-0137) merged before review converged → the merged ADR **reproduced the defect class it was written to fix** (most-advanced-label-wins silently reverts route-backs). → #11632.
- **#11657** — merged **by hand, by me**, on exactly the four signals above. **Pass 7 then found a live defect**: `ShadowDispatch.as_tree_node` hardcoded `"dispatched": False` — an invariant true when written that became false the instant the canary armed, so an armed observation's worker tree contradicted its own receipt. → #11662.

**How to apply:**
- Ask the author directly, offering two answers: *"Converged"* → merge; *"Pass N still to run"* → wait, with no time pressure.
- Ask the **right** author. Route by branch/worktree, not by resemblance — a misrouted question to a sibling builder gets a correct refusal at best, a fabricated answer at worst.
- One pass is not convergence on a large diff. #11665 (72 files) converged on pass 1; an independent pass 2 found three real findings, the worst being that decomposing a loop into a package silently dropped 11 of 12 modules out of `CRITICAL_PATH_GLOBS`, cutting its own required review passes from 3 to 1.
- Automate the *mechanical* lane only. The auto-merge daemon skips `docs/adr/`, `src/*_loop.py`, `src/*runner*.py`, and any PR over 20 files; test-hygiene batches still land unattended.
- Require the head to be unchanged across two consecutive polls before any automatic merge — merging mid-push drops the in-flight commit and, with `--delete-branch`, leaves the author pushing to a branch behind a closed PR.

Related: [[feedback_review_before_merge]], [[feedback_code_review_after_each_pr]], [[feedback_verify_aspirational_glue_code]], [[project_dark_factory_night_2026_08_22]], [[project_porting_a_fix_from_its_description]].
