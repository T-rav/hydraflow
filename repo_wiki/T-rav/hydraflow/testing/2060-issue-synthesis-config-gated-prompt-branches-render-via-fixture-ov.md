---
id: 2060
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T12:50:54.201588+00:00
status: superseded
corroborations: 1
supersedes: 1933
superseded_by: 2189
---

# Config-gated prompt branches: render via fixture overrides

Render config-gated alternative prompt branches via fixture `config_overrides`, never by editing production defaults.

Example: `reviewer._build_review_prompt_with_stats` has a `elif use_quality_gate_in_review` branch that is dead while `max_ci_fix_attempts=2`; a fixture declaring `"config_overrides": {"max_ci_fix_attempts": 0}` renders it for scoring.

**Why:** ADR-0116 §10 holds that rendering a prompt at all is worth more than its score; leaving branches permanently unscored creates blind spots.
