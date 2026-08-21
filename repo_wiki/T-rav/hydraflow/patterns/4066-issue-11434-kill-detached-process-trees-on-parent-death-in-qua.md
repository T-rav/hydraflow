---
id: 4066
topic: patterns
source_issue: 11434
source_phase: plan
created_at: 2026-08-18T06:57:14.697067+00:00
status: active
corroborations: 1
---

# Kill detached process trees on parent death in quality_host_lock

Use `start_new_session=True` and recorded ppid polling to manage child processes in `scripts/quality_host_lock.py`.
- Record `os.getppid()` once in `main()`.
- Use `subprocess.Popen` with `start_new_session=True`.
- If ppid changes, call `os.killpg(os.getpgid(proc.pid), SIGKILL)` and exit with code 75.
**Why:** This prevents unbounded orphan pile-up when the parent process dies unexpectedly.
