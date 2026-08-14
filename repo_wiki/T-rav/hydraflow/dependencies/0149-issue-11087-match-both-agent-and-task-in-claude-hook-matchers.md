---
id: 0149
topic: dependencies
source_issue: 11087
source_phase: plan
created_at: 2026-08-14T06:12:02.565691+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Match both Agent and Task in Claude hook matchers

When wiring PostToolUse hooks that fire on subagent dispatch, match both `Agent` and `Task` in the matcher — the harness event name changed across versions. Example: a `PostToolUse` matcher of `Agent|Task|Skill` in `.claude/settings.json` ensures `hf.clear-review-marker.sh` fires regardless of harness version. **Why:** A matcher that only names `Agent` (or only `Task`) silently never fires on the other version, so the disarm hook never runs and every session gets Stop-blocked.
