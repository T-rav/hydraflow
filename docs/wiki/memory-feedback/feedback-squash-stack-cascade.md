---
source: feedback_squash_stack_cascade.md
name: feedback_squash_stack_cascade
description: How to land a stacked-PR chain onto staging when force-push (rebase --onto) is hook-blocked
status: pending
issue: null
promoted_in: null
wontfix_reason: null
created: '2026-05-31'
---

Landing a stacked-PR chain (#A→#B→#C→#D, each cut from its parent's branch) onto staging when `git push --force` is hook-blocked — so the `git rebase --onto origin/staging <old-parent-tip> <child>` recipe is unavailable.

**Why:** rebase rewrites history → needs force-push → blocked. Auto-merge is also not enabled on this repo ([[feedback_auto_merge_not_enabled]]), so each PR is merged manually.

**How to apply (bottom-up, NON-destructive):**
1. Merge the lowest PR to staging: `gh pr merge <A> --squash`.
2. GitHub auto-retargets the next child's base → staging.
3. For each child bottom-up: `cd` its worktree, `git merge origin/staging`, resolve conflicts, commit (merge commit), push (pre-push gate runs), wait CI green, `gh pr merge --squash`.
4. **Squash-merge naturally drops the duplicated parent commits** — squash diffs the branch against staging *at merge time*, so already-merged ancestor content is excluded. No `--onto` needed.

**The conflict shape to expect:** the squash-merge of each parent *breaks git ancestry* (the squash is a fresh commit), so when you `git merge origin/staging` into a child, ALL the ancestor commits' content re-enters as "incoming" and conflicts with the child's own copies of them. The merge-base goes ancient (pre-stack). Resolve by taking **HEAD (--ours)** for files the child owns — HEAD already = (staging's ancestor content) + (this child's unique delta). VERIFY per file that `--ours` drops nothing staging gained independently: `git diff origin/staging HEAD -- <file>` and check the `-` (staging-only) lines are only ancestor code the PR deliberately rewrote, not an unrelated staging change (e.g. a factory commit, or a fix applied to a parent *after* this child was cut — see [[feedback_waitfor_flake_fix]] for the waitFor case where staging had a fix the child lacked → take --theirs or re-apply). Arch conflicts: always `make arch-regen` + `git add docs/arch/` ([[feedback_cleanup_prs_need_full_suite]] discipline: verify with real tests + build before pushing).

Used 2026-06-01 to land WS-RT #9108–#9111 onto staging after C-1's arch-stamp fix removed the per-file arch-conflict noise. Linked: [[feedback_stacked_pr_rebase]] (the --onto recipe, when force-push IS allowed).
