---
id: 0304
topic: architecture
source_issue: 11099
source_phase: plan
created_at: 2026-08-14T07:08:09.480598+00:00
status: active
corroborations: 1
---

# ADR-0049 kill-switch applies only to BaseBackgroundLoop subclasses

ADR-0049's kill-switch requirement applies to `BaseBackgroundLoop` subclasses with subprocess-spawning runners. Diagnostic CLIs that read state and print JSON — no loop subclass, no subprocess spawn — are exempt.

When adding a read-only diagnostic command, verify it does not subclass `BaseBackgroundLoop` or spawn subprocesses before applying ADR-0049. Any GitHub API access for job data must go through `PRPort.get_workflow_run_jobs`, never a bare `gh` call.
**Why:** Misapplying ADR-0049 to non-loop commands adds unnecessary kill-switch infrastructure and blocks legitimate read-only tooling behind an approval gate.
