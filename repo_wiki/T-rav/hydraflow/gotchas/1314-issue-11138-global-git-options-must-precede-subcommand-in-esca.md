---
id: 1314
topic: gotchas
source_issue: 11138
source_phase: plan
created_at: 2026-08-14T14:08:04.915393+00:00
status: active
corroborations: 1
---

# Global git options must precede subcommand in escape adapters

When invoking `git -c core.quotepath=false grep …` in `escape.auto_diagnose._grep` (precedent: `escape.detect.py:258`), the `-c` flag must come before the `grep` subcommand.

- Correct: `git -c core.quotepath=false grep -l …`
- Wrong: `git grep -c core.quotepath=false -l …` — git errors and `_grep` fails open to zero hits.

**Why:** Misordered global options make the adapter silently return no hits; non-ASCII regression filenames also come back octal-escaped and quoted, breaking path resolution downstream.
