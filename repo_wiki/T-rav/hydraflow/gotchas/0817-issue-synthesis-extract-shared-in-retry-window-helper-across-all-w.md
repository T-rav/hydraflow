---
id: 0817
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T22:06:52.563973+00:00
status: active
corroborations: 1
supersedes: 0704,0705,0706,0707,0708,0709,0710,0711,0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753,0754,0755,0756,0757,0758,0759,0760,0761,0762
---

# Extract shared _in_retry_window helper across all WorkspaceGCLoop phases

GC-safety checks in `src/workspace_gc_loop.py` must be centralized in one `_in_retry_window` helper and reused everywhere a phase decides whether an issue's worktree/branch is collectable.

Example: `_is_safe_to_gc` (state phase) and `_collect_orphaned_branches` (orphan `agent/issue-N` branch phase) must share the helper — adding a guard in only one phase leaves the other free to destroy in-window work via a different code path.

**Why:** GC has multiple independent sweep phases (state, orphan-dir, orphan-branch); a guard fixed in one but not extracted to a shared helper silently reappears as a bug in the others.
