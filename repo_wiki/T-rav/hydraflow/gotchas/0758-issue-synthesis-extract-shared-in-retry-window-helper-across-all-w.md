---
id: 0758
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:18:53.922957+00:00
status: superseded
corroborations: 1
supersedes: 0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671,0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703
superseded_by: 0764
---

# Extract shared _in_retry_window helper across all WorkspaceGCLoop phases

GC-safety checks in `src/workspace_gc_loop.py` must be centralized in one `_in_retry_window` helper and reused everywhere a phase decides whether an issue's worktree/branch is collectable.

Example: `_is_safe_to_gc` (state phase) and `_collect_orphaned_branches` (orphan `agent/issue-N` branch phase) must share the helper — adding a guard in only one phase leaves the other free to destroy in-window work via a different code path.

**Why:** GC has multiple independent sweep phases (state, orphan-dir, orphan-branch); a guard fixed in one but not extracted to a shared helper silently reappears as a bug in the others.
