---
id: 0593
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:08:06.336706+00:00
status: active
corroborations: 1
supersedes: 0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583
---

# is_real_pid must degrade to non-sensitive on any os.get* raise

`is_real_pid` (`src/process_group.py`), called from every reap path, must stay total: wrap `os.get*()` calls when building the sensitive-pid exclusion set so an unexpected raise degrades to "not sensitive" (predicate returns True).

Example: wrap each `os.get*()` call in its own try/except, defaulting to an empty exclusion set on failure.

**Why:** a predicate used inside a signal-handling path that can raise turns a routine reap into an unhandled exception during teardown.
