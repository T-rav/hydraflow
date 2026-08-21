---
id: 4078
topic: patterns
source_issue: 11518
source_phase: plan
created_at: 2026-08-21T09:08:16.052902+00:00
status: active
corroborations: 1
---

# CodeQL fix acceptance: API-verify alert closure; dismiss only as fallback

A code-scanning fix is done only after the alert closes in the API, not when the PR merges.

- Merge to `staging`, confirm the CodeQL actions analysis completed on the merge commit, then accept via `gh api 'repos/T-rav/hydraflow/code-scanning/alerts?state=open&severity=high' --jq length` returning 0.
- Only if the alert survives a completed analysis, PATCH it to `state=dismissed`, `dismissed_reason="false point"`-style values, with a comment pointing at the `# TRUST:` marker in `staging-rc-dryrun.yml`.

**Why:** Alerts auto-close once analysis of fixed code runs; dismissing first hides whether the fix actually satisfied the detector — and these detectors are quirk-gated (the url-substring rule only fires on certain TLDs).
