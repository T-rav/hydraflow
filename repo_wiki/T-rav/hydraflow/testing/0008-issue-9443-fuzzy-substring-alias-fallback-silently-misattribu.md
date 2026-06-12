---
id: 0008
topic: testing
source_issue: 9443
source_phase: review
created_at: 2026-06-12T14:42:30.290567+00:00
status: active
corroborations: 1
---

# Fuzzy substring alias fallback silently misattributes cost for any new model ID

Every new model variant must have an explicit entry in `model_pricing.json` with model-specific aliases — never rely on a bare substring alias (e.g. `"opus"`) as catch-all.

- Wrong: `claude-opus-4-8` substring-matches `"opus"` alias on `claude-opus-4-7` → 3× overcharge ($15/$75 instead of $5/$25).
- Right: add `claude-opus-4-8` entry with alias `"claude-opus-4-8"` only.

`PricingRefreshLoop` only auto-adds LiteLLM-published models, so newly released model IDs accumulate silently until explicitly registered.

**Why:** Fallback-to-substring means any Opus-tier model ID without an explicit entry bills at the wrong rate indefinitely.
