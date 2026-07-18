---
id: 0283
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T17:48:26.496848+00:00
status: active
corroborations: 1
supersedes: 0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247,0248,0249,0250,0251,0252,0253,0254,0255
---

# Skip broken tests with an issue reference; remove after fix

Mark broken tests with a referenced issue, never a bare skip.

```python
@pytest.mark.skip(reason="documenting bug: #1234")
```

Remove the skip immediately after the issue is resolved.

**Why:** Without an issue reference, skipped tests become permanent dead weight with no path to removal or triage.
