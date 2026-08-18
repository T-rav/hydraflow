---
id: 4068
topic: patterns
source_issue: 11434
source_phase: plan
created_at: 2026-08-18T06:57:14.697102+00:00
status: active
corroborations: 1
---

# Detect parent death via recorded ppid, not init pid

Detect parent termination by comparing the current ppid against a recorded value, never by checking `ppid == 1`.
- In `scripts/quality_host_lock.py`, store `os.getppid()` before entering run/queue loops.
- Check for inequality: `os.getppid() != recorded_ppid`.
**Why:** Checking for pid 1 is incorrect under a subreaper (e.g., container runtimes), where the reaper process is not init.
