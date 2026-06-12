---
id: 0007
topic: testing
source_issue: 9443
source_phase: review
created_at: 2026-06-12T14:42:30.290526+00:00
status: active
corroborations: 1
---

# Regression tests must load the real shipped asset, not a tmp_path copy

Pin exact price resolution against the production file (`src/assets/model_pricing.json`), not a synthetic tmp_path fixture.

```python
# tests/regressions/test_opus_explicit_pricing.py
from model_pricing import load_pricing
def test_opus_4_8_rate():
    assert load_pricing().get_rate('claude-opus-4-8') == (5.0, 25.0)
```

Synthetic fixtures validate code paths but let a typo or missing entry in the real asset ship green.

**Why:** A bug is unfixed if the production data file is unchanged — test-only assets give false confidence that the live billing path is correct.
