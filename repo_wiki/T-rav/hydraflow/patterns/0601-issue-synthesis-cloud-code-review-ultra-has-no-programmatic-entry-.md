---
id: 0601
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:08:06.346097+00:00
status: active
corroborations: 1
supersedes: 0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583
---

# Cloud `/code-review ultra` has no programmatic entry point

The cloud ultra review tier is client-side and separately billed — nothing in `src/` can launch it. The reachable equivalent for headless dispatch is the local `commands/code-review.md` plugin command, spawnable via `agent_cli.build_agent_command` + `BaseRunner._execute`.

Example: `ReviewPhase._build_post_verify_runner` uses this local-plugin seam to dispatch 5 parallel reviewers + Haiku confidence scoring.

**Why:** prevents re-researching this dead end when a feature wants cloud-tier review programmatically — it can't; build on the local-plugin path.
