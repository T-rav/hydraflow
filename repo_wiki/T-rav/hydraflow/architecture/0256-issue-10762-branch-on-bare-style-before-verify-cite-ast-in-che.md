---
id: 0256
topic: architecture
source_issue: 10762
source_phase: plan
created_at: 2026-07-28T00:37:27.487544+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Branch on bare style before verify_cite_ast in _check_cite

Rule: In `_check_cite`, the bare-cite branch must execute before the AST verification branch. `Cite.module_as_path()` returns `""` for `"bare"` style (no schema change needed), but if `_check_cite` reaches `verify_cite_ast` first, every bare cite reports broken — including correct ones — because AST lookup fails on an empty module path.

**Why:** Control-flow ordering determines whether valid bare cites survive the check or are universally misreported as rot.
