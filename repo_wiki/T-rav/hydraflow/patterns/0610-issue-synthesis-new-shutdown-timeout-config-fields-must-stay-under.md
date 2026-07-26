---
id: 0610
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:08:06.396477+00:00
status: active
corroborations: 1
supersedes: 0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583
---

# New shutdown-timeout config fields must stay under RepoRuntime.stop's 30s ceiling

When adding a new timeout `Field` to `src/config.py` (e.g. `shutdown_drain_timeout_seconds`), check it against `RepoRuntime.stop`'s existing 30s `wait_for`. Also register the field in the int-env tuple table alongside the `Field` declaration.

Example: a drain budget equal to or above the outer timeout defeats the point of a bounded inner drain.

**Why:** an inner timeout that isn't strictly less than its outer caller's timeout never actually bounds anything in practice.
