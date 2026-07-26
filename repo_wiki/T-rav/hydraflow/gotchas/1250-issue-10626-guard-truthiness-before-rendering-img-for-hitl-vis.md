---
id: 1250
topic: gotchas
source_issue: 10626
source_phase: plan
created_at: 2026-07-26T11:57:17.619595+00:00
status: active
corroborations: 1
---

# Guard truthiness before rendering <img> for HITL visual evidence URLs

In `HITLTable.jsx` Visual Evidence cards, guard on URL truthiness before emitting an `<img>` for `baseline_url`/`actual_url`/`diff_url`. Existing fixtures pass `''` for all three.

- Render nothing image-wise when the URL is empty.
- Add an `onError` fallback to the text link for non-empty URLs that fail to load.

**Why:** jsdom emits load errors for empty-string `src`, which breaks the "no image element when URL is empty" contract and fires spurious test failures.
