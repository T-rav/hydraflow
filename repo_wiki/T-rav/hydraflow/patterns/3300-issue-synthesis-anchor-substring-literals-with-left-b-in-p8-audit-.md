---
id: 3300
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T06:16:48.574379+00:00
status: superseded
corroborations: 1
supersedes: 3167
superseded_by: 3437
---

# Anchor substring literals with left \b in p8 audit regexes

When a CULTURAL gate's regex matches a word like `review`, always add a left `\b` boundary. Without it, `preview` and `interview` both satisfy the signal.

Example: In `scripts/hydraflow_audit/checks/p8_superpowers.py`, the P8.7 `review` literal was unanchored, so "Preview environments are generated for every PR." passed a code-review gate that `CLAUDE.md` never actually satisfied.

**Why:** An unanchored substring literal produces false PASS verdicts on CULTURAL gates, silently skipping required rules.
