---
id: 1146
topic: gotchas
source_issue: 10646
source_phase: plan
created_at: 2026-07-26T12:21:36.986356+00:00
status: active
corroborations: 1
---

# Render only --confidence values that bump attribution off low

When `escape_ledger_loop.py` renders a `--confidence` command for a `low-confidence` finding, offer only `<high|medium>` — never `<low>`. Offering `low` produces a command that runs cleanly but leaves `attribution_confidence == "low"`, so `_surfacing_answered` still won't close the issue on the next reconcile tick.

**Why:** A self-defeating selectable value recreates the original defect with extra steps; the rendered command must always close the issue if executed verbatim.
