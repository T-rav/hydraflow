---
source: feedback_monitor_fix_merge_prs.md
name: monitor-fix-merge-prs
description: 'Travis 2026-07-19: monitoring open PRs and fixing/merging broken ones is PART of the backlog-drive goal — arming auto-merge is not the end of ownership'
status: pending
issue: null
promoted_in: null
wontfix_reason: null
created: '2026-07-19'
---

Travis (2026-07-19, during the backlog drive): "you do need to monitor it and fix/merge broken prs too, keep that as part of the goal."

**Why:** Arming `--auto` merge and moving on leaves PRs to die silently — cancelled Tests jobs (#9983 attempt 3), DIRTY states after sibling merges (#9999), and born-red checks all need hands-on response. The factory's own shepherd loops don't cover everything yet (that's [[backlog-drive-goal-2026-07-19]]'s #9889/#9974 arc), so the operator-agent owns the gap.

**How to apply:** While any authored/armed PR is open: (1) keep a background watcher polling open-PR check states (~3 min cadence, `until`-loop task so completion re-invokes; foreground sleep is blocked); (2) on FAILURE → diagnose the failing job log immediately and fix hands-on (update-branch for stale merge refs / cancelled jobs, code fix + push for real reds); (3) on DIRTY → merge the base branch in, resolve (arch-regen for generated-docs conflicts), push; (4) auto-merge re-arms survive pushes, but VERIFY armed state after any force-refresh. Merged = the only done state.
