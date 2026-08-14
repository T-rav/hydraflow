---
source: feedback_subagent_backgrounds_quality_then_stops.md
name: feedback_subagent_backgrounds_quality_then_stops
description: 'Dispatched subagents on long verification runs background `make quality`/`make test` and then STOP, expecting a monitor to auto-resume them — but their process is dead, so they never resume. Fix: SendMessage-resume (context intact), don''t restart; and prompt them to block foreground + not stop until the PR is open.'
status: promoted
issue: 11095
promoted_in: '#11095'
wontfix_reason: null
created: '2026-07-26'
---

**Pattern (recurred 3+ times in one session: the #10670 stall, P4 #10703, operator-console Task 1).** A background subagent kicks off `make quality` / full pytest (a ~10–20 min run) via its own `run_in_background`, then emits a message like *"the suite is running (~25%); I'll wait for the monitor's completion notification before committing"* and STOPS. Its process has actually terminated, so nothing re-invokes it — the verification result is never captured and the PR is never opened. This is the same fire-and-forget trap that CLAUDE.md warns runners about, wearing an agent-lifecycle disguise.

**Why:** the agent assumes a background waiter will wake it (as the main loop is woken by task-notifications). Subagents don't get that; when they stop with no live children, they're just done.

**How to apply:**
1. **Resume, don't restart.** The completed agent is resumable with full context — `SendMessage(to: <agentId>, ...)` re-enters its transcript (worktree, edits, decisions intact). Tell it: re-run `make quality 2>&1 | tail -40; echo "QUALITY_EXIT=${PIPESTATUS[0]}"` in the FOREGROUND, blocking; if a prior backgrounded make is holding locks, wait/kill it first; then commit + push + open the PR; do NOT stop until the PR exists. Restarting from scratch wastes the whole build.
2. **Preempt in the dispatch prompt.** Add to every build-agent prompt: *"Run `make quality` in the FOREGROUND to completion — never background it and never stop to 'wait for a monitor.' Do not end your turn until the PR is open (or you have an exact error to report)."*

Related: [[feedback_make_quality_pipe_exit_code]] (PIPESTATUS to catch masked exit), [[feedback_dark_factory_autonomy]] (act+report), and the scenario-scope discipline in [[project_suppressions_ratchet_unbaselined_noqa_poisons_staging]].
