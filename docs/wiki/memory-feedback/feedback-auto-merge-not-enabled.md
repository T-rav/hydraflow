---
source: feedback_auto_merge_not_enabled.md
name: Auto-merge not enabled on this repo — direct-merge via gh pr merge
description: '`gh pr merge --auto` returns "Auto merge is not allowed for this repository"
  — use `gh pr merge --squash` directly when CI is green'
status: promoted
issue: 12053
promoted_in: null
wontfix_reason: null
created: '2026-05-02'
---

`gh pr merge <N> --auto --squash` fails with `GraphQL: Auto merge is not allowed for this repository (enablePullRequestAutoMerge)` on this repo. Auto-merge isn't enabled at the repo level (would require admin to toggle in GitHub settings).

**How to apply:**
- For autonomous PR shipping, set up a Monitor that polls CI and direct-merges when green:
  ```bash
  Monitor with command:
    while true; do
      s=$(gh pr view N --json state,statusCheckRollup ...)
      pending=$(...); failed=$(...)
      if [ "$pending" = "0" ] && [ "$failed" = "0" ]; then
        gh pr merge N --squash
        break
      fi
      sleep 90
    done
  ```
- Or, when CI is already green, just run `gh pr merge <N> --squash --delete-branch`.
- The `--delete-branch` may fail with "branch used by worktree" — that's local cleanup blockage, not a merge failure. The actual merge succeeds.
- Verify with `gh pr view N --json state,mergedAt` — `state == "MERGED"` + `mergedAt != null` confirms.

**Enforced in code (#12053):** `src/auto_pr.py` no longer gives up when `--auto` is refused. `_merge_pr_best_effort` / `_merge_pr_best_effort_async` retry once with a direct `gh pr merge <url> --squash`, on both the sync `open_automated_pr` path and the shared async finalize tail. No CI poll loop is needed there because the #10672 green-gate has already confirmed every non-skipped check settled SUCCESS before either merge is attempted. Pinned by `tests/regressions/test_issue_12053.py`. The Monitor-poll recipe above still applies to PRs an agent is driving by hand, where nothing has gated on green yet.
