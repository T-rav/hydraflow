---
id: 1251
topic: gotchas
source_issue: 10626
source_phase: plan
created_at: 2026-07-26T11:57:17.619603+00:00
status: active
corroborations: 1
---

# Degrade gist raw screenshot URLs to link, not broken-image icon

`PRManager.upload_screenshot` stores screenshots as gist raw URLs in `VisualEvidenceItem.baseline_url/actual_url/diff_url`. These may not render inline (hotlinking restrictions), so every `<img>` consuming them needs an `onError` fallback to the existing text link affordance.

Example: `HITLTable.jsx` Visual Evidence cards keep `Baseline`/`Actual`/`Diff` text links as the persistent "open original" affordance alongside the preview.

**Why:** A broken-image icon breaks the evidence UI entirely; the text link is the durable fallback path.
