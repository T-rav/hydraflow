---
id: 4087
topic: patterns
source_issue: 11937
source_phase: plan
created_at: 2026-09-01T09:28:20.470710+00:00
status: active
corroborations: 1
---

# format_terminal omits PASS detail — carry advisories as WARN

If an advisory reason must reach the human-readable CI log, map it to `Status.WARN`, never `Status.PASS`.

`format_terminal` skips PASS detail; the JSON report is never uploaded, so the terminal is the only human surface for advisory text.

Reject the alternative of teaching `format_terminal` to print advisory PASS — global blast radius over every check's PASS messages, and it falsifies ADR-0044's "only warn" wording.

**Why:** A PASS-mapped advisory is computed, then silently discarded before the only human-readable output surface.
