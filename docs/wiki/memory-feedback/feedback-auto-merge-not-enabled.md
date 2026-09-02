---
source: feedback_auto_merge_not_enabled.md
name: Auto-merge not enabled on this repo — direct-merge via gh pr merge
description: 'STALE (verified 2026-09-02): `allow_auto_merge` is now true on this
  repo, so `gh pr merge --auto` is no longer refused'
status: wontfix
issue: 12053
promoted_in: null
wontfix_reason: 'Premise no longer holds. `gh api repos/T-rav/hydraflow` returns
  `allow_auto_merge: true` (verified 2026-09-02), and PRs #12044/#12043/#12039
  armed and merged via --auto (SQUASH), #12049 via MERGE. The GraphQL "Auto merge
  is not allowed for this repository" error this memory describes cannot occur, so
  there is no rule left to enforce in code. The still-true half of the memory (the
  factory polls CI and merges itself rather than relying on --auto) is already the
  documented standard in docs/standards/branch_protection/README.md §"Merge
  mechanism — process-driven, not GitHub auto-merge".'
created: '2026-05-02'
---

> **STALE — do not apply.** Kept for provenance. See `wontfix_reason` above.
> When this was captured (2026-05-02) the repo-level "Allow auto-merge" setting
> was off. It is on now, and `docs/standards/branch_protection/README.md:57`
> records that the branch-protection apply-er flips it on if missing — so the
> failure mode below is not reachable and the workaround is not needed.
>
> For how bot PRs are *supposed* to merge, read
> [`docs/standards/branch_protection/README.md`](../../standards/branch_protection/README.md)
> §"Merge mechanism": the process that opened a PR stays attached and polls CI,
> attempts the merge, and reacts to failure. That standard, not this memory, is
> the live rule.

## Original memory (2026-05-02, no longer accurate)

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

## What is still worth knowing

The verification tip survives the premise: `gh pr view N --json state,mergedAt` — `state == "MERGED"` + `mergedAt != null` — is still how you confirm a merge landed, and `--delete-branch` failing with "branch used by worktree" is still local cleanup blockage rather than a merge failure.

The poll-then-merge shape is also still right, but for a different reason than this memory gives: not because `--auto` is refused, but because the factory wants a process attached through merge that can react to a failure. That is [ADR-0048](../../adr/0048-auto-revert-on-rc-red.md)'s and the branch-protection standard's position, and it is where `--squash` vs `--merge` per base branch is decided (`main` is merge-commit only).

Separately, chasing this memory turned up a live suspicion worth its own investigation: `src/auto_pr.py`'s #10672 green-gate reads `statusCheckRollup` immediately after `gh pr create`, when no check has registered or settled, so it may never arm auto-merge at all — which would leave every `auto_pr`-opened bot PR open for a reason unrelated to this memory. Tracked in issue #12068.
