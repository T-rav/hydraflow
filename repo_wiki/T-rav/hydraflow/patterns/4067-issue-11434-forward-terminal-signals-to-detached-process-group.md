---
id: 4067
topic: patterns
source_issue: 11434
source_phase: plan
created_at: 2026-08-18T06:57:14.697093+00:00
status: active
corroborations: 1
---

# Forward terminal signals to detached process groups

When using `start_new_session=True` in `scripts/quality_host_lock.py`, install `SIGINT`/`SIGTERM`/`SIGHUP` handlers that forward to the child's process group.
- Handler forwards signal to child group.
- Handler exits with `128 + signum`.
**Why:** `start_new_session=True` removes the process from the terminal's foreground group; without forwarding, Ctrl-C would orphan the suite tree.
